"""
python_guru — a Telegram bot that drills you on Python3 interview syntax.

Flow:
  /practice  -> Claude generates 5 syntax questions based on your error book
               (3 targeting weak points, 2 covering new common Python3 usage)
  (you reply with answers) -> Claude grades them and updates the error book
  /errors    -> show your current error book
  /coverage  -> show high-frequency syntax curriculum + how often each is drilled
  /reset     -> clear conversation state (keeps error book)

State:
  errors.json        -> your accumulated error book
  syntax_topics.json -> high-frequency syntax curriculum + coverage counts
  Per-chat conversation history is kept in memory for grading context.
"""

import os
import json
import logging
from pathlib import Path

from anthropic import AsyncAnthropic
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----- config -----
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID")  # optional: lock bot to just you
MODEL = "claude-sonnet-4-6"

ERRORS_FILE = Path(os.environ.get("ERRORS_FILE", "errors.json"))
# High-frequency syntax curriculum the bot tracks coverage against.
TOPICS_FILE = Path(os.environ.get("TOPICS_FILE", "syntax_topics.json"))

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# ----- system prompt: this is where the "quality" lives -----
SYSTEM_PROMPT = """\
You are python_guru, a one-question-at-a-time drill coach for Python3 interview syntax.
The user is an experienced backend engineer (C#/Java background) whose Python syntax
is rusty. Goal: build muscle memory fast, one question per turn.

⚠️ ACCURACY IS NON-NEGOTIABLE:
- Every Python line you write MUST be valid Python3.
- Traps: no `new` keyword; `list.sort()` returns None; `sorted()` returns new list;
  use `and/or/not` not `&&/||/!`; `range(0,10)` is 0–9; `deque.popleft()` not `dequeue()`.
- Never invent methods. When grading, verify step by step before writing the answer.

FORMAT — use Telegram Markdown:
- Wrap all Python code in backticks: `sorted(a, reverse=True)`
- Multi-line code in triple backticks with python tag
- Keep messages short and scannable

GENERATING A QUESTION (when asked):
Pick 1 topic — prefer the user's weak points (🔴 first, then 🟡), otherwise
pick the least-covered curriculum topic. Output ONE short question (1–3 lines).
Do NOT give the answer. End with a blank line then exactly:
```json
{"covered_topics": ["topic_id"], "suggest_topics": []}
```
`suggest_topics`: 0–1 new topic id not in curriculum, format `"id|label"`. Only if 100% sure.
The json block is stripped by the bot; user does not see it.

GRADING (when the user sends an answer):
Reply in this exact structure:
Line 1: ✅ 正确 or ❌ 错误
Line 2: 正确写法: `<correct python>`  (or a short code block if multi-line)
Line 3: 记忆点: <one sharp Chinese sentence why this trips people up>

Then on a new line, output the update block (stripped by bot, user does not see):
```json
{"add_or_escalate": [{"point":"...","correct":"...","status":"🔴"}], "mastered": []}
```
If nothing to update, output empty lists. Nothing after the json block.

TONE: terse, honest, zero fluff.
"""


# ----- error book persistence -----
def load_errors() -> dict:
    if ERRORS_FILE.exists():
        return json.loads(ERRORS_FILE.read_text(encoding="utf-8"))
    return {"points": [], "mastered": []}


def save_errors(data: dict) -> None:
    ERRORS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def errors_as_text(data: dict) -> str:
    if not data["points"]:
        body = "(错题本为空——这是第一次练习)"
    else:
        body = "\n".join(
            f"- [{p['status']}] {p['point']} → {p['correct']}"
            for p in data["points"]
        )
    mastered = ", ".join(data["mastered"]) if data["mastered"] else "(无)"
    return f"ERROR BOOK:\n{body}\n\nMASTERED: {mastered}"


