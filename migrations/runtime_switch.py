"""思考外挂运行时灰度开关：早停与 selection 走 DecisionCore（含审计）。

用法（e1_formal.py 已接 --decision-core）：
    from migrations.runtime_switch import DecisionAwareStop
    stopper = DecisionAwareStop(dc, stop_k=3)
    # 循环内：
    if stopper.check(arm, vote_keys): break
    # 循环后：
    rec, winner = stopper.select(arm, candidates, vote_keys)
"""

from __future__ import annotations

from decisioncore import (CoverageEvidence, DecisionCore, DecisionPoint,  # noqa: F401
                          DecisionType)


class DecisionAwareStop:
    """把 E1 的早停判定与 selection 包装成 DecisionCore 决策点（含审计）。"""

    def __init__(self, dc: DecisionCore, stop_k: int = 3,
                 item_ctx: dict | None = None):
        self.dc = dc
        self.stop_k = stop_k
        self.item_ctx = item_ctx or {}

    def check(self, arm: str, vote_keys: list[str]) -> bool:
        """早停判定（verifiable：票型收敛是谓词，无需候选集）。"""
        tail = vote_keys[-self.stop_k:]
        point = DecisionPoint(
            name=f"{arm}.early_stop", type=DecisionType.VERIFIABLE,
            predicate=lambda t: len(t) >= self.stop_k and len(set(t[-self.stop_k:])) == 1,
            metadata={"migrated_from": "e1_formal stop_k",
                      "arm": arm, **self.item_ctx})
        rec = self.dc.decide_verifiable(point, subject=tail)
        return bool(rec.result)

    def select(self, arm: str, candidates: list[str], vote_keys: list[str]) -> tuple:
        """selection（open：候选来自上游采样，coverage 证据=采样参数）。"""
        point = DecisionPoint(
            name=f"{arm}.answer_selection", type=DecisionType.OPEN,
            candidates=candidates,
            coverage=CoverageEvidence(
                n_candidates=len(candidates),
                source=f"sample(low, n={len(candidates)}, stop={self.stop_k})",
                source_diversity="temperature=0.7"))
        rec, winner = self.dc.decide_open(point, vote_keys)
        return rec, winner
