# app/policy/bandit.py
from __future__ import annotations
from typing import Tuple, Optional
import math
from ..db import exec  # 若你改成 q，請用：from ..db import q as exec

# UCB 探索係數（可依 regime/波動動態調整）
ALPHA: float = 1.0

class Estimator:
    """
    以模板(template_id) × 情境(regime) 的歷史統計，估計其期望值與 UCB。
    - 資料來源：template_stats (n_trades, reward_mean, reward_var)
    - 回傳: (mean, ucb)，給 policy 選擇臂。
    """

    def __init__(self, alpha: float = ALPHA) -> None:
        self.alpha = float(alpha)

    def _fetch_stats(self, template_id: int, regime: int) -> Optional[dict]:
        row = exec(
            "SELECT n_trades, reward_mean, reward_var "
            "FROM template_stats WHERE template_id=:t AND regime=:r",
            t=int(template_id), r=int(regime)
        ).mappings().first()
        return dict(row) if row else None

    def estimate(self, template_id: int, regime: int) -> Tuple[float, float]:
        """
        回傳 (mean, ucb)
        若無資料 → mean=0, ucb=+inf（鼓勵探索）
        """
        stats = self._fetch_stats(template_id, regime)
        if not stats or not stats.get("n_trades"):
            return 0.0, float("inf")

        n = max(int(stats.get("n_trades") or 0), 1)
        mean = float(stats.get("reward_mean") or 0.0)
        var = float(stats.get("reward_var") or 0.0)
        var = max(var, 1e-9)  # 避免 0 導致 ucb 無法探索

        ucb = mean + self.alpha * math.sqrt(var / n)
        return mean, ucb


# ----（選用）Thompson Sampling 版本骨架，之後要切換可直接用 ----
# import random
# import numpy as np
# class ThompsonEstimator(Estimator):
#     def sample(self, template_id: int, regime: int) -> float:
#         stats = self._fetch_stats(template_id, regime)
#         if not stats or not stats.get("n_trades"):
#             return float("+inf")  # 未知臂高探索
#         mean = float(stats.get("reward_mean") or 0.0)
#         var  = max(float(stats.get("reward_var") or 1.0), 1e-6)
#         # 以正態近似的 TS（亦可改 Beta / Gaussian Process 等）
#         return random.gauss(mean, math.sqrt(var))
