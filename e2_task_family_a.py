"""E2 任务族 A：代码评审 bug 检测任务（构造数据 + bug 清单）。

5 段 Python 代码，每段注入 2-3 个真实 bug（含类型标注）。
bug 清单 = selection/fusion 的 ground truth：
  - selection 评测：候选评审的 bug 集合与 gold 的 F1
  - fusion 评测：融合后的 bug 集合与 gold 的 F1（对照 selection）
"""

BUGGY_CODES = [
    # --- 任务 1：off-by-one + 可变默认参数 + 异常吞掉 ---
    {
        "id": "task_1",
        "code": '''def process_batches(items, batch_size=10, results=[]):
    for i in range(0, len(items), batch_size):
        try:
            batch = items[i:i + batch_size]
            processed = [x * 2 for x in batch]
            results.extend(processed)
        except Exception:
            pass
    return results

def find_last(items, predicate):
    for i in range(len(items)):
        if predicate(items[i]):
            target = i
    return target
''',
        "gold_bugs": [
            {"type": "mutable_default", "desc": "results=[] 可变默认参数：多次调用间状态泄漏",
             "location": "process_batches 签名"},
            {"type": "swallowed_exception", "desc": "except Exception: pass 静默吞掉所有异常，失败批次无感知",
             "location": "process_batches try 块"},
            {"type": "nameerror_on_no_match", "desc": "find_last 无匹配时 target 未定义 → NameError；且遍历全表而非逆序（应 range(len-1, -1, -1) 或记录后返回）",
             "location": "find_last"},
        ],
    },
    # --- 任务 2：浅拷贝 + 字符串不可变性误解 ---
    {
        "id": "task_2",
        "code": '''def dedupe(rows):
    seen = set()
    out = []
    for row in rows:
        key = str(sorted(row.keys()))
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out

def normalize(names):
    for n in names:
        n.upper().strip()
    return names

def merge(a, b):
    config = a
    config.update(b)
    return config
''',
        "gold_bugs": [
            {"type": "wrong_dedupe_key", "desc": "去重键是 sorted(row.keys()) 即“字段名列表”——字段名相同的两条不同记录会被误删；应键入字段值",
             "location": "dedupe"},
            {"type": "ignored_result", "desc": "n.upper().strip() 的返回值被丢弃（字符串不可变），归一化无效",
             "location": "normalize"},
            {"type": "shallow_merge", "desc": "config = a 是引用赋值，update 直接改写入参 a（副作用泄漏）",
             "location": "merge"},
        ],
    },
    # --- 任务 3：竞态 + 资源泄漏 ---
    {
        "id": "task_3",
        "code": '''import threading

counter = 0

def worker(tasks):
    global counter
    for t in tasks:
        if t.ready():
            counter += 1
            process(t)

def read_config(path):
    f = open(path)
    data = json.load(f)
    return data

def cached_fetch(key, cache={}):
    if key in cache:
        return cache[key]
    value = expensive(key)
    cache[key] = value
    return value
''',
        "gold_bugs": [
            {"type": "race_condition", "desc": "counter += 1 非原子操作且无锁，多线程下丢更新",
             "location": "worker"},
            {"type": "resource_leak", "desc": "open 后未 close/未用 with，异常路径文件句柄泄漏",
             "location": "read_config"},
            {"type": "unbounded_cache", "desc": "cache={} 可变默认参数 + 无界增长：跨调用状态泄漏与内存膨胀",
             "location": "cached_fetch"},
        ],
    },
    # --- 任务 4：边界条件 + 时间比较 ---
    {
        "id": "task_4",
        "code": '''def slice_page(items, page, size):
    start = page * size
    return items[start:start + size]

def is_expired(expiry_ts, now_ts):
    return expiry_ts > now_ts

def avg_scores(scores):
    total = 0
    for s in scores:
        total += s
    return total / len(scores)
''',
        "gold_bugs": [
            {"type": "no_page_guard", "desc": "page<0 或 size<=0 无守卫：负页码返回尾部切片、size=0 会抛 ZeroDivisionError？不——start=0*0=0 切片为空列表，语义为静默错误",
             "location": "slice_page"},
            {"type": "inverted_expiry", "desc": "is_expired 比较方向颠倒：过期应为 expiry_ts <= now_ts，当前返回“未过期”",
             "location": "is_expired"},
            {"type": "zero_division", "desc": "avg_scores 空列表 → ZeroDivisionError",
             "location": "avg_scores"},
        ],
    },
    # --- 任务 5：类型混淆 + 闭包晚绑定 ---
    {
        "id": "task_5",
        "code": '''def build_handlers():
    handlers = []
    for op in ["add", "mul", "sub"]:
        def handler(x, y):
            return {"add": x + y, "mul": x * y, "sub": x - y}[op]
        handlers.append(handler)
    return handlers

def to_int(value):
    return int(value.strip()) if isinstance(value, str) else value

def pick(d, keys):
    return {k: d[k] for k in keys}
''',
        "gold_bugs": [
            {"type": "late_binding", "desc": "闭包晚绑定：所有 handler 共享同一个 op（循环结束后 op='sub'），add/mul 的 handler 实际做减法",
             "location": "build_handlers"},
            {"type": "crash_on_none", "desc": "to_int 对 None 会 AttributeError（None.strip）——None 与数字路径未处理",
             "location": "to_int"},
            {"type": "keyerror_no_guard", "desc": "pick 对缺失键直接 KeyError，无 .get 守卫——调用方无法区分“键不存在”与“值就是 None”",
             "location": "pick"},
        ],
    },
]

E2_SPEC = {
    "n_tasks": len(BUGGY_CODES),
    "total_bugs": sum(len(t["gold_bugs"]) for t in BUGGY_CODES),
    "sampling_plan": "每段 × N=6 采样（deepseek-flash, low, temperature=0.7, off-peak）→ 30 个候选评审",
    "judges": ["heuristic(长度/关键词)", "vote(bug 集合重叠)", "probe(小模型评分)",
               "llm_judge(pro 排序)", "fusion(bug 集合并集)"],
    "metrics": ["bug-recall", "false-positive rate", "F1", "fusion vs selection 正面对照"],
}

if __name__ == "__main__":
    print(json.dumps(E2_SPEC, ensure_ascii=False, indent=2) if (json := __import__("json")) else "")
    for t in BUGGY_CODES:
        print(f"\n[{t['id']}] gold bugs:")
        for b in t["gold_bugs"]:
            print(f"  - {b['type']}: {b['desc'][:60]}")
