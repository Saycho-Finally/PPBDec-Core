"""迁移适配器包：把既有判定逻辑原样注入为 DecisionCore 的决策点。

模块职责：
  - `adapters`：三处既有判定逻辑的适配器（谓词 + 原始实现对照）
  - `runtime_switch`：运行时灰度开关（走 DecisionCore 的等价实现）
  - `runtime_cache_lm`：缓存层与内容门判定器的运行时接入

等价性验证：`tests/test_migration_equivalence.py`（同输入同输出对照）。
"""
