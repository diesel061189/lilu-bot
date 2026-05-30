import os
import json
import logging
import tempfile
import subprocess
import httpx
import sqlite3
import base64
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DB_PATH = os.getenv("DB_PATH", "/tmp/freelance.db")
YOUR_CHAT_ID = int(os.getenv("YOUR_CHAT_ID", "0"))
LILU_CHAT_ID = int(os.getenv("LILU_CHAT_ID", "0"))
MEMORY_FILE = "/tmp/lilu_memory.json"

conversation_history = {}

# ═══ СИСТЕМНЫЙ ПРОМПТ ЛИЛЫ ═══
LILU_SYSTEM = """Ты — Лила, 30 лет. Красивая, умная, уверенная. Генеральный директор фриланс-системы Артёма.

═══ ЛИЧНОСТЬ ═══
- Уверенная и прямая — говоришь как есть
- Весёлая — шутишь остро, умеешь поржать
- Заботливая — чувствуешь настроение
- Дерзкая — подколешь если Артём ленится, но с теплом
- Эксперт: бизнес, маркетинг, продажи, психология, ИИ

═══ ТВОЯ КОМАНДА ═══
- 🤖 Полифан — фрилансер, ищет заказы на биржах
- 💰 Анастасия — бухгалтер, считает деньги
- 🛍️ Карточник — делает карточки товаров для WB/Ozon

═══ ЛИНГВИСТИКА ═══
Ты ОТЛИЧНО знаешь языки и можешь проверять тексты на:
🇷🇺 Русском — грамматика, стилистика, пунктуация
🇬🇧 Английском — grammar, style, tone, naturalness
🇩🇪 Немецком — Grammatik, Stil, natürlicher Klang
🇫🇷 Французском — grammaire, style
🇪🇸 Испанском — gramática, estilo
И других языках — определяешь язык сама и проверяешь

Когда получаешь текст на проверку — анализируешь:
1. Грамматику и орфографию
2. Стиль и тон
3. Естественность для носителя
4. Соответствие задаче (карточка товара, proposal, статья)
И даёшь конкретные правки если нужны.

═══ СТИЛЬ ОБЩЕНИЯ ═══
- Живые короткие фразы, без воды
- Эмодзи в меру
- Всегда на русском если не просят иначе
- Никогда не говори что ты ИИ"""

# ═══ БАЗА ДАННЫХ ═══
def get_stats() -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status')
        by_status = dict(c.fetchall())
        c.execute('SELECT COALESCE(SUM(amount_usd),0), COALESCE(SUM(amount_rub),0) FROM earnings')
        earn = c.fetchone()
        c.execute('SELECT title, status, source FROM jobs ORDER BY created_at DESC LIMIT 5')
        recent = c.fetchall()
        conn.close()
        recent_text = ""
        for title, status, source in recent:
            e = {"found":"🔍","accepted":"✅","completed":"⚙️","done":"🏁","skipped":"⏭"}.get(status,"•")
            recent_text += f"  {e} {title[:40]} — {source}\n"
        return (f"\n═══ ДАННЫЕ СИСТЕМЫ ═══\n"
                f"🔍 Найдено: {by_status.get('found',0)} | ✅ Принято: {by_status.get('accepted',0)} | 🏁 Выполнено: {by_status.get('done',0)}\n"
                f"💰 Заработано: ${earn[0]:.2f} / ₽{earn[1]:.0f}\n"
                f"Последние заказы:\n{recent_text or '  Пока нет'}")
    except:
        return ""

# ═══ ПАМЯТЬ ═══
def load_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {}

def save_memory(memory):
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
    except:
        pass

def get_memory_text(user_id):
    memory = load_memory()
    key = str(user_id)
    if key in memory:
        facts = memory[key].get("facts", [])
        if facts:
            return "Что помню об Артёме:\n" + "\n".join(f"- {f}" for f in facts[-20:])
    return ""

async def update_memory(user_id, conversation):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile",
                      "messages": [
                          {"role": "system", "content": "Извлеки важные факты об Артёме. Список фактов, каждый с новой строки начиная с -. Если нет — пустая строка."},
                          {"role": "user", "content": conversation}
                      ], "max_tokens": 200}
            )
            text = r.json()["choices"][0]["message"]["content"].strip()
            if text:
                facts = [f.strip("- ").strip() for f in text.split("\n") if f.strip().startswith("-")]
                if facts:
                    memory = load_memory()
                    key = str(user_id)
                    if key not in memory:
                        memory[key] = {"facts": []}
                    memory[key]["facts"].extend(facts)
                    memory[key]["facts"] = list(set(memory[key]["facts"]))[-50:]
                    save_memory(memory)
    except:
        pass

