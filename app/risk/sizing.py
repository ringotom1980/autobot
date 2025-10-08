# app/risk/sizing.py
from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
import math

# 若你把 db.exec 取名為 q，請改成：from ..db import q as exec
from ..db import exec
from ..exec.filters import round_price, round_qty


# -------------------------------
# 小工具
# -------------------------------
def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _get_max_risk_pct() -> float:
    """
    從 settings 取 max_risk_pct；取不到就給預設 1%
    """
    try:
        r = exec("SELECT max_risk_pct FROM settings WHERE id=1").scalar()
        v = _safe_float(r, 0.01)
        return v if v > 0 else 0.01
    except Exception:
        # DB 取值失敗時保底 1%
        return 0.01


# -------------------------------
# 主要 API
# -------------------------------
def size_by_atr(
    price: float,
    atr_pct: float,
    invest_usdt: float,
    leverage: int,
    max_risk_pct: Optional[float] = None,
) -> float:
    """
    用 ATR_pct 動態縮放倉位：
    - 基礎名目 = invest_usdt * leverage
    - 風險縮放 = min(1, (max_risk_pct / atr_pct))；atr_pct<=0 時不縮放（=1）
    回傳「理論數量」（未經精度/名目校正）
    """
    price_f = _safe_float(price)
    base_notional = max(_safe_float(invest_usdt), 0.0) * max(int(leverage), 1)

    if price_f <= 0 or base_notional <= 0:
        return 0.0

    mrp = _safe_float(max_risk_pct, None if max_risk_pct is None else float(max_risk_pct))
    if mrp is None:
        mrp = _get_max_risk_pct()

    atr = _safe_float(atr_pct, 0.0)
    risk_mult = 1.0 if atr <= 0 else min(1.0, max(mrp / atr, 0.0))

    target_notional = base_notional * risk_mult
    qty = target_notional / price_f
    return float(qty)


def apply_precisions(
    price: float,
    qty: float,
    *,
    tick_size: float,
    step_size: float,
    min_notional: float,
) -> Tuple[float, float]:
    """
    依交易所精度校正：
    - price 以 tick_size 向下取整
    - qty  以 step_size 向下取整
    - 若 notional < min_notional → qty 置 0
    回傳：(price_adj, qty_adj)
    """
    p_adj = round_price(_safe_float(price), _safe_float(tick_size))
    q_adj = round_qty(_safe_float(qty), _safe_float(step_size))
    notional = p_adj * q_adj
    if notional < _safe_float(min_notional):
        return p_adj, 0.0
    return p_adj, q_adj


def calc_order(
    *,
    price: float,
    atr_pct: float,
    invest_usdt: float,
    leverage: int,
    tick_size: float,
    step_size: float,
    min_notional: float,
    max_risk_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """
    一次完成：ATR 動態 sizing → 精度/名目校正
    回傳：
      {
        "price_adj": <float>,
        "qty": <float>,
        "notional": <float>,
        "base_notional": invest_usdt*leverage,
        "risk_mult": <0~1>,
        "qty_theo": <float>,     # 新增：理論數量（未校正）
        "price_raw": <float>,     # 新增：輸入原價
        "reason": <str 可選>
      }
    """
    price_f = _safe_float(price)
    invest_f = max(_safe_float(invest_usdt), 0.0)
    leverage_i = max(int(leverage), 1)

    # 先算未校正數量
    qty_theo = size_by_atr(price_f, atr_pct, invest_f, leverage_i, max_risk_pct)

    # 套交易所精度與最小名目
    p_adj, q_adj = apply_precisions(
        price=price_f,
        qty=_safe_float(qty_theo),
        tick_size=_safe_float(tick_size),
        step_size=_safe_float(step_size),
        min_notional=_safe_float(min_notional),
    )

    base_notional = invest_f * leverage_i
    mrp = _safe_float(max_risk_pct, None if max_risk_pct is None else float(max_risk_pct))
    if mrp is None:
        mrp = _get_max_risk_pct()
    atr = _safe_float(atr_pct, 0.0)
    risk_mult = 1.0 if atr <= 0 else min(1.0, max(mrp / atr, 0.0))

    result: Dict[str, Any] = {
        "price_adj": p_adj,
        "qty": q_adj,
        "notional": p_adj * q_adj,
        "base_notional": base_notional,
        "risk_mult": risk_mult,
        "qty_theo": qty_theo,
        "price_raw": price_f,
    }

    # 失敗原因提示（方便上層 log/除錯）
    if q_adj <= 0:
        result["reason"] = (
            f"below minNotional ({_safe_float(min_notional)}) "
            f"or zero qty after precision (step_size={_safe_float(step_size)})"
        )

    return result
