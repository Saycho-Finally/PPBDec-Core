"""ExpertPool 运行时：把五件套注册为可路由专家，端到端编排 + 观测回灌。

从"接口就位"到"运行时接线"的三件事：
  1. ExpertAdapter：每个项目一个薄适配器（能力契约 + 执行入口）
  2. Orchestrator：任务 → 路由（DecisionCoreV2.decide_route）→ 执行 → 审计 + 观测
  3. 观测回灌：CognitiveMonitor 的利用率 → 路由 bias（auxiliary-loss-free 模式的
     运行时实现：过载专家降权、饿死专家升权，不改任务定义）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from decisioncore.registry import ExpertRegistry, ExpertSpec, RouteDecision
from decisioncore.observability import CognitiveMonitor


@dataclass
class ExpertAdapter:
    """项目的运行时适配器：能力契约 + 执行函数 + 自述。"""
    spec: ExpertSpec
    handler: Callable[[dict], dict]
    description: str = ""
    calls: int = 0
    failures: int = 0

    def run(self, task: dict) -> dict:
        self.calls += 1
        try:
            out = self.handler(task)
            return {"ok": True, "expert": self.spec.name, "output": out}
        except Exception as e:                      # noqa: BLE001
            self.failures += 1
            return {"ok": False, "expert": self.spec.name, "error": str(e)[:200]}


@dataclass
class OrchestrationRecord:
    ts: float
    task_kind: str
    required: list[str]
    routed_to: str
    confidence: float
    ok: bool
    alternatives: list[str] = field(default_factory=list)


class Orchestrator:
    """专家池运行时：路由 → 执行 → 审计 → 观测回灌。"""

    def __init__(self, registry: ExpertRegistry | None = None,
                 monitor: CognitiveMonitor | None = None,
                 bias_step: float = 0.05):
        self.registry = registry or ExpertRegistry()
        self.monitor = monitor or CognitiveMonitor()
        self.bias_step = bias_step
        self.bias: dict[str, float] = {}          # 运行时 bias（不改任务，只调路由偏好）
        self.records: list[OrchestrationRecord] = []
        self.adapters: dict[str, ExpertAdapter] = {}

    # ---- 注册 ----

    def register(self, adapter: ExpertAdapter) -> None:
        self.adapters[adapter.spec.name] = adapter
        self.registry.register(adapter.spec)
        self.bias[adapter.spec.name] = 1.0        # 中性 bias

    # ---- 路由（含 bias 调整）----

    def route(self, required: set[str], prefer_deterministic: bool = True) -> RouteDecision:
        """在注册表的确定性路由之上叠加运行时 bias：
        得分 = 1/cost_tier × bias；过载专家（bias<1）让位、饿死专家（bias>1）受青睐。"""
        cands = [e for e in self.registry.experts.values() if required <= e.capabilities]
        if not cands:
            return RouteDecision(expert="", confidence=0.0,
                                 required_capabilities=sorted(required),
                                 alternatives=[], reason="no expert covers required")
        det = [e for e in cands if e.deterministic]
        pool = det if (prefer_deterministic and det) else cands
        scored = sorted(pool, key=lambda e: -(self.bias.get(e.name, 1.0) / e.cost_tier))
        best = scored[0]
        alts = [e.name for e in scored[1:]]
        self.registry.route_history[best.name] += 1
        return RouteDecision(expert=best.name,
                             confidence=round(min(1.0, self.bias.get(best.name, 1.0)), 3),
                             required_capabilities=sorted(required),
                             alternatives=alts,
                             reason=f"bias-adjusted route (bias={self.bias.get(best.name, 1.0):.2f},"
                             f" tier={best.cost_tier})")

    # ---- 端到端执行 ----

    def execute(self, task_kind: str, required: set[str],
                payload: dict) -> dict:
        rd = self.route(required)
        if not rd.expert:
            rec = OrchestrationRecord(time.time(), task_kind, sorted(required),
                                      "", 0.0, False)
            self.records.append(rec)
            return {"ok": False, "error": "no expert", "route": rd.__dict__}
        result = self.adapters[rd.expert].run(payload)
        rec = OrchestrationRecord(time.time(), task_kind, sorted(required),
                                  rd.expert, rd.confidence, result["ok"],
                                  alternatives=rd.alternatives)
        self.records.append(rec)
        self.monitor.record_tool_call(rd.expert, ok=result["ok"])
        self.monitor.record_route(self.registry.snapshot())
        return {"ok": result["ok"], "expert": rd.expert, "route": rd.__dict__,
                "output": result.get("output"), "error": result.get("error")}

    # ---- 观测回灌（auxiliary-loss-free 的运行时版）----

    def rebalance(self) -> dict:
        """按利用率调 bias：利用率 > 50% 的专家降权、0 次的升权。
        不改任务定义，只改路由偏好——对应 MoE 的 auxiliary-loss-free balancing。"""
        total = sum(self.registry.route_history.values()) or 1
        changed = {}
        for name in self.registry.experts:
            util = self.registry.route_history.get(name, 0) / total
            old = self.bias.get(name, 1.0)
            if util > 0.5:
                self.bias[name] = max(0.5, old - self.bias_step)
            elif util == 0:
                self.bias[name] = min(2.0, old + self.bias_step)
            if self.bias[name] != old:
                changed[name] = (round(old, 3), round(self.bias[name], 3))
        return {"changed": changed, "utilization": self.registry.utilization_report(),
                "entropy": self.registry.route_entropy()}

    def health(self) -> dict:
        return {
            "n_experts": len(self.adapters),
            "n_tasks": len(self.records),
            "success_rate": round(
                sum(1 for r in self.records if r.ok) / max(len(self.records), 1), 3),
            "route_entropy": self.registry.route_entropy(),
            "starved": self.registry.starved_experts(),
            "bias": {k: round(v, 2) for k, v in self.bias.items()},
            "monitor": self.monitor.report(),
        }
