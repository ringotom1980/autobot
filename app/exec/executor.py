# app/exec/executor.py
from __future__ import annotations
from typing import Optional, Dict, Any, Tuple
from time import time
import json

from ..db import exec  # 若你改成 q，請改成：from ..db import q as exec
from ..learner.rewards import book_trade
from ..risk.sizing import size_by_atr
from ..risk.guards import should_block_entry, should_exit, journal
from ..binance.fut_client import FutClient

# -------------------------------------------------
# 常見 bar 時長（毫秒）
# -------------------------------------------------
BAR_MS = {"1m": 60_000, "15m": 900_000,
          "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}

# -------------------------------------------------
# 表結構自檢（不破壞既有資料）
# -------------------------------------------------
exec("""
CREATE TABLE IF NOT EXISTS positions (
  pos_id BIGINT NOT NULL AUTO_INCREMENT,
  symbol VARCHAR(16) NOT NULL,
  direction ENUM('LONG','SHORT') NOT NULL,
  entry_price DOUBLE NOT NULL,
  qty DOUBLE NOT NULL,
  margin_type VARCHAR(16) DEFAULT 'ISOLATED',
  leverage INT DEFAULT 1,
  status ENUM('OPEN','CLOSED') NOT NULL DEFAULT 'OPEN',
  opened_at BIGINT NOT NULL,
  closed_at BIGINT NULL,
  pnl_after_cost DOUBLE DEFAULT 0,
  PRIMARY KEY (pos_id),
  KEY idx_positions_s (symbol),
  KEY idx_positions_o (status, opened_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""")
exec("ALTER TABLE positions ADD COLUMN IF NOT EXISTS `interval` VARCHAR(8) NULL")
exec("ALTER TABLE positions ADD COLUMN IF NOT EXISTS `template_id` BIGINT NULL")
exec("ALTER TABLE positions ADD COLUMN IF NOT EXISTS `regime_entry` TINYINT NULL")
exec("ALTER TABLE positions ADD COLUMN IF NOT EXISTS `opened_bar_ms` INT NULL")
exec("ALTER TABLE positions ADD COLUMN IF NOT EXISTS `peak_price` DOUBLE NULL")


exec("""
CREATE TABLE IF NOT EXISTS run_sessions (
  session_id BIGINT NOT NULL AUTO_INCREMENT,
  started_at BIGINT NOT NULL,
  stopped_at BIGINT DEFAULT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  trade_mode ENUM('SIM','LIVE') NOT NULL DEFAULT 'SIM',
  PRIMARY KEY (session_id),
  KEY idx_active (is_active),
  KEY idx_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""")

exec("""
CREATE TABLE IF NOT EXISTS decisions_log (
  id BIGINT NOT NULL AUTO_INCREMENT,
  session_id BIGINT DEFAULT NULL,
  ts BIGINT NOT NULL,
  symbol VARCHAR(16) NOT NULL,
  `interval` VARCHAR(8) NOT NULL,
  action ENUM('LONG','SHORT','HOLD') NOT NULL,
  is_flat TINYINT(1) NOT NULL DEFAULT 1,
  E_long DOUBLE DEFAULT NULL,
  E_short DOUBLE DEFAULT NULL,
  template_id BIGINT DEFAULT NULL,
  PRIMARY KEY (id),
  KEY idx_sess (session_id),
  KEY idx_time (ts),
  KEY idx_sym_iv (symbol, `interval`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""")

# -------------------------------------------------
# 小工具
# -------------------------------------------------


def _bar_ms_of(interval: str) -> int:
    return int(BAR_MS.get(interval, 60_000))


def _safe_load_json(s: Optional[str], fallback):
    try:
        if s is None:
            return fallback
        return json.loads(s)
    except Exception:
        return fallback


def _latest_px(symbol: str, interval: str) -> Optional[Tuple[int, float]]:
    r = exec(
        "SELECT close_time, close FROM candles WHERE symbol=:s AND `interval`=:i ORDER BY close_time DESC LIMIT 1",
        s=symbol, i=interval
    ).mappings().first()
    if not r:
        return None
    return int(r["close_time"]), float(r["close"])


def _latest_regime(symbol: str, interval: str) -> int:
    r = exec(
        "SELECT regime FROM features WHERE symbol=:s AND `interval`=:i ORDER BY close_time DESC LIMIT 1",
        s=symbol, i=interval
    ).mappings().first()
    return int(r["regime"]) if r and r["regime"] is not None else 1


def _avg_atr_pct(symbol: str, interval: str, k: int = 20) -> float:
    rows = exec(
        "SELECT atr_pct FROM features WHERE symbol=:s AND `interval`=:i ORDER BY close_time DESC LIMIT :k",
        s=symbol, i=interval, k=int(k)
    ).mappings().all()
    if not rows:
        return 0.0
    return float(sum(float(r["atr_pct"] or 0.0) for r in rows) / len(rows))


def _settings_for(symbol: str) -> Dict[str, Any]:
    r = exec("SELECT leverage_json, invest_usdt_json, max_risk_pct FROM settings WHERE id=1").mappings().first()
    if not r:
        return {"invest_usdt": 100.0, "leverage": 1, "max_risk_pct": 0.01}
    lev_map = _safe_load_json(r.get("leverage_json"), {})
    inv_map = _safe_load_json(r.get("invest_usdt_json"), {})
    leverage = int(lev_map.get(symbol) or next(iter(lev_map.values()), 1) or 1)
    invest_usdt = float(inv_map.get(symbol) or next(
        iter(inv_map.values()), 100.0) or 100.0)
    return {"invest_usdt": invest_usdt, "leverage": leverage, "max_risk_pct": float(r.get("max_risk_pct") or 0.01)}


def _exit_settings() -> Dict[str, Any]:
    r = exec("""
        SELECT hard_sl_pct, trail_backoff_pct, trail_trigger_pct, max_hold_bars
        FROM settings WHERE id=1
    """).mappings().first()
    return {
        "hard_sl_pct":   (float(r.get("hard_sl_pct")) if r and r.get("hard_sl_pct") is not None else None),
        "trail_backoff": (float(r.get("trail_backoff_pct")) if r and r.get("trail_backoff_pct") is not None else None),
        "trail_trigger": (float(r.get("trail_trigger_pct")) if r and r.get("trail_trigger_pct") is not None else 0.0),
        "max_hold_bars": (int(r.get("max_hold_bars")) if r and r.get("max_hold_bars") is not None else None),
    }


def _settings_mode_and_costs() -> Dict[str, Any]:
    r = exec("SELECT trade_mode, live_armed, fee_rate, slip_rate FROM settings WHERE id=1").mappings().first()
    if not r:
        return {"trade_mode": "SIM", "live_armed": 0, "fee_rate": 0.0004, "slip_rate": 0.0005}
    return {
        "trade_mode": str(r.get("trade_mode") or "SIM").upper(),
        "live_armed": int(r.get("live_armed") or 0),
        "fee_rate": float(r.get("fee_rate") or 0.0004),
        "slip_rate": float(r.get("slip_rate") or 0.0005),
    }


def _settings_risk(symbol: str) -> Dict[str, Any]:
    r = exec("""
        SELECT adv_enabled, max_daily_dd_pct, max_consec_losses, cooldown_bars, min_hold_bars,
               leverage_json, invest_usdt_json
          FROM settings WHERE id=1
    """).mappings().first() or {}

    # adv_enabled 控制「是否啟用進階進場風控 + 最小持有棒數」
    adv = int(r.get("adv_enabled") or 0) == 1

    if not adv:
        # 關閉：全部條件視為不啟用
        return {
            "enabled": False,
            "max_daily_dd_usdt": None,
            "max_consec_losses": 0,
            "cooldown_bars": 0,
            "min_hold_bars": 0,
        }

    # 開啟：照數值計算
    md   = r.get("max_daily_dd_pct")
    mcl  = r.get("max_consec_losses")
    cd   = r.get("cooldown_bars")
    mh   = r.get("min_hold_bars")

    def _load(s, fb="{}"):
        try: return json.loads(s or fb)
        except Exception: return json.loads(fb)
    inv_map = _load(r.get("invest_usdt_json"))
    invest_usdt = float(inv_map.get(symbol) or next(iter(inv_map.values()), 100.0) or 100.0)
    max_dd_usdt = (invest_usdt * float(md)) if md not in (None, 0, 0.0) else None

    return {
        "enabled": True,
        "max_daily_dd_usdt": max_dd_usdt,      # None 表示不啟用此條件
        "max_consec_losses": int(mcl or 0),
        "cooldown_bars":     int(cd  or 0),
        "min_hold_bars":     int(mh  or 0),
    }



def _update_peak(pos_id: int, new_peak: float) -> None:
    exec("UPDATE positions SET peak_price=:pp WHERE pos_id=:id",
         pp=float(new_peak), id=int(pos_id))


def _get_open_pos(symbol: str, interval: str) -> Optional[Dict[str, Any]]:
    r = exec(
        "SELECT * FROM positions WHERE symbol=:s AND `interval`=:i AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
        s=symbol, i=interval
    ).mappings().first()
    return dict(r) if r else None


def _active_session_id() -> Optional[int]:
    """
    優先取 settings.current_session_id；沒有再 fallback 到 run_sessions.is_active=1
    """
    try:
        from ..session import get_active_session_id  # 已有於 app/session.py
        sid = get_active_session_id()
        if sid is not None:
            return int(sid)
    except Exception:
        pass
    sid = exec(
        "SELECT session_id FROM run_sessions WHERE is_active=1 ORDER BY started_at DESC LIMIT 1"
    ).scalar()
    return int(sid) if sid is not None else None



def _log_decision(session_id: Optional[int], symbol: str, interval: str, decision: Dict[str, Any]) -> None:
    ts = int(time() * 1000)
    action = str(decision.get("action", "HOLD")).upper()
    E_long = float(decision.get("E_long", 0.0) or 0.0)
    E_short = float(decision.get("E_short", 0.0) or 0.0)
    tid = decision.get("template_id")
    is_flat = 1 if (_get_open_pos(symbol, interval) is None) else 0
    exec(
        """
        INSERT INTO decisions_log(session_id, ts, symbol, `interval`, action, is_flat, E_long, E_short, template_id)
        VALUES(:sid, :ts, :s, :i, :a, :flat, :el, :es, :tid)
        """,
        sid=session_id, ts=ts, s=symbol, i=interval, a=action, flat=is_flat,
        el=E_long, es=E_short, tid=int(tid) if tid is not None else None
    )

# -------------------------------------------------
# 成本模型（模擬 / 真實覆蓋）
# -------------------------------------------------


def _sim_costs(entry_price: float, exit_price: float, qty_signed: float,
               fee_rate: float, slip_rate: float) -> Dict[str, float]:
    """
    模擬成本：
    commission = (entry_notional + exit_notional) * fee_rate
    slippage   = (entry_notional + exit_notional) * slip_rate
    """
    entry_notional = abs(float(entry_price) * float(qty_signed))
    exit_notional = abs(float(exit_price) * float(qty_signed))
    base = entry_notional + exit_notional
    commission = base * float(fee_rate)
    slippage = base * float(slip_rate)
    gross_pnl = (float(exit_price) - float(entry_price)) * float(qty_signed)
    pnl_after = gross_pnl - commission - slippage
    return {
        "commission": float(commission),
        "slippage":   float(slippage),
        "gross_pnl":  float(gross_pnl),
        "pnl_after":  float(pnl_after),
    }


def _binance_costs_cover(symbol: str, entry_ts_ms: int, exit_ts_ms: int) -> Dict[str, float]:
    """
    從 Binance 取實際 commission / funding_fee（若 API 可用），失敗回傳 {}。
    這裡示意以 FutClient 的方法：user_trades() / income()
    """
    try:
        cli = FutClient()
        # commission：/fapi/v1/userTrades 匯總（抓寬一點時間窗避免邊界）
        trades = cli.user_trades(
            symbol=symbol, start_ms=entry_ts_ms - 3_600_000, end_ms=exit_ts_ms + 3_600_000)
        commission = 0.0
        for t in trades or []:
            commission += float(t.get("commission", 0.0) or 0.0)

        # funding fee：/fapi/v1/income?incomeType=FUNDING_FEE
        incomes = cli.income(symbol=symbol, start_ms=entry_ts_ms - 3_600_000,
                             end_ms=exit_ts_ms + 3_600_000, income_type="FUNDING_FEE")
        funding_fee = 0.0
        for inc in incomes or []:
            funding_fee += float(inc.get("income", 0.0) or 0.0)

        return {"commission": float(commission), "funding_fee": float(funding_fee)}
    except Exception:
        return {}

# -------------------------------------------------
# 你原本相容 API
# -------------------------------------------------


def open_position(symbol: str, direction: str, price: float, qty: float, leverage: int) -> Optional[int]:
    if qty is None or qty <= 0:
        return None
    sid = _active_session_id()
    ts = int(time() * 1000)
    exec(
        """
        INSERT INTO positions(symbol, direction, entry_price, qty, margin_type, leverage, status, opened_at, session_id)
        VALUES(:s, :d, :p, :q, 'ISOLATED', :lev, 'OPEN', :ts, :sid)
        """,
        s=symbol, d=direction, p=price, q=qty, lev=int(leverage), ts=ts, sid=sid
    )
    pos_id = exec(
        "SELECT pos_id FROM positions WHERE symbol=:s AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
        s=symbol
    ).scalar()
    return int(pos_id) if pos_id is not None else None


def close_position(symbol: str, price: float) -> Optional[float]:
    pos = exec("SELECT * FROM positions WHERE symbol=:s AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
               s=symbol).mappings().first()
    if not pos:
        return None
    direction = pos["direction"]
    entry_price = float(pos["entry_price"])
    qty = float(pos["qty"])
    pnl = (price - entry_price) * qty * (1.0 if direction == "LONG" else -1.0)
    ts = int(time() * 1000)
    exec("UPDATE positions SET status='CLOSED', closed_at=:ts, pnl_after_cost=:pnl WHERE pos_id=:id",
         ts=ts, pnl=pnl, id=pos["pos_id"])
    return pnl


def current_direction(symbol: str) -> Optional[str]:
    r = exec("SELECT direction FROM positions WHERE symbol=:s AND status='OPEN' ORDER BY opened_at DESC LIMIT 1", s=symbol).scalar()
    return r if r in ("LONG", "SHORT") else None


def has_open_position(symbol: str) -> bool:
    r = exec(
        "SELECT COUNT(*) FROM positions WHERE symbol=:s AND status='OPEN'", s=symbol).scalar()
    return bool(r and int(r) > 0)

# -------------------------------------------------
# 強化版 開/平倉（含成本模型）
# -------------------------------------------------


def open_position_v2(symbol: str, interval: str, direction: str, price: float, qty: float, leverage: int, *, template_id: Optional[int], regime_entry: int) -> Optional[int]:
    if qty is None or qty <= 0:
        return None
    sid = _active_session_id()

    ts = int(time() * 1000)
    exec(
        """
                INSERT INTO positions(symbol, `interval`, direction, entry_price, qty, margin_type, leverage,
                              status, opened_at, template_id, regime_entry, opened_bar_ms, peak_price, session_id)
        VALUES(:s, :i, :d, :p, :q, 'ISOLATED', :lev, 'OPEN', :ts, :tid, :reg, :bar, :pp, :sid)

        """,
        s=symbol, i=interval, d=direction, p=price, q=qty, lev=int(leverage),
        ts=ts, tid=int(template_id) if template_id is not None else None,
        reg=int(regime_entry), bar=_bar_ms_of(interval), pp=float(price), sid=sid

    )
    pos_id = exec(
        "SELECT pos_id FROM positions WHERE symbol=:s AND `interval`=:i AND status='OPEN' ORDER BY opened_at DESC LIMIT 1",
        s=symbol, i=interval
    ).scalar()
    # 模擬委託紀錄（orders）
    exec("""
        INSERT INTO orders(symbol, side, type, qty, price, status, placed_at, reason, session_id)
        VALUES(:s, :side, 'MARKET', :q, :p, 'FILLED', UNIX_TIMESTAMP()*1000, 'SIM_ORDER', :sid)
    """, s=symbol, side=direction, q=qty, p=price, sid=sid)

    return int(pos_id) if pos_id is not None else None


def close_position_v2(symbol: str, interval: str, last_price: float) -> Optional[float]:
    pos = _get_open_pos(symbol, interval)
    if not pos:
        return None

    mode = _settings_mode_and_costs()
    direction = pos["direction"]
    entry_price = float(pos["entry_price"])
    qty = float(pos["qty"])
    entry_ts = int(pos["opened_at"])
    template_id = pos.get("template_id")
    regime = int(pos.get("regime_entry") or _latest_regime(symbol, interval))
    qty_signed = float(qty) if direction == "LONG" else -float(qty)
    ts = int(time() * 1000)

    # 先做模擬成本（雙模式皆有，用於 fallback）
    sim = _sim_costs(entry_price, float(last_price), qty_signed,
                     mode["fee_rate"], mode["slip_rate"])
    fee = sim["commission"]
    slp = sim["slippage"]
    funding_fee = 0.0

    # 若 LIVE 且已 armed → 用幣安覆蓋實值（取不到則沿用模擬值；並可記一條 risk_journal）
    if mode["trade_mode"] == "LIVE" and mode["live_armed"] == 1:
        cover = _binance_costs_cover(symbol, entry_ts, ts)
        if cover:
            fee = float(cover.get("commission", fee))
            funding_fee = float(cover.get("funding_fee", 0.0))
        else:
            journal("BINANCE_COST_FETCH",
                    f"{symbol} entry={entry_ts} exit={ts}", "WARN")

    # 寫 trades_log（由 book_trade 計算 pnl_after_cost 與 reward & 回傳）
    reward, pnl_after_db = book_trade(
        symbol=symbol,
        interval=interval,
        template_id=int(template_id) if template_id is not None else None,
        regime=int(regime),
        entry_ts=entry_ts,
        exit_ts=ts,
        entry_price=float(entry_price),
        exit_price=float(last_price),
        qty=float(qty_signed),                # LONG 正 / SHORT 負
        fee=float(fee),
        slippage=float(slp),
        funding_fee=float(funding_fee),
        risk_used=0.0,                        # 如有風險額度可填進來
        market_features_json=None,
    )

    # 補上 session_id 到 trades_log：用持倉的 session_id（避免跨 session 收單歸錯帳）
    sid = int(pos.get("session_id")) if pos.get("session_id") is not None else _active_session_id()
    if sid is not None:
        exec("""
            UPDATE trades_log
            SET session_id=:sid
             WHERE symbol=:s AND `interval`=:i AND entry_ts=:ent AND exit_ts=:ext
            ORDER BY trade_id DESC
            LIMIT 1
        """, sid=sid, s=symbol, i=interval, ent=entry_ts, ext=ts)


    exec(
        "UPDATE positions SET status='CLOSED', closed_at=:ts, pnl_after_cost=:p WHERE pos_id=:id",
        ts=ts, p=float(pnl_after_db), id=pos["pos_id"]
    )
    return float(pnl_after_db)

# -------------------------------------------------
# 訊號→動作
# -------------------------------------------------


def apply_decision(symbol: str, interval: str, decision: Dict[str, Any]) -> None:
    _log_decision(_active_session_id(), symbol, interval, decision)

    px = _latest_px(symbol, interval)
    if not px:
        return
    _close_time, last_price = px

    cur_pos = _get_open_pos(symbol, interval)
    action = decision.get("action", "HOLD")
    new_side = action if action in ("LONG", "SHORT") else None

    # 有持倉且訊號反向/無訊號 → 先平倉（但先尊重最小持有棒數）
    # === 有持倉 → 先跑風控出場 should_exit（硬停損 / 移動停損 / 時間停損） ===
    if cur_pos:
        cur_side = cur_pos["direction"]
        entry_px = float(cur_pos["entry_price"])
        opened_ms = int(cur_pos["opened_at"])
        bar_ms = int(cur_pos.get("opened_bar_ms") or _bar_ms_of(interval))
        prev_peak = float(cur_pos.get("peak_price") or entry_px)

        es = _exit_settings()
        hit, rsn, new_peak = should_exit(
            direction=cur_side,
            entry_price=entry_px,
            last_price=float(last_price),
            opened_at_ms=opened_ms,
            bar_ms=bar_ms,
            hard_sl_pct=es["hard_sl_pct"],
            trail_backoff_pct=es["trail_backoff"],
            trail_trigger_pct=es["trail_trigger"],
            peak_price=prev_peak,
            max_hold_bars=es["max_hold_bars"],
        )

        # 同步峰值（即使沒出場也要更新）
        if new_peak is not None and abs(new_peak - prev_peak) > 1e-12:
            _update_peak(int(cur_pos["pos_id"]), float(new_peak))

        # 若觸發任何出場條件 → 直接平倉並結束本根
        if hit:
            pnl = close_position_v2(symbol, interval, float(last_price))
            journal(
                "AUTO_EXIT", f"{rsn}; pnl={pnl:.6f}" if pnl is not None else rsn, "INFO")
            return

        # === 未觸發風控出場 → 才評估反向/無訊號平倉（保留你的最小持有棒數保護） ===
        if (new_side is None) or (new_side != cur_side):
            risk = _settings_risk(symbol)
            min_hold = int(risk["min_hold_bars"] or 0) if risk.get("enabled") else 0
            if min_hold > 0:
                held_bars = max(
                    (int(time()*1000) - int(cur_pos["opened_at"])) // int(bar_ms), 0)
                if held_bars < min_hold:
                    journal(
                        "MIN_HOLD_BLOCK", f"held={held_bars} < min_hold_bars={min_hold}", "INFO")
                    return  # 不平倉也不反向
            pnl = close_position_v2(symbol, interval, float(last_price))
            journal(
                "AUTO_EXIT", f"pnl={pnl:.6f}" if pnl is not None else "flip/hold exit", "INFO")

    # 平掉之後若仍有持倉（同向）→ 不加碼
    cur_pos = _get_open_pos(symbol, interval)
    if cur_pos:
        return

    # 無持倉且 action 不為 LONG/SHORT → 不開倉
    if new_side is None:
        return

    # 風控阻擋（僅當 adv_enabled=1 才會啟用）
    risk = _settings_risk(symbol)
    blocked = False
    reason = ""

    if risk.get("enabled"):
        blocked, reason, _remain = should_block_entry(
            symbol,
            blacklist=None,
            max_daily_dd_usdt=(risk["max_daily_dd_usdt"] if risk["max_daily_dd_usdt"] is not None else 9e18),
            max_consec_losses=int(risk["max_consec_losses"] or 0),
            cooldown_bars=int(risk["cooldown_bars"] or 0),
            bar_ms=_bar_ms_of(interval),
        )

    if blocked:
        journal("BLOCK_ENTRY", reason, "WARN")
        return



    if blocked:
        journal("BLOCK_ENTRY", reason, "WARN")
        return

    # sizing：ATR
    cfg = _settings_for(symbol)
    atr_pct = _avg_atr_pct(symbol, interval, k=20)
    qty = size_by_atr(
        price=float(last_price),
        atr_pct=float(atr_pct),
        invest_usdt=float(cfg["invest_usdt"]),
        leverage=int(cfg["leverage"]),
        max_risk_pct=float(cfg["max_risk_pct"]),
    )
    if qty <= 0:
        journal("NO_SIZE", f"atr_pct={atr_pct:.6f}", "INFO")
        return

    template_id = int(decision.get("template_id") or 1)
    regime = _latest_regime(symbol, interval)
    pos_id = open_position_v2(
        symbol=symbol,
        interval=interval,
        direction=new_side,
        price=float(last_price),
        qty=float(qty),
        leverage=int(cfg["leverage"]),
        template_id=template_id,
        regime_entry=regime,
    )
    if pos_id:
        journal(
            "OPEN", f"{new_side} qty={qty:.6f} px={last_price:.4f} tid={template_id} reg={regime}", "INFO")
