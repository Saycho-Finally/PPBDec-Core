"""DecisionCore 端到端单测（零依赖，无 API）。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decisioncore import (DecisionCore, DecisionPoint, DecisionType,  # noqa: E402
                          CoverageEvidence, ExpertRegistry, ExpertSpec)


def test_verifiable():
    """verifiable：谓词判定，确定性，置信度 1.0。"""
    dc = DecisionCore()
    point = DecisionPoint(name="countdown_check", type=DecisionType.VERIFIABLE,
                          predicate=lambda expr: expr == "3*4")
    rec = dc.decide_verifiable(point, subject="3*4")
    assert rec.result is True and rec.confidence == 1.0 and rec.shift_risk == "none"
    rec2 = dc.decide_verifiable(point, subject="3*5")
    assert rec2.result is False
    print("OK verifiable: 谓词判定确定性")


def test_enumeration():
    """enumeration：封闭枚举，第一个通过谓词的候选。"""
    dc = DecisionCore()
    point = DecisionPoint(name="tier_pick", type=DecisionType.ENUMERATION,
                          candidates=["off", "low", "high"],
                          predicate=lambda c: c in ("low", "off") and c != "off",
                          completeness_note="provider effort list")
    rec = dc.decide_enumeration(point)
    assert rec.result == "low" and rec.solver == "rule_engine"
    print("OK enumeration: 封闭选择")


def test_open_coverage_gate():
    """病态二守门：open 无 coverage 证据 → 拒绝受理。"""
    dc = DecisionCore()
    point = DecisionPoint(name="ans", type=DecisionType.OPEN, candidates=["a", "b"])
    try:
        dc.decide_open(point, vote_keys=["a", "a"])
        assert False, "应拒绝"
    except ValueError as e:
        assert "coverage" in str(e)
    print("OK open gate: 无 coverage 证据被拒绝（病态二守门）")


def test_open_majority():
    """open + coverage：多数投票 + 置信度。"""
    dc = DecisionCore()
    point = DecisionPoint(name="ans", type=DecisionType.OPEN,
                          candidates=["3*4", "3*4", "2*6"],
                          coverage=CoverageEvidence(n_candidates=3,
                                                    source="sample(low, n=4, stop=3)",
                                                    history_coverage_rate=1.0))
    rec, winner = dc.decide_open(point, vote_keys=["12", "12", "12"])
    assert winner == "12" and rec.confidence == 1.0 and rec.shift_risk == "low"
    # 平票 → winner=None
    point2 = DecisionPoint(name="ans2", type=DecisionType.OPEN, candidates=["a", "b"],
                           coverage=CoverageEvidence(n_candidates=2, source="s"))
    rec2, w2 = dc.decide_open(point2, vote_keys=["x", "y"])
    assert w2 is None and rec2.confidence == 0.0
    print("OK open majority: 投票 + 置信度 + 平票处理")


def test_audit_immutability():
    """证据链：逐条 JSONL 不可变落盘。"""
    path = os.path.join(os.path.dirname(__file__), "_audit_test.jsonl")
    dc = DecisionCore(audit_path=path)
    p = DecisionPoint(name="v", type=DecisionType.VERIFIABLE, predicate=lambda x: True)
    dc.decide_verifiable(p, subject="s")
    dc.decide_verifiable(p, subject="s2")
    lines = [json.loads(l) for l in open(path, encoding="utf-8")]
    assert len(lines) == 2 and len({l["decision_id"] for l in lines}) == 2
    assert all("solver" in l and "ts" in l for l in lines)
    os.remove(path)
    print("OK audit: 证据链 JSONL 落盘，decision_id 唯一")


def test_registry():
    """ExpertRegistry：能力契约路由 + 确定性优先 + 熵/饿死检测。"""
    reg = ExpertRegistry()
    reg.register(ExpertSpec(name="calc", capabilities={"arithmetic"},
                            cost_tier=1, deterministic=True))
    reg.register(ExpertSpec(name="code_llm", capabilities={"code", "debug"},
                            cost_tier=2))
    reg.register(ExpertSpec(name="frontier", capabilities={"reason", "ambiguous", "code"},
                            cost_tier=4))
    # 确定性优先：arithmetic 路由到 calc 而非 frontier（frontier 也覆盖 arithmetic？不，frontier 无 arithmetic）
    r1 = reg.route({"arithmetic"})
    assert r1.expert == "calc" and r1.confidence == 1.0
    # code：code_llm(cost 2) 优先于 frontier(cost 4)
    r2 = reg.route({"code"})
    assert r2.expert == "code_llm"
    # 未覆盖能力 → 低置信空路由
    r3 = reg.route({"vision"})
    assert r3.expert == "" and r3.confidence == 0.0
    # 熵与饿死：三次路由后 frontier 未被使用 → 饿死
    assert reg.starved_experts() == ["frontier"]
    ent = reg.route_entropy()
    assert 0 < ent <= 1.6  # 2 次路由的熵有限
    snap = reg.snapshot()
    assert snap["n_experts"] == 3 and "calc" in snap["utilization"]
    print("OK registry: 能力路由 + deterministic 优先 + 饿死检测 + 熵")


def test_llm_judge_stub():
    """LLM judge 桩：恒带 shift_risk=high，不执行。"""
    from decisioncore import llm_judge_stub
    p = DecisionPoint(name="subj", type=DecisionType.OPEN, candidates=["a", "b"])
    rec = llm_judge_stub(p, "some text")
    assert rec.shift_risk == "high" and rec.result is None
    print("OK llm_judge_stub: 末档标注")


if __name__ == "__main__":
    test_verifiable()
    test_enumeration()
    test_open_coverage_gate()
    test_open_majority()
    test_audit_immutability()
    test_registry()
    test_llm_judge_stub()
    print("ALL_DECISIONCORE_TESTS_OK")
