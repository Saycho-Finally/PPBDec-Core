"""E2 任务族 A 正式运行：采样 → 五档判定器 → gold 评测 → DecisionCore 审计。

流程：
  1. 采样：5 段 bug 代码 × 6 评审（deepseek-flash, low, temp=0.7）→ 30 候选
  2. 判定器五档：
     - heuristic：选最长候选
     - union_overlap：与全体候选 bug 并集重叠最多的候选（投票代理）
     - probe：flash choose-from-N
     - llm_judge：pro choose-from-N（上限参照）
     - fusion：pro 合并全部候选去重（光谱新档位——核心对照）
  3. 评测（flash 判定覆盖与误报）：每判定器输出的 bug 集合 vs gold
     → recall / false-positive / F1；selection 损失 = best-single F1 − 判定器 F1
  4. 全程 DecisionCore 审计（open 决策 + coverage 证据）
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get(  # 含 exocortex 包的目录
    "PPB_SAMPLE_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "PPBExt-Sample"))))
sys.path.insert(0, os.path.dirname(__file__))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from decisioncore import (DecisionCore, DecisionPoint,  # noqa: E402
                          DecisionType, CoverageEvidence)
from e2_task_family_a import BUGGY_CODES  # noqa: E402

PRICE = {"hit": 0.003e-6, "miss": 0.15e-6, "out": 0.6e-6}  # flash off-peak

REVIEW_PROMPT = ("请仔细审查以下 Python 代码，列出其中所有的 bug。"
                 "每个 bug 单独一行，格式：- [类型] 位置：问题描述\n\n```python\n{}\n```")

JUDGE_PROMPT = ("以下是多位评审者对同一段代码的 bug 报告。请选出最完整、最准确的一份"
                "（考虑：覆盖 bug 数、描述准确性、无误报）。只回答编号（1-{}）。\n\n{}")

FUSION_PROMPT = ("以下是多位评审者对同一段代码的 bug 报告。请把所有报告中真实有效的 bug "
                 "合并成一份去重后的清单（丢弃错误/重复/幻觉条目），格式与输入一致："
                 "- [类型] 位置：描述\n\n{}\n\n请输出合并后的完整 bug 清单。")

EVAL_PROMPT = ("Gold bug 清单：\n{gold}\n\n待判定报告的 bug 清单：\n{report}\n\n"
               "请逐条判断报告中的每个 bug 是否在 Gold 清单中有对应条目（描述同一问题），"
               "并统计 Gold 清单中有哪些条目未被报告覆盖。输出 JSON："
               '{{"matched_gold": [编号], "false_positives": 数量}}')


def flash_call(adapter, prompt, max_tokens=3000, thinking=True, effort="low"):
    req = GenRequest(messages=[{"role": "user", "content": prompt}],
                     max_tokens=max_tokens, thinking=thinking, effort=effort,
                     temperature=0.3)
    g = adapter.generate(req)
    return g


def sample_reviews(adapter, code, n=6):
    outs = []
    for i in range(n):
        g = flash_call(adapter, REVIEW_PROMPT.format(code), max_tokens=3000)
        outs.append({"idx": i + 1, "text": g.text,
                     "out_tok": g.completion_tokens})
        time.sleep(0.2)
    return outs


def eval_against_gold(adapter, gold_bugs, report_text):
    """flash 判定：报告覆盖了哪些 gold bug + 报告中的误报数。"""
    gold_lines = "\n".join(f"{i+1}. {b['desc']}" for i, b in enumerate(gold_bugs))
    prompt = EVAL_PROMPT.format(gold=gold_lines, report=report_text[:3000])
    g = flash_call(adapter, prompt, max_tokens=400, thinking=False)
    try:
        txt = g.text
        j0 = txt.find("{")
        j1 = txt.rfind("}") + 1
        parsed = json.loads(txt[j0:j1])
        matched = len(parsed.get("matched_gold", []))
        fp = parsed.get("false_positives", 0)
    except Exception:
        matched, fp = 0, 0
    recall = matched / len(gold_bugs) if gold_bugs else 0
    n_reported = report_text.count("- [")
    fp_rate = fp / n_reported if n_reported else 0
    prec = (n_reported - fp) / n_reported if n_reported else 0
    f1 = (2 * prec * recall / (prec + recall)) if (prec + recall) else 0
    return {"matched": matched, "recall": round(recall, 3),
            "false_positives": fp, "precision": round(prec, 3),
            "f1": round(f1, 3)}


def main() -> None:
    ap = argparse.ArgumentParser() if (argparse := __import__("argparse")) else None
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEEPSEEK_API_KEY")
    adapter = adapter_from_config({"type": "openai",
                                   "base_url": "https://api.deepseek.com",
                                   "api_key": key, "model": "deepseek-flash"})
    pro = adapter_from_config({"type": "openai",
                               "base_url": "https://api.deepseek.com",
                               "api_key": key, "model": "deepseek-v4-pro"})
    dc = DecisionCore(audit_path="results/e2_decisions.jsonl")
    os.makedirs("results", exist_ok=True)

    all_results = []
    for task in BUGGY_CODES:
        tid = task["id"]
        code = task["code"]
        gold = task["gold_bugs"]
        print(f"=== {tid}: 采样 6 评审 ===", flush=True)
        reviews = sample_reviews(adapter, code, n=6)
        pool_text = "\n\n".join(f"[评审 {r['idx']}]\n{r['text']}" for r in reviews)
        usd_sample = sum(r["out_tok"] for r in reviews) * PRICE["out"]

        # ---- 判定器五档（全部走 DecisionCore 审计）----
        point = DecisionPoint(
            name=f"{tid}.bug_report_selection", type=DecisionType.OPEN,
            candidates=[r["text"] for r in reviews],
            coverage=CoverageEvidence(
                n_candidates=len(reviews), source="sample(flash/low, n=6)",
                source_diversity="temperature=0.7"))

        # 1) heuristic：最长候选
        best_len = max(reviews, key=lambda r: len(r["text"]))
        rec_h = dc.decide_verifiable(
            DecisionPoint(name=f"{tid}.heuristic_pick",
                          type=DecisionType.VERIFIABLE,
                          predicate=lambda c: c == best_len["text"]),
            subject=best_len["text"])
        heuristic_out = best_len["text"]

        # 2) union_overlap：与全体并集重叠最多的候选（简化投票代理）
        def overlap(r):
            return sum(1 for o in reviews if r is o) * 0 + \
                sum(len(set(r["text"].split()) & set(o["text"].split()))
                    for o in reviews if o is not r)
        best_ov = max(reviews, key=overlap)
        rec_v = dc.decide_verifiable(
            DecisionPoint(name=f"{tid}.union_overlap_pick",
                          type=DecisionType.VERIFIABLE,
                          predicate=lambda c: c == best_ov["text"]),
            subject=best_ov["text"])
        union_out = best_ov["text"]

        # 3) probe：flash choose-from-N
        g_probe = flash_call(adapter, JUDGE_PROMPT.format(len(reviews), pool_text),
                             max_tokens=200, thinking=False)
        try:
            pick_i = int("".join(ch for ch in g_probe.text if ch.isdigit())[:1] or 1)
        except ValueError:
            pick_i = 1
        pick_i = min(max(pick_i, 1), len(reviews))
        probe_out = reviews[pick_i - 1]["text"]

        # 4) llm_judge：pro choose-from-N
        g_judge = pro.generate(GenRequest(
            messages=[{"role": "user",
                       "content": JUDGE_PROMPT.format(len(reviews), pool_text)}],
            max_tokens=300, thinking=True, temperature=0.3))
        try:
            pick_j = int("".join(ch for ch in g_judge.text if ch.isdigit())[:1] or 1)
        except ValueError:
            pick_j = 1
        pick_j = min(max(pick_j, 1), len(reviews))
        judge_out = reviews[pick_j - 1]["text"]

        # 5) fusion：pro 合并去重（光谱新档位）
        g_fusion = pro.generate(GenRequest(
            messages=[{"role": "user",
                       "content": FUSION_PROMPT.format(pool_text)}],
            max_tokens=1500, thinking=True, temperature=0.3))
        fusion_out = g_fusion.text

        # ---- 评测（flash 判定 vs gold）----
        print(f"--- {tid} 评测（gold {len(gold)} bugs）---", flush=True)
        evaluators = {
            "heuristic": heuristic_out, "union_overlap": union_out,
            "probe(flash)": probe_out, "llm_judge(pro)": judge_out,
            "fusion(pro)": fusion_out,
        }
        task_scores = {}
        for name, out_text in evaluators.items():
            sc = eval_against_gold(adapter, gold, out_text)
            sc["out_tokens"] = len(out_text) // 3   # 粗略 token 估计
            task_scores[name] = sc
            print(f"  {name:16s} recall={sc['recall']} prec={sc['precision']} "
                  f"f1={sc['f1']}", flush=True)
        # 上游 coverage：单候选的最大 recall（selection 的天花板）
        singles = [eval_against_gold(adapter, gold, r["text"])["recall"]
                   for r in reviews]
        task_scores["single_best_recall"] = max(singles)
        task_scores["single_avg_recall"] = round(sum(singles) / len(singles), 3)
        task_scores["sample_usd"] = round(usd_sample, 4)
        all_results.append({"task": tid, "scores": task_scores,
                            "reviews": reviews})

    with open("results/e2_task_a_results.json", "w", encoding="utf-8") as f:
        json.dump({"meta": {"ts": time.time(), "n_tasks": len(BUGGY_CODES),
                            "n_reviews_per_task": 6},
                   "tasks": all_results}, f, ensure_ascii=False, indent=2)
    print("SAVED results/e2_task_a_results.json")


if __name__ == "__main__":
    main()
