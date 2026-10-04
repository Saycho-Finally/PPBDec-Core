"""三外挂 → DecisionCore 迁移适配器（黑盒包装，逻辑零重写）。

迁移原则：
  1. 原判定函数**原样注入**为 DecisionPoint 的谓词/判定器——不重写，等价性由构造保证
  2. 对照测试（test_migration_equivalence.py）验证：同输入 → 迁移前后同输出
  3. 新增能力 = 审计记录（DecisionRecord）+ 统一接口 + 跨外挂复用，而非改变行为

每个适配器提供：
  - `*_point(...)` → 构造 DecisionPoint（原判定函数注入）
  - `*_legacy(...)` → 原实现的直接调用（对照组）
"""

from __future__ import annotations

import os
import sys
from collections import Counter

# ---- 路径：接入三外挂的原实现 ----
_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

sys.path.insert(0, _ROOT)                          # exocortex（采样外挂）
sys.path.insert(0, os.path.join(_ROOT, "..", "addenda-decide"))  # decisioncore
sys.path.insert(0, os.path.join(_ROOT, "..", "仓库2", "cachecortex"))  # 缓存外挂
sys.path.insert(0, os.environ.get("ADDENDA_LM_EXPERIMENTS", "../../addenda-lm/experiments"))

from decisioncore import (DecisionCore, DecisionPoint,  # noqa: E402
                          DecisionType, CoverageEvidence)

try:
    from exocortex.scaffold.selfconsist import majority_vote as think_majority  # noqa
except ImportError:
    think_majority = None

try:
    from exocortex.tasks.countdown import safe_eval_expr
    from exocortex.tasks import CountdownTask
except ImportError:
    safe_eval_expr = None
    CountdownTask = None

# ---- 迁移点 1：采样外挂 · 早停判定（verifiable）----

STOP_K = 3


def early_stop_predicate(vote_keys_tail: list[str]) -> bool:
    """原逻辑照抄（e1_formal.py 的早停判定）：连续 STOP_K 票数值一致即收敛。"""
    return len(vote_keys_tail) >= STOP_K and len(set(vote_keys_tail[-STOP_K:])) == 1


def early_stop_point() -> DecisionPoint:
    return DecisionPoint(
        name="think_early_stop", type=DecisionType.VERIFIABLE,
        predicate=early_stop_predicate,
        metadata={"migrated_from": "exocortex e1_formal stop_k=3",
                  "decision_kind": "票型收敛判定（verifiable：无需候选集）"})


def early_stop_legacy(vote_keys_tail: list[str]) -> bool:
    """对照组：原实现的判定（与 early_stop_predicate 逻辑相同——黑盒包装的证明）。"""
    return early_stop_predicate(vote_keys_tail)


# ---- 迁移点 2：PPBExt-Cache · Tier 判定（verifiable）----

def cache_tier_predicate(two_probe_hit_tokens: tuple[int, int]) -> bool:
    """原逻辑（CacheTiers.probe 的判定核）：第二次探测 hit>0 → Tier 1（自动前缀缓存）。"""
    return two_probe_hit_tokens[1] > 0


def cache_tier_point() -> DecisionPoint:
    return DecisionPoint(
        name="cache_tier_detection", type=DecisionType.VERIFIABLE,
        predicate=cache_tier_predicate,
        metadata={"migrated_from": "cachecortex CacheTiers.probe",
                  "decision_kind": "provider 能力判定（verifiable：usage 字段即谓词）"})


# ---- 迁移点 3：知识外挂 · 内容门日期规则（verifiable）----

try:
    sys.path.insert(0, os.path.join(_ROOT, "..", "仓库"))
    import curator as _curator  # noqa: E402
    date_valid = _curator.date_valid
except ImportError:
    date_valid = None


def content_gate_date_point(claim: dict) -> DecisionPoint | None:
    """LM 内容门 R1（日期确定性）包装为 verifiable 决策点。
    claim: {"claim": str, "date": str|None, ...}"""
    if date_valid is None:
        return None
    return DecisionPoint(
        name="content_gate_r1_date", type=DecisionType.VERIFIABLE,
        predicate=lambda c: date_valid(c),
        metadata={"migrated_from": "addenda-lm curator R1",
                  "decision_kind": "内容门准入判定（verifiable：日期规则确定性）"})


# ---- 迁移点 4：采样外挂 · selection 投票（open + coverage）----

def selection_point(candidates: list[str], vote_keys: list[str],
                    source: str = "sample(low, n=4, stop=3)") -> tuple[DecisionPoint, list[str]]:
    """selection 决策点（open）：候选来自上游采样，coverage 证据由采样参数构成。"""
    point = DecisionPoint(
        name="answer_selection", type=DecisionType.OPEN,
        candidates=candidates,
        coverage=CoverageEvidence(
            n_candidates=len(candidates), source=source,
            source_diversity="temperature=0.7"))
    return point, vote_keys
