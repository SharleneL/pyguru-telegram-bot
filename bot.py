"""
python_guru — one-topic-at-a-time drill bot for Python3 interview syntax.

Flow:
  "test me" / /practice → pick topic → show review → quiz (1-10 Qs)
  After round → 3 choices: 1.随机 2.常错 3.继续当前
  "teach me [topic]" → full explanation + 易错点
  Any question during quiz → answered inline, quiz continues
  /errors → error book  /coverage → topic coverage  /stop → end session
"""

import os, json, logging, random
from pathlib import Path
from anthropic import AsyncAnthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_CHAT_ID   = os.environ.get("ALLOWED_CHAT_ID")
MODEL             = "claude-sonnet-4-6"
ERRORS_FILE       = Path(os.environ.get("ERRORS_FILE", "errors.json"))
TOPICS_FILE       = Path(os.environ.get("TOPICS_FILE", "syntax_topics.json"))
client            = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

TRIGGER_PHRASES   = {"test me", "考我", "出题", "练习", "quiz me", "practice"}

# ── system prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are python_guru, a drill coach for Python3 interview syntax.
The user is an experienced backend engineer (C#/Java) whose Python syntax is rusty.

ACCURACY IS NON-NEGOTIABLE:
- Every Python line MUST be valid Python3. Verify before writing.
- Traps: no `new` keyword; `list.sort()` returns None; `sorted()` returns new list;
  use `and/or/not` not `&&/||/!`; `range(0,10)` is 0-9; 3/2=1.5 not 2.5;
  `deque.popleft()` not `dequeue()`; empty set is `set()` not `{}`.

GENERATING A QUESTION (topic is specified by the bot):
- Generate ONE question testing that specific topic.
- Types: fill-in-blank, "what does this return?", spot-the-bug, complete-the-code.
- Do NOT reveal the answer. End with a blank line then exactly:
```json
{"covered_topics": ["topic_id"], "suggest_topics": []}
```

GRADING (user sends answer):
Reply in this exact structure:
Line 1: ✅ 正确 or ❌ 错误
Line 2: 正确写法: `<correct python>`  (use code block if multi-line)
Line 3: 记忆点: <one sharp Chinese sentence>

Then the update block (stripped by bot, user never sees it):
```json
{"add_or_escalate": [{"point":"...","correct":"...","status":"🔴"}], "mastered": []}
```
If nothing to update output empty lists. Nothing after the json block.

ANSWERING SIDE QUESTIONS (when user asks something mid-quiz):
Answer concisely in Chinese with code examples. End with: "继续作答 👇"

TONE: terse, direct, no fluff.
"""

# ── topic complexity (number of questions per round) ─────────────────────────
TOPIC_COMPLEXITY = {
    "list_basics": 4, "list_slice": 3, "list_sort": 4, "list_comprehension": 3,
    "list_modify": 4, "stack_pattern": 3, "deque_queue": 4, "heapq": 6,
    "dict_basics": 5, "dict_iterate": 3, "defaultdict": 3, "set_basics": 3,
    "number_ops": 4, "math_funcs": 3, "ord_chr": 3, "boolean_ops": 3,
    "ternary": 2, "fstrings": 3, "range_ops": 3, "multiple_return": 3, "class_init": 4,
    "helper_methods": 4,
}

# ── topic content (review shown before quiz, teach shown on "teach me") ───────
TOPIC_CONTENT = {
    "list_basics": {
        "title": "list 基础操作",
        "review": (
            "```python\n"
            "a.append(x)   # 加到末尾，O(1)\n"
            "a.pop()       # 删最后，O(1)\n"
            "a.pop(0)      # 删第一，O(n)\n"
            "x in a        # 查找，O(n)\n"
            "len(a)        # 长度\n"
            "a.index(x)    # 第一个x的下标（不存在报 ValueError）\n"
            "```"
        ),
        "teach": (
            "📖 *list 基础操作*\n\n"
            "```python\n"
            "a.append(x)   # 加到末尾，O(1)\n"
            "a.pop()       # 删最后，O(1)\n"
            "a.pop(0)      # 删第一，O(n) 慢！\n"
            "x in a        # 查找，O(n)\n"
            "len(a)        # 长度\n"
            "a.index(x)    # 第一个x下标（不存在报 ValueError）\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "需要频繁头部操作 → 用 `deque`，不用 `pop(0)`\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ set 才有 add\n"
            "a.add(1)\n"
            "# ✅ list 用 append\n"
            "a.append(1)\n"
            "```"
        ),
    },
    "list_slice": {
        "title": "list 切片",
        "review": (
            "```python\n"
            "a = [0, 1, 2, 3, 4]\n"
            "a[2:4]    # [2, 3]  左闭右开，不包括4\n"
            "a[2:-1]   # [2, 3]  到倒数第二个\n"
            "a[:]      # 浅拷贝\n"
            "a[::-1]   # [4,3,2,1,0]  反转\n"
            "a[::2]    # [0, 2, 4]  步长2\n"
            "```"
        ),
        "teach": (
            "📖 *list 切片*\n\n"
            "```python\n"
            "a = [0, 1, 2, 3, 4]\n"
            "a[2:4]    # [2, 3]  左闭右开\n"
            "a[2:-1]   # [2, 3]  负数从右数\n"
            "a[:]      # 浅拷贝\n"
            "a[::-1]   # [4,3,2,1,0]  反转\n"
            "a[::2]    # [0, 2, 4]  步长2\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "`a[::-1]` 反转字符串/数组，O(n)\n\n"
            "⚠️ *易错点*\n"
            "`a[2:4]` 包含 index 2 和 3，不包含 4\n"
            "`a[2:-1]` 不包含最后一个元素"
        ),
    },
    "list_sort": {
        "title": "list 排序",
        "review": (
            "```python\n"
            "sorted(a)                    # 返回新 list，原 list 不变\n"
            "a.sort()                     # 原地排序，返回 None！\n"
            "a.sort(reverse=True)         # 降序\n"
            "sorted(a, key=len)           # 按长度排\n"
            "sorted(a, key=lambda x: -x) # 自定义 key\n"
            "```"
        ),
        "teach": (
            "📖 *list 排序*\n\n"
            "```python\n"
            "sorted(a)                    # 返回新 list，原 list 不变\n"
            "a.sort()                     # 原地，返回 None\n"
            "a.sort(reverse=True)         # 降序\n"
            "sorted(a, key=len)           # 按元素长度\n"
            "sorted(a, key=lambda x: -x) # 自定义\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ sort() 返回 None\n"
            "b = a.sort()   # b 是 None！\n"
            "# ✅\n"
            "b = sorted(a)  # 新 list\n"
            "a.sort()       # 原地，不赋值\n\n"
            "# ❌ 降序传 -1\n"
            "a.sort(-1)\n"
            "# ✅\n"
            "a.sort(reverse=True)\n"
            "```"
        ),
    },
    "list_comprehension": {
        "title": "列表推导式",
        "review": (
            "```python\n"
            "[x for x in a]                 # 基础\n"
            "[x for x in a if x > 0]        # 过滤\n"
            "[x*2 for x in range(5)]        # [0,2,4,6,8]\n"
            "[x for x in a if x != target]  # 过滤某个值\n"
            "{k: v for k, v in d.items()}   # dict 推导\n"
            "{x for x in a}                 # set 推导\n"
            "```"
        ),
        "teach": (
            "📖 *列表推导式*\n\n"
            "```python\n"
            "[x for x in a]                # 基础\n"
            "[x for x in a if x > 0]       # 过滤\n"
            "[x*2 for x in range(5)]       # [0,2,4,6,8]\n"
            "{k: v for k, v in d.items()}  # dict 推导\n"
            "{x for x in a}               # set 推导\n"
            "```\n\n"
            "🎯 比 `filter()`/`map()` 更 Pythonic，优先用推导式\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ if 位置错误\n"
            "[if x>0: x for x in a]\n"
            "# ✅ if 在末尾\n"
            "[x for x in a if x > 0]\n"
            "```"
        ),
    },
    "list_modify": {
        "title": "list 增删改",
        "review": (
            "```python\n"
            "a.insert(2, x)  # 在 index 2 插入 x\n"
            "a.extend(b)     # 把 b 所有元素加到 a（原地）\n"
            "a + b           # 返回新 list（不改 a）\n"
            "a.remove(x)     # 删第一个 x（不存在报 ValueError）\n"
            "a.copy()        # 浅拷贝\n"
            "a.clear()       # 清空（a 仍存在，变成 []）\n"
            "```"
        ),
        "teach": (
            "📖 *list 增删改*\n\n"
            "```python\n"
            "a.insert(i, x)  # 在 index i 插入，O(n)\n"
            "a.extend(b)     # 把 b 合并到 a，原地\n"
            "a + b           # 返回新 list，不改 a\n"
            "a.remove(x)     # 删第一个 x（不存在报 ValueError）\n"
            "a.copy()        # 浅拷贝\n"
            "a.clear()       # 清空（a 仍存在）\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# extend vs append 区别\n"
            "a.append([1,2])  # a 变成 [..., [1,2]] 嵌套！\n"
            "a.extend([1,2])  # a 变成 [..., 1, 2]  展开\n"
            "```"
        ),
    },
    "stack_pattern": {
        "title": "stack（用 list 实现）",
        "review": (
            "```python\n"
            "stack = []\n"
            "stack.append(x)  # push，O(1)\n"
            "stack.pop()      # pop，O(1)\n"
            "stack[-1]        # peek（不删除）\n"
            "if not stack:    # 判断是否为空\n"
            "```"
        ),
        "teach": (
            "📖 *stack（用 list 实现）*\n\n"
            "```python\n"
            "stack = []\n"
            "stack.append(x)  # push\n"
            "stack.pop()      # pop，返回弹出的值\n"
            "stack[-1]        # peek（不删除）\n"
            "if not stack:    # 判断空\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "括号匹配、单调栈 → 标准 list stack\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ 没有 top() 方法\n"
            "stack.top()\n"
            "# ✅\n"
            "stack[-1]\n"
            "```"
        ),
    },
    "deque_queue": {
        "title": "deque（队列）",
        "review": (
            "```python\n"
            "from collections import deque\n"
            "q = deque()\n"
            "q = deque([1, 2, 3])  # 从 list 初始化\n"
            "q.append(x)           # 从右入队\n"
            "q.appendleft(x)       # 从左入队\n"
            "q.popleft()           # 从左出队 ← 队列用这个\n"
            "q.pop()               # 从右出队\n"
            "```"
        ),
        "teach": (
            "📖 *deque（队列）*\n\n"
            "```python\n"
            "from collections import deque  # 必须导入！\n"
            "q = deque()\n"
            "q.append(x)       # 从右加\n"
            "q.appendleft(x)   # 从左加\n"
            "q.popleft()       # 从左取 ← 队列标准\n"
            "q.pop()           # 从右取\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "BFS → `deque` + `popleft()`\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ 这些都不存在\n"
            "q.dequeue()\n"
            "from collections import Queue\n"
            "# ✅\n"
            "q.popleft()\n"
            "from collections import deque  # 小写 d\n"
            "```"
        ),
    },
    "heapq": {
        "title": "heapq（最小堆）",
        "review": (
            "```python\n"
            "import heapq\n"
            "h = []\n"
            "heapq.heappush(h, x)      # 推入\n"
            "heapq.heappop(h)           # 弹出最小值\n"
            "h[0]                       # 查看最小（不删除）\n"
            "heapq.heapify(lst)         # 原地建堆，O(n)\n"
            "heapq.nlargest(k, lst)     # 最大的k个\n"
            "heapq.nsmallest(k, lst)    # 最小的k个\n"
            "# 最大堆：存负数\n"
            "heapq.heappush(h, -x)\n"
            "val = -heapq.heappop(h)\n"
            "```"
        ),
        "teach": (
            "📖 *heapq（最小堆）*\n\n"
            "```python\n"
            "import heapq\n"
            "h = []\n"
            "heapq.heappush(h, x)    # 推入，O(log n)\n"
            "heapq.heappop(h)         # 弹出最小，O(log n)\n"
            "h[0]                     # 查看最小（不删除）\n"
            "heapq.heapify(lst)       # 原地建堆，O(n)\n"
            "heapq.nlargest(k, lst)   # 最大的k个\n"
            "heapq.nsmallest(k, lst)  # 最小的k个\n"
            "```\n\n"
            "最大堆写法：\n"
            "```python\n"
            "heapq.heappush(h, -x)      # 存负数\n"
            "val = -heapq.heappop(h)    # 取出时取反\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "Top K → `nlargest`/`nsmallest`\n"
            "动态维护最小值 → heap\n\n"
            "⚠️ Python 堆是*最小堆*，没有内置最大堆"
        ),
    },
    "dict_basics": {
        "title": "dict 基础",
        "review": (
            "```python\n"
            "d = {}\n"
            "d['k'] = 1               # 赋值\n"
            "d.get('k', 0)            # 安全取值，不存在返回默认值\n"
            "'k' in d                 # 判断 key 存在，O(1)\n"
            "d.pop('k')               # 删除并返回值\n"
            "d.update({'a': 1})       # 批量更新\n"
            "d.clear()                # 清空\n"
            "```"
        ),
        "teach": (
            "📖 *dict 基础*\n\n"
            "```python\n"
            "d = {}  # 或 dict()\n"
            "d['k'] = 1            # 赋值\n"
            "d.get('k', 0)         # 不存在返回0，不报错\n"
            "'k' in d              # O(1) 判断\n"
            "d.pop('k')            # 删除并返回值\n"
            "d.update({'a': 1})    # 批量更新\n"
            "d.clear()             # 清空\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ key 不存在时直接访问报 KeyError\n"
            "d['missing']\n"
            "# ✅\n"
            "d.get('missing', 0)\n"
            "```"
        ),
    },
    "dict_iterate": {
        "title": "dict 遍历",
        "review": (
            "```python\n"
            "for k, v in d.items():  # 遍历键值对（最常用）\n"
            "for k in d:             # 遍历键（简写）\n"
            "for k in d.keys():      # 遍历键\n"
            "for v in d.values():    # 遍历值\n"
            "list(d.keys())          # 转 list\n"
            "sorted(d.keys())        # 排序后的 key list\n"
            "```"
        ),
        "teach": (
            "📖 *dict 遍历*\n\n"
            "```python\n"
            "for k, v in d.items():  # 键值对，最常用\n"
            "for k in d:             # 遍历键简写\n"
            "for k in d.keys():      # 显式\n"
            "for v in d.values():    # 遍历值\n"
            "list(d.keys())          # 转 list\n"
            "sorted(d.keys())        # 排序\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "`d.keys()` 返回 `dict_keys` 视图对象，不是 list\n"
            "需要下标访问时要 `list(d.keys())`"
        ),
    },
    "defaultdict": {
        "title": "defaultdict",
        "review": (
            "```python\n"
            "from collections import defaultdict\n"
            "d = defaultdict(int)    # 默认值 0\n"
            "d = defaultdict(list)   # 默认值 []\n"
            "d = defaultdict(set)    # 默认值 set()\n"
            "d['x'] += 1            # 不用先判断是否存在\n"
            "d['y'].append(1)\n"
            "```"
        ),
        "teach": (
            "📖 *defaultdict*\n\n"
            "```python\n"
            "from collections import defaultdict\n"
            "d = defaultdict(int)   # 访问不存在的key返回0\n"
            "d = defaultdict(list)  # 返回 []\n"
            "d = defaultdict(set)   # 返回 set()\n\n"
            "# 统计频率\n"
            "for x in arr:\n"
            "    d[x] += 1\n\n"
            "# 分组\n"
            "for k, v in pairs:\n"
            "    d[k].append(v)\n"
            "```\n\n"
            "⚠️ *vs dict.get*\n"
            "```python\n"
            "# 等价写法\n"
            "d[x] += 1\n"
            "d[x] = d.get(x, 0) + 1\n"
            "```"
        ),
    },
    "set_basics": {
        "title": "set 基础",
        "review": (
            "```python\n"
            "s = set()              # 空 set（不是 {}！那是空 dict）\n"
            "s = {1, 2, 3}         # 字面量\n"
            "s = set([1, 2, 3])    # 从 list\n"
            "s = set('AaBBB')      # {'A', 'a', 'B'}\n"
            "s.add(x)              # 加\n"
            "s.remove(x)           # 删（不存在报 KeyError）\n"
            "s.discard(x)          # 删（不存在不报错）\n"
            "x in s                # O(1) 查找\n"
            "```"
        ),
        "teach": (
            "📖 *set 基础*\n\n"
            "```python\n"
            "s = set()           # ⚠️ 不是 {}（那是空 dict）\n"
            "s = {1, 2, 3}       # 字面量\n"
            "s = set([1, 2, 3])  # 从 list\n"
            "s.add(x)            # 加\n"
            "s.remove(x)         # 删，不存在报 KeyError\n"
            "s.discard(x)        # 删，不存在不报错\n"
            "x in s              # O(1)\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "去重 → `list(set(arr))`\n"
            "O(1) 查找 → set，不用 list\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "s = {}   # ❌ 空 dict！\n"
            "s = set()  # ✅ 空 set\n"
            "```"
        ),
    },
    "number_ops": {
        "title": "数字运算",
        "review": (
            "```python\n"
            "3 / 2     # 1.5（真除法，Python3）\n"
            "3 // 2    # 1（整除，向下取整）\n"
            "-7 // 2   # -4（向下，不是向零）\n"
            "3 % 2     # 1（取余）\n"
            "2 ** 3    # 8（次方）\n"
            "int(2.6)  # 2（截断，不四舍五入）\n"
            "int(-2.6) # -2（向零截断）\n"
            "```"
        ),
        "teach": (
            "📖 *数字运算*\n\n"
            "```python\n"
            "3 / 2     # 1.5  真除法\n"
            "3 // 2    # 1    整除（向下取整）\n"
            "-7 // 2   # -4   注意：向下不是向零\n"
            "3 % 2     # 1    取余\n"
            "2 ** 3    # 8    次方\n"
            "int(2.6)  # 2    截断（向零）\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# Python3 的 / 是真除法\n"
            "3 / 2 == 1.5  # True（不是 1！）\n"
            "# 整数结果用 //\n"
            "3 // 2 == 1\n"
            "```"
        ),
    },
    "math_funcs": {
        "title": "数学函数",
        "review": (
            "```python\n"
            "abs(-3)               # 3\n"
            "max(1, 2, 3)          # 3（多个参数）\n"
            "max([1, 2, 3])        # 3（list）\n"
            "max(lst, key=abs)     # 按绝对值找最大\n"
            "min(a, b)             # 最小值\n"
            "sum([1, 2, 3])        # 6\n"
            "pow(2, 10)            # 1024 == 2**10\n"
            "float('inf')          # 正无穷\n"
            "float('-inf')         # 负无穷\n"
            "```"
        ),
        "teach": (
            "📖 *数学函数*\n\n"
            "```python\n"
            "abs(-3)               # 3\n"
            "max(1, 2, 3)          # 传多个参数\n"
            "max([1, 2, 3])        # 传 list\n"
            "max(lst, key=abs)     # 带 key\n"
            "sum([1, 2, 3])        # 6\n"
            "pow(2, 10)            # 1024\n"
            "float('inf')          # 正无穷\n"
            "float('-inf')         # 负无穷\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "`float('inf')` 初始化最小值哨兵\n"
            "`max(lst, key=lambda x: x[1])` 按第二个元素找最大"
        ),
    },
    "ord_chr": {
        "title": "ord / chr",
        "review": (
            "```python\n"
            "ord('a')              # 97  (a-z: 97-122)\n"
            "ord('A')              # 65  (A-Z: 65-90)\n"
            "chr(97)               # 'a'\n"
            "ord('c') - ord('a')   # 2（字母转 0-based index）\n"
            "chr(ord('a') + 2)     # 'c'\n"
            "```"
        ),
        "teach": (
            "📖 *ord / chr*\n\n"
            "```python\n"
            "ord('a')  # 97  (a-z: 97-122)\n"
            "ord('A')  # 65  (A-Z: 65-90)\n"
            "ord('0')  # 48  (0-9: 48-57)\n"
            "chr(97)   # 'a'\n\n"
            "# 字母 → 0-based index\n"
            "ord('c') - ord('a')  # 2\n"
            "# index → 字母\n"
            "chr(ord('a') + 2)    # 'c'\n"
            "```\n\n"
            "🎯 *面试场景*\n"
            "字母频率统计：`count[ord(c) - ord('a')] += 1`"
        ),
    },
    "boolean_ops": {
        "title": "布尔运算",
        "review": (
            "```python\n"
            "True and False   # False\n"
            "True or False    # True\n"
            "not True         # False\n"
            "# Python 没有 && || !\n"
            "bool([])         # False（空容器）\n"
            "bool([0])        # True（非空，不管内容）\n"
            "bool(0)          # False\n"
            "bool('')         # False\n"
            "bool(None)       # False\n"
            "```"
        ),
        "teach": (
            "📖 *布尔运算*\n\n"
            "```python\n"
            "and / or / not   # Python 写法\n"
            "# ❌ 不是 && || !\n\n"
            "bool([])    # False  空容器\n"
            "bool([0])   # True   非空 list（元素是0也算True）\n"
            "bool(0)     # False\n"
            "bool('')    # False\n"
            "bool(None)  # False\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌\n"
            "if a && b:\n"
            "# ✅\n"
            "if a and b:\n"
            "```"
        ),
    },
    "fstrings": {
        "title": "f-string 格式化",
        "review": (
            "```python\n"
            "name = 'Alice'; score = 95.678\n"
            "f'{name}'           # 'Alice'\n"
            "f'{score:.2f}'      # '95.68'  2位小数\n"
            "f'{score:.0f}'      # '96'     整数\n"
            "f'{42:>10}'         # '        42' 右对齐\n"
            "f'{42:05}'          # '00042'  补零\n"
            "```"
        ),
        "teach": (
            "📖 *f-string 格式化*\n\n"
            "```python\n"
            "f'{name}'        # 变量\n"
            "f'{score:.2f}'   # '95.68' 2位小数\n"
            "f'{score:.0f}'   # '96' 四舍五入\n"
            "f'{42:>10}'      # '        42' 右对齐\n"
            "f'{42:<10}'      # '42        ' 左对齐\n"
            "f'{42:05}'       # '00042' 补零\n"
            "f'{2+2}'         # '4' 表达式\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ 旧写法\n"
            "'Hello %s' % name\n"
            "# ✅\n"
            "f'Hello {name}'\n"
            "```"
        ),
    },
    "ternary": {
        "title": "三元表达式",
        "review": (
            "```python\n"
            "x = a if condition else b\n"
            "# Python 没有 ?: 运算符\n\n"
            "result = 'yes' if score > 60 else 'no'\n"
            "val = lst[0] if lst else None\n"
            "```"
        ),
        "teach": (
            "📖 *三元表达式*\n\n"
            "```python\n"
            "x = a if condition else b\n\n"
            "result = 'yes' if score > 60 else 'no'\n"
            "val = lst[0] if lst else None\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌ C#/Java 写法\n"
            "x = condition ? a : b\n"
            "# ✅ Python\n"
            "x = a if condition else b\n"
            "```"
        ),
    },
    "range_ops": {
        "title": "range",
        "review": (
            "```python\n"
            "range(5)                  # 0,1,2,3,4\n"
            "range(0, 10)              # 0到9（不包括10！）\n"
            "range(2, 10, 2)           # 2,4,6,8\n"
            "range(3, -1, -1)          # 3,2,1,0\n"
            "range(len(a)-1, -1, -1)   # 倒序遍历数组\n"
            "```"
        ),
        "teach": (
            "📖 *range*\n\n"
            "```python\n"
            "range(5)                 # 0,1,2,3,4\n"
            "range(0, 10)             # 0~9，不含10\n"
            "range(2, 10, 2)          # 2,4,6,8\n"
            "range(3, -1, -1)         # 3,2,1,0\n"
            "range(len(a)-1, -1, -1)  # 倒序遍历\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "`range(0, 10)` 是 0-9，共10个，不含10\n"
            "倒序到0必须写 `-1`：`range(n-1, -1, -1)`"
        ),
    },
    "multiple_return": {
        "title": "多返回值 & 解包",
        "review": (
            "```python\n"
            "def func():\n"
            "    return 1, 2, [3, 4]   # 返回 tuple\n\n"
            "x, y, z = func()          # 解包\n"
            "_, y = func2()            # _ 忽略第一个\n"
            "a, b = b, a               # 交换（不需要 temp）\n"
            "first, *rest = [1,2,3,4]  # rest = [2,3,4]\n"
            "```"
        ),
        "teach": (
            "📖 *多返回值 & 解包*\n\n"
            "```python\n"
            "def func():\n"
            "    return 1, 2, [3, 4]  # 本质是 tuple\n\n"
            "x, y, z = func()         # 解包\n"
            "_, y = func2()           # _ 表示忽略\n"
            "a, b = b, a              # 交换，不用 temp\n"
            "first, *rest = [1,2,3,4] # rest=[2,3,4]\n"
            "```\n\n"
            "🎯 *面试常用*\n"
            "`a, b = b, a` 一行交换两变量"
        ),
    },
    "class_init": {
        "title": "class 基础",
        "review": (
            "```python\n"
            "class Person:\n"
            "    def __init__(self, name, age):\n"
            "        self.name = name\n"
            "        self.age = age\n\n"
            "p = Person('John', 36)   # 没有 new！\n\n"
            "class TreeNode:\n"
            "    def __init__(self, val=0, left=None, right=None):\n"
            "        self.val = val\n"
            "        self.left = left\n"
            "        self.right = right\n"
            "```"
        ),
        "teach": (
            "📖 *class 基础*\n\n"
            "```python\n"
            "class Person:\n"
            "    def __init__(self, name, age):\n"
            "        self.name = name\n"
            "        self.age = age\n\n"
            "p = Person('John', 36)  # 没有 new！\n"
            "```\n\n"
            "⚠️ *易错点*\n"
            "```python\n"
            "# ❌\n"
            "p = new Person('John', 36)\n"
            "# ✅\n"
            "p = Person('John', 36)\n\n"
            "# ❌ 忘记 self\n"
            "def __init__(name, age):\n"
            "# ✅\n"
            "def __init__(self, name, age):\n"
            "```"
        ),
    },
    "helper_methods": {
        "title": "helper method 两种写法",
        "review": (
            "```python\n"
            "# 方法1: inner def（闭包，递归不用 self）\n"
            "def solve(self, root):\n"
            "    def dfs(node):\n"
            "        if node: dfs(node.left)  # 递归直接调\n"
            "    dfs(root)\n\n"
            "# 方法2: sibling method\n"
            "def solve(self, root):\n"
            "    self.dfs(root)       # 调用：self.\n\n"
            "def dfs(self, node):     # 定义：有 self\n"
            "    self.dfs(node.left)  # 递归：self.\n"
            "```"
        ),
        "teach": (
            "📖 *helper method 两种写法*\n\n"
            "*方法1: inner def（推荐）*\n"
            "```python\n"
            "def solve(self, root):\n"
            "    result = []\n"
            "    def dfs(node):\n"
            "        if not node: return\n"
            "        result.append(node.val)\n"
            "        dfs(node.left)   # 递归：直接调，无 self\n"
            "    dfs(root)\n"
            "    return result\n"
            "```\n\n"
            "*方法2: sibling method*\n"
            "```python\n"
            "def solve(self, root):\n"
            "    self.dfs(root)      # 调用：self.\n\n"
            "def dfs(self, node):    # 定义：有 self\n"
            "    self.dfs(node.left) # 递归：self.\n"
            "```\n\n"
            "⚠️ inner def 递归不用 self；sibling method 递归要 self."
        ),
    },
}

# ── DEFAULT_TOPICS (for topics file initialization) ───────────────────────────
DEFAULT_TOPICS = [
    ("list_basics",        "list: append/pop/pop(0)/in/len/index"),
    ("list_slice",         "slice: a[2:4] 左闭右开; a[2:-1]; a[::-1] 反转"),
    ("list_sort",          "sorted(a) 返回新list; a.sort(reverse=True) 原地返回None"),
    ("list_comprehension", "[x for x in a if cond]"),
    ("list_modify",        "insert(i,x)/extend(lst)/remove(x)/copy()/clear()"),
    ("stack_pattern",      "list as stack: append/pop/[-1] peek"),
    ("deque_queue",        "from collections import deque; append/popleft"),
    ("heapq",              "heappush/heappop/heapify/nlargest/nsmallest; max-heap 用 -x"),
    ("dict_basics",        "d[k]=v; get(k,default); k in d; pop(k); update({k:v}); clear()"),
    ("dict_iterate",       "for k,v in d.items(); d.keys(); d.values()"),
    ("defaultdict",        "defaultdict(int) 默认0; defaultdict(list) 默认[]"),
    ("set_basics",         "set(); add/remove/discard/in; set([1,2]); set('AaBBB')"),
    ("number_ops",         "3/2=1.5; 3//2=1 整除; 3%2=1; 2**3=8; int(2.6)=2"),
    ("math_funcs",         "abs/max/min/sum/pow; float('inf')/float('-inf')"),
    ("ord_chr",            "ord('a')=97; chr(97)='a'; ord(ch)-ord('a') 得index"),
    ("boolean_ops",        "and/or/not（不是&&/||/!）; True/False; bool([])=False"),
    ("fstrings",           "f-string formatting: f-string format specs"),
    ("ternary",            "x if cond else y（没有?:运算符）"),
    ("range_ops",          "range(0,10) 是0-9; range(3,-1,-1) 倒序3,2,1,0"),
    ("multiple_return",    "return a,b,c → x,y,z = func(); a,b=b,a 交换"),
    ("class_init",         "__init__(self,...); 没有new关键字; p = Person('John', 36)"),
    ("helper_methods",     "inner def 递归不用self; sibling method 用self.method()"),
]

# ── error book ────────────────────────────────────────────────────────────────
def load_errors() -> dict:
    if ERRORS_FILE.exists():
        return json.loads(ERRORS_FILE.read_text(encoding="utf-8"))
    return {"points": [], "mastered": []}

def save_errors(data: dict) -> None:
    ERRORS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def errors_as_text(data: dict) -> str:
    if not data["points"]:
        body = "(错题本为空)"
    else:
        body = "\n".join(
            f"- [{p['status']}] {p['point']} → {p['correct']}"
            for p in data["points"]
        )
    mastered = ", ".join(data["mastered"]) if data["mastered"] else "(无)"
    return f"ERROR BOOK:\n{body}\n\nMASTERED: {mastered}"

def apply_updates(data: dict, updates: dict) -> dict:
    existing = {p["point"]: p for p in data["points"]}
    for item in updates.get("add_or_escalate", []):
        existing[item["point"]] = {
            "point": item["point"],
            "correct": item.get("correct", ""),
            "status": item.get("status", "🔴"),
        }
    for mp in updates.get("mastered", []):
        if mp in existing:
            existing.pop(mp)
            if mp not in data["mastered"]:
                data["mastered"].append(mp)
    data["points"] = list(existing.values())
    return data

# ── topics / curriculum ───────────────────────────────────────────────────────
def load_topics() -> dict:
    if TOPICS_FILE.exists():
        return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    data = {"topics": [{"id": tid, "label": lbl, "seen": 0} for tid, lbl in DEFAULT_TOPICS]}
    save_topics(data)
    return data

def save_topics(data: dict) -> None:
    TOPICS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def topics_as_text(data: dict) -> str:
    rows = sorted(data["topics"], key=lambda t: t["seen"])
    body = "\n".join(f"- [{t['id']}] {t['label']} (seen {t['seen']})" for t in rows)
    return f"SYNTAX CURRICULUM (lowest seen = least covered):\n{body}"

def apply_coverage(data: dict, covered_ids: list) -> dict:
    by_id = {t["id"]: t for t in data["topics"]}
    for tid in covered_ids:
        if tid in by_id:
            by_id[tid]["seen"] = by_id[tid].get("seen", 0) + 1
    return data

def apply_new_topics(data: dict, suggest_topics: list) -> tuple:
    existing_ids = {t["id"] for t in data["topics"]}
    added = []
    for entry in suggest_topics:
        if "|" not in entry:
            continue
        tid, label = entry.split("|", 1)
        tid = tid.strip(); label = label.strip()
        if tid and tid not in existing_ids:
            data["topics"].append({"id": tid, "label": label, "seen": 0})
            existing_ids.add(tid)
            added.append(label)
    return data, added

# ── topic picking ─────────────────────────────────────────────────────────────
def pick_topic(mode: str, current_topic_id: str = None) -> str:
    topics_data = load_topics()
    topic_ids = [t["id"] for t in topics_data["topics"]]

    if mode == "repeat" and current_topic_id:
        return current_topic_id

    # only pick topics that have content defined
    valid_topics = [t for t in topics_data["topics"] if t["id"] in TOPIC_CONTENT]
    if not valid_topics:
        valid_topics = topics_data["topics"]

    if mode == "weak":
        errors_data = load_errors()
        red = [p["point"].lower() for p in errors_data["points"] if p["status"] == "🔴"]
        yellow = [p["point"].lower() for p in errors_data["points"] if p["status"] == "🟡"]
        weak_words = red + yellow
        if weak_words:
            for t in sorted(valid_topics, key=lambda x: x["seen"]):
                label_lower = t["label"].lower()
                if any(w in label_lower or label_lower in w for w in weak_words):
                    return t["id"]
        return sorted(valid_topics, key=lambda t: t["seen"])[0]["id"]

    # random: weighted toward least-seen
    max_seen = max(t["seen"] for t in valid_topics) if valid_topics else 0
    weights = [max_seen - t["seen"] + 1 for t in valid_topics]
    return random.choices([t["id"] for t in valid_topics], weights=weights, k=1)[0]

def find_topic_by_query(query: str):
    """Fuzzy-match user query to a topic id. Returns None if no match."""
    query = query.lower().strip()
    if not query:
        return None
    def norm(s):
        return s.lower().replace("-", "").replace("_", "").replace(" ", "")
    q = norm(query)
    if query in TOPIC_CONTENT:
        return query
    # normalised id match (fstring -> fstrings, f-string -> fstrings)
    for tid in TOPIC_CONTENT:
        if q in norm(tid) or norm(tid) in q:
            return tid
    # normalised title match
    for tid, c in TOPIC_CONTENT.items():
        if q in norm(c["title"]):
            return tid
    # word overlap
    for tid, c in TOPIC_CONTENT.items():
        words = [norm(w) for w in c["title"].lower().split()]
        if any(q in w or w in q for w in words):
            return tid
    return None


# ── helpers ───────────────────────────────────────────────────────────────────
def _authorized(update: Update) -> bool:
    if ALLOWED_CHAT_ID is None:
        return True
    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)

def _is_question(text: str) -> bool:
    t = text.lower().strip()
    if t.endswith("?") or t.endswith("？"):
        return True
    question_starters = ["什么", "怎么", "为什么", "如何", "解释", "区别",
                         "what", "how", "why", "explain", "difference", "tell me"]
    return any(t.startswith(w) for w in question_starters)

async def call_claude(messages: list, system: str) -> str:
    resp = await client.messages.create(
        model=MODEL, max_tokens=1500, system=system, messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")

def split_grading_and_json(text: str):
    if "```json" in text:
        visible, _, rest = text.partition("```json")
        json_part, _, _ = rest.partition("```")
        try:
            updates = json.loads(json_part.strip())
        except json.JSONDecodeError:
            updates = None
        return visible.strip(), updates
    return text.strip(), None

# ── session ───────────────────────────────────────────────────────────────────
conversations = {}  # type: dict

AFTER_ROUND_MSG = (
    "\n\n选择下一步：\n"
    "1️⃣  随机出题\n"
    "2️⃣  常错考点\n"
    "3️⃣  继续当前考点\n\n"
    "回复 1 / 2 / 3，或说 test me"
)

async def _send_question(chat_id: int, bot) -> None:
    session = conversations[chat_id]
    topic_id = session["topic_id"]
    q_num = session["asked"] + 1
    total = session["total_questions"]

    errors = load_errors()
    topics = load_topics()
    user_msg = (
        f"Topic to focus on: {topic_id}\n"
        f"Question {q_num} of {total}.\n\n"
        + errors_as_text(errors) + "\n\n"
        + topics_as_text(topics)
    )
    messages = session["messages"] + [{"role": "user", "content": user_msg}]
    reply = await call_claude(messages, SYSTEM_PROMPT)

    visible, meta = split_grading_and_json(reply)
    if meta:
        topics = apply_coverage(topics, meta.get("covered_topics", []))
        topics, added = apply_new_topics(topics, meta.get("suggest_topics", []))
        save_topics(topics)
        if added:
            logger.info("New topics added: %s", added)

    session["messages"] = messages + [{"role": "assistant", "content": reply}]
    session["asked"] = q_num

    header = f"*题 {q_num}/{total}*\n\n"
    await bot.send_message(chat_id=chat_id, text=header + (visible or reply), parse_mode="Markdown")

async def _start_session(chat_id: int, bot, mode: str, current_topic_id: str = None) -> None:
    topic_id = pick_topic(mode, current_topic_id)
    total_q = TOPIC_COMPLEXITY.get(topic_id, 3)

    conversations[chat_id] = {
        "messages": [],
        "asked": 0,
        "graded": 0,
        "topic_id": topic_id,
        "total_questions": total_q,
        "phase": "quiz",
    }

    content = TOPIC_CONTENT.get(topic_id, {})
    title = content.get("title", topic_id)
    review = content.get("review", "")

    intro = f"📌 *本轮考察：{title}*（共{total_q}题）\n\n复习一下：\n{review}"
    await bot.send_message(chat_id=chat_id, text=intro, parse_mode="Markdown")
    await _send_question(chat_id, bot)

# ── handlers ──────────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    await update.message.reply_text(
        "👋 *python\\_guru* 上线\n\n"
        "说 *test me* 开始练习\n"
        "*teach me* \\[考点\\] — 查看语法说明\n"
        "/errors — 错题本\n"
        "/coverage — 语法覆盖进度\n"
        "/stop — 停止练习",
        parse_mode="Markdown",
    )

async def practice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await _start_session(update.effective_chat.id, ctx.bot, "random")

async def errors_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    data = load_errors()
    if not data["points"]:
        text = "✅ 错题本是空的，继续加油！"
    else:
        lines = [
            f"{'🔴' if p['status']=='🔴' else '🟡'} *{p['point']}*\n  → `{p['correct']}`"
            for p in data["points"]
        ]
        text = "📕 *错题本*\n\n" + "\n\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")

async def coverage_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    data = load_topics()
    rows = sorted(data["topics"], key=lambda t: t["seen"])
    lines = [f"`{t['id']}` {t['label']} （{t['seen']}次）" for t in rows]
    await update.message.reply_text(
        "📊 *语法覆盖进度*（从少到多）\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )

async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    conversations.pop(update.effective_chat.id, None)
    await update.message.reply_text("⏹ 练习已停止。说 \"test me\" 随时重新开始。")

async def handle_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update): return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # teach me
    if text.lower().startswith("teach me") or text.lower().startswith("教我"):
        await _handle_teach(chat_id, text, ctx.bot)
        return

    # trigger phrases → new session (optionally with specific topic)
    text_lower = text.lower()
    if text_lower in TRIGGER_PHRASES or text_lower.startswith("test me "):
        await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
        topic_query = text_lower.replace("test me", "").strip()
        specific_topic = find_topic_by_query(topic_query) if topic_query else None
        if specific_topic:
            await _start_session(chat_id, ctx.bot, "repeat", specific_topic)
        elif topic_query:
            topic_list = " / ".join(TOPIC_CONTENT.keys())
            await ctx.bot.send_message(chat_id=chat_id,
                text=f"找不到考点 '{topic_query}'。\n\n可用考点：\n{topic_list}")
        else:
            await _start_session(chat_id, ctx.bot, "random")
        return

    # no active session
    if chat_id not in conversations:
        await update.message.reply_text('说 "test me" 开始练习，或 "teach me" 查看语法。')
        return

    session = conversations[chat_id]

    # awaiting choice after round
    if session.get("phase") == "awaiting_choice":
        choice = text.strip()
        current_topic = session.get("topic_id")
        if choice == "1":
            await _start_session(chat_id, ctx.bot, "random")
        elif choice == "2":
            await _start_session(chat_id, ctx.bot, "weak")
        elif choice == "3":
            await _start_session(chat_id, ctx.bot, "repeat", current_topic)
        elif text.lower().startswith("test me "):
            topic_query = text.lower().replace("test me", "").strip()
            specific_topic = find_topic_by_query(topic_query)
            if specific_topic:
                await _start_session(chat_id, ctx.bot, "repeat", specific_topic)
            else:
                await ctx.bot.send_message(chat_id=chat_id, text="找不到这个考点，回复 1/2/3 或说 test me <考点名>")
        else:
            await ctx.bot.send_message(chat_id=chat_id,
                text="请回复 1、2 或 3，或说 test me <考点名>")
        return

    # side question mid-quiz
    if _is_question(text):
        await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
        q_msg = [{"role": "user", "content": f"[SIDE QUESTION] {text}"}]
        reply = await call_claude(session["messages"] + q_msg, SYSTEM_PROMPT)
        visible, _ = split_grading_and_json(reply)
        await update.message.reply_text(visible or reply, parse_mode="Markdown")
        return

    # grade answer
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    session["messages"].append({"role": "user", "content": text})
    reply = await call_claude(session["messages"], SYSTEM_PROMPT)

    visible, updates = split_grading_and_json(reply)
    if updates:
        save_errors(apply_updates(load_errors(), updates))
    session["messages"].append({"role": "assistant", "content": reply})
    session["graded"] += 1

    await update.message.reply_text(visible or "（已批改）", parse_mode="Markdown")

    if session["graded"] >= session["total_questions"]:
        # round complete
        data = load_errors()
        red = sum(1 for p in data["points"] if p["status"] == "🔴")
        yellow = sum(1 for p in data["points"] if p["status"] == "🟡")
        summary = (
            f"✅ *本轮结束！*\n"
            f"考点：{TOPIC_CONTENT.get(session['topic_id'], {}).get('title', session['topic_id'])}\n"
            f"错题本：🔴 {red} · 🟡 {yellow}"
            + AFTER_ROUND_MSG
        )
        session["phase"] = "awaiting_choice"
        await ctx.bot.send_message(chat_id=chat_id, text=summary, parse_mode="Markdown")
    else:
        await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
        await _send_question(chat_id, ctx.bot)

async def _handle_teach(chat_id: int, text: str, bot) -> None:
    # parse topic from "teach me <topic>"
    query = text.lower().replace("teach me", "").replace("教我", "").strip()

    topic_id = None
    if query:
        # exact id match
        if query in TOPIC_CONTENT:
            topic_id = query
        else:
            # fuzzy match on title or id
            for tid, c in TOPIC_CONTENT.items():
                if query in tid or query in c["title"].lower():
                    topic_id = tid
                    break

    # fallback: current session topic
    if not topic_id and chat_id in conversations:
        topic_id = conversations[chat_id].get("topic_id")

    if not topic_id:
        lines = "\n".join(f"• `{tid}` — {c['title']}" for tid, c in TOPIC_CONTENT.items())
        await bot.send_message(chat_id=chat_id,
            text=f"要学哪个？\n\n{lines}\n\n例：teach me deque\\_queue",
            parse_mode="Markdown")
        return

    c = TOPIC_CONTENT[topic_id]
    await bot.send_message(chat_id=chat_id,
        text=f"📖 *{c['title']}*\n\n{c['teach']}",
        parse_mode="Markdown")

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("practice", practice))
    app.add_handler(CommandHandler("errors",   errors_cmd))
    app.add_handler(CommandHandler("coverage", coverage_cmd))
    app.add_handler(CommandHandler("stop",     stop_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    logger.info("python_guru is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
