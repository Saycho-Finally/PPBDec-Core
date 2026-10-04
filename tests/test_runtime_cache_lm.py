"""runtime_cache_lm 测试：CacheTier 与 LM 内容门 R1 的运行时切换等价性。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from migrations.runtime_cache_lm import CacheTierAwareProbe, ContentGateDC  # noqa: E402
from decisioncore import DecisionCore  # noqa: E402

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" —— {note}" if note else ""))


def test_cache_tier_dc():
    print("CacheTier 判定走 DecisionCore")
    dc = DecisionCore(audit_path=None)
    probe = CacheTierAwareProbe(dc)
    point = probe.record_tier("deepseek", (0, 5000), "tier1")
    rec = dc.records[-1]
    check("Tier1 判定（第二次 hit>0）", rec.result is True and
          rec.point_name == "cachetiers.deepseek.tier_detection")
    probe.record_tier("unknown_provider", (0, 0), "tier3")
    rec2 = dc.records[-1]
    check("Tier3 判定（两次全 miss）", rec2.result is False)
    check("审计 2 条", len(dc.records) == 2)


def test_content_gate_r1():
    print("LM 内容门 R1 走 DecisionCore")
    dc = DecisionCore(audit_path=None)
    gate = ContentGateDC(dc)
    if gate._date_valid is None:
        print("  [SKIP] curator 不可导入")
        return
    r1 = gate.r1_date_decision("gate_web", "2026-09-15")
    check("R1 日期判定（同 curator 原行为）", r1 is True and
          dc.records[-1].point_name == "contentgate.gate_web.r1_date")
    check("审计落盘", len(dc.records) == 1)


if __name__ == "__main__":
    print("=" * 60)
    print("CacheTier / ContentGate R1 运行时切换")
    print("=" * 60)
    test_cache_tier_dc()
    test_content_gate_r1()
    print("=" * 60)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("RUNTIME_OK" if n_pass == len(RESULTS) else "RUNTIME_FAIL")
