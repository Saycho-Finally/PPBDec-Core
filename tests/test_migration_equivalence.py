"""迁移等价性测试：三处既有判定逻辑迁移到 DecisionCore 后行为不变。

用法：python tests/test_migration_equivalence.py

对照方式：`migrations/adapters.py` 把原判定函数**原样注入**为 DecisionPoint 的谓词
（黑盒包装，逻辑零重写），本测试逐一验证「迁移前的 legacy 调用」与
「迁移后经 DecisionCore 判定」在同输入下同输出。

外部组件（内容门 curator）不可用时该组用例记为 SKIP，不影响其余用例。
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

from decisioncore import (CoverageEvidence, DecisionCore, DecisionPoint,  # noqa: E402
                          DecisionType)

_spec = importlib.util.spec_from_file_location(
    "adapters", os.path.join(_REPO, "migrations", "adapters.py"))
adapters = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapters)

RESULTS = []
SKIPPED = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def skip(name, note=""):
    SKIPPED.append(name)
    print(f"  [SKIP] {name}" + (f" ---- {note}" if note else ""))


def test_early_stop():
    print("迁移点 1：早停判定（票型收敛，verifiable）")
    dc = DecisionCore()
    point = adapters.early_stop_point()
    for tail, expect in [
        (["12", "12", "12"], True),        # 连续 3 票一致
        (["12", "12"], False),             # 不足 STOP_K
        (["12", "13", "12"], False),       # 中途变化
        (["12", "34", "34", "34"], True),  # 中途变化后收敛
    ]:
        legacy = adapters.early_stop_legacy(tail)
        migrated = dc.decide_verifiable(point, tail).result
        check(f"{tail} -> {expect}", legacy == migrated == expect)


def test_cache_tier():
    print("迁移点 2：缓存层判定（provider usage 字段，verifiable）")
    dc = DecisionCore()
    point = adapters.cache_tier_point()
    for probe, expect in [
        ((0, 0), False),   # 两次探测全 miss
        ((0, 5), True),    # 第二次 hit>0
        ((3, 7), True),    # 缓存已热情形
    ]:
        legacy = adapters.cache_tier_predicate(probe)
        migrated = dc.decide_verifiable(point, probe).result
        check(f"probe={probe} -> {expect}", legacy == migrated == expect)


def test_content_gate():
    print("迁移点 3：内容门日期规则（R1，verifiable）")
    if adapters.date_valid is None:
        for i in range(4):
            skip(f"日期用例 {i + 1}", "curator 不可用（外部组件缺失）")
        return
    dc = DecisionCore()
    point = adapters.content_gate_date_point({})
    for date, expect in [
        ("2025年2月29日", False),  # 非闰年，日期不存在
        ("2024年2月29日", True),   # 闰年，存在
        ("2025年13月1日", False),  # 月份越界
        ("", True),                # 非日期格式放行给 R2
    ]:
        legacy = adapters.date_valid(date)
        migrated = dc.decide_verifiable(point, date).result
        check(f"{date!r} -> {expect}", legacy == migrated == expect)


def test_selection():
    print("迁移点 4：selection 投票（open + coverage）")
    dc = DecisionCore()
    point, keys = adapters.selection_point(["12", "8"], ["12", "12", "8"])
    rec, winner = dc.decide_open(point, keys)
    check("多数投票选出 '12'", winner == "12" and rec.result == "12")
    point2, keys2 = adapters.selection_point(["12", "8"], ["12", "8"])
    rec2, winner2 = dc.decide_open(point2, keys2)
    check("平票时不武断给出 winner", winner2 is None and rec2.confidence == 0.0)


def test_gate_rejection():
    print("显式失败路径：覆盖守门（拒绝受理，不静默降级）")
    dc = DecisionCore()
    bare = DecisionPoint(name="no_cov", type=DecisionType.OPEN, candidates=["a"])
    try:
        dc.decide_open(bare, ["a"])
        check("无 coverage 证据 -> 拒绝受理", False, "未抛错")
    except ValueError:
        check("无 coverage 证据 -> 拒绝受理", True)
    empty = DecisionPoint(name="empty", type=DecisionType.OPEN, candidates=[],
                          coverage=CoverageEvidence(n_candidates=0, source="none"))
    try:
        dc.decide_open(empty, [])
        check("候选为空 -> 拒绝受理", False, "未抛错")
    except ValueError:
        check("候选为空 -> 拒绝受理", True)


def main():
    print("=" * 72)
    print("迁移等价性：三处既有判定逻辑迁移到 DecisionCore 后行为不变")
    print("=" * 72)
    test_early_stop()
    test_cache_tier()
    test_content_gate()
    test_selection()
    test_gate_rejection()
    n_pass = sum(1 for _, s in RESULTS if s == "PASS")
    n_fail = sum(1 for _, s in RESULTS if s == "FAIL")
    tail = f"，{len(SKIPPED)} SKIP（外部组件缺失）" if SKIPPED else ""
    print("=" * 72)
    print(f"总计：{n_pass}/{len(RESULTS)} PASS{tail}"
          + (f"，{n_fail} FAIL" if n_fail else ""))
    if n_fail:
        return 1
    print("MIGRATION_EQUIVALENCE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
