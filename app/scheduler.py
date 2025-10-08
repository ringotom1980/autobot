# app/scheduler.py
from __future__ import annotations
import json, logging
from typing import Tuple, List, Dict
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

try:
    import pytz; TZ = pytz.timezone("Asia/Taipei")
except Exception:
    TZ = None

from .db import exec
from . import db_connect
from .reporter.heartbeat import set_progress, push_error

from .session import create_session_if_needed, close_session_if_needed


log = logging.getLogger("autobot.scheduler")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


# -----------------------------
# 讀取當前設定
# -----------------------------
def _read_settings() -> Tuple[List[str], List[str], int]:
    try:
        row = exec("SELECT symbols_json, intervals_json, is_enabled FROM settings WHERE id=1").mappings().first()
    except Exception as e:
        log.error("讀取 settings 失敗: %s", e)
        return (["BTCUSDT"], ["1m"], 1)

    symbols: List[str] = []
    intervals: List[str] = []

    if row is not None and "is_enabled" in row and row["is_enabled"] is not None:
        try:
            enabled = int(row["is_enabled"])
        except Exception:
            enabled = 1
    else:
        enabled = 1

    if row:
        try:
            symbols = list(json.loads(row["symbols_json"] or "[]"))
        except Exception as e:
            log.warning("settings.symbols_json 解析失敗：%s", e)
        try:
            intervals = list(json.loads(row["intervals_json"] or "[]"))
        except Exception as e:
            log.warning("settings.intervals_json 解析失敗：%s", e)

    if not symbols:
        symbols = ["BTCUSDT"]
    if not intervals:
        intervals = ["1m"]

    return symbols, intervals, enabled


# -----------------------------
# 清除非當前設定的 job_progress（殭屍紀錄）
# -----------------------------
def _cleanup_jobs(active_symbols: List[str], active_intervals: List[str]) -> None:
    try:
        if not active_symbols or not active_intervals:
            return

        syms = tuple(dict.fromkeys(active_symbols))
        ivs  = tuple(dict.fromkeys(active_intervals))

        sym_params: Dict[str, str] = {f"sym{i}": s for i, s in enumerate(syms)}
        iv_params: Dict[str, str]  = {f"iv{i}": v for i, v in enumerate(ivs)}

        sym_placeholders = ", ".join(f":{k}" for k in sym_params.keys())
        iv_placeholders  = ", ".join(f":{k}" for k in iv_params.keys())

        sql = f"""
            DELETE FROM job_progress
            WHERE job_id NOT IN ('main:idle','main:loop','ssh_tunnel')
              AND (
                    (symbol <> '' AND symbol NOT IN ({sym_placeholders}))
                 OR (`interval` <> '' AND `interval` NOT IN ({iv_placeholders}))
              )
        """
        exec(sql, **sym_params, **iv_params)
        log.info("已清除非當前設定的 job_progress 殭屍紀錄")
    except Exception as e:
        push_error("scheduler:cleanup", f"{type(e).__name__}: {e}")
        log.warning("清除 job_progress 殭屻紀錄失敗：%s", e)


