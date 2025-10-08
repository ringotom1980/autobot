# app/data/features.py
from __future__ import annotations
import math
from typing import List, Dict, Any, Tuple, Optional
from ..db import exec
from ..config import Config

# ---------- 指標工具 ----------

def _ema(prev: float, x: float, alpha: float) -> float:
    return alpha * x + (1 - alpha) * prev

def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 1:
        return [float(v) for v in values]
    alpha = 2.0 / (period + 1.0)
    out: List[Optional[float]] = [None] * len(values)
    ema_val: Optional[float] = None
    for i, v in enumerate(values):
        if ema_val is None:
            # 初始化用首個非 None
            ema_val = float(v)
        else:
            ema_val = _ema(ema_val, float(v), alpha)
        out[i] = ema_val
    return out

def _rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    rsis: List[Optional[float]] = [None] * len(values)
    gains: List[float] = [0.0]
    losses: List[float] = [0.0]
    for i in range(1, len(values)):
        delta = values[i] - values[i-1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    # 初始平均
    if len(values) < period + 1:
        return rsis
    avg_gain = sum(gains[1:period+1]) / period
    avg_loss = sum(losses[1:period+1]) / period
    def _rsi_from(gl: Tuple[float,float]) -> float:
        g, l = gl
        if l == 0:
            return 100.0
        rs = g / l
        return 100.0 - 100.0 / (1.0 + rs)
    rsis[period] = _rsi_from((avg_gain, avg_loss))
    # 之後用 Wilder 平滑
    for i in range(period+1, len(values)):
        gain, loss = gains[i], losses[i]
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rsis[i] = _rsi_from((avg_gain, avg_loss))
    return rsis

def _macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9
         ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    ema_fast = _ema_series(values, fast)
    ema_slow = _ema_series(values, slow)
    dif: List[Optional[float]] = []
    for a, b in zip(ema_fast, ema_slow):
        if a is None or b is None:
            dif.append(None)
        else:
            dif.append(a - b)
    # DEA = DIF 的 EMA(signal)
    dif_clean = [0.0 if d is None else d for d in dif]
    dea = _ema_series(dif_clean, signal)
    hist: List[Optional[float]] = []
    for d, e in zip(dif, dea):
        if d is None or e is None:
            hist.append(None)
        else:
            hist.append(d - e)
    return dif, dea, hist

def _rolling_min(arr: List[float], window: int, i: int) -> float:
    j = max(0, i - window + 1)
    return min(arr[j:i+1])

def _rolling_max(arr: List[float], window: int, i: int) -> float:
    j = max(0, i - window + 1)
    return max(arr[j:i+1])

def _kdj(high: List[float], low: List[float], close: List[float], n: int = 9, k_smooth: int = 3, d_smooth: int = 3
        ) -> Tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    rsv: List[Optional[float]] = [None] * len(close)
    for i in range(len(close)):
        ll = _rolling_min(low, n, i)
        hh = _rolling_max(high, n, i)
        denom = (hh - ll)
        if denom == 0:
            rsv[i] = 50.0
        else:
            rsv[i] = (close[i] - ll) / denom * 100.0
    # K 與 D 的平滑
    def _sma(vals: List[Optional[float]], m: int) -> List[Optional[float]]:
        out: List[Optional[float]] = [None] * len(vals)
        acc = 0.0
        cnt = 0
        for i, v in enumerate(vals):
            if v is None:
                out[i] = None
            else:
                acc += v
                cnt += 1
                if cnt >= m:
                    out[i] = acc / m
                    acc -= vals[i - m + 1] if vals[i - m + 1] is not None else 0.0
                else:
                    out[i] = None
        return out
    k_raw = _sma(rsv, k_smooth)
    d_raw = _sma(k_raw, d_smooth)
    kd_diff: List[Optional[float]] = []
    for k, d in zip(k_raw, d_raw):
        if k is None or d is None:
            kd_diff.append(None)
        else:
            kd_diff.append(k - d)
    return k_raw, d_raw, kd_diff

def _atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[Optional[float]]:
    trs: List[float] = [0.0] * len(close)
    for i in range(len(close)):
        if i == 0:
            trs[i] = high[i] - low[i]
        else:
            trs[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr: List[Optional[float]] = [None] * len(close)
    if len(close) < period:
        return atr
    # 初始平均
    acc = sum(trs[:period])
    atr[period-1] = acc / period
    for i in range(period, len(close)):
        atr[i] = (atr[i-1] * (period - 1) + trs[i]) / period  # Wilder
    return atr

def _linreg_slope(values: List[float], win: int = 10) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        j = i - win + 1
        if j < 0: continue
        xs = list(range(win))
        ys = values[j:i+1]
        n = float(win)
        sx = sum(xs); sy = sum(ys)
        sxx = sum(x*x for x in xs)
        sxy = sum(x*y for x, y in zip(xs, ys))
        denom = (n*sxx - sx*sx)
        if denom == 0:
            out[i] = 0.0
        else:
            out[i] = (n*sxy - sx*sy) / denom
    return out

def _finite(x: Optional[float], default: float = 0.0) -> float:
    if x is None: return default
    if math.isnan(x) or math.isinf(x): return default
    return float(x)

# ---------- DB 讀寫 ----------

def _fetch_last_features_ct(symbol: str, interval: str) -> Optional[int]:
    row = exec(
        "SELECT MAX(close_time) AS mx FROM features WHERE symbol=:s AND `interval`=:i",
        s=symbol, i=interval
    ).mappings().first()
    if not row: return None
    mx = row.get("mx")
    return int(mx) if mx is not None else None

def _fetch_candles_for_increment(symbol: str, interval: str, last_ft: Optional[int], warmup: int
                                ) -> List[Dict[str, Any]]:
    """
    取自 last_ft 往前 warmup 根（用於指標暖機），直到最新。
    若 last_ft 為 None，則抓 lookback + warmup 根。
    """
    if last_ft is None:
        # 沒算過特徵：抓 lookback + warmup
        need = int(Config.policy(interval)["lookback"]) + warmup
        rows = exec(
            """
            SELECT close_time, open, high, low, close, volume
            FROM candles
            WHERE symbol=:s AND `interval`=:i
            ORDER BY close_time DESC
            LIMIT :n
            """,
            s=symbol, i=interval, n=need
        ).mappings().all()
    else:
        rows = exec(
            """
            SELECT close_time, open, high, low, close, volume
            FROM candles
            WHERE symbol=:s AND `interval`=:i
              AND close_time >= :from_ct
            ORDER BY close_time ASC
            """,
            s=symbol, i=interval, from_ct=max(0, last_ft - 10_000_000_000)  # 保守，不靠毫秒算，改抓區段後面再裁切
        ).mappings().all()
    rows = list(rows or [])
    # 轉成時間序（ASC）
    rows.sort(key=lambda r: int(r["close_time"]))
    if last_ft is not None and rows:
        # 往前補 warmup
        head = exec(
            """
            SELECT close_time, open, high, low, close, volume
            FROM candles
            WHERE symbol=:s AND `interval`=:i AND close_time < :from_ct
            ORDER BY close_time DESC
            LIMIT :n
            """,
            s=symbol, i=interval, from_ct=rows[0]["close_time"], n=warmup
        ).mappings().all()
        rows = list(reversed(list(head or []))) + rows
    return rows

def _upsert_features_batch(symbol: str, interval: str, feats: List[Dict[str, Any]]) -> int:
    """逐筆 upsert；回傳實際處理筆數（新寫/覆寫都算 1）。"""
    if not feats: return 0
    sql = """
    INSERT INTO features(
      symbol, `interval`, close_time,
      rsi, macd_dif, macd_dea, macd_hist,
      k, d, kd_diff, vol_ratio, atr_pct, slope, range_pct, regime
    ) VALUES (
      :symbol, :interval, :close_time,
      :rsi, :macd_dif, :macd_dea, :macd_hist,
      :k, :d, :kd_diff, :vol_ratio, :atr_pct, :slope, :range_pct, :regime
    )
    ON DUPLICATE KEY UPDATE
      rsi=VALUES(rsi),
      macd_dif=VALUES(macd_dif),
      macd_dea=VALUES(macd_dea),
      macd_hist=VALUES(macd_hist),
      k=VALUES(k),
      d=VALUES(d),
      kd_diff=VALUES(kd_diff),
      vol_ratio=VALUES(vol_ratio),
      atr_pct=VALUES(atr_pct),
      slope=VALUES(slope),
      range_pct=VALUES(range_pct),
      regime=VALUES(regime)
    """
    wrote = 0
    for r in feats:
        exec(sql, **r)
        wrote += 1
    return wrote

# ---------- 對外 API ----------

def compute_and_store_features(symbol: str, interval: str) -> int:
    """
    增量計算：
    只寫入 close_time > last_features_close_time 的 bar。
    回傳本輪實際寫入的筆數。
    """
    warmup = 200  # 讓 MACD/KDJ/ATR 有夠長的緩衝
    last_ft = _fetch_last_features_ct(symbol, interval)
    candles = _fetch_candles_for_increment(symbol, interval, last_ft, warmup)
    if not candles or len(candles) < 5:
        return 0

    # 準備序列
    ct  = [int(r["close_time"]) for r in candles]
    op  = [float(r["open"])  for r in candles]
    hi  = [float(r["high"])  for r in candles]
    lo  = [float(r["low"])   for r in candles]
    cl  = [float(r["close"]) for r in candles]
    vol = [float(r["volume"]) for r in candles]

    rsi = _rsi(cl, 14)
    macd_dif, macd_dea, macd_hist = _macd(cl, 12, 26, 9)
    k, d, kd_diff = _kdj(hi, lo, cl, 9, 3, 3)
    atr = _atr(hi, lo, cl, 14)
    vol_ema20 = _ema_series(vol, 20)
    slope10 = _linreg_slope(cl, 10)

    feats: List[Dict[str, Any]] = []
    last_cut = last_ft if last_ft is not None else -1
    for i in range(len(ct)):
        # 只輸出「新 bar」
        if ct[i] <= last_cut:
            continue
        close_val = cl[i]
        atr_pct = _finite(atr[i], 0.0) / (close_val if close_val != 0 else 1.0)
        vr = 0.0
        if vol_ema20[i] is not None and vol_ema20[i] != 0:
            vr = vol[i] / vol_ema20[i]
        range_pct = (hi[i] - lo[i]) / (close_val if close_val != 0 else 1.0)
        regime = 1 if _finite(macd_hist[i], 0.0) >= 0 else -1

        feats.append({
            "symbol": symbol,
            "interval": interval,
            "close_time": ct[i],
            "rsi": _finite(rsi[i], 50.0),
            "macd_dif": _finite(macd_dif[i], 0.0),
            "macd_dea": _finite(macd_dea[i], 0.0),
            "macd_hist": _finite(macd_hist[i], 0.0),
            "k": _finite(k[i], 50.0),
            "d": _finite(d[i], 50.0),
            "kd_diff": _finite(kd_diff[i], 0.0),
            "vol_ratio": _finite(vr, 1.0),
            "atr_pct": _finite(atr_pct, 0.0),
            "slope": _finite(slope10[i], 0.0),
            "range_pct": _finite(range_pct, 0.0),
            "regime": regime,
        })

    wrote = _upsert_features_batch(symbol, interval, feats)
    # 記錄摘要（模仿你原本的 log 風格）
    if wrote > 0:
        try:
            ct_min = ct[0]
            ct_max = ct[-1]
            raw = len(ct)
            use = wrote
            drop = raw - use if raw >= use else 0
            from .. import db as _db  # 只為了記錄樣式一致，不產生環狀匯入
            _db.log = _db.log if hasattr(_db, "log") else None  # 容錯
        except Exception:
            pass
    return wrote
