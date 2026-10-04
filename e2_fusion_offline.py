"""E2 离线 fusion 对照：确定性 fusion（候选行抽取+聚类去重）vs best-single selection。

零 API 成本——用第一轮已存的 30 个候选评审。
fusion 近似 = 抽取所有 "- [类型]" 行 → 按类型+位置关键词聚类去重 → fused bug 列表。
这测的是 fusion 机制的核心（并集信息量 > 单候选信息量），不含 LLM 合并质量。
"""

import json
import re
import os

prior = json.load(open("results/e2_task_a_results.json", encoding="utf-8"))
sys_path = os.path.join(os.path.dirname(__file__))
sys.path.insert(0, sys_path) if False else None
from e2_task_family_a import BUGGY_CODES  # noqa: E402

OUT = []
for ti, task in enumerate(BUGGY_CODES):
    tid = task["id"]
    gold = task["gold_bugs"]
    reviews = prior["tasks"][ti]["reviews"]

    # ---- 候选 bug 条目池抽取 ----
    entries = []
    for r in reviews:
        for line in r["text"].split("\n"):
            line = line.strip().lstrip("-•* ").strip()
            if line.startswith("[") and "]" in line:
                typ = line[1:line.index("]")]
                rest = line[line.index("]") + 1:].strip()
                if rest:
                    entries.append({"type": typ, "rest": rest, "review": r["idx"]})

    # ---- 聚类去重（类型 + 描述关键词重叠）----
    def norm(e):
        words = set(re.findall(r"[\w\u4e00-\u9fff]+", e["rest"].lower()))
        return words

    clusters = []
    for e in entries:
        w = norm(e)
        merged = False
        for cl in clusters:
            if cl["type"] == e["type"]:
                ov = len(w & cl["words"]) / max(len(w | cl["words"]), 1)
                if ov > 0.35:
                    cl["votes"] += 1
                    cl["words"] |= w
                    merged = True
                    break
        if not merged:
            clusters.append({"type": e["type"], "words": w, "votes": 1,
                             "sample": e["rest"][:60]})

    # ---- fused vs gold：类型匹配判定（cluster 类型命中 gold 类型 = 覆盖）----
    gold_types = [b["type"] for b in gold]
    matched_types = set()
    for cl in clusters:
        for gt in gold_types:
            if gt in cl["type"] or cl["type"] in gt or \
                    any(w in gt for w in cl["words"] if len(w) > 3):
                matched_types.add(gt)
    fused_recall = len(matched_types) / len(gold_types)
    fused_precision = len(matched_types) / len(clusters) if clusters else 0
    fused_f1 = (2 * fused_precision * fused_recall /
                (fused_precision + fused_recall)) if (fused_precision + fused_recall) else 0

    # ---- best-single 对照（复用第一轮的 selection 评测：单候选最大 recall）----
    # 第一轮已算 single_best_recall（flash 评测口径）——这里用类型匹配同口径重算
    def single_recall_type(text):
        covered = set()
        for line in text.split("\n"):
            for gt in gold_types:
                if gt in line or any(w in line for w in re.findall(
                        r"[\w\u4e00-\u9fff]+", gt) if len(w) > 3):
                    covered.add(gt)
        return len(covered) / len(gold_types)

    singles = [single_recall_type(r["text"]) for r in reviews]
    best_single = max(singles)
    avg_single = sum(singles) / len(singles)

    # union 上界：全部候选类型匹配的并集覆盖
    union_cov = set()
    for r in reviews:
        union_cov |= {gt for gt in gold_types
                      if any(gt in line or line.find(gt.split("_")[0]) >= 0
                             for line in r["text"].split("\n"))}
    # 宽松 union：逐 gold 检查任一候选提及
    union_hit = 0
    for b in gold:
        kw = re.findall(r"[\w\u4e00-\u9fff]+", b["desc"])
        kws = [w for w in kw + [b["type"]] if len(w) > 2][:6]
        if any(any(kw2 in r["text"] for kw2 in kws if len(kw2) > 2)
               for r in reviews):
            union_hit += 1
    union_recall = union_hit / len(gold)

    OUT.append({
        "task": tid,
        "gold_bugs": len(gold),
        "clusters": len(clusters),
        "votes_dist": sorted([c["votes"] for c in clusters], reverse=True),
        "fused_recall_type": round(fused_recall, 3),
        "fused_precision_type": round(fused_precision, 3),
        "fused_f1_type": round(fused_f1, 3),
        "best_single_recall": round(best_single, 3),
        "avg_single_recall": round(avg_single, 3),
        "union_recall_all_candidates": round(union_recall, 3),
    })
    print(f"[{tid}] clusters={len(clusters):2d} fused_recall={fused_recall:.2f} "
          f"best_single={best_single:.2f} avg_single={avg_single:.2f} "
          f"union_all={union_recall:.2f}")

# ---- 汇总 ----
import statistics
fm = [r["fused_f1_type"] for r in OUT]
bs = [r["best_single_recall"] for r in OUT]
av = [r["avg_single_recall"] for r in OUT]
un = [r["union_recall_all_candidates"] for r in OUT]
print("\n=== 汇总（类型匹配口径）===")
print(f"  deterministic fusion F1  均值: {statistics.mean(fm):.3f}")
print(f"  best-single recall       均值: {statistics.mean(bs):.3f}")
print(f"  avg-single recall        均值: {statistics.mean(av):.3f}")
print(f"  union(全部候选并集) recall: {statistics.mean(un):.3f}  ← fusion 理论上界")
print("\n解读：union 上界 vs best-single 的差 = selection 损失在开放域的量级；"
      "deterministic fusion 能吃到多少这个差 = fusion 机制的实证价值。")

with open("results/e2_fusion_offline.json", "w", encoding="utf-8") as f:
    json.dump({"per_task": OUT, "summary": {
        "fusion_f1_mean": round(statistics.mean(fm), 3),
        "best_single_mean": round(statistics.mean(bs), 3),
        "avg_single_mean": round(statistics.mean(av), 3),
        "union_upper_bound_mean": round(statistics.mean(un), 3)}},
        f, ensure_ascii=False, indent=2)
print("SAVED results/e2_fusion_offline.json")
