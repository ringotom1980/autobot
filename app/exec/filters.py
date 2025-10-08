# app/exec/filters.py
from __future__ import annotations
from typing import Dict, Any, Mapping
from decimal import Decimal, ROUND_DOWN, InvalidOperation

# ------------------------------------------------
# 既有：輕量前置濾網（保留原樣）
# ------------------------------------------------
def pass_basic_filters(decision: Dict[str, Any]) -> bool:
    """
    輕量前置濾網：
    - HOLD 不下單
    - 分數強度門檻（避免雜訊）：預設 3.0
    """
    action = decision.get("action", "HOLD")
    if action == "HOLD":
        return False
    e_long = float(decision.get("E_long", 0.0) or 0.0)
    e_short = float(decision.get("E_short", 0.0) or 0.0)
    strength = max(abs(e_long), abs(e_short))
    return strength >= 3.0


# ------------------------------------------------
# 新增：交易精度對齊工具（提供 sizing.py 匯入）
# ------------------------------------------------
__all__ = [
    "round_price",
    "round_qty",
    "round_price_by_filters",
    "round_qty_by_filters",
]

def _to_decimal(x: Any) -> Decimal:
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

def _quantize_down(value: Decimal, step: Decimal) -> Decimal:
    """
    將 value 依指定 step 向下對齊（符合交易所規則）。
    例：step=0.10 → 123.456 → 123.40
        step=0.001 → 0.123456 → 0.123
    """
    if step <= 0:
        return value
    # 用 ticks 方式避免二進位浮點誤差
    ticks = (value / step).to_integral_value(rounding=ROUND_DOWN)
    # 量化模板：確保小數位長度與 step 一致
    tpl = step if step < 1 else Decimal("1")
    return (ticks * step).quantize(tpl, rounding=ROUND_DOWN)

def round_price(price: Any, tick_size: Any) -> float:
    """
    依 tick_size 向下取整的價格對齊。
    """
    p = _to_decimal(price)
    t = _to_decimal(tick_size)
    return float(_quantize_down(p, t))

def round_qty(qty: Any, step_size: Any) -> float:
    """
    依 step_size 向下取整的數量對齊。
    """
    q = _to_decimal(qty)
    s = _to_decimal(step_size)
    return float(_quantize_down(q, s))

# 方便直接用整組 filters（tickSize / stepSize）時呼叫
def _get_filter_val(filters: Mapping[str, Any], key: str, default: str = "0") -> Decimal:
    v = filters.get(key, default)
    return _to_decimal(v)

def round_price_by_filters(price: Any, filters: Mapping[str, Any]) -> float:
    return round_price(price, _get_filter_val(filters, "tickSize"))

def round_qty_by_filters(qty: Any, filters: Mapping[str, Any]) -> float:
    return round_qty(qty, _get_filter_val(filters, "stepSize"))
