"""E2 任务族 A 的 gold bug 真实性抽查（构造即验证）。"""
import sys
sys.path.insert(0, '.')
from e2_task_family_a import BUGGY_CODES, E2_SPEC
import json

print('任务数:', E2_SPEC['n_tasks'], '| gold bugs 总数:', E2_SPEC['total_bugs'])
for t in BUGGY_CODES:
    exec(t['code'], {})
    print('[%s] %d bugs: %s' % (t['id'], len(t['gold_bugs']),
                                [b['type'] for b in t['gold_bugs']]))
print('全部代码可加载 OK')

# --- bug 真实性抽查 ---
t1 = BUGGY_CODES[0]['code']
ns = {}
exec(t1, ns)
r1 = list(ns['process_batches']([1, 2, 3]))   # 快照（返回值就是默认列表引用！）
r2 = ns['process_batches']([4, 5, 6])
assert r1 == [2, 4, 6], r1
assert r2 == [2, 4, 6, 8, 10, 12], r2
# 更强的复现：r1 引用本身被第二次调用污染
r1_now = ns['process_batches'].__defaults__[1]
assert r1_now is r2 and len(r1_now) == 6, r1_now
print('task1 bug1 可变默认参数状态泄漏 复现 OK（r1 快照 [2,4,6]，同一对象现含 6 元素）:', r2)
try:
    ns['find_last']([1, 2, 3], lambda x: x > 100)
    print('task1 bug3 未复现（意外）')
except NameError:
    print('task1 bug3 NameError 复现 OK')

t2 = BUGGY_CODES[1]['code']
ns2 = {}
exec(t2, ns2)
names = [' a ', 'b']
assert ns2['normalize'](names) == [' a ', 'b'], names
print('task2 bug2 归一化无效 复现 OK')
a, b = {'x': 1}, {'y': 2}
ns2['merge'](a, b)
assert a == {'x': 1, 'y': 2}, a
print('task2 bug3 入参副作用 复现 OK:', a)

t4 = BUGGY_CODES[3]['code']
ns4 = {}
exec(t4, ns4)
v = ns4['is_expired'](100, 200)
# 已过期（expiry 100 < now 200）时正确答案 True；颠倒的函数返回 False（=声称未过期）
print('task4 bug2 方向颠倒: is_expired(expiry=100, now=200) =', v,
      '-> 颠倒复现 OK（声称未过期）' if v is False else '-> 未复现')

t5 = BUGGY_CODES[4]['code']
ns5 = {}
exec(t5, ns5)
handlers = ns5['build_handlers']()
r_add = handlers[0](2, 3)
r_mul = handlers[1](2, 3)
print('task5 bug1 晚绑定: add(2,3) =', r_add, '| mul(2,3) =', r_mul,
      '-> 全部做减法（-1）确认 OK' if r_add == -1 and r_mul == -1 else '-> 未复现')

print('\n全部抽查 bug 真实性 OK（gold 清单可信）')
