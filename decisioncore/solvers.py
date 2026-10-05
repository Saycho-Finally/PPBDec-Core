"""决策器光谱：program_verifier → rule_engine → majority_vote → llm_judge(桩)。

规则：沿光谱从左往右找第一个能处理该决策点的判定器。
llm_judge 是理论档位：需要"无谓词 + 枚举不完备 + 低移位风险"三条件同时成立，
且结果永远带 shift_risk: high 标注——v0.1 只提供桩（不做真实 LLM 调用）。
"""

from __future__ import annotations

import json
from collections import Counter

from decisioncore.core import (MIN_CANDIDATES, CoverageEvidence, DecisionPoint,
                               DecisionRecord, DecisionType)


def solve_verifiable(point: DecisionPoint, subject) -> DecisionRecord:
    """程序谓词判定：开放空间上按谓词判定，无候选集。确定性，零成本。"""
    assert point.predicate is not None, "verifiable 决策点必须提供谓词"
    passed = bool(point.predicate(subject))
    return DecisionRecord(
        decision_id="", ts=0.0, point_name=point.name,
        point_type=DecisionType.VERIFIABLE.value,
        solver="program_verifier", result=passed, confidence=1.0,
        alternatives=[], coverage_evidence=None,
        shift_risk="none",
        notes=f"predicate={point.predicate.__name__ if hasattr(point.predicate, '__name__') else 'lambda'}",
    )


def solve_enumeration(point: DecisionPoint) -> DecisionRecord:
    """枚举选择：封闭候选集（完备性由协议保证）。默认规则=取第一个通过谓词的候选；
    无谓词时取 majority（候选即票）。"""
    assert point.candidates, "enumeration 候选集为空"
    winner = None
    for c in point.candidates:
        if point.predicate is None or point.predicate(c):
            winner = c
            break
    confidence = 1.0 if winner is not None else 0.0
    return DecisionRecord(
        decision_id="", ts=0.0, point_name=point.name,
        point_type=DecisionType.ENUMERATION.value,
        solver="rule_engine", result=winner, confidence=confidence,
        alternatives=[c for c in point.candidates if c != winner],
        coverage_evidence={"completeness_note": point.completeness_note,
                           "n_candidates": len(point.candidates)},
        shift_risk="none",
        notes="closed enumeration; first-match rule" if point.predicate else "closed enumeration; no predicate (returns first)",
    )


def solve_open_majority(point: DecisionPoint, vote_keys: list[str],
                        min_candidates: int = MIN_CANDIDATES
                        ) -> tuple[DecisionRecord, str | None]:
    """open 决策的多数投票判定（self-consistency 式）。
    vote_keys：每个候选的投票键（如 Countdown 数值）；None 项为废票。

    前置：coverage 证据必须存在且 n_candidates>0，否则抛 ValueError（拒绝受理）。
    **覆盖不足**（候选数低于下限）：降级受理——结果保留，但
    置信度折半、shift_risk 强制 high、记录标注 degraded，
    避免把弱证据当充分证据用。
    """
    if point.coverage is None:
        raise ValueError("open 决策缺少 coverage 证据——DecisionCore 拒绝受理（病态二守门）")
    if point.coverage.n_candidates == 0:
        raise ValueError("open 决策候选为空")
    sufficient, why = point.coverage.sufficiency(min_candidates)
    degraded = not sufficient

    keys = [k for k in vote_keys if k]
    if not keys:
        rec = _open_record(point, solver="majority_vote", result=None,
                           confidence=0.0, alternatives=[], degraded=degraded,
                           extra_note=f"coverage 不足（{why}）：降级受理" if degraded else "")
        return rec, None
    counter = Counter(keys)
    top, cnt = counter.most_common(1)[0]
    tie = list(counter.values()).count(cnt) > 1
    conf = cnt / len(keys) if not tie else 0.0
    if degraded:
        conf = conf / 2                      # 降级：置信度折半
    winner = None if tie else top
    shift = "low" if (not degraded and point.coverage.history_coverage_rate
                      and point.coverage.history_coverage_rate > 0.8) else "high"
    rec = _open_record(point, solver="majority_vote(value_key)", result=winner,
                       confidence=round(conf, 4), alternatives=dict(counter),
                       shift_risk=shift, degraded=degraded,
                       extra_note=f"coverage 不足（{why}）：降级受理，置信度折半"
                       if degraded else "")
    return rec, winner


def _open_record(point, solver, result, confidence, alternatives,
                 shift_risk: str = "high", degraded: bool = False,
                 extra_note: str = "") -> DecisionRecord:
    notes = "open selection; candidate set constructed upstream"
    if extra_note:
        notes += f" | {extra_note}"
    return DecisionRecord(
        decision_id="", ts=0.0, point_name=point.name,
        point_type=DecisionType.OPEN.value, solver=solver, result=result,
        confidence=confidence, alternatives=alternatives,
        coverage_evidence={"n_candidates": point.coverage.n_candidates,
                           "source": point.coverage.source,
                           "source_diversity": point.coverage.source_diversity,
                           "history_coverage_rate": point.coverage.history_coverage_rate},
        shift_risk=shift_risk,  # 默认 high；历史覆盖率 >0.8 且覆盖充分时降为 low
        degraded=degraded,
        notes=notes,
    )


def llm_judge_stub(point: DecisionPoint, subject: str) -> DecisionRecord:
    """LLM judge 桩：v0.1 不做真实调用。存在仅为标注光谱末档的语义。
    触发条件（三缺一不可）：无谓词 + 候选不完备 + 声明低移位风险。
    结果恒带 shift_risk: high。"""
    return DecisionRecord(
        decision_id="", ts=0.0, point_name=point.name,
        point_type=point.type.value, solver="llm_judge_stub", result=None,
        confidence=None, alternatives=[], coverage_evidence=None,
        shift_risk="high",
        notes="LLM judge is the last resort; not executed in v0.1 (stub). "
              "Upgrade requires: no predicate available + incomplete enumeration + declared low shift risk.",
    )


class DecisionCore:
    """决策核：受理 DecisionPoint，路由到光谱判定器，落证据链。"""

    def __init__(self, audit_path: str | None = None):
        self.audit_path = audit_path
        self.records: list[DecisionRecord] = []

    def decide_verifiable(self, point: DecisionPoint, subject) -> DecisionRecord:
        rec = solve_verifiable(point, subject)
        self._commit(rec)
        return rec

    def decide_enumeration(self, point: DecisionPoint) -> DecisionRecord:
        rec = solve_enumeration(point)
        self._commit(rec)
        return rec

    def decide_open(self, point: DecisionPoint, vote_keys: list[str],
                    min_candidates: int = MIN_CANDIDATES
                    ) -> tuple[DecisionRecord, str | None]:
        """coverage 缺失或候选为空 → 抛错拒绝；覆盖不足 → 降级受理（记录标 degraded）。"""
        rec, winner = solve_open_majority(point, vote_keys, min_candidates)
        self._commit(rec)
        return rec, winner

    def _commit(self, rec: DecisionRecord) -> None:
        rec.decision_id = uuid.uuid4().hex[:12]
        rec.ts = time.time()
        self.records.append(rec)
        if self.audit_path:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(rec.to_json() + "\n")


import time
import uuid  # noqa: E402  (模块底部导入保持 core 纯净)
