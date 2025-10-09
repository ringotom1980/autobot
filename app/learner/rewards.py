# app/learner/rewards.py
from __future__ import annotations
from typing import Optional, Tuple
import json
from ..db import exec as q
from ..learner.horizon import learn_exit_horizon

# -----------------------------------------------
# 防守性建表（不破壞既有；僅在缺表時建立正確版本）
# -----------------------------------------------

# trades_log：與現行 DB 相容（若已存在，這段不會動到現有結構）
q("""
CREATE TABLE IF NOT EXISTS trades_log (
  trade_id BIGINT NOT NULL AUTO_INCREMENT,
  symbol VARCHAR(16) NOT NULL,
  template_id BIGINT NULL,
  regime TINYINT NULL,
  `interval` VARCHAR(8) NOT NULL,
  entry_ts BIGINT NOT NULL,
  exit_ts BIGINT NULL,
  entry_price DOUBLE NOT NULL,
  exit_price DOUBLE NULL,
  qty DOUBLE NOT NULL DEFAULT 0,
  fee DOUBLE DEFAULT 0,
  slippage DOUBLE DEFAULT 0,
  funding_fee DOUBLE DEFAULT 0,
  pnl_after_cost DOUBLE DEFAULT NULL,
  risk_used DOUBLE DEFAULT NULL,
  reward DOUBLE DEFAULT NULL,
  market_features_json LONGTEXT NULL,
  PRIMARY KEY (trade_id),
  KEY idx_tl_time (symbol, `interval`, entry_ts),
  KEY idx_tl_exit_ts (exit_ts),
  KEY idx_tl_siet (symbol, `interval`, exit_ts),
  KEY idx_tpl (template_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
""")

# template_stats：與你匯出的實際表一致（PRIMARY KEY=(template_id, regime)）
q("""
CREATE TABLE IF NOT EXISTS template_stats (
  template_id BIGINT NOT NULL,
  regime TINYINT NOT NULL,
  n_trades INT DEFAULT 0,
  reward_sum DOUBLE DEFAULT 0,
  reward_mean DOUBLE DEFAULT 0,
  reward_var DOUBLE DEFAULT 0,
  last_used_at BIGINT DEFAULT NULL,
  is_frozen TINYINT DEFAULT 0,
  sum_reward DOUBLE NOT NULL DEFAULT 0,  -- 你的表目前就有，先保留作為過渡
  last_pnl DOUBLE NOT NULL DEFAULT 0,
  last_exit_ts BIGINT DEFAULT NULL,
  PRIMARY KEY (template_id, regime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
""")

# -----------------------------------------------
# 小工具
# -----------------------------------------------

def _compute_reward(pnl_after_cost: float, risk_used: float) -> float:
    """Reward 預設等於扣成本後 PnL；若提供 risk_used，可轉成風險報酬。"""
    if risk_used and float(risk_used) != 0.0:
        return float(pnl_after_cost) / float(risk_used)
    return float(pnl_after_cost)

# -----------------------------------------------
# 對外 API
# -----------------------------------------------

def book_trade(
    *,
    symbol: str,
    interval: str,
    template_id: Optional[int],
    regime: int,
    entry_ts: int,
    exit_ts: int,
    entry_price: float,
    exit_price: float,
    qty: float,                  # 多單正數；空單負數
    fee: float = 0.0,
    slippage: float = 0.0,
    funding_fee: float = 0.0,
    risk_used: float = 0.0,
    market_features_json: Optional[str] = None,
) -> Tuple[float, float]:
    """
    寫入 trades_log 並更新 template_stats；
    回傳 (reward, pnl_after_cost)
    """
    gross_pnl = (float(exit_price) - float(entry_price)) * float(qty)
    pnl_after = float(gross_pnl) - float(fee or 0.0) - float(slippage or 0.0) - float(funding_fee or 0.0)
    reward = _compute_reward(pnl_after, risk_used)

    # 寫入成交紀錄
    q("""
    INSERT INTO trades_log(
      symbol, `interval`, template_id, regime,
      entry_ts, exit_ts, entry_price, exit_price,
      qty, fee, slippage, funding_fee, risk_used, pnl_after_cost, reward, market_features_json
    ) VALUES (
      :s, :i, :tid, :reg,
      :ent, :ext, :ep, :xp,
      :q, :fee, :slp, :fuf, :risk, :pnl, :rw, :mf
    )
    """,
      s=symbol, i=interval, tid=int(template_id) if template_id is not None else None,
      reg=int(regime),
      ent=int(entry_ts), ext=int(exit_ts),
      ep=float(entry_price), xp=float(exit_price),
      q=float(qty),
      fee=float(fee or 0.0), slp=float(slippage or 0.0), fuf=float(funding_fee or 0.0),
      risk=float(risk_used or 0.0),
      pnl=float(pnl_after), rw=float(reward),
      mf=(market_features_json if market_features_json is None
          else (market_features_json if isinstance(market_features_json, str)
                else json.dumps(market_features_json, ensure_ascii=False)))
    )

    # 更新 template_stats（以 (template_id, regime) 為鍵）
    if template_id is not None:
        q("""
        INSERT INTO template_stats(template_id, regime, n_trades, reward_sum, last_pnl, last_exit_ts, sum_reward)
        VALUES(:tid, :reg, 1, :rw, :pnl, :ext, :rw)
        ON DUPLICATE KEY UPDATE
          n_trades     = n_trades + 1,
          reward_sum   = reward_sum + VALUES(reward_sum),
          sum_reward   = sum_reward + VALUES(sum_reward),  -- 過渡期雙寫；日後可移除此欄位與此行
          last_pnl     = VALUES(last_pnl),
          last_exit_ts = VALUES(last_exit_ts)
        """, tid=int(template_id), reg=int(regime), rw=float(reward), pnl=float(pnl_after), ext=int(exit_ts))

    # === 自動學習最佳出場棒數（僅當 settings.exit_horizon_auto=1） ===
    try:
        ena = q("SELECT exit_horizon_auto FROM settings WHERE id=1").scalar()
        if int(ena or 0) == 1:
            # 推斷方向 & 絕對張數
            direction = "LONG" if float(qty) > 0 else "SHORT"
            learn_exit_horizon(
                symbol=symbol, interval=interval, template_id=template_id, regime=int(regime),
                entry_ts=int(entry_ts), exit_ts=int(exit_ts),
                direction=direction, entry_price=float(entry_price), qty_abs=abs(float(qty)),
                k_min=1, k_max=12   # 先用 1~12 根搜尋，可再調
            )
    except Exception:
        pass


    return float(reward), float(pnl_after)
