# app/policy/policy.py
from __future__ import annotations
import math
import logging
from typing import Dict, Any, List, Optional, Tuple

from ..db import exec
from . import templates_eval as te
from . import templates_repo as repo

log = logging.getLogger("autobot.policy")

# 安全常數
_EPS = 1e-9
_MAX_SCORE = 1e6  # 防爆上限，避免無限大造成下游混亂

# 可微調的 baseline（當沒有任何模板匹配時使用）
_BASELINE_TPL = {
    "LONG": 1,   # 你的種子：baseline long
    "SHORT": 2,  # 你的種子：baseline short
}

# Bandit 參數（與 evolver 保持一致）
_UCB_C = 2.0
_RISK_PENALTY = 0.05


def _safe_div(num: float, den: float) -> float:
    den = den if abs(den) > _EPS else (_EPS if den >= 0 else -_EPS)
    return num / den


def _finite(x: float, default: float = 0.0) -> float:
    if x is None or isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return default
    return float(x)


def _clip_score(x: float) -> float:
    x = _finite(x, 0.0)
    if x > _MAX_SCORE:
        return _MAX_SCORE
    if x < -_MAX_SCORE:
        return -_MAX_SCORE
    return x


def _fetch_recent_features(symbol: str, interval: str, n: int = 50) -> List[Dict[str, Any]]:
    rows = exec(
        """
        SELECT close_time, rsi, macd_dif, macd_dea, macd_hist, kd_diff,
               slope, atr_pct, vol_ratio, regime
        FROM features
        WHERE symbol=:s AND `interval`=:i
        ORDER BY close_time DESC
        LIMIT :n
        """,
        s=symbol, i=interval, n=int(n)
    ).mappings().all()
    return list(rows or [])


def _avg(vals: List[float], default: float = 0.0) -> float:
    if not vals:
        return default
    return _finite(sum(_finite(v, 0.0) for v in vals) / len(vals), default)

# === 新增：動態門檻工具 ===

def _recent_gap_quantile(symbol: str, interval: str, n: int = 300, q: float = 0.75) -> Optional[float]:
    """
    從 decisions_log 取最近 n 筆的 gap=|E_long - E_short|，回傳分位數 q。
    不足（<50 筆）則回 None。
    """
    rows = exec("""
        SELECT ABS(COALESCE(E_long,0) - COALESCE(E_short,0)) AS gap
          FROM decisions_log
         WHERE symbol=:s AND `interval`=:i
         ORDER BY id DESC
         LIMIT :n
    """, s=symbol, i=interval, n=int(n)).mappings().all()
    vals = [float(r["gap"] or 0.0) for r in rows or [] if r and r.get("gap") is not None]
    if len(vals) < 50:
        return None
    vals.sort()
    k = max(0, min(int(len(vals) * float(q)), len(vals)-1))
    return float(vals[k])

def _dynamic_entry_threshold(symbol: str, interval: str, feats: List[Dict[str, Any]],
                             alpha: float = 0.9) -> float:
    """
    動態門檻：
    1) 先用 decisions_log 的 P75(gap) × alpha
    2) 若樣本不足，用 ATR 尺度 fallback（對齊你目前 E 的量級）
    """
    q = _recent_gap_quantile(symbol, interval, n=300, q=0.75)
    if q is not None and q > 0:
        return float(q) * float(alpha)

    # fallback: 用 ATR 尺度估（你現在 E 是用 atr_pct 當風險分母，量級很大）
    k = min(50, len(feats))
    atr_mean = _avg([r.get("atr_pct", 0.0) for r in feats[:k]], 0.0)
    scale = 2_000_000.0  # 如要更保守可調大；更積極調小
    return max(1.0, float(atr_mean) * scale)


def _decide_direction(feats: List[Dict[str, Any]]) -> Tuple[str, float, float]:
    """
    以最近 20 根做平均，計算 E_long / E_short 與方向。
    回傳 (action, E_long, E_short)
    """
    if not feats:
        return ("HOLD", 0.0, 0.0)

    k = min(20, len(feats))
    sub = feats[:k]

    avg_macd = _avg([r.get("macd_hist", 0.0) for r in sub], 0.0)
    avg_kd   = _avg([r.get("kd_diff",   0.0) for r in sub], 0.0)
    avg_rsi  = _avg([r.get("rsi",      50.0) for r in sub], 50.0)
    avg_slope= _avg([r.get("slope",     0.0) for r in sub], 0.0)
    avg_atr  = _avg([r.get("atr_pct",   0.0) for r in sub], 0.0)
    avg_volr = _avg([r.get("vol_ratio", 1.0) for r in sub], 1.0)

    # 把 RSI 轉為 -1..+1 的偏離
    rsi_bias = (avg_rsi - 50.0) / 50.0

    # 原始多空分數（可依需求調整權重）
    long_raw  =  + 1.0 * avg_macd + 0.8 * avg_kd + 0.6 * rsi_bias + 0.5 * avg_slope
    short_raw =  - 1.0 * avg_macd - 0.8 * avg_kd - 0.6 * rsi_bias - 0.5 * avg_slope

    # 用波動(atr_pct)做風險尺度，避免分母過小導致 inf
    risk_scale = max(avg_atr, 1e-5)  # 極小值保護
    E_long  = _clip_score(_safe_div(long_raw,  risk_scale))
    E_short = _clip_score(_safe_div(short_raw, risk_scale))

    # 再依成交量/波動做溫和壓縮
    compress = max(0.5, min(2.0, avg_volr))  # 0.5~2.0
    E_long  = _clip_score(E_long  / compress)
    E_short = _clip_score(E_short / compress)

    action = "HOLD"
    if E_long > 0 and E_long >= abs(E_short):
        action = "LONG"
    elif E_short > 0 and E_short > E_long:
        action = "SHORT"

    return (action, float(_finite(E_long, 0.0)), float(_finite(E_short, 0.0)))


