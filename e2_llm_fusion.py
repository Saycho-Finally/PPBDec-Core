"""E2 LLM fusion 正式对照：Fusion-of-N 式合并 vs deterministic fusion vs best-single。

复用第一轮 30 候选。每任务：pro fusion 合并 → flash 评测 vs gold → 三层对照。
全程 DecisionCore 审计（open 决策 + coverage 证据）。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get("EXOCORTEX_ROOT", "../exocortex"))
sys.path.insert(0, os.path.dirname(__file__))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from decisioncore import (DecisionCore, DecisionPoint,  # noqa: E402
                          DecisionType, CoverageEvidence)
from e2_task_family_a import BUGGY_CODES  # noqa: E402

FUSION_PROMPT = ("以下是多位评审者对同一段代码的 bug 报告。请合并所有真实有效的 bug 为一份"
                 "去重清单（丢弃错误/重复/幻觉条目），每条一行、格式严格为："
                 "- [类型] 位置：描述\n\n{pool}\n\n只输出合并后的清单。")


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEEPSEEK_API_KEY")
    prior = json.load(open("results/e2_task_a_results.json", encoding="utf-8"))
    det = json.load(open("results/e2_fusion_offline.json", encoding="utf-8"))
    flash = adapter_from_config({"type": "openai",
                                 "base_url": "https://api.deepseek.com",
                                 "api_key": key, "model": "deepseek-flash"})
    pro = adapter_from_config({"type": "openai", "base_url": "https://api.deepseek.com",
                               "api_key": key, "model": "deepseek-v4-pro"})
    dc = DecisionCore(audit_path="results/e2_llm_fusion_audit.jsonl")

    # --- key 活性预检（pro + flash 各一发）---
    for name, ad in [("pro", pro), ("flash", flash)]:
        g = ad.generate(GenRequest(messages=[{"role": "user", "content": "OK"}],
                                   max_tokens=4, thinking=False))
        print(f"{name} alive: {g.text!r}")

    out_tasks = []
    for ti, task in enumerate(BUGGY_CODES):
        tid = task["id"]
        gold = task["gold_bugs"]
        reviews = prior["tasks"][ti]["reviews"]
        if not any(r["text"].strip() for r in reviews):
            print(f"[{tid}] 候选全空（第一轮采样缺陷），跳过")
            continue
        pool_text = "\n\n".join(f"[评审 {r['idx']}]\n{r['text']}" for r in reviews)

        # LLM fusion（Fusion-of-N 式，pro）
        point = DecisionPoint(
            name=f"{tid}.llm_fusion", type=DecisionType.OPEN,
            candidates=[r["text"] for r in reviews],
            coverage=CoverageEvidence(n_candidates=len(reviews),
                                      source="sample(flash/low, n=6)",
                                      source_diversity="temperature=0.7"))
        dc.decide_enumeration(DecisionPoint(  # 占位审计：fusion 触发记录
            name=f"{tid}.fusion_trigger", type=DecisionType.ENUMERATION,
            candidates=["llm_fusion", "det_fusion", "best_single"],
            completeness_note="spectra comparison protocol"))
        g_f = pro.generate(GenRequest(
            messages=[{"role": "user", "content": FUSION_PROMPT.format(pool=pool_text)}],
            max_tokens=2500, thinking=False, temperature=0.3))
        fusion_out = g_f.text

        # flash 评测（与第一轮同口径）
        gold_lines = "\n".join(f"{i+1}. {b['desc']}" for i, b in enumerate(gold))
        eval_prompt = (f"Gold bug 清单：\n{gold_lines}\n\n待判定报告：\n{fusion_out[:3000]}\n\n"
                       "请判断报告覆盖了 Gold 清单中的哪几条（描述同一问题即可），以及报告中有几条"
                       '是 Gold 里没有的（误报）。只输出 JSON：{"matched_gold": [编号], '
                       '"false_positives": 数量}')
        g_e = flash.generate(GenRequest(messages=[{"role": "user", "content": eval_prompt}],
                                        max_tokens=300, thinking=False))
        txt = g_e.text
        matched = fp = 0
        try:
            j0, j1 = txt.find("{"), txt.rfind("}") + 1
            parsed = json.loads(txt[j0:j1])
            matched = len(parsed.get("matched_gold", []))
            fp = int(parsed.get("false_positives", 0))
        except Exception:
            m = re.search(r'"matched_gold"\s*:\s*\[([^\]]*)\]', txt)
            if m:
                matched = len([x for x in m.group(1).split(",") if x.strip()])
            m2 = re.search(r'"false_positives"\s*:\s*(\d+)', txt)
            fp = int(m2.group(1)) if m2 else 0
        recall = matched / len(gold)
        lines = [l for l in fusion_out.split("\n") if l.strip().startswith("-")]
        n_rep = max(len(lines), 1)
        prec = (n_rep - fp) / n_rep
        f1 = (2 * prec * recall / (prec + recall)) if (prec + recall) else 0

        det_f1 = det["per_task"][ti]["fused_f1_type"] if ti < len(det["per_task"]) else None
        best_single = det["per_task"][ti]["best_single_recall"] if ti < len(det["per_task"]) else None
        out_tasks.append({
            "task": tid, "llm_fusion_recall": round(recall, 3),
            "llm_fusion_precision": round(prec, 3), "llm_fusion_f1": round(f1, 3),
            "det_fusion_f1": det_f1, "best_single_recall": best_single,
            "n_lines_fused": len(lines), "fp": fp,
            "fusion_head": fusion_out[:200],
        })
        print(f"[{tid}] LLM fusion: recall={recall:.2f} prec={prec:.2f} f1={f1:.3f} "
              f"(det_fusion_f1={det_f1}, best_single={best_single})", flush=True)

    # 汇总（有效任务）
    valid = [t for t in out_tasks if t["best_single_recall"] is not None]
    summary = {}
    for k in ("llm_fusion_f1", "det_fusion_f1", "best_single_recall"):
        vals = [t[k] for t in valid if t[k] is not None]
        summary[k] = round(sum(vals) / len(vals), 3) if vals else None
    print("\n=== 三层对照汇总（均值）===")
    for k, v in summary.items():
        print(f"  {k:22s} {v}")

    with open("results/e2_llm_fusion_results.json", "w", encoding="utf-8") as f:
        json.dump({"tasks": out_tasks, "summary": summary}, f,
                  ensure_ascii=False, indent=2)
    print("SAVED results/e2_llm_fusion_results.json")


if __name__ == "__main__":
    main()
