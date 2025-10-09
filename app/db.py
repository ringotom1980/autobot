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


# app/db.py

def _build_engine() -> Engine:
    cfg = Config()
    # 先確保 SSH 隧道已啟動（與舊介面相容）
    db_connect.get_connection().close()
    # ★ 等 0.3s，給隧道一個穩定時間窗（避免剛起來就握手失敗）
    import time; time.sleep(0.3)

    # 建 Engine：開啟 pre_ping + 較短 recycle + 連線逾時
    return create_engine(
        _make_url(cfg),
        pool_pre_ping=True,          # 取用前先 SELECT 1
        pool_recycle=180,            # ★ 3 分內主動回收，低於常見 wait_timeout
        pool_size=5,
        max_overflow=10,
        pool_reset_on_return="rollback",
        future=True,
        connect_args={               # ★ 防卡死
            "connect_timeout": 10,
            "read_timeout": 10,
            "write_timeout": 10,
            "charset": "utf8mb4",
        },
        isolation_level="AUTOCOMMIT",
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
    global _engine
    try:
        with engine().connect() as conn:
            res: Result = conn.execute(text(sql), params)
            # AUTOCOMMIT 已開，這行留著也無害
            conn.commit()
            return res
    except (OperationalError, InterfaceError) as e:
        if not retry_once:
            raise
        log.warning("DB 連線異常，嘗試自動重試一次：%s", e)

        # 1) 先確保隧道
        try:
            db_connect.get_connection().close()
        except Exception as ee:
            log.error("重啟 SSH 隧道失敗：%s", ee)

        # 2) 丟棄舊池
        try:
            if _engine is not None:
                _engine.dispose(close=True)
        except Exception:
            pass

        # 3) 重建 Engine，並給一點緩衝時間
        _engine = _build_engine()
        import time; time.sleep(0.3)

        # 4) 再試一次
        with engine().connect() as conn:
            res: Result = conn.execute(text(sql), params)
            conn.commit()
            return res


def exec(sql: str, /, **params) -> Result:
    return _retryable_exec(sql, params, retry_once=True)
