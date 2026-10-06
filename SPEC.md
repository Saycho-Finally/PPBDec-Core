# PPBDec-Core Spec v0.5（2026-10-06）

> 定位：**共享的判定/选择子层**——上层组件内部本来各自带着决策逻辑
> （知识注入的内容门与路由、采样策略的早停与 selection、能力探测与预算），
> 本模块把它们抽成一个统一的决策核（DecisionCore）。

---

## 一、理论约束（从实测批判继承，非协商项）

### 批判一：决策模型只做 selection，天花板被 coverage 封死

决策 = 选项集构造（难，开放世界）+ 选项内选择（易，封闭世界）。
决策模型只做后者。两种病态：

- **病态一（伪决策）**：候选集只有一个真答案——不需要选择，需要计算或查找
- **病态二（coverage 缺失）**：正确答案不在候选集里——选择器再准也是零

**推论**：DecisionCore 不接受"无 coverage 保证的开放选择"作为可路由决策——
开放选择必须先经过上游采样/检索（由调用方声明 coverage 证据）。

### 批判二：判定器可靠性分场景

- 分布内：小模型/内部表示/程序验证器匹敌大模型（BERT-210M GSM8K 98.8%；INSPECTOR 内部探针 80-90%）
- 分布移位：LLM judge 退化到近随机（arXiv 2603.06594，6642 人工标注）

**推论**：判定器按**决策点声明**路由，不默认 LLM。每个 DecisionPoint 必须声明
自己的类型与分布移位风险，DecisionCore 据此配档。

## 二、决策点类型学（三类）

| 类型 | 语义 | coverage 保证 | 判定器 | 例子 |
|---|---|---|---|---|
| `verifiable` | 谓词在开放空间上定义（判定，不是选择） | 不需要候选集 | **程序验证器**（确定性，零成本） | Countdown 数值验证、JSON schema、主干哈希检查 |
| `enumeration` | 候选集有完备性保证的枚举选择 | 候选集由代码/协议枚举（工具集、标签集、档位表） | 规则 → 探针 → 微模型（按预算升档） | 模型路由、工具选择、档位选择 |
| `open` | 候选集由上游采样构造 | **调用方必须附 coverage 证据**（采样次数/来源多样性/历史覆盖率） | 投票 → 探针 → LLM（末档，带移位警告） | 答案 selection、RAG chunk 挑选 |

**路由规则**：verifiable 一票优先（有谓词绝不投票）；enumeration 按 cost_tier 升档。
open 的 coverage 按三态处理：

| coverage 状态 | 处理 |
|---|---|
| 缺失 / 候选为空 | **拒绝受理**（抛 ValueError；病态二守门） |
| 存在但不足（候选数低于下限，或缺来源说明） | **降级受理**：结果保留，但置信度折半、`shift_risk` 强制 high、记录标 `degraded` |
| 充分 | 正常受理；历史覆盖率 > 0.8 时 `shift_risk` 可降为 low |

降级的意义：弱证据并非不可用，但**不能被当成充分证据**。降级标记随 `DecisionRecord`
进入审计链，事后归因时可区分"当时就是弱证据"与"当时证据充分但选错了"。

LLM judge 的结果永远带 `shift_risk: high` 标注。

## 三、决策器光谱（从确定性到生成式）

```
program_verifier（确定性，$0）          ← 已实现
  → rule_engine（确定性，$0）           ← 已实现
    → small_probe（内部表示/微模型，$低）   ← 未实现（见八、缺口核对表）
      → micro_decision_model（2B 级，$低-中）← 未实现
        → llm_judge（生成式，$高，移位风险高）  ← 桩（三条件守门，永不默认）
```

另有 `majority_vote`：不属于光谱档位，是 **open 型决策点的判定器**
（对上游采样候选做多数投票，与 coverage 三态守门配合）。

规则：**沿光谱从左往右找第一个能处理该决策点的判定器**。升级到 llm_judge 需要
显式声明理由（无谓词可用 + 枚举不完备 + 低移位风险三者同时成立）——这在实践中
几乎不发生，所以 llm_judge 是理论档位而非默认路径。

## 四、证据链审计（DecisionRecord）

每次决策落一条不可变记录（回应"模型不说话不代表没替你做决定"的问责问题）。
下方为**真实字段形状**（与 `DecisionRecord.to_json()` 一致）：

```json
{
  "decision_id": "5ac7a9cd769a",
  "ts": 1791249095.67,
  "point_name": "answer_selection",
  "point_type": "open",
  "solver": "majority_vote(value_key)",
  "result": "3*4",
  "confidence": 0.75,
  "alternatives": {"3*4": 3, "2*6": 1},
  "coverage_evidence": {"n_candidates": 4, "source": "sample(low, n=4, stop=3)",
                        "source_diversity": "temperature=0.7",
                        "history_coverage_rate": null},
  "shift_risk": "high",
  "degraded": false,
  "notes": "open selection; candidate set constructed upstream"
}
```

