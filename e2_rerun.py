"""E2 重评：复用已有采样，重跑 judge/fusion 两档（修复解析）+ 全判定器重评。

修复项：
  1. judge：输出约束为 JSON {"pick": N}，解析容错（找 "pick" 键，fallback 最后出现的数字）
  2. fusion：prompt 强制输出格式 "- [类型] 位置：描述"；评测 n_reported 改为非空行数
  3. 评测器：JSON 解析容错（正则提取 matched 数作为 fallback）
"""

import json
import os
import re
import time
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get("EXOCORTEX_ROOT", "../exocortex"))
sys.path.insert(0, os.path.dirname(__file__))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from decisioncore import (DecisionCore, DecisionPoint,  # noqa: E402
                          DecisionType, CoverageEvidence)
from e2_task_family_a import BUGGY_CODES  # noqa: E402

PRICE = {"hit": 0.003e-6, "miss": 0.15e-6, "out": 0.6e-6}


def pro_call(adapter, prompt, max_tokens=1500, thinking=True):
    req = GenRequest(messages=[{"role": "user", "content": prompt}],
                     max_tokens=max_tokens, thinking=thinking, temperature=0.3)
    return adapter.generate(req)


def extract_pick(text: str, n: int) -> int:
    """稳健编号提取：优先 JSON "pick" 键，fallback 找"评审 N"/独立数字。"""
    m = re.search(r'"pick"\s*:\s*(\d+)', text)
    if m:
        return min(max(int(m.group(1)), 1), n)
    m = re.search(r'评审\s*(\d+)', text)
    if m:
        return min(max(int(m.group(1)), 1), n)
    nums = re.findall(r'\b(\d+)\b', text)
    if nums:
        return min(max(int(nums[-1]), 1), n)
    return 1


def eval_against_gold(adapter, gold_bugs, report_text):
    gold_lines = "\n".join(f"{i+1}. {b['desc']}" for i, b in enumerate(gold_bugs))
    prompt = (f"Gold bug 清单：\n{gold_lines}\n\n待判定报告：\n{report_text[:3000]}\n\n"
              "请判断报告覆盖了 Gold 清单中的哪几条（描述同一问题即可，措辞不必相同），"
              "以及报告中有几条是 Gold 里没有的（误报）。只输出 JSON："
              '{"matched_gold": [编号如1,2], "false_positives": 数量}')
    g = pro_call(adapter, prompt, max_tokens=300, thinking=False)
    txt = g.text
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
    recall = matched / len(gold_bugs) if gold_bugs else 0
    lines = [l for l in report_text.split("\n") if l.strip().startswith("-")]
    n_reported = max(len(lines), 1)
    prec = (n_reported - fp) / n_reported if n_reported else 0
    f1 = (2 * prec * recall / (prec + recall)) if (prec + recall) else 0
    return {"matched": matched, "recall": round(recall, 3), "false_positives": fp,
            "precision": round(prec, 3), "f1": round(f1, 3)}


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEEPSEEK_API_KEY")
    prior = json.load(open("results/e2_task_a_results.json", encoding="utf-8"))
    flash = adapter_from_config({"type": "openai",
                                 "base_url": "https://api.deepseek.com",
                                 "api_key": key, "model": "deepseek-flash"})
    pro = adapter_from_config({"type": "openai", "base_url": "https://api.deepseek.com",
                               "api_key": key, "model": "deepseek-v4-pro"})
    dc = DecisionCore(audit_path="results/e2_decisions_v2.jsonl")

    final = {"meta": {"ts": time.time(), "note": "judge/fusion 重跑（解析修复），其余复用第一轮"}}
    for ti, task in enumerate(BUGGY_CODES):
        tid = task["id"]
        gold = task["gold_bugs"]
        tdata = prior["tasks"][ti]
        reviews = tdata["reviews"]
        pool_text = "\n\n".join(f"[评审 {r['idx']}]\n{r['text']}" for r in reviews)
        scores = {k: v for k, v in tdata["scores"].items()
                  if k in ("heuristic", "union_overlap")}

        # judge（JSON 约束重跑）
        judge_prompt = (f"以下是多位评审者对同一段代码的 bug 报告。请选出最完整、最准确的一份。"
                        f"只输出 JSON：{{\"pick\": 编号}}\n\n{pool_text}")
        g_j = pro_call(pro, judge_prompt, 200)
        pick_j = extract_pick(g_j.text, len(reviews))
        judge_out = reviews[pick_j - 1]["text"]
        scores["llm_judge(pro)"] = eval_against_gold(flash, gold, judge_out)

        # fusion（格式约束重跑）
        fusion_prompt = (f"以下是多位评审者对同一段代码的 bug 报告。请合并所有真实有效的 bug "
                         f"为一份去重清单，每条一行、格式严格为：- [类型] 位置：描述\n\n{pool_text}")
        g_f = pro_call(fusion_prompt, 1500)
        fusion_out = g_f.text
        scores["fusion(pro)"] = eval_against_gold(flash, gold, fusion_out)
        scores["fusion_raw_head"] = fusion_out[:150]

        print(f"=== {tid}（重评后）===", flush=True)
        for k in ("heuristic", "union_overlap", "llm_judge(pro)", "fusion(pro)"):
            s = scores[k]
            print(f"  {k:18s} recall={s['recall']} prec={s['precision']} f1={s['f1']}",
                  flush=True)
        final.setdefault("tasks", []).append({"task": tid, "scores": scores})

    # 汇总均值
    import statistics
    summary = {}
    for k in ("heuristic", "union_overlap", "llm_judge(pro)", "fusion(pro)"):
        f1s = [t["scores"][k]["f1"] for t in final["tasks"]]
        summary[k] = round(statistics.mean(f1s), 3)
    final["summary_mean_f1"] = summary
    print("\n=== 五任务均值 F1 ===")
    for k, v in summary.items():
        print(f"  {k:18s} {v}")
    with open("results/e2_final_comparison.json", "w", encoding="utf-8") as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print("SAVED results/e2_final_comparison.json")


if __name__ == "__main__":
    main()
