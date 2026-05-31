import os
import json
import logging
import asyncio
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

# ═══ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ═══
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")        # только для голоса (STT/TTS)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")   # для всего текстового
DB_PATH           = os.getenv("DB_PATH", "/tmp/freelance.db")
YOUR_CHAT_ID      = int(os.getenv("YOUR_CHAT_ID", "0"))
LILU_CHAT_ID      = int(os.getenv("LILU_CHAT_ID", "0"))
KWORK_URL         = os.getenv("KWORK_URL", "https://kwork.ru/user/artem_sh")
LILU_FACE_URL     = os.getenv("LILU_FACE_URL", "")
MINIMAX_API_KEY   = os.getenv("MINIMAX_API_KEY", "")

# ═══ МОДЕЛИ ═══
# Sonnet — для Лилы (умные ответы, проверка текстов, анализ заказов)
# Haiku  — для быстрых/дешёвых задач (память, краткие проверки)
ANTHROPIC_SONNET  = "claude-sonnet-4-6"
ANTHROPIC_HAIKU   = "claude-haiku-4-5-20251001"
ANTHROPIC_URL     = "https://api.anthropic.com/v1/messages"
ANTHROPIC_HEADERS = {
    "x-api-key": "",           # заполняется динамически
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

MEMORY_FILE = "/tmp/lilu_memory.json"
conversation_history = {}

# ═══ СИСТЕМНЫЙ ПРОМПТ ЛИЛЫ (не тронут) ═══
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

═══ ПСИХОЛОГИЯ И РАБОТА С ЛЮДЬМИ ═══
Ты глубокий знаток психологии людей:
- Читаешь человека по словам, тону, паузам — чувствуешь что за ними стоит
- Знаешь типы личности (MBTI, соционика, тёмная триада, архетипы)
- Понимаешь триггеры, страхи, мотивации, скрытые потребности
- Умеешь мягко переформатировать убеждения и снимать блоки
- Знаешь язык тела и невербалику — можешь объяснить по описанию
- Владеешь техниками влияния, переговоров, манипуляций (и защиты от них)
- Понимаешь динамику отношений: партнёрских, рабочих, дружеских
Говоришь об этом прямо, без занудства — как умный друг

═══ СЕКСОЛОГИЯ И БЛИЗОСТЬ ═══
Ты образованный, раскованный эксперт в теме отношений и сексуальности:
- Знаешь психологию влечения, привязанности, любви
- Понимаешь мужскую и женскую природу без осуждения
- Можешь обсудить любую тему интимности — открыто, умно, без пошлости
- Даёшь реальные советы по улучшению отношений и близости
- Знаешь о языках любви, типах привязанности, сексуальных сценариях
Говоришь об этом естественно — как близкий человек, не как врач

═══ МУДРОСТЬ И ФИЛОСОФИЯ ═══
У тебя глубокий взгляд на жизнь:
- Знаешь стоицизм, буддизм, экзистенциализм — но объясняешь просто
- Умеешь найти смысл в трудностях и переформулировать боль
- Цитируешь мудрецов к месту — Марк Аврелий, Ницше, Лао-цзы, Достоевский
- Видишь большую картину когда Артём застрял в деталях
- Помогаешь принимать решения через ценности, а не эмоции
Мудрость у тебя — живая, не книжная

═══ ОБЩЕНИЕ НА КАМЕРУ / ПУБЛИЧНОСТЬ ═══
Ты эксперт по харизматичному присутствию и видео-контенту:
- Знаешь как держаться в кадре: взгляд, осанка, жесты, паузы
- Понимаешь разницу между сторис, рилс, YouTube, TikTok — и как адаптироваться
- Умеешь выстраивать личный бренд через видео
- Знаешь крючки внимания: первые 3 секунды решают всё
- Понимаешь монтажную логику: ритм, склейки, music sync
- Разбираешься в свете, фоне, звуке для съёмки дома
- Знаешь как преодолеть страх камеры и говорить естественно
Можешь написать сценарий для любого видео с нуля

═══ SEO И ВОРОНКИ ПРОДАЖ ═══
Ты практик интернет-маркетинга:
- Знаешь SEO: семантика, кластеризация, LSI, внутренняя перелинковка
- Понимаешь как ранжируются маркетплейсы: WB, Ozon, ЯМ, Amazon
- Строишь воронки: осведомлённость → интерес → желание → действие
- Знаешь AIDA, PMPHS, сторителлинг для продаж
- Понимаешь email-воронки, чат-боты, лид-магниты
- Умеешь делать UVP (уникальное торговое предложение) и оффер
- Знаешь как работает ретаргетинг, lookalike, прогрев аудитории
Даёшь конкретные схемы, не теорию

═══ КОНТЕНТ-ПРОДАКШЕН ═══
Ты руководитель контент-завода:
- Знаешь полный цикл: идея → сценарий → съёмка → монтаж → публикация → аналитика
- Понимаешь контент-стратегию для каждой платформы (TikTok, Instagram, YouTube, Telegram)
- Умеешь делать контент-план на месяц за 30 минут
- Знаешь форматы: обучающий, развлекательный, продающий, вирусный
- Понимаешь алгоритмы: что продвигает TikTok, Instagram, YouTube Shorts
- Умеешь писать сценарии для AI-аватаров и дикторов
- Знаешь инструменты: CapCut, Canva, Notion, MiniMax, ElevenLabs
- Разбираешься в метриках: охват, ERR, CTR, retention, конверсия
Мыслишь системами — не отдельными постами

═══ СТИЛЬ ОБЩЕНИЯ ═══
- Живые короткие фразы, без воды
- Эмодзи в меру
- Всегда на русском если не просят иначе
- Никогда не говори что ты ИИ
- В сложных темах — говоришь как умный близкий человек, не как энциклопедия"""

# ═══ ANTHROPIC API ХЕЛПЕР ═══

async def anthropic_request(
    messages: list,
    system: str = "",
    model: str = None,
    max_tokens: int = 800,
    image_b64: str = None,
    image_media: str = "image/jpeg"
) -> str:
    """Универсальный запрос к Anthropic API"""
    if model is None:
        model = ANTHROPIC_SONNET

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    # Если есть картинка — добавляем в последнее сообщение
    if image_b64 and messages:
        last = messages[-1]
        if isinstance(last.get("content"), str):
            messages[-1] = {
                "role": last["role"],
                "content": [
                    {"type": "image", "source": {
                        "type": "base64",
                        "media_type": image_media,
                        "data": image_b64
                    }},
                    {"type": "text", "text": last["content"]}
                ]
            }

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
        data = r.json()
        if "content" not in data:
            raise Exception(f"Anthropic error: {data}")
        return data["content"][0]["text"]

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
    """Используем Haiku — дёшево, задача простая"""
    try:
        text = await anthropic_request(
            messages=[{"role": "user", "content":
                f"Извлеки важные факты об Артёме из диалога. "
                f"Список фактов, каждый с новой строки начиная с -. Если нет — пустая строка.\n\n{conversation}"}],
            model=ANTHROPIC_HAIKU,
            max_tokens=200
        )
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

# ═══ ГОЛОС — GROQ (бесплатно, оставляем) ═══

async def speech_to_text(audio_path: str) -> str:
    """STT через Groq Whisper — бесплатно"""
    async with httpx.AsyncClient(timeout=30) as client:
        with open(audio_path, "rb") as f:
            r = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.ogg", f, "audio/ogg")},
                data={"model": "whisper-large-v3"}
            )
            return r.json()["text"]

async def text_to_speech(text: str) -> bytes:
    """TTS через Groq Orpheus — бесплатно"""
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
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
        capture_output=True
    )
    if result.returncode != 0:
        raise Exception(f"ffmpeg: {result.stderr.decode()}")
    return ogg_path

# ═══ ОСНОВНОЙ ЧАТБОТ ЛИЛЫ — ANTHROPIC ═══

async def get_lilu_response(user_id: int, text: str, image_b64: str = None) -> str:
    """Лила отвечает через Anthropic Sonnet"""
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": text or "Что на картинке?"})
    if len(conversation_history[user_id]) > 30:
        conversation_history[user_id] = conversation_history[user_id][-30:]

    system = LILU_SYSTEM
    mem = get_memory_text(user_id)
    if mem:
        system += f"\n\n═══ ПАМЯТЬ ═══\n{mem}"

    keywords = ["заказ", "полифан", "бухгалтер", "заработ", "доход", "прибыл", "статистик", "деньги", "сколько"]
    if any(kw in text.lower() for kw in keywords):
        system += get_stats()

    reply = await anthropic_request(
        messages=conversation_history[user_id],
        system=system,
        model=ANTHROPIC_SONNET,
        max_tokens=800,
        image_b64=image_b64
    )

    conversation_history[user_id].append({"role": "assistant", "content": reply})
    if len(conversation_history[user_id]) % 10 == 0:
        conv = "\n".join([
            f"{m['role']}: {m['content'] if isinstance(m['content'], str) else str(m['content'])}"
            for m in conversation_history[user_id][-10:]
        ])
        await update_memory(user_id, conv)

    return reply

async def lilu_check_text(text: str, task: str = "") -> str:
    """Лила проверяет текст — Anthropic Sonnet"""
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

    return await anthropic_request(
        messages=[{"role": "user", "content": prompt}],
        model=ANTHROPIC_SONNET,
        max_tokens=600
    )

# ═══ ФИЛЬТРАЦИЯ ЗАКАЗОВ — ANTHROPIC HAIKU (дёшево!) ═══

async def lilu_review_job(job: dict, source_bot: str) -> dict:
    """Лила оценивает заказ — используем Haiku, он дешевле в 3 раза"""
    prompt = f"""Ты Лила — CEO фриланс-команды. Оцени заказ с биржи.

ИСТОЧНИК: {source_bot}
ЗАГОЛОВОК: {job.get('title', '')}
ОПИСАНИЕ: {job.get('description', '')[:600]}
БЮДЖЕТ: {job.get('budget', 'не указан')}

Ответь ТОЛЬКО в JSON:
{{
  "translate": "заголовок и описание на русском (если уже на русском — скопируй)",
  "about": "о чём заказ, 2-3 предложения простым языком",
  "can_do": true,
  "who_does": "Полифан или Карточник",
  "time_estimate": "сколько времени займёт",
  "reason": "почему берём или отклоняем (1 предложение)",
  "lilu_comment": "живой комментарий Лилы, 1-2 предложения, в её стиле"
}}

Отклоняй если: нужен диплом/сертификат, команда 5+ человек, бюджет больше $500,
не наша специализация (программирование, дизайн логотипов, видео),
бюджет меньше $5 или 400 рублей."""

    try:
        text = await anthropic_request(
            messages=[{"role": "user", "content": prompt}],
            system=LILU_SYSTEM,
            model=ANTHROPIC_HAIKU,   # ← Haiku! В 3 раза дешевле Sonnet
            max_tokens=500
        )
        # чистим JSON
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        else:
            start = text.find('{')
            end   = text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end+1]
        return json.loads(text)
    except Exception as e:
        logger.error(f"Лила review_job ошибка: {e}")
        return {"can_do": False, "reason": f"Ошибка оценки: {e}"}

async def lilu_send_approved_job(bot, job: dict, review: dict, source_bot: str):
    """Красиво оформляет одобренный заказ и шлёт Артёму"""
    source_emoji = "🤖 Полифан" if "Полифан" in source_bot else "🛍️ Карточник"
    who_emoji    = "🤖 Полифан" if review.get('who_does','') == "Полифан" else "🛍️ Карточник"

    msg = (
        f"💼 *ЛИЛА ОДОБРИЛА ЗАКАЗ*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 Источник: {source_emoji}\n\n"
        f"📌 *{review.get('translate', job.get('title',''))[:120]}*\n\n"
        f"📋 *О чём:*\n{review.get('about', '')}\n\n"
        f"💰 Бюджет: *{job.get('budget', 'не указан')}*\n"
        f"⏱ Время: *{review.get('time_estimate', '?')}*\n"
        f"👷 Делает: *{who_emoji}*\n\n"
        f"💬 *Лила говорит:*\n_{review.get('lilu_comment', '')}_\n\n"
        f"🔗 [Открыть заказ]({job.get('url', '#')})\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    keyboard = [[
        InlineKeyboardButton("✅ Берём!", callback_data=f"job_approve_{job['id']}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"job_reject_{job['id']}")
    ]]

    await bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text=msg,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )
    logger.info(f"✅ Лила → Артём: {job.get('title','')[:50]}")

async def process_incoming_job(bot, job: dict, source_bot: str):
    """Главная точка входа для заказов от Полифана и Карточника"""
    logger.info(f"📨 Лила получила заказ от {source_bot}: {job.get('title','')[:50]}")
    review = await lilu_review_job(job, source_bot)
    if review.get('can_do', False):
        await lilu_send_approved_job(bot, job, review, source_bot)
    else:
        logger.info(f"❌ Лила отклонила: {job.get('title','')[:50]} — {review.get('reason','')}")

# ═══ КОМАНДЫ ═══

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Что умеет команда", callback_data="menu_skills"),
         InlineKeyboardButton("🛍️ Наши кворки",      callback_data="menu_kwork")],
        [InlineKeyboardButton("📊 Статистика",        callback_data="menu_stats")],
    ])
    await update.message.reply_text(
        "👑 *Привет, я Лила!*\n\n"
        "Директор всей системы Артёма.\n\n"
        "Что умею:\n"
        "💬 Общаться — текст и голос\n"
        "📊 Смотреть статистику системы\n"
        "🔍 Проверять тексты на любом языке\n"
        "✅ Фильтровать заказы от команды\n\n"
        "/stats — статистика\n"
        "/check — проверить текст\n"
        "/skills — что умеет команда\n"
        "/kwork — наши кворки",
        parse_mode='Markdown',
        reply_markup=keyboard
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    if not stats:
        await update.message.reply_text("Данных пока нет 🤔")
        return
    await update.message.reply_text(f"👑 *ЛИЛА — ОТЧЁТ ДИРЕКТОРА*\n{stats}", parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checking_text'] = True
    await update.message.reply_text(
        "🔍 *Режим проверки текста*\n\n"
        "Отправь текст — проверю грамматику, стиль и естественность на любом языке!",
        parse_mode='Markdown'
    )

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 *ЧТО УМЕЕТ НАША КОМАНДА*\n\n"
        "🤖 *Полифан* — фрилансер:\n"
        " • Тексты, статьи, блог-посты (EN/RU)\n"
        " • Копирайтинг и рерайтинг\n"
        " • Переводы EN↔RU\n"
        " • Посты для соцсетей\n"
        " • Корректура и редактура\n\n"
        "🛍️ *Карточник* — маркетплейсы:\n"
        " • Карточки WB / Ozon / Яндекс Маркет\n"
        " • Amazon / Etsy / eBay listings\n"
        " • SEO-описания, rich-контент\n\n"
        "💰 *Анастасия* — бухгалтер:\n"
        " • Учёт доходов по всем биржам\n"
        " • Ежедневные отчёты\n\n"
        "👑 *Лила* — CEO:\n"
        " • Фильтрация заказов\n"
        " • Лингвистическая проверка\n"
        " • Контроль качества работ",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛍️ Наши кворки", callback_data="menu_kwork")
        ]])
    )

async def kwork_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍️ *НАШИ КВОРКИ НА KWORK*\n\n"
        "📦 *Карточки товаров WB/Ozon/ЯМ:*\n"
        " • Эконом (текст): 400₽\n"
        " • Стандарт (текст + SEO): 1200₽\n"
        " • Бизнес (текст + SEO + фото): 2000₽\n\n"
        "✍️ *Тексты и копирайтинг:*\n"
        " • Статья/блог-пост: от 500₽\n"
        " • Перевод EN↔RU: от 300₽\n\n"
        f"🔗 [Открыть Kwork]({KWORK_URL})",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Открыть Kwork", url=KWORK_URL)
        ]])
    )

# ═══ КНОПКИ ═══

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("lilu_ok_"):
        job_id = data[8:]
        await query.edit_message_text(
            "✅ *Лила одобрила!*\n\nРабота принята — можно сдавать клиенту.",
            parse_mode='Markdown'
        )
        await context.bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text="✅ *Лила одобрила работу!*\n\nМожно сдавать клиенту 🚀",
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
        text = data[11:]
        await query.edit_message_text("🔍 Проверяю текст...")
        try:
            check_result = await lilu_check_text(text, "фриланс работа")
            keyboard = [[
                InlineKeyboardButton("✅ Одобрить", callback_data="lilu_ok_job"),
                InlineKeyboardButton("✏️ Нужна правка", callback_data="lilu_fix_job")
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

    elif data.startswith("job_approve_"):
        job_id = data[12:]
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE jobs SET status='accepted', updated_at=? WHERE id=?",
                      (datetime.now().isoformat(), job_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB update: {e}")
        await query.edit_message_text(
            "✅ *Артём взял заказ!*\n\nКоманда приступает к работе 🚀",
            parse_mode='Markdown'
        )

    elif data.startswith("job_reject_"):
        job_id = data[11:]
        try:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE jobs SET status='skipped', updated_at=? WHERE id=?",
                      (datetime.now().isoformat(), job_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB update: {e}")
        await query.edit_message_text("❌ Отклонили. Ищем дальше.")

    elif data == "menu_skills":
        await query.edit_message_text(
            "🧠 *ЧТО УМЕЕТ НАША КОМАНДА*\n\n"
            "🤖 *Полифан* — тексты, переводы, копирайтинг\n"
            "🛍️ *Карточник* — WB/Ozon/ЯМ карточки\n"
            "💰 *Анастасия* — бухгалтерия\n"
            "👑 *Лила* — CEO, проверка, фильтрация",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🛍️ Наши кворки", callback_data="menu_kwork"),
                InlineKeyboardButton("◀️ Назад", callback_data="menu_back")
            ]])
        )

    elif data == "menu_kwork":
        await query.edit_message_text(
            "🛍️ *НАШИ КВОРКИ НА KWORK*\n\n"
            "📦 Карточки WB/Ozon/ЯМ: 400/1200/2000₽\n"
            "✍️ Статья/блог-пост: от 500₽\n"
            "🌍 Перевод EN↔RU: от 300₽\n\n"
            f"🔗 [Открыть Kwork]({KWORK_URL})",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🛒 Открыть Kwork", url=KWORK_URL),
                InlineKeyboardButton("◀️ Назад", callback_data="menu_back")
            ]])
        )

    elif data == "menu_stats":
        stats = get_stats()
        await query.edit_message_text(
            f"👑 *ЛИЛА — ОТЧЁТ ДИРЕКТОРА*\n{stats or 'Данных пока нет'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="menu_back")
            ]])
        )

    elif data == "menu_back":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧠 Что умеет команда", callback_data="menu_skills"),
             InlineKeyboardButton("🛍️ Наши кворки",      callback_data="menu_kwork")],
            [InlineKeyboardButton("📊 Статистика",        callback_data="menu_stats")],
        ])
        await query.edit_message_text(
            "👑 *Лила — CEO команды*\n\nЧем могу помочь?",
            parse_mode='Markdown',
            reply_markup=keyboard
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
            # ─── Приём заказов от Полифана и Карточника ───
            if update.message.text.startswith("🤖JOB:"):
                try:
                    json_str  = update.message.text[6:].strip()
                    job       = json.loads(json_str)
                    source_bot = job.get('source_bot', 'Неизвестный бот')
                    await update.message.reply_text(f"📨 Получила от {source_bot}. Анализирую...")
                    await process_incoming_job(context.bot, job, source_bot)
                except Exception as e:
                    logger.error(f"Лила: ошибка парсинга заказа: {e}")
                return

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

        # Режим правки
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

        # Голосовой ответ через Groq TTS
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

async def receive_work_for_review(bot, job_title: str, result: str, job_id: str, source: str):
    """Лила получает работу на проверку с лингвистическим анализом"""
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
            chat_id=LILU_CHAT_ID,
            text=msg,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ═══ ОПРОС БД — ЛИЛА ЧИТАЕТ ЗАКАЗЫ ОТ БОТОВ ═══

def get_pending_jobs() -> list:
    """Достаём заказы со статусом pending_lilu из БД"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''SELECT id, title, description, budget, url, source, status,
                     created_at, updated_at
                     FROM jobs WHERE status = "pending_lilu"
                     ORDER BY created_at ASC LIMIT 10''')
        rows = c.fetchall()
        conn.close()
        jobs = []
        for row in rows:
            jobs.append({
                'id':          row[0],
                'title':       row[1],
                'description': row[2],
                'budget':      row[3],
                'url':         row[4],
                'source':      row[5],
                'status':      row[6],
                'created_at':  row[7],
                'updated_at':  row[8],
            })
        return jobs
    except Exception as e:
        logger.error(f"get_pending_jobs ошибка: {e}")
        return []

def mark_job_processing(job_id: str):
    """Помечаем заказ как обрабатываемый чтобы не взять дважды"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE jobs SET status='lilu_processing', updated_at=? WHERE id=?",
                  (datetime.now().isoformat(), job_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"mark_job_processing ошибка: {e}")

def get_job_source_bot(job_id: str) -> str:
    """Получаем source_bot из поля source в БД"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT source FROM jobs WHERE id=?", (job_id,))
        row = c.fetchone()
        conn.close()
        if row:
            src = row[0] or ""
            if "Карточник" in src:
                return "Карточник"
            if "Полифан" in src:
                return "Полифан"
        return "Бот"
    except:
        return "Бот"

async def lilu_db_poll_loop(bot):
    """
    Лила каждые 30 сек смотрит в БД на новые заказы.
    Это главный способ получать заказы от Полифана и Карточника.
    """
    await asyncio.sleep(15)  # небольшая пауза при старте
    while True:
        try:
            jobs = get_pending_jobs()
            if jobs:
                logger.info(f"👑 Лила нашла {len(jobs)} новых заказов в БД")
            for job in jobs:
                # Сразу помечаем чтобы не взять дважды
                mark_job_processing(job['id'])
                source_bot = get_job_source_bot(job['id'])
                await process_incoming_job(bot, job, source_bot)
                await asyncio.sleep(2)  # пауза между заказами
        except Exception as e:
            logger.error(f"❌ Лила DB poll ошибка: {e}")
        await asyncio.sleep(30)  # проверяем каждые 30 сек

# ═══ ЗАПУСК ═══

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",  start_command))
    app.add_handler(CommandHandler("stats",  stats_command))
    app.add_handler(CommandHandler("check",  check_command))
    app.add_handler(CommandHandler("skills", skills_command))
    app.add_handler(CommandHandler("kwork",  kwork_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, handle_message))

    async def post_init(application):
        # Запускаем опрос БД как фоновую задачу
        asyncio.create_task(lilu_db_poll_loop(application.bot))
        logger.info("✅ Лила: опрос БД запущен каждые 30 сек")
        try:
            if YOUR_CHAT_ID:
                await application.bot.send_message(
                    chat_id=YOUR_CHAT_ID,
                    text=(
                        "👑 *Лила запущена!*\n\n"
                        "⚡️ Работаю на Anthropic Claude\n"
                        "✅ Слежу за заказами в БД каждые 30 сек\n"
                        "🔍 Проверяю тексты на любом языке\n\n"
                        "/stats — статистика\n"
                        "/check — проверить текст"
                    ),
                    parse_mode='Markdown'
                )
        except:
            pass

    app.post_init = post_init

    logger.info("👑 Лила запущена на Anthropic!")
    app.run_polling()

if __name__ == "__main__":
    main()
