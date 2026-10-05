"""coverage gate 的降级路径测试（v0.3 增量）。

原有语义：coverage 缺失或候选为空 → 拒绝受理（抛 ValueError）。
新增语义：coverage **存在但不足** → 降级受理——结果保留，但置信度折半、
shift_risk 强制 high、记录标注 degraded，避免把弱证据当充分证据用。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decisioncore import (MIN_CANDIDATES, CoverageEvidence,  # noqa: E402
                          DecisionCore, DecisionPoint, DecisionType)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def point(n_cand, source="sample(low, n=4, stop=3)", hist=None):
    return DecisionPoint(
        name="pick", type=DecisionType.OPEN, candidates=[f"c{i}" for i in range(max(n_cand, 1))],
        coverage=CoverageEvidence(n_candidates=n_cand, source=source,
                                  source_diversity="temperature=0.7",
                                  history_coverage_rate=hist))


def test_sufficiency():
    print("覆盖充分性判定")
    ok, why = CoverageEvidence(4, "sample(low, n=4)").sufficiency()
    check("候选数达标 → 充分", ok, why)
    ok2, why2 = CoverageEvidence(1, "sample(low, n=1)").sufficiency()
    check("候选数低于下限 → 不足", ok2 is False and "下限" in why2, why2)
    ok3, why3 = CoverageEvidence(4, "   ").sufficiency()
    check("缺来源说明 → 不足", ok3 is False, why3)
    check("下限常量为 2", MIN_CANDIDATES == 2)


def test_sufficient_path():
    print("充分覆盖：正常路径（行为不变）")
    dc = DecisionCore()
    rec, winner = dc.decide_open(point(4), ["12", "12", "8"])
    check("不标降级", rec.degraded is False)
    check("置信度未折半", rec.confidence == round(2 / 3, 4), str(rec.confidence))
    check("选出多数票", winner == "12")


def test_degraded_path():
    print("覆盖不足：降级受理")
    dc = DecisionCore()
    rec, winner = dc.decide_open(point(1), ["12"])
    check("标记 degraded", rec.degraded is True)
    check("shift_risk 强制 high", rec.shift_risk == "high", rec.shift_risk)
    check("置信度折半（1.0 → 0.5）", rec.confidence == 0.5, str(rec.confidence))
    check("降级原因写入 notes", "coverage 不足" in rec.notes, rec.notes[:40])
    check("仍然给出结果（不拒绝）", winner == "12")
    check("覆盖证据随记录留存",
          rec.coverage_evidence.get("n_candidates") == 1)


def test_degraded_blocks_low_risk():
    print("降级压过高历史覆盖率")
    dc = DecisionCore()
    rec, _ = dc.decide_open(point(1, hist=0.95), ["12"])
    check("历史覆盖率高也不给 shift_risk=low",
          rec.shift_risk == "high" and rec.degraded is True)
    dc2 = DecisionCore()
    rec2, _ = dc2.decide_open(point(4, hist=0.95), ["12", "12"])
    check("覆盖充分时高历史覆盖率才降为 low",
          rec2.shift_risk == "low" and rec2.degraded is False)


def test_reject_unchanged():
    print("拒绝路径未被削弱（回归）")
    dc = DecisionCore()
    bare = DecisionPoint(name="x", type=DecisionType.OPEN, candidates=["a"])
    try:
        dc.decide_open(bare, ["a"])
        check("无 coverage 仍拒绝受理", False, "未抛错")
    except ValueError:
        check("无 coverage 仍拒绝受理", True)
    empty = point(0)
    try:
        dc.decide_open(empty, [])
        check("候选为空仍拒绝受理", False, "未抛错")
    except ValueError:
        check("候选为空仍拒绝受理", True)


def test_audit_carries_degraded():
    print("审计记录携带降级标记")
    p = os.path.join(os.path.dirname(__file__), "_tmp_audit.jsonl")
    if os.path.exists(p):
        os.remove(p)
    dc = DecisionCore(audit_path=p)
    dc.decide_open(point(1), ["12"])
    line = json.loads(open(p, encoding="utf-8").read().strip().split("\n")[-1])
    check("JSONL 字段含 degraded=True", line.get("degraded") is True)
    check("JSONL 字段含 shift_risk=high", line.get("shift_risk") == "high")
    os.remove(p)


if __name__ == "__main__":
    print("=" * 62)
    print("DecisionCore v0.3：coverage 降级路径")
    print("=" * 62)
    test_sufficiency()
    test_sufficient_path()
    test_degraded_path()
    test_degraded_blocks_low_risk()
    test_reject_unchanged()
    test_audit_carries_degraded()
    print("=" * 62)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("COVERAGE_DEGRADE_OK" if n_pass == len(RESULTS) else "COVERAGE_DEGRADE_FAIL")
    sys.exit(0 if n_pass == len(RESULTS) else 1)
