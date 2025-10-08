# app/config.py
from dataclasses import dataclass
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

@dataclass
class Config:
    # ===== DB（固定走 SSH 隧道 → 127.0.0.1:3307）=====
    DB_HOST: str = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT: int = int(os.getenv("DB_PORT", "3307"))
    DB_NAME: str = os.getenv("DB_NAME", "u327657097_autobot_db")
    DB_USER: str = os.getenv("DB_USER", "u327657097_autobot_admin")
    DB_PASS: str = os.getenv("DB_PASS", "")
    DB_CHARSET: str = os.getenv("DB_CHARSET", "utf8mb4")
    DB_COLLATION: str = os.getenv("DB_COLLATION", "utf8mb4_general_ci")

    # ===== SSH（本機開隧道用；你原本 .env 已有）=====
    SSH_HOST: str = os.getenv("SSH_HOST", "")
    SSH_PORT: int = int(os.getenv("SSH_PORT", "22"))
    SSH_USER: str = os.getenv("SSH_USER", "")
    SSH_PASS: str = os.getenv("SSH_PASS", "")

    # ===== Binance =====
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")
    BINANCE_BASE: str = os.getenv("BINANCE_BASE", "https://fapi.binance.com")

    # ===== Runtime =====
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Taipei")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ===== 週期對應策略（不破壞前端；可用 .env 覆蓋）=====
    FETCH_COLD_1M:  int = int(os.getenv("FETCH_COLD_1M", 200))
    FETCH_COLD_15M: int = int(os.getenv("FETCH_COLD_15M", 200))
    FETCH_COLD_30M: int = int(os.getenv("FETCH_COLD_30M", 300))
    FETCH_COLD_1H:  int = int(os.getenv("FETCH_COLD_1H", 400))

    FETCH_INC_1M:   int = int(os.getenv("FETCH_INC_1M", 3))
    FETCH_INC_15M:  int = int(os.getenv("FETCH_INC_15M", 2))
    FETCH_INC_30M:  int = int(os.getenv("FETCH_INC_30M", 2))
    FETCH_INC_1H:   int = int(os.getenv("FETCH_INC_1H", 2))

    LOOKBACK_1M:    int = int(os.getenv("LOOKBACK_1M", 200))
    LOOKBACK_15M:   int = int(os.getenv("LOOKBACK_15M", 200))
    LOOKBACK_30M:   int = int(os.getenv("LOOKBACK_30M", 300))
    LOOKBACK_1H:    int = int(os.getenv("LOOKBACK_1H", 400))

    @staticmethod
    def policy(interval: str) -> dict:
        s = (interval or "").lower()
        if s == "1m":
            return {"cold": Config.FETCH_COLD_1M, "inc": Config.FETCH_INC_1M, "lookback": Config.LOOKBACK_1M}
        if s == "15m":
            return {"cold": Config.FETCH_COLD_15M, "inc": Config.FETCH_INC_15M, "lookback": Config.LOOKBACK_15M}
        if s == "30m":
            return {"cold": Config.FETCH_COLD_30M, "inc": Config.FETCH_INC_30M, "lookback": Config.LOOKBACK_30M}
        if s == "1h":
            return {"cold": Config.FETCH_COLD_1H, "inc": Config.FETCH_INC_1H, "lookback": Config.LOOKBACK_1H}
        return {"cold": Config.FETCH_COLD_1M, "inc": Config.FETCH_INC_1M, "lookback": Config.LOOKBACK_1M}
