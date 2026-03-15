import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

user_histories: dict[int, list] = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("Привіт! Я OpenClaw — бот на базі Claude AI. Напиши мені що-небудь!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": text})

    # Keep last 20 messages
    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            messages=user_histories[user_id],
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Сталася помилка. Спробуй ще раз.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
