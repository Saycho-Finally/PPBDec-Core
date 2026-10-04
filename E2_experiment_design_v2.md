# E2 正式实验设计 v2 ｜ 不可验证任务的 selection 质量测量（2026-10-03）

> 转向依据：E1 的 18 臂全量确认可验证任务上 selection 损失 = 0（数值投票即验证器）——
> 程序验证器在此域增量为零。E2 的价值域正式转向**不可验证任务**：
> selection 真正开放、无 ground truth、判定器光谱需要真实考验的地方。

---

## 一、任务族设计（两个，互补）

### 任务族 A：代码评审（弱 ground truth 可构造）[重点]推荐先做

**设计**：给 LLM 一段含已知 bug 的代码，要求列出 bug。多路采样（N×effort 组合）产生候选评审，
selection 的准确率用**已知 bug 清单**核算（召回率 + 误报率）。

- 为什么可行：bug 清单是构造时注入的 ground truth——**不可验证任务里最接近可验证的域**
- 决策点：从 K 个候选评审中选"最完整正确的一个"（open + coverage）或合并（selection 变 fusion）
- 测量：selection 准确率 vs coverage（上游采样覆盖了多少 bug）→ **selection 损失第一次在开放域被量化**
- 对照：数值投票不可用 → 判定器光谱真正上阵（llm_judge 档 vs 探针档 vs 简单启发式：候选长度/特异性）

### 任务族 B：开放问答的双 judge 一致性

**设计**：无标准答案问题（"方案 A 与 B 哪个更适合 X 场景"），N 路采样答案，
用**两个独立 LLM judge**（不同模型家族）做 pair-wise 比较，测量 judge 间一致率。

- 测量：judge-agreement 率作为 selection 可信度的下界代理；不一致率高的决策点
  自动标记 `shift_risk: high`（DecisionCore 的审计字段直接消费）
- 定位：不测 accuracy（无 ground truth），测**决策稳定性**——一致的错误仍是错误，
  但不一致的决策点暴露了"这个决策不该被自动化"

## 一点五、文献锚点（2026-10-03 检索——假设已有正面先例）

1. **Fusion-of-N vs Best-of-N**（"Making, Not Taking, the Best of N"，ICLR 2026）：
   把聚合范式从"选最好"改为"fusor 合成新答案 y⋆∉Y"，**超越候选池上界（oracle）**。
   核心概念 polylithic quality——每个候选都含高/低质量片段（正是"合并才是价值"的学术表述）。
   Zero-training（fusor 就是一个 prompt）；关键经验：**必须显式指示丢弃最差片段**。
2. **GSA**（arXiv 2503.04104）：LLM 聚合自身响应 > choose-from-N / self-refine；
   **open-ended 任务上 self-consistency 不适用而生成式聚合有效**（Alpaca-eval/MT-bench 增益）
3. **DVDR-LLM**（ICSE 2026 LLM4Code）：多 LLM 集成漏洞检测，比单模型准确率 +10-12%，
   多文件漏洞 recall +18%；共识阈值 T 平衡 precision/recall
4. **三 AI 多数决**（Nolan Lawson 工程实践）：三个不同 AI 评审同一代码，多数一致的
   bug 几乎零假阳性——**与我们的 bug 清单设计完全同构**
5. Snap CodePal 多轮共识：并行基线轮 + 前两轮一致则中止第三轮——**与我们的早停同构**

**E2 的独特增量**：把 Fusion 作为 DecisionCore 光谱的新档位（selection 的替代判定器），
与五档判定器同台对照——文献测的是 fusion vs BON，我们测的是 fusion 在**决策器光谱里的位置**。

## 二、判定器光谱的对照矩阵（任务族 A）

| 判定器档 | 实现 | 预期 |
|---|---|---|
| 启发式 | 候选长度 / bug 关键词计数 | 基线（可能意外地强）|
| 投票 | 候选间的 bug 集合重叠投票 | 中档 |
| 探针 | 小模型对候选评分 | 中档 |
| LLM judge | pro 对候选排序 | 上限参照 |
| **fusion（DecisionCore 特有）** | 候选 bug 集合并集（不做选择，做合并）| **可能显著高于全部 selection 方法**——如果 fusion 赢了，"选择"这个动作本身就该被"合并"替代 |

**fusion 假设**（本轮最重要的科学问题）：在可分解任务上，selection 的问题设定本身是错的——
候选是部分正确的视图，合并优于选择。这与"决策模型批判"同源：选择是廉价胶水，合并才是价值。

## 三、执行计划（需 key，预算 ~$0.5-1）

1. 构造 5 段含 2-3 个已知 bug 的 Python 代码（bug 清单入库）
2. 每段 × N=6 采样（low，off-peak）→ 30 个候选评审
3. 五档判定器 × 5 段对照（LLM judge 档用 pro，~$0.3）
4. 产出：selection 损失在开放域的第一次量化 + fusion vs selection 的正面对照
5. DecisionRecord 全量审计（open 决策 + coverage 证据 + outcome_check 回填 bug 清单）

## 四、与 DecisionCore 的接口

- 任务族 A 的决策点：`type=open, coverage={n_candidates=6, source="sample(low,6)"}`
- 判定器五档全部走 DecisionCore 光谱（v0.2 已就位）
- 审计落 decisions.jsonl——**这是 DecisionCore 第一次在真实开放域运行**
