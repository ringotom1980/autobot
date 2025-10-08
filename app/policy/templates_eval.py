# app/policy/templates_eval.py
from __future__ import annotations
from typing import Dict, Any, List
from typing import Optional
import math

# -------------------------------------------------
# （保留）將單筆 features 分箱 → 產生用來比對模板的 bins
#   rsi_bin:  L(<30) | M(30~70) | H(>70)
#   macd_bin: P(正向) | N(負向)  （優先用 hist；退而求其次用 dif>=dea）
#   kd_bin:   P(K>D) | N(K<=D)
#   vol_bin:  L(<0.8) | M(0.8~1.2) | H(1.2~1.8) | X(>=1.8)
# -------------------------------------------------
def feature_bins(f: Dict[str, Any]) -> Dict[str, str]:
    rsi = float(f.get("rsi", 50.0))
    kd_diff = float(f.get("kd_diff", 0.0))
    volr = float(f.get("vol_ratio", 1.0))
    hist = f.get("macd_hist", None)
    dif = f.get("macd_dif", None)
    dea = f.get("macd_dea", None)

    # RSI
    if rsi < 30:
        rsi_bin = "L"
    elif rsi > 70:
        rsi_bin = "H"
    else:
        rsi_bin = "M"

    # MACD（優先用 hist）
    if hist is not None:
        macd_bin = "P" if float(hist) >= 0 else "N"
    elif dif is not None and dea is not None:
        macd_bin = "P" if float(dif) >= float(dea) else "N"
    else:
        macd_bin = "P"  # 缺值時給中性偏多

    # KD
    kd_bin = "P" if kd_diff >= 0 else "N"

    # 量比
    if volr < 0.8:
        vol_bin = "L"
    elif volr < 1.2:
        vol_bin = "M"
    elif volr < 1.8:
        vol_bin = "H"
    else:
        vol_bin = "X"

    return {
        "rsi_bin": rsi_bin,
        "macd_bin": macd_bin,
        "kd_bin": kd_bin,
        "vol_bin": vol_bin,
    }


# -------------------------------------------------
# （保留）模板比對：模板欄位可為 "L|M|H" 允許集合；空/None 視為萬用牌
# fields: rsi_bin / macd_bin / kd_bin / vol_bin
# side: "LONG" or "SHORT"
# -------------------------------------------------
def _field_ok(tmpl_val: Any, bin_val: str) -> bool:
    """tmpl_val 若為空 → 通配；否則用 '|' 切集合比對"""
    if tmpl_val is None:
        return True
    s = str(tmpl_val).strip()
    if not s or s == "*":
        return True
    allow = {x.strip() for x in s.split("|") if x.strip()}
    return bin_val in allow


def match_templates(templates: List[Dict[str, Any]], bins: Dict[str, str], side: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in templates:
        if (t.get("status") or "ACTIVE") != "ACTIVE":
            continue
        if side and str(t.get("side")) != side:
            continue
        if not (
            _field_ok(t.get("rsi_bin"),  bins["rsi_bin"]) and
            _field_ok(t.get("macd_bin"), bins["macd_bin"]) and
            _field_ok(t.get("kd_bin"),   bins["kd_bin"]) and
            _field_ok(t.get("vol_bin"),  bins["vol_bin"])
        ):
            continue
        out.append(t)
    return out


# -------------------------------------------------
# ➕ 新增：Bandit / 風險調整 評分 與 凍結判斷
# 期待輸入為 template_stats 的彙總：
#   summary = { n_trades, reward_mean, reward_var(=方差), last_used_at, ... }
# -------------------------------------------------
def _safe(x: float, default: float = 0.0) -> float:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return default
    return float(x)


def ucb1_score(mean: float, n: int, total: int, c: float = 2.0) -> float:
    """UCB1 上信賴界：mean + c * sqrt(ln(total)/(n))；n=0 時回無限大促進探索。"""
    mean = _safe(mean, 0.0)
    n = max(int(n), 0)
    total = max(int(total), 1)
    if n <= 0:
        return float("inf")
    return mean + c * math.sqrt(math.log(total) / n)


def lcb(mean: float, n: int, var: float, z: float = 1.0) -> float:
    """下信賴界，近似 mean - z * sqrt(var / n)；n<=1 時回 mean。"""
    mean = _safe(mean, 0.0)
    n = max(int(n), 0)
    var = _safe(var, 0.0)
    if n <= 1:
        return mean
    return mean - z * math.sqrt(max(var, 0.0) / n)


def bandit_score(summary: Dict[str, Any], total_plays: int,
                 method: str = "ucb1", c: float = 2.0,
                 risk_penalty: float = 0.0) -> float:
    """
    綜合評分：預設 UCB1，再扣除風險懲罰。
    risk_penalty 會乘上 sqrt(var) 以懲罰波動。
    """
    n = int(summary.get("n_trades") or 0)
    mean = float(summary.get("reward_mean") or 0.0)
    var = float(summary.get("reward_var") or 0.0)

    if method.lower() == "ucb1":
        score = ucb1_score(mean, n, total_plays, c=c)
    else:
        score = mean  # 後備：純平均

    score -= risk_penalty * math.sqrt(max(var, 0.0))
    return score


def should_freeze(summary: Dict[str, Any],
                  min_n: int = 20,
                  mean_thresh: float = 0.0,
                  lcb_z: float = 1.0,
                  stale_ms: Optional[int] = None,
                  now_ms: Optional[int] = None) -> bool:
    """
    凍結準則：
    1) 交易筆數達門檻且平均報酬 < 0
    2) 或 LCB < 0（風險調整後不佳）
    3) （選配）長期沒被使用也可凍結
    """
    n = int(summary.get("n_trades") or 0)
    mean = float(summary.get("reward_mean") or 0.0)
    var = float(summary.get("reward_var") or 0.0)
    if n >= min_n and mean < mean_thresh:
        return True
    if n >= max(5, min_n // 2) and lcb(mean, n, var, z=lcb_z) < 0:
        return True

    if stale_ms and now_ms:
        last_used = int(summary.get("last_used_at") or 0)
        if last_used > 0 and now_ms - last_used > stale_ms:
            return True
    return False
