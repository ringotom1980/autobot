# app/reporter/heartbeat.py
from __future__ import annotations
from typing import Optional, Dict, Any
from ..db import exec

# -------- 低階：寫入 job_progress --------
def set_progress(job_id: str, phase: str, *, symbol: str = "", interval: str = "",
                 step: int = 0, total: int = 1, pct: float | None = None) -> None:
    step_i = max(int(step), 0)
    total_i = max(int(total), 1)
    pct_v = float(round(100.0 * min(step_i / total_i, 1.0), 1)) if pct is None else float(pct)
    exec("""
        INSERT INTO job_progress(job_id, phase, symbol, `interval`, step, total, pct)
        VALUES(:id, :ph, :s, :i, :st, :tt, :pc)
        ON DUPLICATE KEY UPDATE
          phase=VALUES(phase),
          symbol=VALUES(symbol),
          `interval`=VALUES(`interval`),
          step=VALUES(step),
          total=VALUES(total),
          pct=VALUES(pct),
          updated_at=CURRENT_TIMESTAMP
    """, id=job_id[:64], ph=phase[:32], s=symbol[:16], i=interval[:8],
       st=step_i, tt=total_i, pc=pct_v)


# -------- 低階：寫入 risk_journal（以 JOB:<id> 為 rule）--------
def push_error(job_id: str, detail: str, level: str = "CRIT") -> None:
    exec(
        "INSERT INTO risk_journal(ts, rule, detail, level) VALUES(UNIX_TIMESTAMP()*1000, :r, :d, :l)",
        r=f"JOB:{job_id}"[:64], d=detail[:255], l="CRIT" if level not in ("INFO","WARN","CRIT") else level
    )

def push_info(job_id: str, detail: str) -> None:
    exec(
        "INSERT INTO risk_journal(ts, rule, detail, level) VALUES(UNIX_TIMESTAMP()*1000, :r, :d, 'INFO')",
        r=f"JOB:{job_id}"[:64], d=detail[:255]
    )

# -------- 高階：decorator（包住任何 job）--------
def with_heartbeat(job_id: str, *, symbol: str = "", interval: str = ""):
    """
    使用方式：
    @with_heartbeat("collector:BTCUSDT:1m", symbol="BTCUSDT", interval="1m")
    def run():
        ...
    """
    def _wrap(fn):
        def _inner(*args, **kwargs):
            try:
                set_progress(job_id, "RUN", symbol=symbol, interval=interval, step=0, total=1)
                out = fn(*args, **kwargs)
                set_progress(job_id, "OK", symbol=symbol, interval=interval, step=1, total=1, pct=100.0)
                return out
            except Exception as e:
                # 不讓例外把整個 scheduler/main 弄掛
                push_error(job_id, f"{type(e).__name__}: {e}")
                set_progress(job_id, "ERROR", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
                return None
        return _inner
    return _wrap

# -------- 彙總心跳（給 /api/health.php 參考實作邏輯）--------
def summarize(err_window_min: int = 15, stale_after_sec: int = 300) -> list[Dict[str, Any]]:
    """
    回傳每個 job 的狀態：
    [{ job, ok, last_ok_at, last_err_at, err_count_window, message }]
    """
    rows = exec("""
        SELECT jp.job_id, jp.phase, UNIX_TIMESTAMP(jp.updated_at)*1000 AS upd_ms,
               jp.symbol, jp.`interval`, jp.pct
        FROM job_progress jp
        ORDER BY jp.updated_at DESC
    """).mappings().all()
    seen = set()
    jobs = []
    for r in rows:
        jid = r["job_id"]
        if jid in seen:  # 以最新一筆為準
            continue
        seen.add(jid)
        last_ok_at = int(r["upd_ms"])
        # 查最近錯誤
        errs = exec("""
            SELECT MAX(ts) AS last_err, COUNT(*) AS cnt
            FROM risk_journal
            WHERE rule=:rule AND level IN ('WARN','CRIT')
              AND ts >= UNIX_TIMESTAMP()*1000 - :win_ms
        """, rule=f"JOB:{jid}", win_ms=int(err_window_min*60*1000)).mappings().first() or {}
        last_err_at = int(errs.get("last_err") or 0)
        err_cnt = int(errs.get("cnt") or 0)
        # stale 判定
        stale = (exec("SELECT UNIX_TIMESTAMP()*1000").scalar() or 0) - last_ok_at > stale_after_sec*1000
        ok = (r["phase"] == "OK") and (not stale) and (err_cnt < 3)
        jobs.append({
            "job": jid,
            "ok": bool(ok),
            "last_ok_at": last_ok_at,
            "last_err_at": last_err_at or None,
            "err_count_window": err_cnt,
            "phase": r["phase"],
            "symbol": r["symbol"],
            "interval": r["interval"],
            "pct": float(r["pct"] or 0.0),
            "message": "OK" if ok else ("STALE" if stale else r["phase"]),
        })
    return jobs
