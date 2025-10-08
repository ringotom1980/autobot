# app/db.py
from __future__ import annotations
from typing import Optional
import urllib.parse
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Result
from sqlalchemy.exc import OperationalError, InterfaceError

from .config import Config
from . import db_connect

log = logging.getLogger("autobot.db")

_engine: Optional[Engine] = None


def _make_url(cfg: Config) -> str:
    """
    建立 SQLAlchemy 連線字串（MySQL + PyMySQL）
    host/port 固定走隧道 127.0.0.1:3307
    """
    user = (cfg.DB_USER or "").strip()
    pwd_raw = (cfg.DB_PASS or "")
    db = (cfg.DB_NAME or "").strip()
    charset = (cfg.DB_CHARSET or "utf8mb4").strip()

    # 最小必要檢查
    missing = [k for k, v in (("DB_USER", user), ("DB_PASS", pwd_raw), ("DB_NAME", db)) if not v]
    if missing:
        raise RuntimeError(f"DB 連線參數不足，缺少：{', '.join(missing)}；請檢查 .env 或載入順序")

    # 密碼做 URL 編碼，避免含 @ : / # & % 等符號時斷裂
    pwd = urllib.parse.quote_plus(pwd_raw)

    host = "127.0.0.1"
    port = 3307

    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset={charset}"


def _build_engine() -> Engine:
    cfg = Config()
    # 先確保 SSH 隧道已啟動（與舊介面相容）
    db_connect.get_connection().close()
    # 建 Engine：開啟 pre_ping + 合理的 pool 設定，降低 wait_timeout 中斷
    return create_engine(
        _make_url(cfg),
        pool_pre_ping=True,       # 送 SELECT 1 偵測壞連線，自動重連
        pool_recycle=1800,        # 30 分回收，避免被 MySQL wait_timeout 掉線
        pool_size=5,              # 小型專案夠用
        max_overflow=10,          # 高峰時額外連線
        future=True,
    )


def engine() -> Engine:
    """
    Lazy 單例 Engine；隧道確保後建立 Engine
    """
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def _retryable_exec(sql: str, params, *, retry_once: bool = True) -> Result:
    """
    執行 SQL，遇到連線類錯誤做一次自動重試（會重啟隧道 + 重建 Engine）
    """
    global _engine
    try:
        with engine().connect() as conn:
            res: Result = conn.execute(text(sql), params)
            conn.commit()
            return res
    except (OperationalError, InterfaceError) as e:
        if not retry_once:
            raise
        # 常見錯誤碼：2003/2013/2014/2055 等（連線失敗、lost connection、server has gone away）
        log.warning("DB 連線異常，嘗試自動重試一次：%s", e)
        try:
            # 確保隧道仍在（或重啟）
            db_connect.get_connection().close()
        except Exception as ee:
            log.error("重啟 SSH 隧道失敗：%s", ee)
        # 重建 Engine
        try:
            if _engine is not None:
                _engine.dispose(close=True)
        except Exception:
            pass
        _engine = _build_engine()
        # 再試一次
        with engine().connect() as conn:
            res: Result = conn.execute(text(sql), params)
            conn.commit()
            return res


def exec(sql: str, /, **params) -> Result:
    return _retryable_exec(sql, params, retry_once=True)