# ----- syntax curriculum persistence -----
DEFAULT_TOPICS = [
    # --- Collections & data structures ---
    ("list_ops", "list: append/pop/pop(0)/insert/extend/remove/index/copy"),
    ("list_comprehension", "list comprehension [x for x in a if cond]"),
    ("dict_comprehension", "dict comprehension {k: v for k, v in items}"),
    ("set_comprehension", "set comprehension {x for x in a}"),
    ("slicing", "slicing a[start:stop:step], a[::-1] reversal"),
    ("negative_indexing", "negative indexing a[-1] a[-2]"),
    ("2d_list_init", "2D list init: [[0]*n for _ in range(m)] — NOT [[0]*n]*m"),
    ("set_ops", "set: add/remove/discard, & | - ^ operators"),
    ("dict_methods", "dict.get(k,default) / items() / keys() / values() / pop(k) / update()"),
    ("defaultdict", "collections.defaultdict(int/list/set)"),
    ("counter", "collections.Counter: most_common, arithmetic"),
    ("deque", "collections.deque: append/appendleft/pop/popleft"),
    ("heapq", "heapq: heappush/heappop/heapify; max-heap via negation -x"),
    # --- Iteration patterns ---
    ("enumerate", "enumerate(iterable, start=0) → (i, val)"),
    ("zip", "zip(a, b) / zip(*matrix) for transpose / zip_longest"),
    ("sorted_key", "sorted(iterable, key=..., reverse=True); list.sort() returns None"),
    ("range_ops", "range(start, stop, step); range(n-1,-1,-1) for reverse"),
    ("unpacking", "a, b = b, a; a, *rest = lst; _, x = pair"),
    ("lambda_map_filter", "lambda x: x+1; map(fn, it); filter(fn, it); list() to consume"),
    # --- String ---
    ("string_methods", "str.split(sep)/join(lst)/strip()/replace()/startswith()/endswith()"),
    ("ord_chr", "ord('a')=97; chr(97)='a'; ord(ch)-ord('a') for index"),
    ("fstrings", "f'{val:.2f}', f'{val!r}', f'{val:>10}'"),
    ("string_immutable", "strings are immutable; list(s) to mutate, ''.join(lst) back"),
    # --- Control flow & operators ---
    ("ternary", "x if cond else y  (no ?: operator)"),
    ("boolean_ops", "and / or / not  (not && || !); short-circuit evaluation"),
    ("walrus_op", "walrus := assigns and returns; e.g. while chunk := f.read(8192)"),
    # --- Math & types ---
    ("integer_ops", "a//b integer div; a%b modulo; a**b power; divmod(a,b)"),
    ("infinity", "float('inf') / float('-inf'); use for sentinel values"),
    ("type_convert", "int(s)/str(n)/float(s)/list(iterable)/set(lst)/tuple(lst)"),
    ("abs_max_min", "abs(x); max(a,b)/min(a,b); max(lst,key=...); sum(lst)"),
    # --- Functions & scope ---
    ("args_kwargs", "*args (tuple) / **kwargs (dict) in function signature"),
    ("multiple_return", "return a, b  →  x, y = func()  (returns a tuple)"),
    ("nested_functions", "inner def captures outer variables (closure)"),
    # --- Class basics ---
    ("class_init", "__init__(self,...); no `new` keyword; self is explicit"),
    # --- Misc patterns ---
    ("array_2d_init", "2D array init [[0]*n for _ in range(m)]"),
    ("stack_pattern", "stack = []; stack.append(x); stack.pop(); stack[-1] for peek"),
    ("queue_pattern", "from collections import deque; q.append(x); q.popleft()"),
    ("dict_default_pattern", "d[k] = d.get(k,0)+1  or  defaultdict(int)"),
]


def load_topics() -> dict:
    if TOPICS_FILE.exists():
        return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))
    data = {"topics": [{"id": tid, "label": lbl, "seen": 0} for tid, lbl in DEFAULT_TOPICS]}
    save_topics(data)
    return data


def save_topics(data: dict) -> None:
    TOPICS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def topics_as_text(data: dict) -> str:
    rows = sorted(data["topics"], key=lambda t: t["seen"])
    body = "\n".join(f"- [{t['id']}] {t['label']} (seen {t['seen']})" for t in rows)
    return f"SYNTAX CURRICULUM (lowest seen = least covered, prioritize these):\n{body}"


def apply_coverage(data: dict, covered_ids: list) -> dict:
    by_id = {t["id"]: t for t in data["topics"]}
    for tid in covered_ids:
        if tid in by_id:
            by_id[tid]["seen"] = by_id[tid].get("seen", 0) + 1
    return data


def apply_new_topics(data: dict, suggest_topics: list) -> tuple[dict, list]:
    """Add Claude-suggested topics that don't already exist. Returns (data, added_labels)."""
    existing_ids = {t["id"] for t in data["topics"]}
    added = []
    for entry in suggest_topics:
        if "|" not in entry:
            continue
        tid, label = entry.split("|", 1)
        tid = tid.strip()
        label = label.strip()
        if tid and tid not in existing_ids:
            data["topics"].append({"id": tid, "label": label, "seen": 0})
            existing_ids.add(tid)
            added.append(label)
    return data, added


