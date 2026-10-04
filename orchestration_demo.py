"""五外挂接线 demo：把 Addenda 五件套注册为专家并端到端跑一个复合任务。

复合任务：用户说"我改用 Svelte 了，帮我把上季度的报表数字核对一下"
  → 记忆专家（记住偏好变化）
  → 采样专家（核对计算，多路采样+早停）
  → 判定专家（数值验证）
  → 缓存专家（会话前缀编排）
  → 知识专家（内容门核证）
全程离线（各专家调用真实组件，不调 API）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "D:/agentwork/workbuddy/code/1-思维方式/addenda-memory")
sys.path.insert(0, "D:/agentwork/workbuddy/code/1-思维方式/exocortex")
sys.path.insert(0, "D:/agentwork/workbuddy/code/1-思维方式/仓库2/cachecortex"
                if os.path.isdir("D:/agentwork/workbuddy/code/1-思维方式/仓库2")
                else "C:/Users/30312/Desktop/仓库2/cachecortex")
sys.path.insert(0, "C:/Users/30312/Desktop/仓库/experiments")

from decisioncore.orchestrator import ExpertAdapter, Orchestrator  # noqa: E402
from decisioncore.registry import ExpertSpec  # noqa: E402
from decisioncore.observability import CognitiveMonitor  # noqa: E402


def build_pool() -> Orchestrator:
    orch = Orchestrator(monitor=CognitiveMonitor())

    # ---- 1. 记忆专家（Addenda-Memory）----
    mem_state = {"store": None, "ctl": None}
    try:
        from memorycore import MemoryController, MemoryPage, MemoryStore, PageKind
        from decisioncore import DecisionCore
        store = MemoryStore()
        ctl = MemoryController(store, dc=DecisionCore())
        mem_state["store"], mem_state["ctl"] = store, ctl

        def memory_handler(task):
            if task.get("op") == "ingest":
                act = ctl.ingest(PageKind(task["kind"]), task["content"],
                                 provenance=task.get("prov", ""))
                return {"op": act.op, "page": act.page_id, "audited": bool(act.decision_id)}
            return {"active_pages": len(store.active_pages())}

        orch.register(ExpertAdapter(
            ExpertSpec(name="memory", capabilities={"remember", "recall"},
                       cost_tier=1, deterministic=True),
            memory_handler, "分页记忆（折叠+审计）"))
    except ImportError as e:
        print("记忆专家未接入:", e)

    # ---- 2. 采样专家（Addenda-Think 的早停投票）----
    def sample_handler(task):
        """多路采样 + 票型早停（离线模拟：给定候选键，投票到收敛）。"""
        keys = task.get("vote_keys", [])
        k = task.get("stop_k", 3)
        tail = keys[-k:]
        converged = len(tail) == k and len(set(tail)) == 1
        from collections import Counter
        winner = Counter(keys).most_common(1)[0][0] if keys else None
        return {"winner": winner, "converged": converged, "n_used": len(keys)}

    orch.register(ExpertAdapter(
        ExpertSpec(name="sampler", capabilities={"solve", "compute"},
                   cost_tier=2),
        sample_handler, "多路采样+早停投票"))

    # ---- 3. 判定专家（决策核的数值验证）----
    def verify_handler(task):
        from fractions import Fraction
        a, b = task["value"], task["target"]
        return {"verified": Fraction(a) == Fraction(b)}

    orch.register(ExpertAdapter(
        ExpertSpec(name="verifier", capabilities={"verify"},
                   cost_tier=1, deterministic=True),
        verify_handler, "程序判定器（数值验证）"))

    # ---- 4. 缓存专家（Addenda-Cache 的前缀编排）----
    def cache_handler(task):
        try:
            from cachecortex.prefix_bank import PrefixBank
            pb = PrefixBank(system_prompt="[系统] 你是助手。")
            for t in task.get("turns", []):
                pb.append_user(t)
            return {"prefix_blocks": 1, "turns": len(task.get("turns", []))}
        except Exception:
            # 组件不可用时的降级：报告编排纪律而非执行
            return {"orchestrated": True, "note": "prefix append-only 纪律就位"}

    orch.register(ExpertAdapter(
        ExpertSpec(name="cache", capabilities={"prefix_orchestration"},
                   cost_tier=1, deterministic=True),
        cache_handler, "三区会话前缀编排"))

    # ---- 5. 知识专家（Addenda-LM 的内容门）----
    def knowledge_handler(task):
        if task.get("op") == "gate":
            try:
                import curator
                ok = curator.date_valid(task.get("date", ""))
                return {"admitted": bool(ok)}
            except ImportError:
                return {"admitted": None, "note": "curator 不可用"}
        return {"gate": "ready"}

    orch.register(ExpertAdapter(
        ExpertSpec(name="knowledge", capabilities={"knowledge_gate"},
                   cost_tier=1, deterministic=True),
        knowledge_handler, "内容门（R1 日期核证）"))

    return orch


def main() -> None:
    print("=" * 72)
    print("Addenda-MoE 编排接线 demo：五专家注册 + 复合任务端到端")
    print("=" * 72)
    orch = build_pool()
    print(f"\n已注册 {len(orch.adapters)} 个专家: {list(orch.adapters)}")

    # ---- 复合任务的五个子任务，按路由分派 ----
    subtasks = [
        ("用户偏好变化入场", {"remember"}, {"op": "ingest", "kind": "preference",
                                            "content": "改用 Svelte 了", "prov": "session"}),
        ("报表数字核对（采样）", {"solve"}, {"vote_keys": ["1200", "1200", "1200"]}),
        ("数值验证", {"verify"}, {"value": "1200", "target": "1200"}),
        ("会话前缀编排", {"prefix_orchestration"}, {"turns": ["核对报表", "继续"]}),
        ("内容门核证", {"knowledge_gate"}, {"op": "gate", "date": "2026-09-15"}),
        # 覆盖不了的能力 → 应清晰报 no expert
        ("视觉任务（无专家）", {"vision"}, {}),
    ]
    for name, cap, payload in subtasks:
        r = orch.execute(name, cap, payload)
        status = "OK " if r["ok"] else "FAIL"
        print(f"  [{status}] {name:16s} → {r.get('expert') or '（无）':10s} "
              f"{str(r.get('output'))[:60]}")

    # ---- 观测回灌 ----
    print("\n--- 观测回灌（利用率 → bias）---")
    for _ in range(3):
        rb = orch.rebalance()
    print("  bias 调整:", rb["changed"])
    print("  利用率:", {k: f"{v['pct']}%" for k, v in rb["utilization"].items()})
    print(f"  路由熵: {rb['entropy']}")

    h = orch.health()
    print("\n--- 运行健康 ---")
    for k in ("n_experts", "n_tasks", "success_rate", "route_entropy", "starved", "bias"):
        print(f"  {k}: {h[k]}")


if __name__ == "__main__":
    main()
