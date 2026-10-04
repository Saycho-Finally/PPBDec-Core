"""治理层与可观测性测试（MoE 架构补全模块）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decisioncore.observability import CognitiveMonitor  # noqa: E402
from decisioncore.governance import AddonManifest, Governance  # noqa: E402

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def test_observability():
    print("认知可观测性三件套")
    mon = CognitiveMonitor(window=20)
    # token velocity：连续膨胀
    for t in [1000, 1200, 1500, 1900, 2500]:
        mon.record_tokens(t, label="turn")
    check("velocity 预警（单轮 50%+ 膨胀）", len(mon.velocity_alerts) >= 1,
          f"{len(mon.velocity_alerts)} 次")
    # 正常速率不预警
    mon2 = CognitiveMonitor()
    for t in [1000, 1010, 1020, 1030, 1040]:
        mon2.record_tokens(t)
    check("平稳速率无预警", len(mon2.velocity_alerts) == 0)
    # tool error rate
    mon.record_tool_call("search", ok=True)
    mon.record_tool_call("search", ok=False)
    mon.record_tool_call("search", ok=False)
    r = mon.report()
    check("工具失败率统计", r["tool_error_rate"] == round(2 / 3, 3))
    check("循环耗尽预警（连续同工具+末次失败）", len(mon.loop_alerts) >= 1)
    check("健康状态 degraded", mon.health() == "degraded")
    # 路由事件
    mon.record_route({"route_entropy": 0.9, "starved_experts": []})
    check("路由事件入账", mon.report()["route_events"] == 1)


def test_governance():
    print("治理层：冲突检测 / 依赖 / 预检")
    g = Governance()
    m1 = AddonManifest(name="cache", version="0.1", touches={"prefix"},
                       exclusive={"history.front"})
    m2 = AddonManifest(name="memory", version="0.1", touches={"history"},
                       exclusive={"history.front"})     # 与 m1 互斥
    m3 = AddonManifest(name="think", version="0.1", touches={"output"},
                       depends_on={"nonexistent"})       # 缺依赖

    c1 = g.register(m1)
    check("首个外挂无冲突", c1 == [])
    c2 = g.register(m2)
    check("互斥资源冲突检出", len(c2) == 1 and c2[0].kind == "exclusive_clash",
          c2[0].detail if c2 else "")
    c3 = g.register(m3)
    check("缺依赖检出", any(c.kind == "missing_dependency" for c in c3))
    report = g.check_all()
    check("治理报告", report["n_addons"] == 3 and report["n_conflicts"] == 2)
    # 预检不注册
    m4 = AddonManifest(name="oss", version="0.1", touches={"prefix"},
                       exclusive={"history.front"})
    ok, found = g.can_load(m4)
    check("预检拒绝互斥外挂（不注册）", ok is False and len(found) >= 1 and
          "oss" not in g.manifests, f"{len(found)} 处冲突")
    m5 = AddonManifest(name="safe", version="0.1", touches={"output"})
    ok2, found2 = g.can_load(m5)
    check("预检放行无冲突外挂", ok2 is True and found2 == [])


if __name__ == "__main__":
    print("=" * 60)
    print("MoE 架构补全：治理层 + 认知可观测性")
    print("=" * 60)
    test_observability()
    test_governance()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("MOE_COMPLETE_OK" if n_pass == len(RESULTS) else "MOE_FAIL")
