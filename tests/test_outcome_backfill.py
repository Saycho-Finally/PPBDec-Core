"""outcome_check 回填测试（SPEC §四承诺项的实现）。

纪律：原决策记录**一字不改**（不可变）；outcome 以追加事件落账，
消费方按 decision_id 关联。给没发生过的决策补写结果 → 拒绝。
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decisioncore import (CoverageEvidence, DecisionCore,  # noqa: E402
                          DecisionPoint, DecisionType)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def make_point():
    return DecisionPoint(
        name="sel", type=DecisionType.OPEN, candidates=["a", "b"],
        coverage=CoverageEvidence(n_candidates=4, source="sample(low, n=4)"))


def test_backfill():
    print("回填基本行为")
    p = os.path.join(os.path.dirname(__file__), "_tmp_outcome.jsonl")
    if os.path.exists(p):
        os.remove(p)
    dc = DecisionCore(audit_path=p)
    rec, _ = dc.decide_open(make_point(), ["a", "a", "b"])
    ev = dc.record_outcome(rec.decision_id, ok=True, detail="程序验证器核对通过")
    check("回填返回事件且 ok=True", ev is not None and ev["ok"] is True)
    check("事件携带决策点信息",
          ev["point_name"] == "sel" and ev["point_type"] == "open")
    check("detail 透传", ev["detail"] == "程序验证器核对通过")
    check("事件类型标记为 outcome", ev["type"] == "outcome")
    dc2 = DecisionCore()
    check("未知 decision_id → None（不造账）",
          dc2.record_outcome("nonexistent", ok=True) is None)
    if os.path.exists(p):
        os.remove(p)


def test_immutability_and_chain():
    print("不可变纪律与审计链")
    p = os.path.join(os.path.dirname(__file__), "_tmp_outcome2.jsonl")
    if os.path.exists(p):
        os.remove(p)
    dc = DecisionCore(audit_path=p)
    rec, _ = dc.decide_open(make_point(), ["a", "a", "b"])
    before = rec.to_json()
    dc.record_outcome(rec.decision_id, ok=False, detail="事后发现选错")
    after = rec.to_json()
    check("回填后原决策记录一字不改", before == after)
    lines = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    check("JSONL 两行：决策在前、outcome 在后",
          len(lines) == 2 and "type" not in lines[0]
          and lines[1].get("type") == "outcome")
    check("outcome 与决策按 decision_id 关联",
          lines[1]["decision_id"] == lines[0]["decision_id"])
    check("outcome 的 ok=False 被如实记录", lines[1]["ok"] is False)
    dc.record_outcome(rec.decision_id, ok=True, detail="复验翻案")
    lines2 = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    check("同一决策可多次回填（append-only）", len(lines2) == 3)
    if os.path.exists(p):
        os.remove(p)


def test_in_memory():
    print("无审计文件时也记账")
    dc = DecisionCore()
    rec, _ = dc.decide_open(make_point(), ["a", "a", "b"])
    dc.record_outcome(rec.decision_id, ok=True)
    check("内存账本记录 outcome", len(dc.outcomes) == 1
          and dc.outcomes[0]["decision_id"] == rec.decision_id)


if __name__ == "__main__":
    print("=" * 62)
    print("DecisionCore：outcome_check 回填")
    print("=" * 62)
    test_backfill()
    test_immutability_and_chain()
    test_in_memory()
    print("=" * 62)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("OUTCOME_OK" if n_pass == len(RESULTS) else "OUTCOME_FAIL")
    sys.exit(0 if n_pass == len(RESULTS) else 1)
