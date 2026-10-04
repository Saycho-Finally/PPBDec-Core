"""编排运行时测试：ExpertPool 接线 / bias 回灌 / 观测联动 / 无覆盖处理。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decisioncore.orchestrator import ExpertAdapter, Orchestrator  # noqa: E402
from decisioncore.registry import ExpertSpec  # noqa: E402

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def mk_pool():
    orch = Orchestrator()
    orch.register(ExpertAdapter(
        ExpertSpec(name="cheap_det", capabilities={"a"}, cost_tier=1,
                   deterministic=True), lambda t: {"v": "cheap"}, "确定性便宜"))
    orch.register(ExpertAdapter(
        ExpertSpec(name="expensive", capabilities={"a", "b"}, cost_tier=4),
        lambda t: {"v": "exp"}, "贵的"))
    orch.register(ExpertAdapter(
        ExpertSpec(name="rare", capabilities={"a", "c"}, cost_tier=2),
        lambda t: {"v": "rare"}, "冷门"))
    return orch


def test_routing():
    print("路由：确定性优先 + 能力覆盖 + 无覆盖")
    orch = mk_pool()
    r1 = orch.route({"a"})
    check("确定性便宜优先", r1.expert == "cheap_det", r1.reason)
    r2 = orch.route({"b"}, prefer_deterministic=False)
    check("非确定场景按 bias/tier", r2.expert == "expensive")
    r3 = orch.route({"vision"})
    check("无覆盖 → 空路由", r3.expert == "" and r3.confidence == 0.0)


def test_execute_and_audit():
    print("执行 + 审计 + 观测联动")
    orch = mk_pool()
    res = orch.execute("t1", {"a"}, {})
    check("执行成功", res["ok"] and res["expert"] == "cheap_det")
    check("编排记录落账", len(orch.records) == 1)
    check("观测记账（tool_call + route）", orch.monitor.report()["tool_calls_total"] == 1
          and orch.monitor.report()["route_events"] == 1)
    fail = orch.execute("t2", {"vision"}, {})
    check("无覆盖任务清晰失败", not fail["ok"] and fail["error"] == "no expert")


def test_rebalance():
    print("观测回灌：不均衡 → bias 调整")
    orch = mk_pool()
    # 构造不均衡：cheap_det 打 8 次（>50%），rare 与 expensive 各 1 次
    for _ in range(8):
        orch.execute("hot", {"a"}, {})
    orch.execute("cold1", {"b"}, {})          # expensive
    orch.execute("cold2", {"c"}, {})          # rare（capability a+c，route 选 a 组里的 rare？）
    total = sum(orch.registry.route_history.values())
    hot_util = orch.registry.route_history.get("cheap_det", 0) / total
    check("构造出过载专家", hot_util > 0.5, f"cheap_det util={hot_util:.2f}")
    before = dict(orch.bias)
    rb = orch.rebalance()
    check("过载专家降权", orch.bias["cheap_det"] < before["cheap_det"],
          f"{before['cheap_det']} → {orch.bias['cheap_det']}")
    starved = [n for n in orch.registry.experts
               if orch.registry.route_history.get(n, 0) == 0]
    if starved:
        check("饿死专家升权", all(orch.bias[n] > 1.0 for n in starved),
              f"{starved} → {[orch.bias[n] for n in starved]}")
    else:
        check("饿死专家升权（无饿死则跳过）", True)
    check("熵随分布报告", 0 <= rb["entropy"] <= 2.0, f"entropy={rb['entropy']}")


def test_bias_affects_routing():
    print("回路：bias 改变路由偏好")
    orch = mk_pool()
    # 人为压低 expensive 的 bias、抬高 rare
    orch.bias["expensive"] = 0.5
    orch.bias["rare"] = 2.0
    r = orch.route({"a", "c"}, prefer_deterministic=False)
    # 候选：expensive(4, bias .5 → .125)、rare(2, bias 2.0 → 1.0) → rare 胜
    check("bias 改变路由结果", r.expert == "rare", f"→ {r.expert} ({r.reason})")


def test_health():
    print("健康报告")
    orch = mk_pool()
    orch.execute("t", {"a"}, {})
    h = orch.health()
    check("健康字段齐全", all(k in h for k in
                          ("n_experts", "n_tasks", "success_rate",
                           "route_entropy", "starved", "bias", "monitor")))
    check("成功率正确", h["success_rate"] == 1.0)


if __name__ == "__main__":
    print("=" * 60)
    print("ExpertPool 编排运行时测试")
    print("=" * 60)
    test_routing()
    test_execute_and_audit()
    test_rebalance()
    test_bias_affects_routing()
    test_health()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("ORCH_OK" if n_pass == len(RESULTS) else "ORCH_FAIL")
