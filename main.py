import os
import re
import base64
import logging
import tempfile
import httpx
from gtts import gTTS
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
import anthropic

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

user_histories: dict[int, list] = {}

OPUS_KEYWORDS = re.compile(
    r"\b(алгоритм|архітектур|оптимізац|рефактор|debug|дебаг|помилк|баг|складн|реалізу|напиши код|зроби систем"
    r"|algorithm|architect|optim|refactor|implement|complex|system design|debug)\b",
    re.IGNORECASE,
)
SONNET_KEYWORDS = re.compile(
    r"\b(поясни|розкажи|як працює|що таке|порівняй|проаналізуй|напиши|зроби|допоможи|знайди"
    r"|explain|how does|what is|compare|analyze|write|create|help|find)\b",
    re.IGNORECASE,
)

def pick_model(text: str) -> tuple[str, str]:
    if len(text) > 300 or OPUS_KEYWORDS.search(text):
        return "claude-opus-4-6", "🔴 Opus"
    if len(text) > 80 or SONNET_KEYWORDS.search(text):
        return "claude-sonnet-4-6", "🟡 Sonnet"
    return "claude-haiku-4-5-20251001", "🟢 Haiku"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "Привіт! Я OpenClaw — бот на базі Claude AI.\n\n"
        "🟢 Haiku — для чату\n"
        "🟡 Sonnet — для задач\n"
        "🔴 Opus — для складного коду\n"
        "🖼 Фото — аналізую зображення\n\n"
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

    model, label = pick_model(text)
    logger.info(f"user={user_id} model={model} len={len(text)}")

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=user_histories[user_id],
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(f"{label}\n\n{reply}")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Сталася помилка. Спробуй ще раз.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption or "Що на цьому фото? Опиши детально."

    if user_id not in user_histories:
        user_histories[user_id] = []

    # Download the highest quality photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Build message with image — always use Sonnet for vision
    model = "claude-sonnet-4-6"
    label = "🟡 Sonnet 🖼"

    image_message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": caption},
        ],
    }

    # For history we store text-only version
    history_message = {"role": "user", "content": f"[фото] {caption}"}
    user_histories[user_id].append(history_message)
    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    logger.info(f"user={user_id} model={model} photo+caption")

    try:
        # Send image directly (not via history to avoid storing large b64)
        messages_with_image = user_histories[user_id][:-1] + [image_message]
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=messages_with_image,
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(f"{label}\n\n{reply}")
    except Exception as e:
        logger.error(f"Error [photo]: {e}")
        await update.message.reply_text("Не вдалося обробити фото. Спробуй ще раз.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_histories:
        user_histories[user_id] = []

    # Download voice file
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)
    voice_bytes = await file.download_as_bytearray()

    await update.message.reply_text("🎤 Розпізнаю голос...")

    # Transcribe with Groq Whisper
    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("voice.ogg", bytes(voice_bytes), "audio/ogg")},
            data={"model": "whisper-large-v3", "response_format": "text"},
            timeout=30,
        )
        response.raise_for_status()
        text = response.text.strip()
    except Exception as e:
        logger.error(f"Whisper error: {e}")
        await update.message.reply_text("Не вдалося розпізнати голос. Спробуй ще раз.")
        return

    if not text:
        await update.message.reply_text("Не розчув. Спробуй ще раз.")
        return

    logger.info(f"user={user_id} transcribed: {text[:80]}")

    # Process transcribed text through Claude
    user_histories[user_id].append({"role": "user", "content": text})
    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    model, label = pick_model(text)

    try:
        claude_response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=user_histories[user_id],
        )
        reply = claude_response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})

        # Detect language for TTS (simple heuristic)
        lang = "uk" if re.search(r"[а-яіїєґА-ЯІЇЄҐ]", reply) else "en"

        # Generate voice response
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tts_path = f.name
        gTTS(text=reply, lang=lang).save(tts_path)

        await update.message.reply_text(f"🎤 _«{text}»_", parse_mode="Markdown")
        with open(tts_path, "rb") as audio:
            await update.message.reply_voice(voice=audio)
        os.unlink(tts_path)
    except Exception as e:
        logger.error(f"Error [voice→claude]: {e}")
        await update.message.reply_text("Помилка при відповіді. Спробуй ще раз.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
