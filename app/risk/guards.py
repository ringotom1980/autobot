# app/risk/guards.py
from __future__ import annotations
from typing import Optional, Tuple, Iterable
from time import time
from ..db import exec  # 若你改成 q，請用：from ..db import q as exec

# -------------------------------------------------
# 風控記事
# -------------------------------------------------
def _active_session_id():
    try:
        from ..session import get_active_session_id
        sid = get_active_session_id()
        return int(sid) if sid is not None else None
    except Exception:
        pass
    sid = exec("SELECT session_id FROM run_sessions WHERE is_active=1 ORDER BY started_at DESC LIMIT 1").scalar()
    return int(sid) if sid is not None else None

def journal(rule: str, detail: str, level: str = "INFO") -> None:
    sid = _active_session_id()
    exec(
        "INSERT INTO risk_journal(ts, rule, detail, level, session_id) "
        "VALUES(UNIX_TIMESTAMP()*1000, :r, :d, :l, :sid)",
        r=rule[:64], d=detail[:255], l=level, sid=sid
    )


# -------------------------------------------------
# 停損類（依收盤價判斷）
# -------------------------------------------------
def hard_stop(direction: str, entry_price: float, last_price: float, hard_sl_pct: float) -> Tuple[bool, str]:
    """
    硬停損：到達百分比即出場（方向對稱）
    hard_sl_pct 例如 0.01 = 1%
    """
    if hard_sl_pct is None or hard_sl_pct <= 0:
        return False, ""
    if direction == "LONG":
        hit = (last_price <= entry_price * (1 - hard_sl_pct))
    else:  # SHORT
        hit = (last_price >= entry_price * (1 + hard_sl_pct))
    return (True, f"hard_stop {hard_sl_pct:.4f}") if hit else (False, "")

def trailing_stop(
    direction: str,
    entry_price: float,
    last_price: float,
    peak_price: float,
    backoff_pct: float,
    trigger_pct: float = 0.0
) -> Tuple[bool, str, float]:
    """
    移動停損（簡化版）
    - peak_price：多單為最高價、空單為最低價（呼叫端維護）
    - backoff_pct：回撤比例觸發出場（如 0.005）
    - trigger_pct：先走出一定利潤後才啟動（如 0.003；0 表示隨時）
    回傳：(should_exit, reason, new_peak)
    """
    if backoff_pct is None or backoff_pct <= 0:
        return False, "", peak_price

    new_peak = peak_price
    if direction == "LONG":
        new_peak = max(peak_price, last_price) if peak_price else last_price
        armed = (new_peak >= entry_price * (1 + (trigger_pct or 0.0)))
        hit = armed and (last_price <= new_peak * (1 - backoff_pct))
    else:
        new_peak = min(peak_price, last_price) if peak_price else last_price
        armed = (new_peak <= entry_price * (1 - (trigger_pct or 0.0)))
        hit = armed and (last_price >= new_peak * (1 + backoff_pct))

    return (True, f"trailing_stop backoff={backoff_pct:.4f}", new_peak) if hit else (False, "", new_peak)

def time_stop(opened_at_ms: int, max_hold_bars: int, bar_ms: int) -> Tuple[bool, str]:
    """
    時間停損：持倉超過指定 bar 數則出場
    """
    if not max_hold_bars or max_hold_bars <= 0:
        return False, ""
    now_ms = int(time() * 1000)
    held_bars = (now_ms - int(opened_at_ms)) // int(bar_ms)
    return (True, f"time_stop {held_bars}>{max_hold_bars}") if held_bars >= max_hold_bars else (False, "")

# -------------------------------------------------
# 帳戶/風控級（以交易日誌推導）
# -------------------------------------------------
def daily_max_drawdown_hit(limit_usdt: float) -> Tuple[bool, str]:
    """
    以 trades_log 推算「今日實現損益累計」是否跌破 -limit_usdt
    limit_usdt：今日允許最大虧損金額（USDT）
    """
    if not limit_usdt or limit_usdt <= 0:
        return False, ""
    start = exec("SELECT UNIX_TIMESTAMP(CURDATE())*1000").scalar()
    pnl = exec(
        "SELECT COALESCE(SUM(pnl_after_cost),0) FROM trades_log WHERE exit_ts >= :s",
        s=int(start)
    ).scalar() or 0.0
    hit = float(pnl) <= -float(limit_usdt)
    return (True, f"daily_dd {pnl:.2f}<={-float(limit_usdt):.2f}") if hit else (False, "")

