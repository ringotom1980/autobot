from __future__ import annotations
from typing import Optional, Dict, Any
from ..db import exec as q

# 讀當前覆蓋
def get_overrides(symbol: str, interval: str, template_id: int, regime: int) -> Optional[Dict[str, Any]]:
    if not template_id:
        return None
    r = q("""
        SELECT max_hold_bars
          FROM policy_overrides
         WHERE template_id=:tid AND `interval`=:iv AND regime=:rg AND symbol=:s
         LIMIT 1
    """, tid=int(template_id), iv=interval, rg=int(regime), s=symbol).mappings().first()
    return dict(r) if r else None

# 學習最佳出場棒數（簡版：在 entry→exit 區間內，用「未來 k 根的 close」模擬提前/延後出場的 PnL，挑 PnL 最佳的 k）
def learn_exit_horizon(
    *, symbol: str, interval: str, template_id: Optional[int], regime: int,
    entry_ts: int, exit_ts: int, direction: str, entry_price: float, qty_abs: float,
    k_min: int = 1, k_max: int = 12
) -> None:
    if template_id is None or qty_abs <= 0:
        return

    # 取 entry 之後到 exit 之後一點點的 K 線（確保能看到 exit 前後的數根）
    rows = q("""
        SELECT close_time, close
          FROM candles
         WHERE symbol=:s AND `interval`=:i
           AND close_time >= :ent - 1*60*1000
           AND close_time <= :ext + 60*60*1000
         ORDER BY close_time ASC
    """, s=symbol, i=interval, ent=int(entry_ts), ext=int(exit_ts)).mappings().all()
    if not rows:
        return

    # 找到 entry 所在或最近的 index
    times  = [int(r["close_time"]) for r in rows]
    prices = [float(r["close"]) for r in rows]
    # entry_idx：第一個 close_time >= entry_ts
    entry_idx = next((i for i, t in enumerate(times) if t >= entry_ts), None)
    if entry_idx is None:
        return

    best_k = None
    best_pnl = None
    qty_signed = qty_abs if direction == "LONG" else -qty_abs

    # 枚舉 k，使用第 entry_idx + k 的 close 做假想出場
    for k in range(max(1, int(k_min)), max(int(k_min), int(k_max)) + 1):
        idx = entry_idx + k
        if idx >= len(prices):
            break
        exit_px_k = prices[idx]
        pnl_k = (exit_px_k - float(entry_price)) * float(qty_signed)
        if (best_pnl is None) or (pnl_k > best_pnl):
            best_pnl = pnl_k
            best_k = k

    if best_k is None:
        return

    # 落庫覆蓋（同鍵 UPSERT）
    q("""
        INSERT INTO policy_overrides(template_id, `interval`, regime, symbol, max_hold_bars)
        VALUES(:tid, :iv, :rg, :s, :k)
        ON DUPLICATE KEY UPDATE
          max_hold_bars = VALUES(max_hold_bars),
          updated_at = CURRENT_TIMESTAMP
    """, tid=int(template_id), iv=interval, rg=int(regime), s=symbol, k=int(best_k))