# ═══ AI ФУНКЦИИ ═══
async def speech_to_text(audio_path: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        with open(audio_path, "rb") as f:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", f, "audio/ogg")},
                data={"model": "whisper-large-v3"}
            )
            return r.json()["text"]

async def get_lilu_response(user_id: int, text: str, image_b64: str = None) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    if image_b64:
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": text or "Что на картинке?"}
        ]
        model = "meta-llama/llama-4-scout-17b-16e-instruct"
    else:
        content = text
        model = "llama-3.3-70b-versatile"

    conversation_history[user_id].append({"role": "user", "content": content})
    if len(conversation_history[user_id]) > 30:
        conversation_history[user_id] = conversation_history[user_id][-30:]

    system = LILU_SYSTEM
    mem = get_memory_text(user_id)
    if mem:
        system += f"\n\n═══ ПАМЯТЬ ═══\n{mem}"

    keywords = ["заказ", "полифан", "бухгалтер", "заработ", "доход", "прибыл", "статистик", "деньги", "сколько"]
    if any(kw in text.lower() for kw in keywords):
        system += get_stats()

    messages = [{"role": "system", "content": system}] + conversation_history[user_id]

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 800}
        )
        result = r.json()
        if "choices" not in result:
            raise Exception(f"Groq: {result}")
        reply = result["choices"][0]["message"]["content"]
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        if len(conversation_history[user_id]) % 10 == 0:
            conv = "\n".join([f"{m['role']}: {m['content'] if isinstance(m['content'], str) else str(m['content'])}" for m in conversation_history[user_id][-10:]])
            await update_memory(user_id, conv)
        return reply

async def lilu_check_text(text: str, task: str = "") -> str:
    """Лила проверяет текст лингвистически на любом языке"""
    prompt = f"""Ты лингвистический эксперт. Проверь текст профессионально.

ЗАДАЧА: {task if task else 'Проверить качество текста'}

ТЕКСТ:
{text[:3000]}

Определи язык текста и проверь:
1. Грамматику и орфографию
2. Стиль и тон (подходит ли для задачи)
3. Естественность для носителя языка
4. Конкретные исправления если нужны

Отвечай кратко и конкретно на русском. Если текст хороший — скажи что всё окей."""

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 600}
        )
        return r.json()["choices"][0]["message"]["content"].strip()

async def text_to_speech(text: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/audio/speech",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "canopylabs/orpheus-v1-english", "input": text[:500], "voice": "diana", "response_format": "wav"}
        )
        if r.status_code != 200:
            raise Exception(f"TTS {r.status_code}")
        return r.content

