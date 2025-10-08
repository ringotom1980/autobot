# app/binance/fut_client.py
from typing import Optional, Dict, Any, List
import time, hmac, hashlib, logging, requests
from urllib.parse import urlencode
from ..config import Config

BASE = getattr(Config, "BINANCE_BASE", None) or "https://fapi.binance.com"

log = logging.getLogger("binance")
if not log.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

class FutClient:
    def __init__(self, api_key: Optional[str]=None, api_secret: Optional[str]=None, timeout: int=10) -> None:
        self.k = api_key or getattr(Config, "BINANCE_API_KEY", "") or ""
        self.s = api_secret or getattr(Config, "BINANCE_API_SECRET", "") or ""
        self.timeout = timeout
        self.session = requests.Session()
        if self.k:
            self.session.headers.update({"X-MBX-APIKEY": self.k})

    # ---------- Public ----------
    def klines(self, symbol: str, interval: str, limit: int=500,
               start_time: Optional[int]=None, end_time: Optional[int]=None) -> List[Any]:
        url = f"{BASE}/fapi/v1/klines"
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": int(limit)}
        if start_time is not None: params["startTime"] = int(start_time)
        if end_time is not None: params["endTime"] = int(end_time)
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("klines error: %s url=%s params=%s", e, url, params)
            return []

    def exchange_info(self, symbol: Optional[str]=None) -> Dict[str, Any]:
        url = f"{BASE}/fapi/v1/exchangeInfo"; params: Dict[str, Any] = {}
        if symbol: params["symbol"] = symbol
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning("exchangeInfo error: %s", e)
            return {"symbols":[{"filters": []}]}

    # ---------- Private ----------
    def _sign(self, params: Dict[str, Any]) -> str:
        qs = urlencode(params)
        sig = hmac.new(self.s.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        return qs + "&signature=" + sig

    def account(self) -> Dict[str, Any]:
        url = f"{BASE}/fapi/v2/account"; ts = int(time.time()*1000)
        try:
            qs = self._sign({"timestamp": ts})
            r = self.session.get(url + "?" + qs, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def user_trades(self, symbol: str, start_ms: Optional[int]=None, end_ms: Optional[int]=None, limit: int=1000) -> List[Dict[str, Any]]:
        """
        GET /fapi/v1/userTrades
        """
        url = f"{BASE}/fapi/v1/userTrades"
        params: Dict[str, Any] = {"symbol": symbol.upper(), "limit": int(min(max(limit,1), 1000)), "timestamp": int(time.time()*1000)}
        if start_ms is not None: params["startTime"] = int(start_ms)
        if end_ms is not None: params["endTime"] = int(end_ms)
        try:
            qs = self._sign(params)
            r = self.session.get(url + "?" + qs, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("user_trades error: %s", e)
            return []

    def income(self, symbol: Optional[str]=None, start_ms: Optional[int]=None, end_ms: Optional[int]=None, income_type: Optional[str]=None, limit: int=1000) -> List[Dict[str, Any]]:
        """
        GET /fapi/v1/income  (type=FUNDING_FEE / COMMISSION / etc.)
        """
        url = f"{BASE}/fapi/v1/income"
        params: Dict[str, Any] = {"limit": int(min(max(limit,1), 1000)), "timestamp": int(time.time()*1000)}
        if symbol: params["symbol"] = symbol.upper()
        if start_ms is not None: params["startTime"] = int(start_ms)
        if end_ms is not None: params["endTime"] = int(end_ms)
        if income_type: params["incomeType"] = income_type
        try:
            qs = self._sign(params)
            r = self.session.get(url + "?" + qs, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.warning("income error: %s", e)
            return []
