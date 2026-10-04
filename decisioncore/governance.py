"""治理层：外挂栈的冲突检测 / 权限边界 / 版本声明（对齐看门狗项目定位）。

设计原则（MoE 生态治理的启示）：
  - 权限边界：外挂声明它要动什么（prefix / 权重外模块 / 会话历史 / 外部 IO）
  - 冲突检测：两个外挂声明了互斥操作时拒绝加载（如"都要改写同一段历史"）
  - 版本与依赖：外挂声明最小宿主版本与依赖（加载前校验）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AddonManifest:
    """外挂清单：声明能力、触及范围与依赖。"""
    name: str
    version: str
    touches: set[str]          # 触及面：prefix / history / tools / external_io / output
    requires_host: str = ">=0.1"
    depends_on: set[str] = field(default_factory=set)
    exclusive: set[str] = field(default_factory=set)   # 声明互斥的资源（如 "history.front"）


@dataclass
class Conflict:
    kind: str          # exclusive_clash / missing_dependency / version_mismatch
    a: str
    b: str
    detail: str


class Governance:
    """加载期治理：在 Addon 装载前做冲突/依赖/版本校验。"""

    def __init__(self):
        self.manifests: dict[str, AddonManifest] = {}
        self.conflicts: list[Conflict] = []

    def register(self, m: AddonManifest) -> list[Conflict]:
        """注册并返回本次引入的冲突（空列表 = 通过）。"""
        found: list[Conflict] = []
        # 1) 互斥资源冲突
        for other in self.manifests.values():
            clash = m.exclusive & other.exclusive
            if clash:
                found.append(Conflict(
                    "exclusive_clash", m.name, other.name,
                    f"互斥资源: {sorted(clash)}"))
        # 2) 依赖缺失
        for dep in m.depends_on:
            if dep not in self.manifests:
                found.append(Conflict("missing_dependency", m.name, dep,
                                      f"缺少依赖 {dep}"))
        # 3) 宿主版本（占位：字符串比较留给宿主实现）
        if m.requires_host and m.requires_host.startswith(">="):
            pass  # 宿主版本解析由调用方注入
        self.manifests[m.name] = m
        self.conflicts.extend(found)
        return found

    def check_all(self) -> dict:
        return {
            "n_addons": len(self.manifests),
            "n_conflicts": len(self.conflicts),
            "conflicts": [c.__dict__ for c in self.conflicts],
            "policy": "拒绝加载互斥外挂；缺依赖告警；版本不匹配告警",
        }

    def can_load(self, m: AddonManifest) -> tuple[bool, list[Conflict]]:
        """预检：不注册，仅返回是否可加载及冲突清单（供 DSH 启动/安装前调用）。"""
        found: list[Conflict] = []
        for other in self.manifests.values():
            clash = m.exclusive & other.exclusive
            if clash:
                found.append(Conflict("exclusive_clash", m.name, other.name,
                                      f"互斥资源: {sorted(clash)}"))
        for dep in m.depends_on:
            if dep not in self.manifests:
                found.append(Conflict("missing_dependency", m.name, dep,
                                      f"缺少依赖 {dep}"))
        return (len(found) == 0), found
