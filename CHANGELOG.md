# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-10-05

范围收敛：本仓库只承载决策层，编排层交由独立层级承载。

### Added

- `tests/test_migration_equivalence.py`：迁移等价性 15 项可复现用例
  （早停 4 / 缓存层 3 / 内容门日期 4 / selection 2 / 覆盖守门 2）
- `migrations/` 补包声明（`__init__.py`），使 `from migrations.*` 的导入关系显式化
- 恢复 E2 的证据链审计产出（`results/e2_decisions.jsonl`、
  `results/e2_llm_fusion_audit.jsonl`）——这两个文件由 `e2_run.py` 与
  `e2_llm_fusion.py` 写出，此前的仓库组装未包含它们

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