def _select_template(side: str, last_feat: Dict[str, Any]) -> int:
    """
    依照當下 bins 與 bandit 分數，從 ACTIVE templates 中挑一個 template_id。
    若完全找不到匹配者，回傳 baseline。
    """
    # 1) 產生 bins
    bins = te.feature_bins(last_feat)

    # 2) 拿 active 清單與績效彙總
    actives = repo.get_active_templates()
    summaries = repo.get_all_templates_summary(active_only=True)
    total_plays = sum(int(summ.get("n_trades") or 0) for summ in summaries.values()) or 1

    # 3) 先篩選出 side & 條件匹配的模板
    matched = te.match_templates(actives, bins, side=side)

    # 4) 若無匹配，回 baseline
    if not matched:
        baseline = _BASELINE_TPL.get(side)
        if baseline is None:
            # 萬一 baseline 沒設到這個 side，就挑第一個同 side 的 active
            for t in actives:
                if t.get("side") == side:
                    return int(t["template_id"])
            # 還是沒有就硬回 1
            return 1
        return int(baseline)

    # 5) 用 bandit 分數選最佳
    best_score = -float("inf")
    best_tid = None
    for t in matched:
        tid = int(t["template_id"])
        summ = summaries.get(tid, {}) or {}
        score = te.bandit_score(summ, total_plays, method="ucb1",
                                c=_UCB_C, risk_penalty=_RISK_PENALTY)
        if score > best_score:
            best_score = score
            best_tid = tid

    # 萬一全是空資料
    if best_tid is None:
        best_tid = int(matched[0]["template_id"])

    return best_tid


def evaluate_symbol_interval(symbol: str, interval: str) -> Dict[str, Any]:
    """
    決策流程（整合模板系統）：
    1) 讀 features → 計算 E_long/E_short 與方向（LONG/SHORT/HOLD）
    2) 若 HOLD → 回傳 template_id 以 baseline 為主（可視需要回 0）
    3) 若 LONG/SHORT → 依 bins + bandit 選出最佳 template_id
    4) 觸碰 template_stats 的 last_used_at（帶上目前 regime）
    """
    feats = _fetch_recent_features(symbol, interval, n=50)
    if not feats:
        return {"action": "HOLD", "E_long": 0.0, "E_short": 0.0, "template_id": _BASELINE_TPL["LONG"]}

    action, E_long, E_short = _decide_direction(feats)
    # === 新增：用動態門檻覆蓋 action（gap 不夠大 → HOLD） ===
    gap = abs(float(E_long) - float(E_short))
    th = _dynamic_entry_threshold(symbol, interval, feats, alpha=0.9)  # 0.8~1.2 可微調
    if gap < th:
        action = "HOLD"

    last = feats[0]  # 最新一根
    regime = int(_finite(last.get("regime"), 0))

    # HOLD 時：你可以選擇回傳 0；這裡先用 LONG baseline，方便下游統計
    if action == "HOLD":
        tpl_id = _BASELINE_TPL.get("LONG", 1)
        try:
            repo.touch_template_last_used(tpl_id, regime)
        except Exception as e:
            log.warning(f"touch baseline template failed: {e}")
        return {
            "action": "HOLD",
            "E_long": E_long,
            "E_short": E_short,
            "template_id": int(tpl_id),
        }

    # LONG / SHORT → 用模板系統挑 id
    tpl_id = _select_template(action, last)

    # 更新該模板的 last_used_at（不在這裡更新 reward，reward 應由成交/平倉時寫入）
    try:
        repo.touch_template_last_used(tpl_id, regime)
    except Exception as e:
        log.warning(f"touch template failed: tid={tpl_id} err={e}")

    return {
        "action": action,
        "E_long": E_long,
        "E_short": E_short,
        "template_id": int(tpl_id),
    }
