"""DecisionCore v0.2：route 型决策点（ExpertRegistry 集成）。

route 决策 = enumeration 的特例：候选集是专家注册表，判定器是能力匹配规则，
审计记录额外携带路由分布快照（熵/饿死检测）——MoE 负载均衡的运行时输入。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from decisioncore.core import DecisionRecord
from decisioncore.registry import ExpertRegistry, RouteDecision


class RouteDecisionPoint:
    """路由型决策点：声明所需能力，由注册表执行匹配。"""

    def __init__(self, name: str, required_capabilities: set[str],
                 registry: ExpertRegistry,
                 prefer_deterministic: bool = True):
        self.name = name
        self.required_capabilities = set(required_capabilities)
        self.registry = registry
        self.prefer_deterministic = prefer_deterministic


class DecisionCoreV2:
    """在 v0.1 DecisionCore 基础上增加 route 决策（与 registry 集成）。"""

    def __init__(self, audit_path: str | None = None):
        self.audit_path = audit_path
        self.records: list[DecisionRecord] = []

    def decide_route(self, point: RouteDecisionPoint) -> tuple[DecisionRecord, RouteDecision]:
        rd = point.registry.route(point.required_capabilities,
                                  prefer_deterministic=point.prefer_deterministic)
        rec = DecisionRecord(
            decision_id=uuid.uuid4().hex[:12], ts=time.time(),
            point_name=point.name, point_type="route",
            solver="expert_registry(capability_match"
            + (", deterministic_first" if point.prefer_deterministic else "") + ")",
            result=rd.expert, confidence=rd.confidence,
            alternatives=rd.alternatives,
            coverage_evidence={"required": sorted(point.required_capabilities),
                               "n_eligible": len(rd.alternatives) + (1 if rd.expert else 0),
                               "registry_snapshot": point.registry.snapshot()},
            shift_risk="none",   # 封闭注册表 + 协议枚举 = 无分布移位
            notes=rd.reason,
        )
        self._commit(rec)
        return rec, rd

    def _commit(self, rec: DecisionRecord) -> None:
        self.records.append(rec)
        if self.audit_path:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(rec.to_json() + "\n")
