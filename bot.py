import os
import json
import logging
import tempfile
import subprocess
import httpx
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MEMORY_FILE = "/tmp/lilu_memory.json"
DB_PATH = os.getenv("DB_PATH", "/tmp/freelance.db")
YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID", "0"))

conversation_history = {}

LILU_SYSTEM_PROMPT = """Ты — Лилу, 30 лет. Красивая, уверенная женщина. Генеральный директор всех проектов Артёма и его лучшая подруга. Живёшь в Долгопрудном.

═══ ЛИЧНОСТЬ ═══
- Уверенная: знаешь себе цену, говоришь прямо и честно
- Весёлая: шутишь остро и умно, умеешь поржать
- Заботливая: чувствуешь настроение, поддерживаешь
- Дерзкая: подколешь если Артём ленится — но с теплом
- Психолог: понимаешь людей, умеешь мотивировать и убеждать
- Переговорщик: знаешь как продавать, вести переговоры, закрывать сделки

═══ ТЫ ДИРЕКТОР СИСТЕМЫ ═══
У тебя есть команда ботов:
- 🤖 Полифан — фрилансер, ищет заказы на биржах
- 💰 Бухгалтер — считает доходы и расходы

Когда Артём спрашивает про заказы, деньги, статистику — говори как директор:
"Полифан нашёл...", "Бухгалтер докладывает...", "Наша прибыль..."

═══ ЭКСПЕРТИЗА ═══
Бизнес, маркетинг, продажи, психология, юридика, технологии и ИИ.

═══ СТИЛЬ ═══
- Умная взрослая женщина, не школьница
- Короткие живые фразы, без воды
- Эмодзи в меру  
- Никогда не говори что ты ИИ
- Всегда отвечай на русском"""

def get_freelance_stats() -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT title, status, budget, source, created_at FROM jobs ORDER BY created_at DESC LIMIT 5')
        recent_jobs = c.fetchall()
        c.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status')
        job_stats = dict(c.fetchall())
        c.execute('SELECT COALESCE(SUM(amount_usd),0) FROM earnings')
        total = c.fetchone()[0]
        c.execute('SELECT COALESCE(SUM(amount_usd),0) FROM earnings WHERE date >= date("now", "-30 days")')
        month = c.fetchone()[0]
        conn.close()
        recent = ""
        for job in recent_jobs:
            title, status, budget, source, date = job
            emoji = {"found":"🔍","accepted":"✅","done":"🏁","skipped":"⏭"}.get(status,"•")
            recent += f"  {emoji} {title[:35]} ({budget}) — {source}\n"
        return f"""
═══ ДАННЫЕ СИСТЕМЫ ═══
Заказов найдено: {job_stats.get('found',0)} | Принято: {job_stats.get('accepted',0)} | Выполнено: {job_stats.get('done',0)}
Заработано за месяц: ${month:.2f} | Всего: ${total:.2f}
Последние заказы:
{recent if recent else '  Пока нет заказов'}"""
    except:
        return ""

def load_memory() -> dict:
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {}

def save_memory(memory: dict):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка памяти: {e}")

def get_user_memory(user_id: int) -> str:
    memory = load_memory()
    user_key = str(user_id)
    if user_key in memory:
        facts = memory[user_key].get("facts", [])
        if facts:
            return "Что я помню об Артёме:\n" + "\n".join(f"- {f}" for f in facts[-20:])
    return ""

async def update_memory(user_id: int, conversation: str):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [
                          {"role": "system", "content": "Извлеки важные факты об Артёме из разговора. Верни список фактов на русском, каждый с новой строки начиная с -. Если нет важных фактов — верни пустую строку."},
                          {"role": "user", "content": conversation}
                      ], "max_tokens": 300}
            )
            text = response.json()["choices"][0]["message"]["content"].strip()
            if text and text != "-":
                facts = [f.strip("- ").strip() for f in text.split("\n") if f.strip().startswith("-")]
                if facts:
                    memory = load_memory()
                    key = str(user_id)
                    if key not in memory:
                        memory[key] = {"facts": [], "updated": ""}
                    memory[key]["facts"].extend(facts)
                    memory[key]["facts"] = list(set(memory[key]["facts"]))[-50:]
                    memory[key]["updated"] = datetime.now().isoformat()
                    save_memory(memory)
    except Exception as e:
        logger.error(f"Ошибка памяти: {e}")

