# app/session.py
from __future__ import annotations
from time import time
from typing import Optional, Tuple
from .db import exec  # 直接用你現有的 exec()

# -------------------------------------------------
# 基本工具
# -------------------------------------------------
def now_ms() -> int:
    return int(time() * 1000)

# -------------------------------------------------
# Settings 讀/寫
# -------------------------------------------------
def read_settings_basic() -> Tuple[int, str, Optional[int]]:
    """回傳 (is_enabled, trade_mode, current_session_id)"""
    row = exec("SELECT is_enabled, trade_mode, current_session_id FROM settings WHERE id=1").mappings().first()
    if not row:
        return 1, "SIM", None
    is_enabled = int(row.get("is_enabled") or 1)
    trade_mode = str(row.get("trade_mode") or "SIM").upper()
    cur_sid = row.get("current_session_id")
    return is_enabled, trade_mode, (int(cur_sid) if cur_sid is not None else None)

def set_current_session(session_id: Optional[int]) -> None:
    if session_id is None:
        exec("UPDATE settings SET current_session_id=NULL WHERE id=1")
    else:
        exec("UPDATE settings SET current_session_id=:sid WHERE id=1", sid=int(session_id))

# -------------------------------------------------
# Session 建立/結束邏輯
# -------------------------------------------------
def get_active_session_id() -> Optional[int]:
    """優先用 settings.current_session_id；沒有就用 run_sessions.is_active=1 的最新一筆"""
    _en, _mode, cur = read_settings_basic()
    if cur is not None:
        return cur
    sid = exec("SELECT session_id FROM run_sessions WHERE is_active=1 ORDER BY started_at DESC LIMIT 1").scalar()
    return int(sid) if sid is not None else None

def create_session_if_needed() -> Optional[int]:
    """當 settings.is_enabled=1 且沒有 current_session_id → 建立新 session"""
    is_enabled, trade_mode, cur = read_settings_basic()
        # ★ 若 current_session_id 指向的 session 已結束或不存在 → 視為沒有 session
    if cur is not None:
        row = exec("SELECT is_active FROM run_sessions WHERE session_id=:sid", sid=int(cur)).mappings().first()
        if (not row) or int(row.get("is_active", 0)) == 0:
            set_current_session(None)
            cur = None

    if is_enabled != 1:
        return None
    if cur is not None:
        return cur

    ts = now_ms()
    exec("INSERT INTO run_sessions (started_at, stopped_at, mode, is_active) VALUES (:st, NULL, :m, 1)",
         st=ts, m=trade_mode)
    new_id = exec("SELECT LAST_INSERT_ID()").scalar()
    sid = int(new_id) if new_id is not None else None
    if sid is not None:
        set_current_session(sid)
    return sid

def close_session_if_needed() -> None:
    """當 settings.is_enabled=0 且 current_session_id 不為 NULL → 結束該 session"""
    is_enabled, _mode, cur = read_settings_basic()
    if cur is None:
        return
    if is_enabled == 0:
        ts = now_ms()
        exec("UPDATE run_sessions SET stopped_at=:t, is_active=0 WHERE session_id=:sid", t=ts, sid=int(cur))
        set_current_session(None)
