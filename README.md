# Addenda-Decide ｜ 补遗：LLM 应用的统一判定/选择子层 · DecisionCore

**一句话**：LLM 应用里到处都是决策（门、路由、早停、选择、预算），但它们散装在各自的项目里。
本模块把它们抽成一个**统一的决策核**：决策点按类型声明，判定器沿确定性光谱路由，
每次决策落一条不可变的证据链——并且**开放决策的默认判定器是"合并"而不是"挑选"**
（fusion F1 0.716 vs 最好单候选，实测见下）。

> License: MIT ｜ 依赖：核心零依赖 ｜ Python ≥3.10

---

## 设计约束（从实测批判继承，非协商项）

1. **决策 = 选项集构造（上游）+ 选项内选择（本模块）**。决策模型只做后者，
   价值天花板被前者封死——因此本模块**拒绝受理无 coverage 证据的开放决策**
   （候选集里没有的东西，选不出来）。
2. **判定器可靠性分场景**：分布内小模型匹敌大模型（BERT-210M 判别 GSM8K 98.8%）；
   分布移位下 LLM judge 退化到近随机（arXiv 2603.06594，6642 人工标注）。
   因此判定器**按决策点声明路由**，不默认 LLM。

## 决策点类型学

| 类型 | 语义 | 判定器 | 例子 |
|---|---|---|---|
| `verifiable` | 谓词判定（开放空间，无候选集） | 程序验证器（确定性，零成本） | 数值验证、schema 检查、票型收敛 |
| `enumeration` | 封闭枚举选择（完备性由协议保证） | 规则 → 探针 → 微模型 | 模型路由、工具选择 |
| `open` | 上游采样构造的候选集 | **必须附 coverage 证据**；默认判定器为 fusion | 答案 selection、评审挑选 |
| `route` | 专家注册表上的能力匹配 | capability 契约匹配（deterministic 优先） | MoE 路由、外挂选择 |

## 判定器光谱

```
program_verifier（$0，确定性）→ rule_engine（$0）→ majority_vote（$低）
  → fusion（合并替代选择）→ small_probe → micro_decision_model
    → llm_judge（末档，恒带 shift_risk=high）
```

规则：沿光谱从左往右找第一个能处理该决策点的判定器。升级到 llm_judge 需要
三条件同时成立（无谓词 + 枚举不完备 + 声明低移位风险）——实践中几乎不发生。

## 实测：开放决策上 fusion 完胜 selection

任务：5 段含已知 bug 的 Python 代码（15 个 gold bug，全部执行级验证）× 6 路采样评审 ×
五档判定器对照（30 个候选，Flash low 档采样）：

| 判定器 | 均值 F1 | 说明 |
|---|---|---|
| 最好单候选（selection 上限） | ~0.6 | selection 的天花板 |
| deterministic fusion（零 LLM 聚类） | 0.216 | 机械并集的底线 |
| **LLM fusion（Fusion-of-N 式）** | **0.716** | **recall 全 1.0**；单任务满分零误报 |

**结论**：可分解任务上，"合并候选"显著优于"挑选候选"——
与 Fusion-of-N（ICLR 2026）的结论互证，且本模块把它落成了判定器光谱的一个正式档位。

## 证据链审计

每次决策落一条不可变 DecisionRecord（JSONL append-only）：

```json
{"decision_id": "a1b2c3", "ts": 1790000000.0,
 "point_name": "answer_selection", "point_type": "open",
 "solver": "majority_vote(value_key)", "confidence": 1.0,
 "coverage_evidence": {"n_candidates": 4, "source": "sample(low, n=4)"},
 "alternatives": {"12": 3}, "shift_risk": "low",
 "result": "12"}
```

## 快速上手

```python
from decisioncore import DecisionCore, DecisionPoint, DecisionType, CoverageEvidence

dc = DecisionCore(audit_path="decisions.jsonl")

# verifiable：程序谓词（零成本，确定性）
dc.decide_verifiable(
    DecisionPoint(name="check", type=DecisionType.VERIFIABLE,
                  predicate=lambda x: x == "42"), subject="42")

# open：上游采样 + coverage 证据 + 多数投票
rec, winner = dc.decide_open(
    DecisionPoint(name="pick", type=DecisionType.OPEN,
                  candidates=["3*4", "2*6"],
                  coverage=CoverageEvidence(n_candidates=2, source="sample(low,2)")),
    vote_keys=["12", "12"])
```

## 仓库结构

```
decisioncore/    核心库（core 类型学 / solvers 光谱 / registry 专家表 / route 路由决策）
migrations/      三外挂运行时切换适配器（黑盒注入原判定函数，逻辑零重写）
tests/           32 项测试全过（核心七测 + v2 十测 + 迁移等价性十五测 + runtime 五测）
results/         E2 实测数据（采样候选 / fusion 对照 JSON）
e2_task_family_a.py  任务族 A：5 段含已知 bug 的代码 + 15 个执行级验证的 gold bug
SPEC.md          完整设计文档（类型学 / 光谱 / 审计 / 理论约束）
E2_正式实验设计_v2.md  实验设计与文献锚点
```

## 测试状态

- 核心七测：类型路由 / coverage 守门 / 审计不可变性 / registry 熵与饿死 / 末档标注
- v0.2 十测：route 决策 / 运行时灰度开关等价性
- 三外挂迁移等价性 15/15：思考早停 / CacheTier / 内容门 R1 / selection 投票
  （黑盒注入原判定函数，同输入同输出）
- runtime 切换 5/5：CacheTier 与内容门 R1 的运行时路径

## 引用的先行者

- "Making, Not Taking, the Best of N"（ICLR 2026）：Fusion-of-N vs Best-of-N——
  fusion 档位的理论来源（polylithic 质量观、超越 oracle）
- DVDR-LLM（ICSE 2026 LLM4Code）：多 LLM 集成漏洞检测 +10-12%——任务族 A 的同域先例
- Nolan Lawson 三 AI 多数决：bug 检测的工程同构
- GSA（arXiv 2503.04104）：open-ended 任务上 self-consistency 不适用而生成式聚合有效
- BERT-as-a-Judge / INSPECTOR：小判定器匹敌大模型的实证
- "A Coin Flip for Safety"（arXiv 2603.06594）：LLM judge 分布移位退化的审计