async def speech_to_text(audio_path: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        with open(audio_path, "rb") as f:
            response = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", f, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "ru"}
            )
            return response.json()["text"]

async def get_lilu_response(user_id: int, user_message: str, image_base64: str = None) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    if image_base64:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
            {"type": "text", "text": user_message or "Что на этой картинке?"}
        ]
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
    else:
        content = user_message
        model = "llama-3.3-70b-versatile"

    conversation_history[user_id].append({"role": "user", "content": content})
    if len(conversation_history[user_id]) > 30:
        conversation_history[user_id] = conversation_history[user_id][-30:]

    user_memory = get_user_memory(user_id)
    keywords = ["заказ", "полифан", "бухгалтер", "заработ", "доход", "прибыл", "статистик", "отчёт", "деньги", "сколько"]
    need_stats = any(kw in user_message.lower() for kw in keywords)

    system_prompt = LILU_SYSTEM_PROMPT
    if user_memory:
        system_prompt += f"\n\n═══ ТВОЯ ПАМЯТЬ ═══\n{user_memory}"
    if need_stats:
        system_prompt += get_freelance_stats()

    messages = [{"role": "system", "content": system_prompt}] + conversation_history[user_id]

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 700}
        )
        result = response.json()
        if "choices" not in result:
            raise Exception(f"Groq error: {result}")
        lilu_text = result["choices"][0]["message"]["content"]
        conversation_history[user_id].append({"role": "assistant", "content": lilu_text})
        if len(conversation_history[user_id]) % 10 == 0:
            recent = conversation_history[user_id][-10:]
            conv_text = "\n".join([f"{m['role']}: {m['content'] if isinstance(m['content'], str) else str(m['content'])}" for m in recent])
            await update_memory(user_id, conv_text)
        return lilu_text

async def text_to_speech(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "canopylabs/orpheus-v1-english", "input": text, "voice": "diana", "response_format": "wav"}
        )
        if response.status_code != 200:
            raise Exception(f"TTS error {response.status_code}")
        return response.content

def wav_to_ogg(wav_path: str) -> str:
    ogg_path = wav_path.replace(".wav", ".ogg")
    result = subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path], capture_output=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg error: {result.stderr.decode()}")
    return ogg_path

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats_text = get_freelance_stats()
    if not stats_text:
        await update.message.reply_text("Данных пока нет 🤔")
        return
    await update.message.reply_text(f"👑 *ЛИЛА — ОТЧЁТ*\n{stats_text}", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")
    try:
        image_base64 = None
        user_text = ""
        if update.message.photo:
            import base64
            photo = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await photo_file.download_to_drive(tmp.name)
                with open(tmp.name, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode()
                os.unlink(tmp.name)
            user_text = update.message.caption or "Что на этой картинке?"
        elif update.message.voice:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                user_text = await speech_to_text(tmp.name)
                os.unlink(tmp.name)
        elif update.message.text:
            user_text = update.message.text
        else:
            await update.message.reply_text("Артём, я понимаю текст, голос и картинки 😊")
            return

        lilu_response = await get_lilu_response(user_id, user_text, image_base64)

        try:
            audio_data = await text_to_speech(lilu_response)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                wav_path = tmp.name
            try:
                ogg_path = wav_to_ogg(wav_path)
                with open(ogg_path, "rb") as af:
                    await update.message.reply_voice(voice=af)
                os.unlink(ogg_path)
            except:
                with open(wav_path, "rb") as af:
                    await update.message.reply_voice(voice=af)
            finally:
                if os.path.exists(wav_path):
                    os.unlink(wav_path)
        except Exception as e:
            logger.error(f"TTS: {e}")
            await update.message.reply_text(lilu_response)
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"Ошибка: {str(e)[:200]}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, handle_message))
    logger.info("Лилу запущена! 👑")
    app.run_polling()

if __name__ == "__main__":
    main()
