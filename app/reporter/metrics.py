# app/reporter/metrics.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import json
from ..db import exec  # 若你改成 q，請用：from ..db import q as exec

def _rows(sql: str, **params):
    return exec(sql, **params).mappings().all()

def _scalar(sql: str, **params):
    return exec(sql, **params).scalar()

def _get_symbols() -> List[str]:
    r = _rows("SELECT symbols_json FROM settings WHERE id=1")
    if not r:
        return []
    try:
        return list(json.loads(r[0]["symbols_json"] or "[]"))
    except Exception:
        return []

def _now_ms() -> int:
    return int(_scalar("SELECT UNIX_TIMESTAMP()*1000") or 0)

def _start_ms_days_ago(days: int) -> int:
    return int(_scalar("SELECT UNIX_TIMESTAMP(DATE_SUB(NOW(), INTERVAL :d DAY))*1000", d=days) or 0)

def kpis_today() -> Dict[str, Any]:
    start = int(_scalar("SELECT UNIX_TIMESTAMP(CURDATE())*1000") or 0)  # 今日 00:00:00
    row = _rows(
        """
        SELECT
          COALESCE(SUM(pnl_after_cost),0)        AS pnl,
          COALESCE(SUM(fee),0)                   AS fee,
          COALESCE(SUM(CASE WHEN pnl_after_cost>0 THEN 1 ELSE 0 END),0) AS wins,
          COALESCE(SUM(CASE WHEN pnl_after_cost<0 THEN 1 ELSE 0 END),0) AS losses,
          COALESCE(COUNT(*),0)                   AS n
        FROM trades_log
        WHERE exit_ts >= :start
        """, start=start
    )[0]
    gross_abs = abs(float(row["pnl"])) + float(row["fee"])
    fee_ratio = (float(row["fee"]) / gross_abs) if gross_abs > 0 else 0.0
    winrate = (float(row["wins"]) / max(int(row["n"]), 1)) if row["n"] else 0.0
    return {
        "pnl_today": float(row["pnl"]),
        "fee_today": float(row["fee"]),
        "fee_ratio_today": float(fee_ratio),
        "trades_today": int(row["n"]),
        "winrate_today": float(winrate),
    }

def series_7d() -> List[Dict[str, Any]]:
    start7 = _start_ms_days_ago(7)
    rows = _rows(
        """
        SELECT exit_ts, pnl_after_cost AS pnl, fee
        FROM trades_log
        WHERE exit_ts >= :start
        ORDER BY exit_ts ASC
        """, start=start7
    )
    return [dict(r) for r in rows]

def max_drawdown_7d() -> float:
    rows = series_7d()
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for r in rows:
        eq += float(r["pnl"] or 0.0)
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return float(mdd)  # 負值

def win_rr_7d() -> Tuple[float, float]:
    rows = series_7d()
    wins = [float(r["pnl"]) for r in rows if float(r["pnl"]) > 0]
    losses = [abs(float(r["pnl"])) for r in rows if float(r["pnl"]) < 0]
    n = len(rows)
    winrate = (len(wins) / n) if n > 0 else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    rr = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    return float(winrate), float(rr)

def fee_ratio_7d() -> float:
    rows = series_7d()
    fee = sum(float(r["fee"] or 0.0) for r in rows)
    gross_abs = sum(abs(float(r["pnl"] or 0.0)) for r in rows) + fee
    return float(fee / gross_abs) if gross_abs > 0 else 0.0

def consec_losses_current() -> int:
    rows = _rows(
        "SELECT pnl_after_cost FROM trades_log ORDER BY exit_ts DESC LIMIT 200"
    )
    k = 0
    for r in rows:
        if float(r["pnl_after_cost"]) < 0:
            k += 1
        else:
            break
    return k

def open_positions_summary() -> List[Dict[str, Any]]:
    rows = _rows(
        """
        SELECT symbol, direction, entry_price, qty, leverage, opened_at
        FROM positions
        WHERE status='OPEN'
        ORDER BY opened_at DESC
        """
    )
    return [dict(r) for r in rows]

def latest_regime(symbol: str, interval: str) -> Optional[int]:
    r = _rows(
        """
        SELECT regime FROM features
        WHERE symbol=:s AND `interval`=:i
        ORDER BY close_time DESC LIMIT 1
        """, s=symbol, i=interval
    )
    return int(r[0]["regime"]) if r else None


def dashboard_metrics() -> Dict[str, Any]:
    today = kpis_today()
    wr7, rr7 = win_rr_7d()
    mdd7 = max_drawdown_7d()
    fee7 = fee_ratio_7d()
    opens = open_positions_summary()
    syms = _get_symbols()
    # 只抓第一個 symbol 的 1m 當前 regime（可視需求擴充）
    reg = latest_regime(syms[0], "1m") if syms else None
    return {
        **today,
        "winrate_7d": float(wr7),
        "rr_7d": float(rr7),
        "max_drawdown_7d": float(mdd7),  # 負值
        "fee_ratio_7d": float(fee7),
        "open_positions": opens,
        "current_regime": reg,
        "now_ms": _now_ms(),
    }
