"""DecisionCore v0.2 测试：route 决策 + 运行时灰度开关等价性。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from decisioncore.route import DecisionCoreV2, RouteDecisionPoint  # noqa: E402
from decisioncore import DecisionCore  # noqa: E402
from decisioncore import ExpertRegistry, ExpertSpec  # noqa: E402
from migrations.runtime_switch import DecisionAwareStop  # noqa: E402
from migrations.adapters import early_stop_predicate  # noqa: E402

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def test_route():
    print("route 决策：registry 集成 + 审计快照")
    reg = ExpertRegistry()
    reg.register(ExpertSpec(name="verifier", capabilities={"verify"}, cost_tier=1,
                            deterministic=True))
    reg.register(ExpertSpec(name="micro_dm", capabilities={"verify", "route"},
                            cost_tier=2))
    dc = DecisionCoreV2(audit_path=None)
    point = RouteDecisionPoint("solver_pick", {"verify"}, reg)
    rec, rd = dc.decide_route(point)
    check("deterministic-first 路由", rd.expert == "verifier" and rec.confidence == 1.0)
    check("审计含 registry 快照", "registry_snapshot" in rec.coverage_evidence and
          rec.coverage_evidence["registry_snapshot"]["n_experts"] == 2)
    check("shift_risk=none（封闭注册表）", rec.shift_risk == "none")
    # 二次路由后熵/饿死可观测
    dc.decide_route(point)
    snap = reg.snapshot()
    check("路由分布统计", snap["route_entropy"] >= 0 and
          snap["starved_experts"] == ["micro_dm"])


def test_runtime_switch_equivalence():
    print("运行时灰度开关等价性：DecisionAwareStop vs 原判定（同输入同输出）")
    dc = DecisionCore(audit_path=None)
    stopper = DecisionAwareStop(dc, stop_k=3, item_ctx={"suite": "cd6"})
    cases = [
        (["12", "12", "12"], True),
        (["12", "12"], False),
        (["12", "13", "12"], False),
        (["12", "34", "34", "34"], True),
    ]
    ok = True
    for tail, expected in cases:
        via_dc = stopper.check("test_arm", tail)
        legacy = early_stop_predicate(tail)
        check(f"早停 {tail} → {expected}", via_dc == legacy == expected)
        ok = ok and (via_dc == legacy == expected)
    # selection 等价
    rec, winner = stopper.select("test_arm", ["3*4", "3*4", "2*6"],
                                 ["12", "12", "12"])
    check("selection 走 DecisionCore", winner == "12" and rec.confidence == 1.0)
    # 审计落盘验证
    path = os.path.join(os.path.dirname(__file__), "_switch_audit.jsonl")
    dc2 = DecisionCore(audit_path=path)
    stopper2 = DecisionAwareStop(dc2, stop_k=3)
    stopper2.check("a", ["1", "1", "1"])
    stopper2.select("a", ["x", "y"], ["1", "1"])
    lines = [json.loads(l) for l in open(path, encoding="utf-8")]
    check("运行时审计落盘", len(lines) == 2 and
          {l["point_type"] for l in lines} == {"verifiable", "open"})
    os.remove(path)
    return ok


if __name__ == "__main__":
    print("=" * 60)
    print("DecisionCore v0.2：route 决策 + 运行时灰度开关")
    print("=" * 60)
    test_route()
    ok = test_runtime_switch_equivalence()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("V2_OK" if ok and n_pass == len(RESULTS) else "V2_FAIL")