字段语义：`coverage_evidence.source`（候选从哪来——coverage 审计）、`solver`
（用了哪档判定器）、`alternatives`（未被选中的选项与票数——事后归因）、
`shift_risk`（分布移位风险声明）、`degraded`（coverage 不足时的降级标记）。

**事后回填**：`record_outcome(decision_id, ok, detail)` 以**追加**方式落一条
`{"type": "outcome", ...}` 事件，原决策记录一字不改（不可变纪律），
消费方按 `decision_id` 关联。本核不给不在账内的 decision_id 补写结果。

## 五、与编排层的接口

DecisionCore 的 `enumeration` 决策点消费**专家注册表**（ExpertRegistry）：

- 注册表提供 capability 契约（ExpertSpec：capabilities/cost_tier/tools）——路由有具体物可推理
- 注册表维护路由分布统计（熵/利用率/饿死检测）——编排层的负载均衡输入
- RouteDecision 带置信度；低置信改变控制流（多专家并行 / 升级路由 / 拆任务）

专家注册表由本仓库的 `decisioncore/registry.py` 提供协议与默认实现；编排运行时不在
本仓库范围内（见第六节）。

## 六、实现范围（v0.3）

**在本仓库内：**

- `decisioncore/core.py`：DecisionPoint / DecisionRecord / 决策器协议
- `decisioncore/solvers.py`：光谱实现（program_verifier / rule_engine / majority_vote / llm_judge 桩）
- `decisioncore/registry.py`：ExpertRegistry 协议 + 默认实现
- `decisioncore/route.py`：route 决策（能力契约匹配 + 路由分布快照）
- `migrations/`：迁移适配器（原判定函数原样注入，逻辑零重写）
- 审计：DecisionRecord 以 JSONL append-only 落盘，由 DecisionCore 内部提交
- 依赖：核心零依赖

**不在本仓库内（0.3.0 起移出）：**

- 编排运行时（专家池执行、负载均衡回灌）
- 装载前治理预检（互斥资源/依赖/版本）
- 认知可观测性（token 速率/循环耗尽/工具错误率/路由健康）

## 七、与三项目的对接计划

| 项目 | 决策点 | 迁移路径 |
|---|---|---|
| 知识注入 | 内容门三规则（verifiable）→ 技能路由（enumeration） | 内容门谓词注册为 verifier |
| 采样策略 | 早停（verifiable：票型收敛）→ selection（open+coverage）→ 档位（enumeration） | 已有 coverage/selection 分解，直接对接 |
| 前缀缓存 | provider 层判定（verifiable：usage 字段探测）→ 杠杆选择（enumeration） | 能力探测结果注册为 rule_engine |

## 八、缺口核对表（2026-10-06 逐条核对）

对照实现、测试与验证实验报告逐条核对的结果。**这张表就是 D2 的交付物**，
后续新增承诺时同步更新。

| SPEC 承诺 | 状态 | 依据 |
|---|---|---|
| verifiable / enumeration / open 三类决策点 | 已实现 | `solvers.py` 三判定器 + 全部测试套件 |
| open 的 coverage 三态（缺失拒绝 / 不足降级 / 充分受理） | 已实现（0.4.0） | `tests/test_coverage_degrade.py` 19 项 |
| 判定器光谱五档 | 部分实现 | program_verifier / rule_engine / llm_judge（桩）已实现；`small_probe`、`micro_decision_model` **未实现**（无内部表示探针与微模型接入，无调用方） |
| DecisionRecord 不可变 JSONL 落盘 | 已实现 | `_commit` append-only，由 DecisionCore 内部提交 |
| `outcome_check` 事后回填对错 | 已实现（0.5.0） | `record_outcome`：追加 outcome 事件、原记录不改；`tests/test_outcome_backfill.py` 11 项 |
| 迁移：知识注入内容门（verifiable） | 已实现 | `migrations/adapters.py` 迁移点 3 |
| 迁移：采样早停（verifiable）+ selection（open） | 已实现 | 迁移点 1 / 4 |
| 迁移：采样档位选择（enumeration） | 未实现 | 无对应迁移点，档位选择仍留在采样侧（见下） |
| 迁移：前缀缓存能力探测（rule_engine） | 已实现 | 迁移点 2 + `migrations/runtime_cache_lm.py` |
| 低置信改变控制流（并行 / 升级 / 拆任务） | 部分 | `RouteDecision` 携带置信度与备选；控制流变更属编排层（本仓库范围外，见第六节） |
| 编排运行时 / 治理预检 / 可观测性 | 移出本仓库 | 0.3.0 起由 PPB-MoE 承载（含静默失败检测） |
| 版本号与 CHANGELOG 一致性 | 已实现 | 审计器一致性检查项 |

**未实现项的去向**：`small_probe` / `micro_decision_model` 需要接入内部表示或微模型，
在出现第一个真实调用方之前不实现（避免无消费者的设计）；采样档位选择的迁移
需采样侧先明确档位枚举的完备性来源；两者都在出现需求时按本 SPEC 的类型学补位。
