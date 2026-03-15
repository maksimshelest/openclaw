import os
import re
import logging
import anthropic
import httpx
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

user_histories: dict[int, list] = {}

CODE_KEYWORDS = re.compile(
    r"\b(код|програм|функці|клас|скрипт|баг|дебаг|алгоритм|архітектур|рефактор|реалізу|deploy|докер|docker"
    r"|code|program|function|class|script|bug|debug|algorithm|architect|refactor|implement|fix|error|exception)\b",
    re.IGNORECASE,
)
TASK_KEYWORDS = re.compile(
    r"\b(поясни|розкажи|як працює|що таке|порівняй|проаналізуй|напиши|зроби|допоможи|знайди|переклади|склади"
    r"|explain|how does|what is|compare|analyze|write|create|help|find|translate)\b",
    re.IGNORECASE,
)

def pick_provider(text: str) -> tuple[str, str]:
    """Returns (provider, label)"""
    if CODE_KEYWORDS.search(text) or len(text) > 300:
        return "claude", "🤖 Claude"
    if TASK_KEYWORDS.search(text) or len(text) > 80:
        return "gemini", "♊ Gemini"
    return "groq", "⚡ Groq"

def ask_claude(messages: list) -> str:
    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=messages,
    )
    return response.content[0].text

def ask_groq(messages: list) -> str:
    response = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={"model": "llama-3.3-70b-versatile", "messages": messages, "max_tokens": 1024},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def ask_gemini(messages: list) -> str:
    # Convert to Gemini format
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
        json={"contents": contents},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["candidates"][0]["content"]["parts"][0]["text"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "Привіт! Я OpenClaw 🦾\n\n"
        "⚡ Groq (Llama) — чат\n"
        "♊ Gemini — питання та аналіз\n"
        "🤖 Claude — код та програмування\n\n"
        "Модель обирається автоматично!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})
    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    provider, label = pick_provider(text)
    logger.info(f"user={user_id} provider={provider} len={len(text)}")

    try:
        if provider == "claude":
            reply = ask_claude(user_histories[user_id])
        elif provider == "gemini":
            reply = ask_gemini(user_histories[user_id])
        else:
            reply = ask_groq(user_histories[user_id])

        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(f"{label}\n\n{reply}")
    except Exception as e:
        logger.error(f"Error [{provider}]: {e}")
        await update.message.reply_text("Сталася помилка. Спробуй ще раз.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
