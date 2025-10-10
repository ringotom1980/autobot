# app/main.py
from __future__ import annotations
import json, time, logging, math
from typing import Any, Dict, List, Tuple
from .db import exec
from .config import Config
from . import db_connect  # 確保隧道
from .exec.executor import apply_decision
from .reporter.heartbeat import set_progress, push_error
from .session import create_session_if_needed, close_session_if_needed
from .scheduler import build_and_start_scheduler  # ← 新增：啟動 APScheduler（含 daily/weekly evolver）

_SCHED = None  # ← 新增：保存 scheduler 參考，避免被垃圾回收


logging.basicConfig(
    level=getattr(Config, "LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("autobot")

# ---- 內部記憶（避免每輪都做冷啟）----
_cold_done: Dict[Tuple[str,str], bool] = {}

# ---- 工具 ----
def _interval_ms(interval: str) -> int:
    s = (interval or "").lower().strip()
    if s.endswith("m"):
        return int(s[:-1] or "1") * 60_000
    if s.endswith("h"):
        return int(s[:-1] or "1") * 60 * 60_000
    return 60_000  # 預設 1m

def _now_ms_floor(interval_ms: int) -> int:
    now_ms = int(time.time() * 1000)
    return (now_ms // interval_ms) * interval_ms - 1

def _get_last_close_ms(symbol: str, interval: str) -> int | None:
    try:
        r = exec(
            "SELECT MAX(close_time) AS mx FROM candles WHERE symbol=:s AND `interval`=:i",
            s=symbol, i=interval
        ).mappings().first()
        mx = r and r.get("mx")
        return int(mx) if mx is not None else None
    except Exception as e:
        log.warning("讀取最後 close_time 失敗：%s %s | %s", symbol, interval, e)
        return None

def _cold_fill_if_needed(symbol: str, interval: str) -> int:
    key = (symbol, interval)
    if _cold_done.get(key):
        return 0

    itv_ms = _interval_ms(interval)
    target_lookback = int(Config.policy(interval)["lookback"])
    last_close = _get_last_close_ms(symbol, interval)
    now_close = _now_ms_floor(itv_ms)

    need = 0
    if last_close is None:
        need = target_lookback
    else:
        gap = max(0, (now_close - last_close) // itv_ms)
        try:
            r = exec(
                "SELECT COUNT(1) AS cnt FROM candles WHERE symbol=:s AND `interval`=:i",
                s=symbol, i=interval
            ).mappings().first()
            have = int(r.get("cnt", 0))
        except Exception:
            have = 0
        need = max(0, target_lookback - have) + gap

    if need <= 0:
        _cold_done[key] = True
        return 0

    log.info("cold-fill 檢測：%s %s 需補 %d 根 (lookback=%d)", symbol, interval, need, target_lookback)

    inc = int(Config.policy(interval)["inc"])
    inc = max(1, inc)
    wrote_total = 0
    max_rounds = math.ceil(need / inc) + 2

    try:
        from .data.collector import fetch_klines_to_db
    except Exception as e:
        log.exception("載入 collector 失敗，無法補齊：%s", e)
        push_error(f"coldfill:{symbol}:{interval}", f"{type(e).__name__}: {e}")
        return 0

    for _ in range(max_rounds):
        wrote = 0
        try:
            wrote = fetch_klines_to_db(symbol=symbol, interval=interval)
        except Exception as e:
            log.exception("cold-fill 例外：%s %s | %s", symbol, interval, e)
            push_error(f"coldfill:{symbol}:{interval}", f"{type(e).__name__}: {e}")
            break
        wrote_total += int(wrote or 0)

        last_close = _get_last_close_ms(symbol, interval)
        have_row = exec(
            "SELECT COUNT(1) AS cnt FROM candles WHERE symbol=:s AND `interval`=:i",
            s=symbol, i=interval
        ).mappings().first()
        have = int(have_row.get("cnt", 0)) if have_row else 0
        gap = 0 if last_close is None else max(0, (now_close - last_close) // itv_ms)
        still_need = max(0, target_lookback - have) + gap

        log.info("cold-fill 進度：%s %s | 累計寫入=%d，仍需估算=%d", symbol, interval, wrote_total, still_need)

        if still_need <= 0 or wrote == 0:
            break
        time.sleep(0.3)

    _cold_done[key] = True
    return wrote_total

# ---- 設定讀取（包含 is_enabled）----
def read_settings() -> Dict[str, Any]:
    try:
        row = exec("SELECT symbols_json, intervals_json, is_enabled FROM settings WHERE id=1").mappings().first()
    except Exception as e:
        log.error("讀取 settings 失敗: %s", e)
        return {"symbols": ["BTCUSDT"], "intervals": ["1m"], "is_enabled": 1}
    symbols, intervals = [], []
    # ★★ 修正：嚴格讀 is_enabled，避免 0 被 or 1 吃掉
    if row is not None and "is_enabled" in row and row["is_enabled"] is not None:
        try:
            enabled = int(row["is_enabled"])
        except Exception:
            enabled = 1
    else:
        enabled = 1
    if row:
        try: symbols = list(json.loads(row["symbols_json"] or "[]"))
        except Exception as e: log.warning("settings.symbols_json 解析失敗: %s", e)
        try: intervals = list(json.loads(row["intervals_json"] or "[]"))
        except Exception as e: log.warning("settings.intervals_json 解析失敗: %s", e)
    if not symbols: symbols = ["BTCUSDT"]
    if not intervals: intervals = ["1m"]
    return {"symbols": symbols, "intervals": intervals, "is_enabled": enabled}

# ---- 單步工作 ----
def try_collect(symbol: str, interval: str) -> int:
    from .data.collector import fetch_klines_to_db
    wrote = fetch_klines_to_db(symbol=symbol, interval=interval)
    if wrote == 0:
        log.debug("collector wrote 0 rows: %s %s", symbol, interval)
    else:
        log.info("collector wrote: %s %s = %d rows", symbol, interval, wrote)
    return wrote

def try_features(symbol: str, interval: str) -> int:
    from .data.features import compute_and_store_features
    wrote = compute_and_store_features(symbol=symbol, interval=interval)
    if wrote == 0:
        log.debug("features wrote 0 rows: %s %s (candles 可能不足或 NaN 暖機丟棄)", symbol, interval)
    return wrote

def try_policy(symbol: str, interval: str) -> Dict[str, Any]:
    from .policy.policy import evaluate_symbol_interval
    res = evaluate_symbol_interval(symbol=symbol, interval=interval) or {}
    return {"action": str(res.get("action","HOLD")).upper(),
            "E_long": float(res.get("E_long",0.0)),
            "E_short": float(res.get("E_short",0.0)),
            "template_id": res.get("template_id")}

# ---- 主循環 ----
def one_cycle() -> None:
    # ★ 每輪先確保隧道活著（輕量檢查）
    try:
        db_connect.ensure_tunnel_alive()
    except Exception as _e:
        log.warning("ensure_tunnel_alive 失敗：%s", _e)

    st = read_settings()
        # ★ session 維護：依 is_enabled 自動建立/結束
    try:
        if int(st.get("is_enabled", 1)) == 1:
            create_session_if_needed()
        else:
            close_session_if_needed()
    except Exception as e:
        log.warning("session 維護失敗：%s", e)

    if int(st.get("is_enabled", 1)) != 1:
        now_ms = int(exec("SELECT UNIX_TIMESTAMP()*1000").scalar() or 0)
        set_progress("main:idle", "IDLE", step=1, total=1, pct=100.0)
        log.info("策略停用中（is_enabled=0）。heartbeat now_ms=%s", now_ms)
        return

    symbols: List[str] = st["symbols"]; intervals: List[str] = st["intervals"]
    for s in symbols:
        for i in intervals:
            job_base = f"{s}:{i}"
            # 冷啟補資料（只有啟用時才會做）
            try:
                set_progress(f"coldfill:{job_base}", "RUN", symbol=s, interval=i, step=0, total=1)
                cold_wrote = _cold_fill_if_needed(s, i)
                set_progress(f"coldfill:{job_base}", "OK", symbol=s, interval=i, step=1, total=1, pct=100.0)
                if cold_wrote:
                    log.info("cold-fill 完成：%s %s 共寫入 %d 筆", s, i, cold_wrote)
            except Exception as e:
                push_error(f"coldfill:{job_base}", f"{type(e).__name__}: {e}")
                set_progress(f"coldfill:{job_base}", "ERROR", symbol=s, interval=i, step=0, total=1, pct=0.0)

            # collector
            wc = 0
            try:
                set_progress(f"collector:{job_base}", "RUN", symbol=s, interval=i, step=0, total=1)
                wc = try_collect(s, i)
                set_progress(f"collector:{job_base}", "OK", symbol=s, interval=i, step=1, total=1, pct=100.0)
            except Exception as e:
                push_error(f"collector:{job_base}", f"{type(e).__name__}: {e}")
                set_progress(f"collector:{job_base}", "ERROR", symbol=s, interval=i, step=0, total=1, pct=0.0)

            # features
            wf = 0
            try:
                set_progress(f"features:{job_base}", "RUN", symbol=s, interval=i, step=0, total=1)
                wf = try_features(s, i)
                set_progress(f"features:{job_base}", "OK", symbol=s, interval=i, step=1, total=1, pct=100.0)
            except Exception as e:
                push_error(f"features:{job_base}", f"{type(e).__name__}: {e}")
                set_progress(f"features:{job_base}", "ERROR", symbol=s, interval=i, step=0, total=1, pct=0.0)

            # policy
            res = {"action":"HOLD","E_long":0.0,"E_short":0.0,"template_id":None}
            try:
                set_progress(f"policy:{job_base}", "RUN", symbol=s, interval=i, step=0, total=1)
                res = try_policy(s, i)
                set_progress(f"policy:{job_base}", "OK", symbol=s, interval=i, step=1, total=1, pct=100.0)
            except Exception as e:
                push_error(f"policy:{job_base}", f"{type(e).__name__}: {e}")
                set_progress(f"policy:{job_base}", "ERROR", symbol=s, interval=i, step=0, total=1, pct=0.0)

            log.info(
                "decision %s %s | action=%s E_long=%.3f E_short=%.3f tmpl=%s | wrote(candles=%d,features=%d)",
                s, i, res["action"], res["E_long"], res["E_short"], res.get("template_id"), wc, wf
            )
            # executor
            try:
                set_progress(f"executor:{job_base}", "RUN", symbol=s, interval=i, step=0, total=1)
                apply_decision(s, i, res)
                set_progress(f"executor:{job_base}", "OK", symbol=s, interval=i, step=1, total=1, pct=100.0)
            except Exception as e:
                push_error(f"executor:{job_base}", f"{type(e).__name__}: {e}")
                set_progress(f"executor:{job_base}", "ERROR", symbol=s, interval=i, step=0, total=1, pct=0.0)

def main():
    log.info("Autobot shadow mode start. timezone=%s", getattr(Config, "TIMEZONE", "Asia/Taipei"))
    db_connect.get_connection().close()  # 啟隧道
    # === 新增：啟動 APScheduler（會自動掛載 bar 任務 + daily/weekly evolver）===
    global _SCHED
    if _SCHED is None:
        try:
            _SCHED = build_and_start_scheduler(only_evolver=True)
            set_progress("scheduler", "OK", step=1, total=1, pct=100.0)
            log.info("APScheduler 啟動完成（含 daily_evolver / weekly_evolver）")
        except Exception as e:
            push_error("scheduler:start", f"{type(e).__name__}: {e}")
            log.exception("APScheduler 啟動失敗：%s", e)

    # ★ 啟動當下保險：先建/先收一次 session
    try:
        en = int(exec("SELECT is_enabled FROM settings WHERE id=1").scalar() or 0)
        if en == 1:
            create_session_if_needed()
        else:
            close_session_if_needed()
    except Exception as e:
        log.warning("session 啟動檢查失敗：%s", e)


    PERIOD = 60  # 每 60 秒一輪
    while True:
        t0 = time.time()
        # ★★ 迴圈層再做一次保險（和 one_cycle 內的檢查彼此獨立）
        try:
            db_connect.ensure_tunnel_alive()
        except Exception as _e:
            log.warning("ensure_tunnel_alive(main loop) 失敗：%s", _e)
        try:
            one_cycle()
        except Exception as e:
            log.exception("main cycle 例外: %s", e)
            push_error("main:cycle", f"{type(e).__name__}: {e}")
        elapsed = time.time() - t0
        remain = max(0, PERIOD - int(elapsed))
        set_progress("main:loop", "OK", step=1, total=1, pct=100.0)
        log.info("一輪完成，耗時 %.1fs；休息 %ds 後下一輪", elapsed, remain)
        for sec in range(remain, 0, -1):
            if sec % 10 == 0 or sec <= 5:
                log.debug("下一輪倒數：%ds", sec)
            time.sleep(1)

if __name__ == "__main__":
    main()
