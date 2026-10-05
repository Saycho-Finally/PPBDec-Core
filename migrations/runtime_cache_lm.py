"""CacheTiers 与 LM 内容门的运行时灰度开关（同 DecisionAwareStop 模式）。

迁移原则不变：原判定函数黑盒注入，DecisionCore 只做接口统一 + 审计。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(__file__)
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.environ.get("PPB_CACHE_ROOT", os.path.join(_ROOT, "PPBExt-Cache")))
sys.path.insert(0, os.environ.get(
    "PPB_KNOWLEDGE_EXPERIMENTS",
    os.path.join(_ROOT, "PPBExt-Knowledge", "experiments")))

from decisioncore import DecisionCore, DecisionPoint, DecisionType  # noqa: E402


class CacheTierAwareProbe:
    """CacheTiers 的层判定走 DecisionCore（verifiable：usage 字段即谓词）。

    原实现：两次同前缀请求 → 第二次 hit>0 → Tier 1。
    本包装不改 probe 逻辑，只把"判层"这一步变成带审计的决策点。"""

    def __init__(self, dc: DecisionCore):
        self.dc = dc

    def record_tier(self, provider: str, two_probe_hit_tokens: tuple[int, int],
                    tier_result: str) -> DecisionPoint:
        """判层决策点（原 probe 已得出 tier_result，此处为判定过程留审计）。"""
        point = DecisionPoint(
            name=f"cachetiers.{provider}.tier_detection",
            type=DecisionType.VERIFIABLE,
            predicate=lambda two: two[1] > 0,   # 第二次 hit>0 → 自动前缀缓存可用
            metadata={"migrated_from": "cachecortex CacheTiers.probe",
                      "tier_result": tier_result,
                      "decision_kind": "provider 能力判定（verifiable）"})
        self.dc.decide_verifiable(point, subject=two_probe_hit_tokens)
        return point


class ContentGateDC:
    """LM 内容门 R1 的运行时切换（R2 佐证计分/R3 准入为批处理逻辑，
    单条运行时包装先覆盖 R1——R2/R3 的接口占位见 实现边界）。"""

    def __init__(self, dc: DecisionCore):
        self.dc = dc
        self._date_valid = None
        try:
            sys.path.insert(0, os.environ.get(
                "PPB_KNOWLEDGE_EXPERIMENTS",
                os.path.join(_ROOT, "PPBExt-Knowledge", "experiments")))
            import curator as _curator  # noqa: E402
            self._date_valid = _curator.date_valid
            self._curate = _curator.curate
        except ImportError:
            pass

    def r1_date_decision(self, gate: str, date_str: str) -> bool | None:
        """R1 日期确定性判定（verifiable，黑盒注入 date_valid）。"""
        if self._date_valid is None:
            return None
        point = DecisionPoint(
            name=f"contentgate.{gate}.r1_date", type=DecisionType.VERIFIABLE,
            predicate=self._date_valid,
            metadata={"migrated_from": "curator R1",
                      "decision_kind": "内容门准入判定（verifiable：日期规则）"})
        rec = self.dc.decide_verifiable(point, subject=date_str)
        return bool(rec.result)

    # 实现边界：R2 佐证计分（TIER_W 加权）与 R3 准入（score>=2 或 official）属
    # 批处理组合逻辑；其单条运行时包装需 curator 提供 per-claim 接口，当前仅覆盖 R1。
