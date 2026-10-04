"""PPBDec-Core：统一判定/选择子层（所有外挂的公共决策核）。

理论约束与完整设计见 SPEC.md。快速上手：

    from decisioncore import DecisionCore, DecisionPoint, DecisionType, CoverageEvidence

    dc = DecisionCore(audit_path="decisions.jsonl")

    # verifiable：程序谓词判定（零成本，确定性）
    rec = dc.decide_verifiable(
        DecisionPoint(name="countdown_check", type=DecisionType.VERIFIABLE,
                      predicate=lambda expr: safe_eval(expr) == target),
        subject="3*4")

    # enumeration：封闭枚举选择
    rec = dc.decide_enumeration(
        DecisionPoint(name="model_route", type=DecisionType.ENUMERATION,
                      candidates=["flash", "pro"], completeness_note="provider model list"))

    # open：必须附 coverage 证据，否则拒绝受理
    rec, winner = dc.decide_open(
        DecisionPoint(name="answer_selection", type=DecisionType.OPEN,
                      candidates=candidates,
                      coverage=CoverageEvidence(n_candidates=4, source="sample(low, n=4)")),
        vote_keys=vote_keys)
"""

from decisioncore.core import (CoverageEvidence, DecisionPoint, DecisionRecord,
                               DecisionType, RouteDecision)
from decisioncore.solvers import DecisionCore, llm_judge_stub
from decisioncore.registry import ExpertRegistry, ExpertSpec
from decisioncore.governance import AddonManifest, Conflict, Governance
from decisioncore.observability import CognitiveMonitor
from decisioncore.orchestrator import ExpertAdapter, Orchestrator

__version__ = "0.1.0"

__all__ = [
    "DecisionCore", "DecisionPoint", "DecisionType", "DecisionRecord",
    "CoverageEvidence", "RouteDecision",
    "ExpertRegistry", "ExpertSpec", "llm_judge_stub",
    "Governance", "AddonManifest", "Conflict", "CognitiveMonitor",
    "ExpertAdapter", "Orchestrator",
    "__version__",
]