# -----------------------------
# 單一 bar 週期任務
# -----------------------------
def _job_one(symbol: str, interval: str) -> None:
    # 每次執行前重新讀設定（關鍵：動態比對）
    cur_syms, cur_ivs, enabled = _read_settings()
    job_base = f"{symbol}:{interval}"
     # 確保 session 狀態正確（依 is_enabled 自動開/關）
    try:
        if enabled == 1:
            create_session_if_needed()
        else:
            close_session_if_needed()
    except Exception as _e:
        log.warning("session 維護失敗：%s", _e)

    if enabled != 1:
        set_progress(f"bar:{job_base}", "SKIP", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        log.info("排程略過（is_enabled=0）：%s %s", symbol, interval)
        return

    # 不在當前設定 → 直接 SKIP，避免舊任務再寫進度
    if (symbol not in cur_syms) or (interval not in cur_ivs):
        set_progress(f"bar:{job_base}", "SKIP", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        log.info("排程略過（不在當前 settings）：%s %s | settings=%s x %s", symbol, interval, cur_syms, cur_ivs)
        return

    # 1) collector
    try:
        set_progress(f"collector:{job_base}", "RUN", symbol=symbol, interval=interval, step=0, total=1)
        from .data.collector import fetch_klines_to_db
        _ = fetch_klines_to_db(symbol=symbol, interval=interval)
        set_progress(f"collector:{job_base}", "OK", symbol=symbol, interval=interval, step=1, total=1, pct=100.0)
    except Exception as e:
        push_error(f"collector:{job_base}", f"{type(e).__name__}: {e}")
        set_progress(f"collector:{job_base}", "ERROR", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        return

    # 2) features
    try:
        set_progress(f"features:{job_base}", "RUN", symbol=symbol, interval=interval, step=0, total=1)
        from .data.features import compute_and_store_features
        _ = compute_and_store_features(symbol=symbol, interval=interval)
        set_progress(f"features:{job_base}", "OK", symbol=symbol, interval=interval, step=1, total=1, pct=100.0)
    except Exception as e:
        push_error(f"features:{job_base}", f"{type(e).__name__}: {e}")
        set_progress(f"features:{job_base}", "ERROR", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        return

    # 3) policy
    try:
        set_progress(f"policy:{job_base}", "RUN", symbol=symbol, interval=interval, step=0, total=1)
        from .policy.policy import evaluate_symbol_interval
        res = evaluate_symbol_interval(symbol=symbol, interval=interval) or {}
        set_progress(f"policy:{job_base}", "OK", symbol=symbol, interval=interval, step=1, total=1, pct=100.0)
        log.info(
            "decision %s %s | action=%s E_long=%.3f E_short=%.3f tmpl=%s",
            symbol, interval, str(res.get("action", "HOLD")).upper(),
            float(res.get("E_long", 0.0)), float(res.get("E_short", 0.0)),
            res.get("template_id"),
        )
    except Exception as e:
        push_error(f"policy:{job_base}", f"{type(e).__name__}: {e}")
        set_progress(f"policy:{job_base}", "ERROR", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        return

    # 4) executor
    try:
        set_progress(f"executor:{job_base}", "RUN", symbol=symbol, interval=interval, step=0, total=1)
        from .exec.executor import apply_decision
        apply_decision(symbol=symbol, interval=interval, decision=res)
        set_progress(f"executor:{job_base}", "OK", symbol=symbol, interval=interval, step=1, total=1, pct=100.0)
    except Exception as e:
        push_error(f"executor:{job_base}", f"{type(e).__name__}: {e}")
        set_progress(f"executor:{job_base}", "ERROR", symbol=symbol, interval=interval, step=0, total=1, pct=0.0)
        return


# -----------------------------
# 掛載並啟動 Scheduler
# -----------------------------
def build_and_start_scheduler() -> BackgroundScheduler:
    db_connect.get_connection().close()

    symbols, intervals, enabled = _read_settings()
        # 啟動當下先整一次 session 狀態，並印出目前 sid
    try:
        if enabled == 1:
            create_session_if_needed()
        else:
            close_session_if_needed()
        cur_sid = exec("SELECT current_session_id FROM settings WHERE id=1").scalar()
        log.info("Session check @boot: is_enabled=%s current_session_id=%s", enabled, cur_sid)
    except Exception as _e:
        log.exception("session 初始化失敗：%s", _e)

    # 啟動前先清殭屍 job_progress（避免前端看到舊的幣種/週期）
    try:
        _cleanup_jobs(symbols, intervals)
    except Exception:
        pass

    scheduler = (BackgroundScheduler(timezone=TZ) if TZ else BackgroundScheduler())
    scheduler.start()
    log.info("Scheduler started. tz=%s is_enabled=%s", getattr(TZ, "zone", "system"), enabled)

    for s in symbols:
        for itv in intervals:
            trig, kwargs = _parse_interval(itv)
            job_id = f"bar_{s}_{itv}"
            try:
                scheduler.add_job(
                    _job_one,
                    trigger=trig,
                    id=job_id,
                    kwargs={"symbol": s, "interval": itv},
                    replace_existing=True,
                    coalesce=True,
                    max_instances=1,
                    **kwargs,
                )
                log.info("掛載任務：%s (%s)", job_id, itv)
            except Exception as e:
                push_error(f"scheduler:{s}:{itv}", f"{type(e).__name__}: {e}")
                log.exception("掛載任務失敗：%s %s | %s", s, itv, e)

    # 每日/每週占位
    try:
        scheduler.add_job(
            lambda: __import__('app.evolver.evolver', fromlist=['evolver']).evolver.run_once(),
            trigger=CronTrigger(hour=23, minute=55, timezone=TZ) if TZ else CronTrigger(hour=23, minute=55),
            id="daily_evolver",
            replace_existing=True, coalesce=True, max_instances=1
        )
        scheduler.add_job(
            lambda: __import__('app.evolver.evolver', fromlist=['evolver']).evolver.run_weekly(),
            trigger=CronTrigger(day_of_week="sun", hour=23, minute=55, timezone=TZ) if TZ else CronTrigger(day_of_week="sun", hour=23, minute=55),
            id="weekly_evolver",
            replace_existing=True, coalesce=True, max_instances=1
        )
    except Exception as e:
        push_error("scheduler:evolver", f"{type(e).__name__}: {e}")
        log.exception("掛載演化任務失敗：%s", e)

    return scheduler


def _parse_interval(interval: str):
    s = (interval or "").lower().strip()
    if s.endswith("m"):
        return ("interval", {"minutes": int(s[:-1] or "1")})
    if s.endswith("h"):
        return ("interval", {"hours": int(s[:-1] or "1")})
    return ("interval", {"minutes": 1})


if __name__ == "__main__":
    import time as _t
    sch = build_and_start_scheduler()
        # 二次保險：主程式入口也建一次並印 sid
    try:
        from .session import create_session_if_needed
        sid = create_session_if_needed()
        log.info("Session check @__main__: created_sid=%s", sid)
    except Exception as _e:
        log.exception("session 檢查（__main__）失敗：%s", _e)

    log.info("app.scheduler 正在背景排程，按 Ctrl+C 結束。")
    try:
        while True:
            _t.sleep(1)
    except KeyboardInterrupt:
        log.info("停止排程…")
        sch.shutdown(wait=False)
