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
        pool_pre_ping=True,
        pool_recycle=180,
        pool_size=5,
        max_overflow=10,
        pool_reset_on_return="rollback",
        pool_timeout=10,                 # ★ 借連線拿不到時最多等 10s
        future=True,
        connect_args={
            "connect_timeout": 10,
            "read_timeout": 20,          # ★ 放寬，避免瞬時抖動誤判
            "write_timeout": 20,
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


def _retryable_exec(sql: str, params, *, max_retries: int = 2) -> Result:
    global _engine
    delay = 0.8
    attempt = 0
    while True:
        try:
            with engine().connect() as conn:
                res: Result = conn.execute(text(sql), params)
                conn.commit()
                return res
        except (OperationalError, InterfaceError) as e:
            msg = str(e).lower()
            lost = ("lost connection" in msg or "server has gone away" in msg
                    or "is not connected" in msg or "timeout" in msg)
            if not lost or attempt >= max_retries:
                raise
            log.warning("DB 連線問題，%.1fs 後重試（%d/%d）: %s", delay, attempt+1, max_retries, e)

            # 先確保隧道
            try:
                db_connect.get_connection().close()
            except Exception as ee:
                log.warning("確保 SSH 隧道失敗: %s", ee)

            # 丟棄舊池、重建
            try:
                if _engine is not None:
                    _engine.dispose(close=True)
            except Exception:
                pass
            _engine = _build_engine()

            import time
            time.sleep(delay)
            delay = min(delay * 1.8, 5.0)
            attempt += 1



def exec(sql: str, /, **params) -> Result:
    return _retryable_exec(sql, params, max_retries=2)
