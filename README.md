# python_guru 🐍

A Telegram bot that drills you on Python3 interview syntax. Pulls questions from
your accumulated error book, grades your answers, and updates the book — all over
Telegram so you can practice in spare moments without opening a new Claude session.

## Commands
- `/practice` — get 5 syntax questions (3 weak-point + 2 from the syntax curriculum)
- (reply with answers) — bot grades + updates `errors.json`
- `/errors` — view your error book
- `/coverage` — view the high-frequency syntax curriculum + how often each topic has been drilled
- `/reset` — clear current conversation state (keeps error book)

## State files
- `errors.json` — your accumulated error book (weak points + mastered)
- `syntax_topics.json` — the high-frequency Python3 syntax curriculum and per-topic coverage counts. The 2 "new coverage" questions each round prefer the least-drilled topics. Edit `DEFAULT_TOPICS` in `bot.py` to change the curriculum.

---

## Setup (one-time)

### 1. Create the Telegram bot
1. Open Telegram, message **@BotFather**
2. Send `/newbot`, follow prompts, pick a name + username (e.g. `my_python_guru_bot`)
3. Copy the **bot token** it gives you (looks like `12345:ABC-xyz...`)

### 2. Get your Anthropic API key
- https://console.anthropic.com → API Keys → create one. Copy it.

### 3. (Optional but recommended) Lock the bot to just you
- Message your new bot anything, then visit
  `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
- Find `"chat":{"id": NNNN}` — that number is your `ALLOWED_CHAT_ID`.

---

## Run it

### Option A — locally (quickest test)
```bash
cd python_guru
pip install -r requirements.txt
export TELEGRAM_TOKEN="your-telegram-token"
export ANTHROPIC_API_KEY="your-anthropic-key"
export ALLOWED_CHAT_ID="your-chat-id"   # optional
python bot.py
```
Then message your bot `/practice` in Telegram. (Bot only runs while this process
is alive — fine for testing, not for 24/7.)

### Option B — host on Railway (24/7, auto-deploy from GitHub)
1. Push this folder to a GitHub repo.
2. https://railway.app → New Project → Deploy from GitHub repo → pick it.
3. **Add a persistent Volume** (this is what keeps your error book across deploys):
   - Service → **Variables/Settings → Volumes → New Volume**
   - Mount path: `/data`
4. In the service **Variables** tab, add:
   - `TELEGRAM_TOKEN`
   - `ANTHROPIC_API_KEY`
   - `ALLOWED_CHAT_ID` (optional, recommended)
   - `ERRORS_FILE=/data/errors.json`
   - `TOPICS_FILE=/data/syntax_topics.json`
5. Railway auto-installs `requirements.txt` and runs `python bot.py` (see `railway.json` / `Procfile`).
6. Every `git push` redeploys automatically — and `/data` survives each redeploy, so your
   error book and coverage counts persist.

> ✅ **Persistence:** because `ERRORS_FILE` and `TOPICS_FILE` point inside the `/data`
> volume, your error book and syntax coverage are NOT wiped when you redeploy or when
> I push a code change. The first run auto-creates `syntax_topics.json` from the
> built-in curriculum.

### Updating the bot later (via Claude Code)
Tell Claude what to change → it edits the code here → `git push` → Railway redeploys
automatically within ~1 min. Your `/data` state is untouched.

---

## Tuning quality
All the "smart" behavior lives in `SYSTEM_PROMPT` in `bot.py` — question mix,
grading style, error-book update rules. Edit that string to change how it teaches.
The model is set to `claude-opus-4-5`; you can drop to a cheaper/faster model by
changing `MODEL`.