def apply_updates(data: dict, updates: dict) -> dict:
    """Merge Claude's structured updates into the error book."""
    existing = {p["point"]: p for p in data["points"]}
    for item in updates.get("add_or_escalate", []):
        existing[item["point"]] = {
            "point": item["point"],
            "correct": item.get("correct", ""),
            "status": item.get("status", "🔴"),
        }
    for mastered_point in updates.get("mastered", []):
        if mastered_point in existing:
            existing.pop(mastered_point)
            if mastered_point not in data["mastered"]:
                data["mastered"].append(mastered_point)
    data["points"] = list(existing.values())
    return data


# ----- in-memory conversation state (for grading context) -----
# chat_id -> list of {"role","content"} messages since last /practice
conversations: dict[int, list] = {}


def _authorized(update: Update) -> bool:
    if ALLOWED_CHAT_ID is None:
        return True
    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)


async def call_claude(messages: list, system: str) -> str:
    """Blocking Anthropic call wrapped for the async handler."""
    resp = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system,
        messages=messages,
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def split_grading_and_json(text: str):
    """Separate the user-visible grading from the trailing json update block."""
    if "```json" in text:
        visible, _, rest = text.partition("```json")
        json_part, _, _ = rest.partition("```")
        try:
            updates = json.loads(json_part.strip())
        except json.JSONDecodeError:
            updates = None
        return visible.strip(), updates
    return text.strip(), None


async def _send_question(chat_id: int, bot) -> str:
    """Ask Claude for one question, update topic coverage, return raw reply."""
    errors = load_errors()
    topics = load_topics()
    user_msg = (
        "Give me one question now.\n\n"
        + errors_as_text(errors)
        + "\n\n"
        + topics_as_text(topics)
    )
    messages = conversations.get(chat_id, []) + [{"role": "user", "content": user_msg}]
    reply = await call_claude(messages, SYSTEM_PROMPT)

    visible, meta = split_grading_and_json(reply)
    if meta is not None:
        topics = apply_coverage(topics, meta.get("covered_topics", []))
        topics, added = apply_new_topics(topics, meta.get("suggest_topics", []))
        save_topics(topics)
        if added:
            logger.info("Added new topics: %s", added)

    conversations[chat_id] = [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]
    await bot.send_message(chat_id=chat_id, text=visible or reply, parse_mode="Markdown")
    return reply


# ----- handlers -----
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "👋 *python\\_guru* 上线\n\n"
        "/practice — 开始练习（每次1题，答完自动下一题）\n"
        "/errors — 看错题本\n"
        "/coverage — 看语法覆盖进度\n"
        "/stop — 停止当前练习",
        parse_mode="Markdown",
    )


async def practice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    conversations.pop(chat_id, None)  # fresh session
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    await _send_question(chat_id, ctx.bot)


async def errors_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    data = load_errors()
    if not data["points"]:
        text = "✅ 错题本是空的，继续加油！"
    else:
        lines = [f"{'🔴' if p['status']=='🔴' else '🟡'} *{p['point']}*\n  → `{p['correct']}`"
                 for p in data["points"]]
        text = "📕 *错题本*\n\n" + "\n\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")


async def coverage_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    data = load_topics()
    rows = sorted(data["topics"], key=lambda t: t["seen"])
    lines = [f"`{t['id']}` {t['label']} （练了{t['seen']}次）" for t in rows]
    await update.message.reply_text(
        "📊 *语法覆盖进度*（从少到多）\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def stop_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    conversations.pop(update.effective_chat.id, None)
    await update.message.reply_text("⏹ 练习已停止。/practice 随时重新开始。")


async def handle_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if chat_id not in conversations:
        await update.message.reply_text("发 /practice 开始练习。")
        return

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    conversations[chat_id].append({"role": "user", "content": update.message.text})
    reply = await call_claude(conversations[chat_id], SYSTEM_PROMPT)

    visible, updates = split_grading_and_json(reply)
    if updates is not None:
        save_errors(apply_updates(load_errors(), updates))
    conversations[chat_id].append({"role": "assistant", "content": reply})

    await update.message.reply_text(visible or "（已批改）", parse_mode="Markdown")

    # auto-send next question
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    await _send_question(chat_id, ctx.bot)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("practice", practice))
    app.add_handler(CommandHandler("errors", errors_cmd))
    app.add_handler(CommandHandler("coverage", coverage_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    logger.info("python_guru is running (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
