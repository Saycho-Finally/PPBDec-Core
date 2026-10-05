"""DecisionCore：统一判定/选择子层（PPBDec-Core 核心）。

设计约束（SPEC.md §一，非协商项）：
  1. 决策 = 选项集构造（上游，不在本模块）+ 选项内选择（本模块）。
     本模块拒绝受理无 coverage 证据的 open 决策。
  2. 判定器按决策点声明路由：verifiable 一票优先，open 的 LLM 判定永远带移位标注。
  3. 每次决策落一条不可变 DecisionRecord（JSONL append-only 证据链）。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class DecisionType(str, Enum):
    VERIFIABLE = "verifiable"   # 谓词判定（开放空间，无候选集）
    ENUMERATION = "enumeration" # 封闭枚举选择（完备性由协议保证）
    OPEN = "open"               # 上游采样构造的候选集（需 coverage 证据）


# open 决策的候选数下限：低于此值视为"覆盖不足"——不拒绝，但降级受理并在记录中标注
MIN_CANDIDATES = 2


@dataclass
class CoverageEvidence:
    """open 决策的 coverage 证据。缺失或候选为空 → 拒绝受理；
    存在但不足 → **降级受理**（结果保留，标注 degraded）。"""
    n_candidates: int
    source: str                      # 候选来源描述（如 "sample(low, n=4, stop=3)"）
    source_diversity: str = ""       # 采样多样性说明（temperature 等）
    history_coverage_rate: float | None = None  # 同类决策点的历史覆盖率（若有）

    def sufficiency(self, min_candidates: int = MIN_CANDIDATES) -> tuple[bool, str]:
        """覆盖是否充分。返回 (是否充分, 原因)。"""
        if self.n_candidates < min_candidates:
            return False, f"候选数 {self.n_candidates} < 下限 {min_candidates}"
        if not self.source.strip():
            return False, "缺少候选来源说明"
        return True, ""


@dataclass
class DecisionPoint:
    """一个决策点：声明类型、候选、判定器，由 DecisionCore 执行并审计。"""
    name: str
    type: DecisionType
    # verifiable：谓词（输入任意对象，输出 bool）。存在即一票优先。
    predicate: Callable[[Any], bool] | None = None
    # enumeration / open：候选列表
    candidates: list[Any] = field(default_factory=list)
    # enumeration：候选的完备性说明（协议/枚举来源）
    completeness_note: str = ""
    # open：coverage 证据（open 必填，否则拒绝）
    coverage: CoverageEvidence | None = None
    # 选择函数：如何从候选中选出 winner（默认第一个通过谓词/多数投票由 solver 决定）
    metadata: dict = field(default_factory=dict)


@dataclass
class DecisionRecord:
    """不可变证据链记录。"""
    decision_id: str
    ts: float
    point_name: str
    point_type: str
    solver: str
    result: Any
    confidence: float | None
    alternatives: list[Any]
    coverage_evidence: dict | None
    shift_risk: str           # none / low / high
    degraded: bool = False    # coverage 不足时降级受理的标记
    notes: str = ""

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, default=str)


@dataclass
class RouteDecision:
    """路由型决策（enumeration over experts）的返回：不止名字，还要能改变控制流。"""
    expert: str
    confidence: float
    required_capabilities: list[str]
    alternatives: list[str]
    reason: str