def consec_losses_cooldown(max_consec_losses: int, cooldown_bars: int, bar_ms: int) -> Tuple[bool, str, Optional[int]]:
    """
    連虧 N 次後進入冷卻：回 True 表示應該暫停進場
    也會回傳剩餘冷卻 bars（估算）
    """
    if not max_consec_losses or max_consec_losses <= 0:
        return False, "", None

    rows = exec(
        "SELECT exit_ts, pnl_after_cost FROM trades_log ORDER BY exit_ts DESC LIMIT 100"
    ).mappings().all()

    streak = 0
    last_exit = None
    for r in rows:
        if float(r["pnl_after_cost"] or 0.0) < 0:
            streak += 1
            last_exit = int(r["exit_ts"])
        else:
            break

    if streak >= max_consec_losses:
        if cooldown_bars and cooldown_bars > 0 and last_exit:
            now_ms = int(time() * 1000)
            passed_bars = max((now_ms - last_exit) // int(bar_ms), 0)
            remain = max(int(cooldown_bars) - int(passed_bars), 0)
            if remain > 0:
                return True, f"cooldown consec={streak} remain_bars={remain}", remain
        # 沒設定 cooldown_bars 就一律擋
        return True, f"cooldown consec={streak}", 0

    return False, "", None

def blacklist_block(symbol: str, blacklist: Optional[Iterable[str]]) -> Tuple[bool, str]:
    if not blacklist:
        return False, ""
    blocked = symbol in set(blacklist)
    return (True, f"blacklist {symbol}") if blocked else (False, "")

# -------------------------------------------------
# 綜合評估：是否該平倉 / 是否該暫停進場
# -------------------------------------------------
def should_exit(
    direction: str,
    entry_price: float,
    last_price: float,
    opened_at_ms: int,
    bar_ms: int,
    *,
    hard_sl_pct: Optional[float] = None,
    trail_backoff_pct: Optional[float] = None,
    trail_trigger_pct: Optional[float] = 0.0,
    peak_price: Optional[float] = None,
    max_hold_bars: Optional[int] = None,
) -> Tuple[bool, str, Optional[float]]:
    """
    回傳：(should_exit, reason, new_peak_price)
    - 會依序檢查：硬停損 → 移動停損 → 時間停損
    """
    hit, rsn = hard_stop(direction, entry_price, last_price, hard_sl_pct or 0.0)
    if hit:
        journal("HARD_STOP", rsn, "WARN")
        return True, rsn, peak_price

    hit, rsn, new_peak = trailing_stop(
        direction, entry_price, last_price,
        peak_price or 0.0,
        trail_backoff_pct or 0.0,
        trail_trigger_pct or 0.0
    )
    if hit:
        journal("TRAIL_STOP", rsn, "INFO")
        return True, rsn, new_peak

    hit, rsn = time_stop(opened_at_ms, int(max_hold_bars or 0), int(bar_ms))
    if hit:
        journal("TIME_STOP", rsn, "INFO")
        return True, rsn, peak_price

    return False, "", peak_price

def should_block_entry(
    symbol: str,
    *,
    blacklist: Optional[Iterable[str]] = None,
    max_daily_dd_usdt: Optional[float] = None,
    max_consec_losses: Optional[int] = None,
    cooldown_bars: Optional[int] = None,
    bar_ms: int = 60_000,
) -> Tuple[bool, str, Optional[int]]:
    """
    綜合檢查是否暫停新進場
    回傳：(blocked, reason, remain_bars)
    """
    hit, rsn = blacklist_block(symbol, blacklist)
    if hit:
        journal("BLOCK_ENTRY", rsn, "WARN")
        return True, rsn, None

    hit, rsn = daily_max_drawdown_hit(float(max_daily_dd_usdt or 0.0))
    if hit:
        journal("BLOCK_ENTRY", rsn, "CRIT")
        return True, rsn, None

    hit, rsn, remain = consec_losses_cooldown(int(max_consec_losses or 0), int(cooldown_bars or 0), int(bar_ms))
    if hit:
        journal("BLOCK_ENTRY", rsn, "WARN")
        return True, rsn, remain

    return False, "", None
