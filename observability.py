"""认知可观测性：外挂栈的健康监控（MoE 工程实践的三件套 + 路由健康）。

导入自 MoE serving 的监控清单（agent 级 APM）：
  - token velocity：token 消耗速率（上下文膨胀预警）
  - loop exhaustion：循环耗尽（同工具反复调用无进展）
  - tool error rate：工具失败率
  - route health：路由熵 / 专家饿死 / 利用率（消费 ExpertRegistry.snapshot）
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass
class ObservabilityEvent:
    ts: float
    kind: str          # token / tool_call / route / decision
    payload: dict = field(default_factory=dict)


class CognitiveMonitor:
    """认知可观测性：为 agent 循环与 MoE 路由提供统一健康台账。"""

    def __init__(self, window: int = 50):
        self.events: deque[ObservabilityEvent] = deque(maxlen=window)
        self.token_history: list[tuple[float, int]] = []
        self.tool_calls: Counter = Counter()
        self.tool_errors: Counter = Counter()
        self.loop_alerts: list[dict] = []
        self.velocity_alerts: list[dict] = []

    # ---- 三件套 ----

    def record_tokens(self, n_tokens: int, label: str = "") -> None:
        self.token_history.append((time.time(), n_tokens))
        if len(self.token_history) >= 5:
            recent = [t for _, t in self.token_history[-5:]]
            growth = (recent[-1] - recent[0]) / max(recent[0], 1)
            if growth > 0.5:   # 单轮 50%+ 膨胀 → 预警
                self.velocity_alerts.append(
                    {"ts": time.time(), "label": label, "growth": round(growth, 3)})

    def record_tool_call(self, tool: str, ok: bool = True) -> None:
        self.tool_calls[tool] += 1
        if not ok:
            self.tool_errors[tool] += 1
        self.events.append(ObservabilityEvent(time.time(), "tool_call",
                                              {"tool": tool, "ok": ok}))
        # 循环耗尽：窗口内同工具连续 3 次以上且最近有失败
        last = [e for e in list(self.events)[-6:] if e.kind == "tool_call"]
        if len(last) >= 3 and len({e.payload["tool"] for e in last[-3:]}) == 1 \
                and not last[-1].payload["ok"]:
            self.loop_alerts.append(
                {"ts": time.time(), "tool": tool,
                 "note": "连续同工具调用且末次失败——循环耗尽疑似"})

    def record_route(self, registry_snapshot: dict) -> None:
        self.events.append(ObservabilityEvent(time.time(), "route", registry_snapshot))

    # ---- 报告 ----

    def report(self) -> dict:
        n_tools = sum(self.tool_calls.values())
        n_err = sum(self.tool_errors.values())
        return {
            "token_events": len(self.token_history),
            "velocity_alerts": self.velocity_alerts[-3:],
            "tool_calls_total": n_tools,
            "tool_error_rate": round(n_err / n_tools, 3) if n_tools else 0.0,
            "loop_alerts": self.loop_alerts[-3:],
            "route_events": sum(1 for e in self.events if e.kind == "route"),
        }

    def health(self) -> str:
        r = self.report()
        if r["loop_alerts"] or (r["tool_error_rate"] > 0.3):
            return "degraded"
        if r["velocity_alerts"]:
            return "watch"
        return "healthy"
