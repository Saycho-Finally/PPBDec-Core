# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [Unreleased]

## [0.5.0] - 2026-10-06

### Added

- **`outcome_check` 事后回填**：`DecisionCore.record_outcome(decision_id, ok, detail)`
  以追加方式落 outcome 事件，原决策记录一字不改（不可变纪律）；
  不在账内的 decision_id 拒绝补写。补齐 SPEC §四的承诺项
- SPEC 新增**缺口核对表**（逐条核对实现与承诺），并修正 §四的 JSON 示例
  （此前示例的嵌套 `point` 对象、`candidates_source`、内嵌 `outcome_check`
  与真实字段形状不符）；光谱档位标注实现状态
- `tests/test_outcome_backfill.py`：11 项测试，测试总数 56 → 67

### Fixed

- SPEC 缺口核对确认两处未兑现项并如实记录：`small_probe` / `micro_decision_model`
  两档判定器未实现（无调用方，不预先设计）；采样档位选择（enumeration）未迁移

## [0.4.0] - 2026-10-05

### Added

- **coverage 降级路径**：open 决策的覆盖证据**存在但不足**（候选数低于下限，
  或缺少候选来源说明）时不再一律拒绝，而是降级受理——结果保留，但置信度折半、
  `shift_risk` 强制为 high、`DecisionRecord` 标注 `degraded`
- `CoverageEvidence.sufficiency()` 与常量 `MIN_CANDIDATES`（默认 2）
- `tests/test_coverage_degrade.py`：19 项测试

### Changed

- `DecisionRecord` 新增 `degraded` 字段（审计链可见降级）
- `decide_open` / `solve_open_majority` 新增 `min_candidates` 参数（默认 2）
- **拒绝路径不变**：coverage 缺失或候选为空仍抛 ValueError

## [0.3.0] - 2026-10-05

范围收敛：本仓库只承载决策层，编排层交由独立层级承载。

### Added

- `tests/test_migration_equivalence.py`：迁移等价性 15 项可复现用例
  （早停 4 / 缓存层 3 / 内容门日期 4 / selection 2 / 覆盖守门 2）
- `migrations/` 补包声明（`__init__.py`），使 `from migrations.*` 的导入关系显式化
- 恢复 E2 的证据链审计产出（`results/e2_decisions.jsonl`、
  `results/e2_llm_fusion_audit.jsonl`）——这两个文件由 `e2_run.py` 与
  `e2_llm_fusion.py` 写出，此前的仓库组装未包含它们

### Fixed

- 迁移适配器与运行时接入的环境变量默认路径失效（历史品牌前缀 + 已改名的旧目录名），
  统一为 `PPB_SAMPLE_ROOT` / `PPB_CACHE_ROOT` / `PPB_KNOWLEDGE_EXPERIMENTS`
- 路径修好后，运行时测试中此前跳过的内容门用例恢复执行，测试总数由 35 升至 **37**

### Changed

- 迁移适配器的源实现路径改为按当前仓库名解析，并支持环境变量覆盖
  （`PPB_SAMPLE_ROOT` / `PPB_CACHE_ROOT` / `PPB_KNOWLEDGE_EXPERIMENTS`）
- 迁移适配器补上本仓库根的路径注入，使其可独立导入运行
- README / SPEC 的测试口径改为可复现的实际数字
- README 补登记 `validate_task_family.py`（此前未列入仓库结构）
- README 与实验报告补充第一轮 `results/e2_task_a_results.json` 的退化口径说明
  （其 `scores` 段五个判定器指标完全相同，不可当作有效对照引用）

### Removed

- `e2_rerun.py`：中间产物，已被 `e2_llm_fusion.py` 取代（报告引用的三档对照数字出自后者）。
  该脚本另有三处缺陷：fusion 调用漏传适配器参数、judge 调用未关思考且预算仅 200、
  审计对象创建后未使用致其声明的产出无法生成。全仓库零引用，其两个声明产出
  （`e2_final_comparison.json`、`e2_decisions_v2.jsonl`）不存在且无人引用

### Removed

- 编排层模块（编排运行时 / 治理预检 / 认知可观测性）移出本仓库，由对应层级独立承载
- 编排层专用的测试与文档（编排运行时测试、治理与可观测性测试、路线文档）
- 公开接口相应收敛：不再导出编排、治理与可观测性相关的类型

## [0.2.0] - 2026-10-04

- v0.2 route 决策与运行时灰度开关
- （该版本的治理与可观测性部分已于 0.3.0 移出）

## [0.1.0] - 2026-10-03

- DecisionCore 核心（类型学 / 光谱 / 审计）+ 迁移等价性 + 开放决策实证
