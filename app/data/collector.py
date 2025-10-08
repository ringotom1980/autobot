# app/data/collector.py
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional, Tuple
import logging
import math
import requests

from ..db import exec
from ..config import Config

log = logging.getLogger("autobot")

BINANCE_BASE = getattr(Config, "BINANCE_BASE", "https://fapi.binance.com").rstrip("/")

# Binance 單次最大根數（期貨 K 線可到 1500；保守取 1000 也足夠）
MAX_LIMIT = 1000

# 依據 interval 轉換毫秒
def _interval_ms(interval: str) -> int:
    s = (interval or "").lower().strip()
    if s.endswith("m"):
        return int(s[:-1] or "1") * 60_000
    if s.endswith("h"):
        return int(s[:-1] or "1") * 60 * 60_000
    return 60_000  # default 1m

# 對齊「應該已經收完的」bar close_time（毫秒）
def _now_close_ms(interval_ms: int) -> int:
    now_ms = int(time.time() * 1000)
    return (now_ms // interval_ms) * interval_ms - 1

def _last_candle_close_ms(symbol: str, interval: str) -> Optional[int]:
    row = exec(
        "SELECT MAX(close_time) AS mx FROM candles WHERE symbol=:s AND `interval`=:i",
        s=symbol, i=interval
    ).mappings().first()
    mx = row and row.get("mx")
    return int(mx) if mx is not None else None

def _insert_candles(symbol: str, interval: str, rows: List[Tuple[int,float,float,float,float,float,int]]) -> int:
    """
    rows: list of (open_time, open, high, low, close, volume, close_time)
    回傳實際 upsert 的筆數（新寫/覆寫都算 1）。
    """
    if not rows:
        return 0
    sql = """
    INSERT INTO candles(
      symbol, `interval`, open_time, open, high, low, close, volume, close_time
    ) VALUES (
      :symbol, :interval, :open_time, :open, :high, :low, :close, :volume, :close_time
    )
    ON DUPLICATE KEY UPDATE
      open=VALUES(open),
      high=VALUES(high),
      low=VALUES(low),
      close=VALUES(close),
      volume=VALUES(volume)
    """
    wrote = 0
    for (ot, o, h, l, c, v, ct) in rows:
        exec(sql,
             symbol=symbol, interval=interval,
             open_time=int(ot),
             open=float(o), high=float(h), low=float(l), close=float(c), volume=float(v),
             close_time=int(ct))
        wrote += 1
    return wrote

def _fetch_binance_klines(symbol: str, interval: str, start_ms: Optional[int], end_ms: Optional[int], limit: int) -> List[list]:
    """
    呼叫 Binance 期貨 K 線 /fapi/v1/klines
    回傳原始陣列（每筆 12 欄）
    """
    params: Dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "limit": int(limit),
    }
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)

    url = f"{BINANCE_BASE}/fapi/v1/klines"
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Binance 回傳非 list：{data}")
    log.info("klines 回 %d 筆：%s %s (limit=%s start=%s end=%s)",
             len(data), symbol, interval, params.get("limit"), params.get("startTime"), params.get("endTime"))
    return data

def fetch_klines_to_db(symbol: str, interval: str) -> int:
    """
    只抓「缺少的根數」：
    - 以 DB 目前最大 close_time 與現在時間對齊，計算缺幾根；
    - 若缺 0 根 → 不打 API，直接回 0；
    - 若缺 > 0 → 以 startTime = last_close+1 迴圈抓，直到補完或來源沒有資料。
    回傳：實際 upsert 的筆數。
    """
    interval_ms = _interval_ms(interval)
    now_ct = _now_close_ms(interval_ms)  # 現在應該已收完的 close_time
    last_ct = _last_candle_close_ms(symbol, interval)

    # 計算缺口
    if last_ct is None:
        # DB 無資料：抓 lookback 視窗
        lookback = int(Config.policy(interval)["lookback"])
        need = lookback
        start_ms = now_ct - (need - 1) * interval_ms
    else:
        gap = max(0, (now_ct - last_ct) // interval_ms)  # 距離現在缺幾根
        if gap <= 0:
            # 已最新 → 不抓
            return 0
        need = gap
        start_ms = last_ct + 1  # 下一根的 open_time/或任何落在下一根內的毫秒都可

    wrote_total = 0
    remain = need
    # 由於 Binance 每次最多回 MAX_LIMIT，故迴圈補齊
    while remain > 0:
        this_limit = min(MAX_LIMIT, remain)
        # endTime 可不帶，Binance 會從 startTime 往後抓 limit 根
        raw = _fetch_binance_klines(symbol, interval, start_ms=start_ms, end_ms=None, limit=this_limit)
        if not raw:
            break

        # 轉換/過濾，只取必要欄位
        parsed: List[Tuple[int,float,float,float,float,float,int]] = []
        for arr in raw:
            # arr: [openTime, open, high, low, close, volume, closeTime, ...]
            ot = int(arr[0]); o = float(arr[1]); h = float(arr[2]); l = float(arr[3]); c = float(arr[4])
            v = float(arr[5]); ct = int(arr[6])
            # 僅處理 <= now_ct 的已收完 K 線
            if ct > now_ct:
                continue
            parsed.append((ot, o, h, l, c, v, ct))

        if not parsed:
            break

        wrote = _insert_candles(symbol, interval, parsed)
        if wrote > 0:
            wrote_total += wrote
            ct_min = parsed[0][6]; ct_max = parsed[-1][6]
            log.info("寫入 candles：%s %s wrote=%d range=[%d,%d]", symbol, interval, wrote, ct_min, ct_max)
            # 下一輪從最後一筆之後繼續
            start_ms = ct_max + 1
            # 更新 remain：以實際寫入根數遞減，避免上游重疊
            remain -= wrote
        else:
            break  # 沒寫入 → 代表都重覆了

        # Binance 速率保守一點
        time.sleep(0.2)

    if wrote_total == 0:
        log.warning("collector wrote 0 rows: %s %s", symbol, interval)
    else:
        log.info("collector wrote: %s %s = %d rows", symbol, interval, wrote_total)
    return wrote_total
