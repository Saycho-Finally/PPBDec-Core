# 变更记录 (Changelog)

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.3.0] - 2026-10-05

范围收敛：本仓库只承载决策层，编排层交由独立层级承载。

### Added

- `tests/test_migration_equivalence.py`：迁移等价性 15 项可复现用例
  （早停 4 / 缓存层 3 / 内容门日期 4 / selection 2 / 覆盖守门 2）

### Changed

- 迁移适配器的源实现路径改为按当前仓库名解析，并支持环境变量覆盖
  （`PPB_SAMPLE_ROOT` / `PPB_CACHE_ROOT` / `PPB_KNOWLEDGE_EXPERIMENTS`）
- 迁移适配器补上本仓库根的路径注入，使其可独立导入运行
- README / SPEC 的测试口径改为可复现的实际数字

### Removed

- 编排层模块（编排运行时 / 治理预检 / 认知可观测性）移出本仓库，由对应层级独立承载
- 编排层专用的测试与文档（编排运行时测试、治理与可观测性测试、路线文档）
- 公开接口相应收敛：不再导出编排、治理与可观测性相关的类型

## [0.2.0] - 2026-10-04

- v0.2 route 决策与运行时灰度开关
- （该版本的治理与可观测性部分已于 0.3.0 移出）

## [0.1.0] - 2026-10-03

- DecisionCore 核心（类型学 / 光谱 / 审计）+ 迁移等价性 + 开放决策实证