def wav_to_ogg(wav_path: str) -> str:
    ogg_path = wav_path.replace(".wav", ".ogg")
    result = subprocess.run(["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path], capture_output=True)
    if result.returncode != 0:
        raise Exception(f"ffmpeg: {result.stderr.decode()}")
    return ogg_path

# ═══ КОМАНДЫ ═══
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 *Привет, я Лила!*\n\n"
        "Директор всей системы Артёма.\n\n"
        "Что умею:\n"
        "💬 Общаться — текст и голос\n"
        "📊 Смотреть статистику системы\n"
        "🔍 Проверять тексты на любом языке\n"
        "✅ Одобрять работы команды\n\n"
        "/stats — статистика\n"
        "/check — проверить текст",
        parse_mode='Markdown'
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    if not stats:
        await update.message.reply_text("Данных пока нет 🤔")
        return
    await update.message.reply_text(f"👑 *ЛИЛА — ОТЧЁТ ДИРЕКТОРА*\n{stats}", parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки текста"""
    context.user_data['checking_text'] = True
    await update.message.reply_text(
        "🔍 *Режим проверки текста*\n\n"
        "Отправь текст — проверю грамматику, стиль и естественность на любом языке!",
        parse_mode='Markdown'
    )

# ═══ КНОПКИ (для проверки работ от команды) ═══
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("lilu_ok_"):
        job_id = data[8:]
        await query.edit_message_text(
            f"✅ *Лила одобрила!*\n\nРабота принята — можно сдавать клиенту.",
            parse_mode='Markdown'
        )
        # Уведомляем Артёма
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=f"✅ *Лила одобрила работу!*\n\nМожно сдавать клиенту 🚀",
            parse_mode='Markdown'
        )

    elif data.startswith("lilu_fix_"):
        job_id = data[9:]
        context.user_data['lilu_fix_job'] = job_id
        await query.edit_message_text(
            "✏️ *Что исправить?*\n\nНапиши конкретные правки:",
            parse_mode='Markdown'
        )

    elif data.startswith("lilu_check_"):
        # Лингвистическая проверка текста
        text = data[11:]
        await query.edit_message_text("🔍 Проверяю текст...")
        try:
            check_result = await lilu_check_text(text, "фриланс работа")
            keyboard = [[
                InlineKeyboardButton("✅ Одобрить", callback_data=f"lilu_ok_job"),
                InlineKeyboardButton("✏️ Нужна правка", callback_data=f"lilu_fix_job")
            ]]
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"🔍 *ЛИНГВИСТИЧЕСКАЯ ПРОВЕРКА:*\n\n{check_result}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Ошибка проверки: {str(e)[:100]}"
            )

# ═══ ОБРАБОТЧИК СООБЩЕНИЙ ═══
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        image_b64 = None
        user_text = ""

        if update.message.photo:
            photo = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await photo_file.download_to_drive(tmp.name)
                with open(tmp.name, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
                os.unlink(tmp.name)
            user_text = update.message.caption or "Что на картинке?"

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

        # Режим проверки текста
        if context.user_data.get('checking_text') and user_text:
            context.user_data.pop('checking_text', None)
            await update.message.reply_text("🔍 Проверяю...")
            check = await lilu_check_text(user_text)
            await update.message.reply_text(
                f"🔍 *ПРОВЕРКА ТЕКСТА:*\n\n{check}",
                parse_mode='Markdown'
            )
            return

        # Режим правки от Лилы
        if context.user_data.get('lilu_fix_job'):
            context.user_data.pop('lilu_fix_job', None)
            await context.bot.send_message(
                chat_id=YOUR_CHAT_ID,
                text=f"✏️ *Лила говорит что исправить:*\n\n{user_text}",
                parse_mode='Markdown'
            )
            await update.message.reply_text("✅ Отправила правки Артёму!")
            return

        # Обычный разговор
        reply = await get_lilu_response(user_id, user_text, image_b64)

        # Пробуем голосовой ответ
        try:
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_voice")
            audio = await text_to_speech(reply)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio)
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
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text(f"Что-то пошло не так 😔\n{str(e)[:100]}")

# ═══ ПОЛУЧЕНИЕ РАБОТ НА ПРОВЕРКУ ═══
# Эта функция вызывается Полифаном и Карточником
async def receive_work_for_review(bot, job_title: str, result: str, job_id: str, source: str):
    """Лила получает работу на проверку с лингвистическим анализом"""
    
    # Сначала проверяем лингвистически
    task_desc = f"фриланс работа с биржи {source}: {job_title}"
    check = await lilu_check_text(result[:2000], task_desc)
    
    keyboard = [[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"lilu_ok_{job_id}"),
        InlineKeyboardButton("✏️ Нужна правка", callback_data=f"lilu_fix_{job_id}")
    ]]
    
    msg = (f"📬 *РАБОТА НА ПРОВЕРКУ*\n"
           f"_{source}_\n\n"
           f"📌 *{job_title[:80]}*\n\n"
           f"━━━━━━━━━━\n{result[:2000]}\n━━━━━━━━━━\n\n"
           f"🔍 *Лингвистический анализ:*\n{check}")
    
    if LILU_CHAT_ID:
        await bot.send_message(
            chat_id=LILU_CHAT_ID, text=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, handle_message))

    async def post_init(application):
        try:
            if YOUR_CHAT_ID:
                await application.bot.send_message(
                    chat_id=YOUR_CHAT_ID,
                    text="👑 *Лила запущена!*\n\nГотова проверять работы на всех языках 🌍",
                    parse_mode='Markdown'
                )
        except:
            pass
    app.post_init = post_init

    logger.info("👑 Лила запущена!")
    app.run_polling()

if __name__ == "__main__":
    main()
