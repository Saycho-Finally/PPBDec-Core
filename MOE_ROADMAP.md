# MoE 架构 ｜ 完整路线与优化计划（2026-10-04）

> 本文档是应用层稀疏 MoE 架构的实现总账与优化路线。四层架构图见会话语境；
> 缺口清单来自《外挂系列架构 v2》（2026-10-03），本文记录落地状态与后续。

---

## 一、当前实现状态（四层 + 49 项测试全过）

| 层 | 组件 | 状态 | 测试 |
|---|---|---|---|
| ① 治理层 | Governance（冲突/权限/依赖预检）| [通过] 新落地 | 6 项 |
| ① 治理层 | CognitiveMonitor（token 速率/循环耗尽/工具错误/路由健康）| [通过] 新落地 | 6 项 |
| ② Router | DecisionCore v0.2（类型学/光谱/审计/route）| [通过] | 17 项 |
| ③ Expert Pool | 知识/缓存/采样三位专家在线；记忆/工具修复候选 | 部分 | 迁移 15 + runtime 5 |
| ④ 基础设施 | Ledger / ExpertRegistry / 进度落盘 / 预热保活 | [通过] | 含于上 |

**v2 七缺口的落地进度**：
1. [通过] DecisionCore 未实现 → v0.2 完成
2. [通过] ExpertSpec 注册表缺失 → experts.py 落地
3. [通过] 路由熵/饿死监控缺失 → registry + CognitiveMonitor
4. [通过] 治理层未接入 → Governance 落地（12/12）
5. ⏳ Refusal Bias 处理 → 设计待做（P1）
6. [通过] 认知可观测性三件套 → CognitiveMonitor 落地
7. ⏳ 外挂粒度评估 → P1

## 二、优化路线

### P1（本周，零 API 成本）

1. **Refusal Bias 处理（历史折叠）**：能力升级后历史里的拒答记录会持续 conditioning
   （DMoE 的 Surgical History Pruning 指出）。本项目采用 append-only 兼容的**折叠**方案：
   不删除历史，追加一条"能力已就绪"的折叠记录（带时间戳与来源），让后续轮次读到更新后的
   状态。接口：`ExternalMemory.append_fold(old_ref, new_fact)`
2. **外挂粒度审计**（thin and narrow 原则）：当前思考外挂是三合一（采样/早停/预算守卫）——
   按 fine-grained 原则评估是否拆成三个独立专家模块（受益：路由更锐利、缓存前缀更稳定；
   代价：注册表与编排复杂度上升）。产出一页评估报告
3. **cachecortex 集成**：experts.py 进包导出（`from cachecortex import ExpertRegistry`）
   + 应用指南

### P2（两周，小规模 API 成本）

4. [通过] **ExpertPool 实战接线（2026-10-04 完成）**：`orchestrator.py`（ExpertAdapter +
   Orchestrator）——五件套全部注册为专家并端到端跑通复合任务（memory/sampler/verifier/
   cache/knowledge 五子任务全路由正确；无覆盖能力清晰失败）；`orchestration_demo.py` 为
   可运行 demo；14 项测试全过
5. [通过] **观测回灌路由（2026-10-04 完成）**：rebalance() 实现 auxiliary-loss-free 的运行时版
   ——利用率 >50% 降 bias（实测 1.0→0.95）、饿死升 bias、bias 改变路由偏好（实测 rare 以
   bias 2.0 胜出 4 倍贵专家）。闭环：执行 → 观测 → bias → 路由
6. **fusion 并入 DecisionCore**：E2 已证 fusion 优于 selection —— 把 fusion 判定器
   正式实现进光谱（当前是实验脚本），作为 open 决策的默认档

### P3（择机）

7. **看门狗接入**：治理层的 DSH 插件形态落地（Governance 的 can_load 预检正好对应
   看门狗的核心诉求：安装前后冲突检测）
8. **EMO 式 document 级路由**：批处理场景（同一文档/任务的多次调用共享专家子集）
9. **社区迭代**：PPBDec-Core 上线后的反馈（fusion 默认档位的实际使用数据）

## 三、优化原则（不变）

- **先测量再优化**：任何新组件先在 E2 式对照里验证（fusion 的 3.3 倍优势就是先测后定的）
- **零依赖核心**：decisioncore 核心保持零第三方依赖（治理/观测模块同样）
- **证据链优先**：新增的每个决策点都要落 DecisionRecord
- **测试即文档**：新模块先进测试套件（当前 49 项），失败的断言优先怀疑测试口径
