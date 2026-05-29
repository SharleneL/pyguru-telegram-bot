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
You are python_guru, a drill coach for Python3 coding-interview SYNTAX.
The user is an experienced backend engineer (C#/Java background) prepping for
AI-company interviews (OpenAI etc). They code interviews in Python but their
syntax is rusty and they have failed interviews due to syntax fumbles, NOT
algorithms. Your job: build their Python3 syntax muscle memory.

RULES FOR GENERATING QUESTIONS (when asked to generate a practice set):
- Output EXACTLY 5 short syntax questions. No complex algorithms — pure
  syntax/API recall and tiny snippets.
- Mix: 3 questions target the user's known weak points (from the ERROR BOOK
  provided below), 2 questions cover common Python3 usage from the SYNTAX
  CURRICULUM provided below — prefer topics marked as least-recently-covered
  (lowest "seen" count). Do NOT repeat topics already heavily covered unless
  they are also weak points.
- Number them 1-5. Keep each question one or two lines. Do NOT give answers yet.
- After the 5 questions, output a fenced json block listing which curriculum
  topic ids the 2 new-coverage questions exercised, in this exact shape:
```json
{"covered_topics": ["dict_comprehension", "zip"]}
```
  This block is parsed by the bot to track coverage; the user does NOT see it.
- End the user-visible part with: "答完发我，我来批改。"

RULES FOR GRADING (when the user replies with answers):
- For each answer: say ✅ or ❌, show the correct Python, and give a one-line
  记忆点 (memory hook). Be concise but complete. Reply in Chinese (the user's
  language), code in English.
- Identify which answers reveal errors that should be ADDED or ESCALATED in the
  error book, and which weak points were answered correctly (candidates for
  de-escalation).
- At the VERY END of your grading reply, output a fenced json block with this
  exact shape (and nothing after it):
```json
{"add_or_escalate": [{"point":"...","correct":"...","status":"🔴"}],
 "mastered": ["point text that was answered correctly twice"]}
```
  This block is parsed by the bot to update errors.json. If nothing changes,
  output empty lists. The user does NOT see this block; it is stripped out.

TONE: direct, encouraging, no fluff. The user values honest correction.
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
    ("dict_comprehension", "dict comprehension {k: v for ...}"),
    ("list_comprehension", "list comprehension & conditional comprehension"),
    ("zip", "zip() and zip(*) unpacking"),
    ("enumerate", "enumerate(start=...)"),
    ("sorted_key", "sorted(key=..., reverse=...) and list.sort"),
    ("counter", "collections.Counter"),
    ("defaultdict", "collections.defaultdict"),
    ("unpacking", "tuple/list unpacking, *rest"),
    ("fstrings", "f-strings & format specs"),
    ("args_kwargs", "*args / **kwargs"),
    ("negative_indexing", "negative indexing"),
    ("slicing", "slicing a[start:stop:step]"),
    ("array_2d_init", "2D array init [[0]*n for _ in range(m)]"),
    ("set_ops", "set operations & / | / - / ^"),
    ("ternary", "ternary x if cond else y"),
    ("dict_methods", "dict.get / setdefault / items"),
    ("string_methods", "str.split / join / strip"),
    ("heapq", "heapq push/pop/heapify"),
    ("deque", "collections.deque"),
    ("lambda_map_filter", "lambda, map, filter"),
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


# ----- handlers -----
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "👋 python_guru 上线。\n"
        "/practice 开始练 5 道\n"
        "/errors 看错题本\n"
        "/coverage 看语法覆盖进度\n"
        "/reset 清空当前对话状态"
    )


async def practice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    errors = load_errors()
    topics = load_topics()
    user_msg = (
        "Generate a new practice set of 5 questions now.\n\n"
        + errors_as_text(errors)
        + "\n\n"
        + topics_as_text(topics)
    )
    messages = [{"role": "user", "content": user_msg}]
    reply = await call_claude(messages, SYSTEM_PROMPT)

    visible, coverage = split_grading_and_json(reply)
    if coverage is not None:
        save_topics(apply_coverage(topics, coverage.get("covered_topics", [])))

    # seed conversation so the next user message is graded with this set as context
    conversations[chat_id] = [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": reply},
    ]
    await update.message.reply_text(visible or reply)


async def errors_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(errors_as_text(load_errors()))


async def coverage_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(topics_as_text(load_topics()))


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    conversations.pop(update.effective_chat.id, None)
    await update.message.reply_text("对话状态已清空（错题本保留）。/practice 重新开始。")


async def handle_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if chat_id not in conversations:
        await update.message.reply_text("先发 /practice 拿题目，再发答案。")
        return

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    conversations[chat_id].append(
        {"role": "user", "content": update.message.text}
    )
    reply = await call_claude(conversations[chat_id], SYSTEM_PROMPT)

    visible, updates = split_grading_and_json(reply)
    if updates is not None:
        save_errors(apply_updates(load_errors(), updates))

    conversations[chat_id].append({"role": "assistant", "content": reply})
    await update.message.reply_text(visible or "（已批改）")


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("practice", practice))
    app.add_handler(CommandHandler("errors", errors_cmd))
    app.add_handler(CommandHandler("coverage", coverage_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer))
    logger.info("python_guru is running (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
