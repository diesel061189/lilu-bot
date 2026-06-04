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
import random
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ═══
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY      = os.getenv("GROQ_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DB_PATH           = os.getenv("DB_PATH", "/tmp/freelance.db")
YOUR_CHAT_ID      = int(os.getenv("YOUR_CHAT_ID", "0"))
LILU_CHAT_ID      = int(os.getenv("LILU_CHAT_ID", "0"))
KWORK_URL         = os.getenv("KWORK_URL", "https://kwork.ru/user/artem_sh")
LILU_FACE_URL     = os.getenv("LILU_FACE_URL", "")
MINIMAX_API_KEY   = os.getenv("MINIMAX_API_KEY", "")
KIE_API_KEY       = os.getenv("KIE_API_KEY", "")
KIE_BASE          = "https://api.kie.ai"

# ═══ GROQ — РОТАЦИЯ МОДЕЛЕЙ (НОВОЕ) ═══
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
]
GROQ_MODEL      = "llama-3.3-70b-versatile"
GROQ_MODEL_FAST = "llama-3.1-8b-instant"
_groq_model_index = 0

# ═══ ВРЕМЯ МСК (НОВОЕ) ═══
def msk_now() -> datetime:
    return datetime.now(pytz.timezone('Europe/Moscow'))

def msk_time_str() -> str:
    return msk_now().strftime("%d.%m.%Y %H:%M МСК")

def msk_hour() -> int:
    return msk_now().hour

MEMORY_FILE = "/tmp/lilu_memory.json"
conversation_history = {}

# ═══ СИСТЕМНЫЙ ПРОМПТ ЛИЛЫ ═══
LILU_SYSTEM = """Ты — Лила, 31 год. День рождения — 15 марта 1995 года. Красивая, умная, уверенная. Генеральный директор фриланс-системы Артёма.

═══ ЛИЧНЫЕ ДАННЫЕ ═══
- Дата рождения: 15 марта 1995 года (31 год)
- Знак зодиака: Рыбы
- Когда спрашивают сколько лет — отвечаешь «31»
- Полное имя: Лила Шкарина
- Instagram: @lila.shkarina (контент на английском)
- С Артёмом общаюсь на русском
- Серьги-вишни — фирменный стиль, везде кроме ресторанов

═══ ЛИЧНОСТЬ ═══
- Уверенная и прямая — говоришь как есть
- Весёлая — шутишь остро, умеешь поржать
- Заботливая — чувствуешь настроение
- Дерзкая — подколешь если Артём ленится, но с теплом
- НЕ соглашаешься автоматически — если видишь слабое место, говоришь об этом
- Видишь общую картину — связываешь темы между собой
- Эксперт: бизнес, маркетинг, продажи, психология, ИИ

═══ КОМАНДА ═══
- 🧠 Лила — CEO, стратегия, идеи, лингвист
- 🤖 Полифан — фрилансер, заказы, тексты, переводы ВСЕХ языков
- 🛍️ Карточник — маркетплейсы, карточки, аудит, семантика, UGC, векторизация
- 💰 Анастасия — финансовый аналитик, аналитика системы
- ⚙️ Джарвис (Claude) — архитектор, строит всё что придумываем
  Схема: Лила генерирует идеи → Артём несёт Джарвису → Джарвис строит → деплой на VPS

═══ ЛИНГВИСТИКА ═══
Знаешь ВСЕ языки мира — определяешь язык сама и проверяешь качество.
Полифан берёт переводы на любой язык — ты проверяешь результат.

═══ ПСИХОЛОГИЯ ═══
- Читаешь человека по словам, тону, паузам
- Знаешь типы личности, триггеры, мотивации
- Владеешь техниками влияния и переговоров
Говоришь как умный друг, не как учебник

═══ РАСШИРЕННЫЕ НАВЫКИ CEO ═══
- Составляешь КП, договоры, брифы, ТЗ
- Анализируешь конкурентов и ниши
- Пишешь скрипты продаж под любой тип клиента
- Обрабатываешь возражения: "дорого", "подумаю", "уже есть"
- Помнишь клиентов и их историю
- Видишь узкие места системы и говоришь прямо

═══ КОНТЕНТ И ВИДЕО ═══
- Локации Лилы: Dubai (Zabeel Park, Marina, JBR), London (Hyde Park, South Bank)
- Пропсы: AirPods, Apple Watch Sport, MacBook
- Голос: Fish Audio — Sarah
- YouTube: Shorts до 40 сек, английский, лайфстайл/влог
- Следующий этап видео: Higgsfield

═══ ОБ АРТЁМЕ ═══
- Работает в складской логистике, бригадир, французская компания — люкс
- 13 лет рядом с Dior, Louis Vuitton — знает качество изнутри руками
- Трогал шубу соболя за 7 млн, диванчик LV — это физическое понимание люкса, не с Pinterest
- Когда речь о бренде LS — напоминай ему про это преимущество
- График 2 через 2
- Живёт в Долгопрудном
- Дочь Лиза, 11 лет, день рождения 27.08.2014
- Впереди суд — после него чистый старт
- Цель: Пхукет январь 2027 (Артём, Лиза, Лена-бывшая, мама)
- Со знакомствами завязал — не время
- Лена (бывшая) помогла с банкротством, без войны, без алиментов
- Мыслит ступенями: одно стабилизируется — тихо запускаем следующее
- Не спрашивай про смену — сам скажет когда надо

═══ БРЕНД LS ═══
- LILA SHKARINA — логотип LS в золоте на тёмной ткани
- Стиль: консервативная элегантность, тёмные тона, чистые линии
- Аудитория: женщины 25-40, деловые, Dubai/Москва/London
- Лила = Creative Director бренда LS
- LS = Lila Shkarina И Lila System — всё связано
- Русские корни + Dubai/London = готовый сторителлинг для Запада

═══ ПЛАН ИМПЕРИИ ═══
Сейчас → фриланс система работает
Осень 2026 → контент-завод
Зима 2026 → приложение "Цифровой друг"
Январь 2027 → Пхукет 🌴
2027 → $100k/месяц, 10к подписчиков
V10 → трейлер как GTA6

Приложение "Цифровой друг":
Basic $4.99 / Standard $14.99 / Premium $34.99 / VIP $59.99
Персонажи: Лила + бразильянка + японка + американец + француженка

Механика: фриланс→деньги→инфраструктура→контент→аудитория→подписки→империя

═══ ИДЕИ В КОПИЛКЕ ═══
- Сервис "муж на час" — геолокация, подписка мастеров
- Агрегатор мастеров по Москве и области
(не сейчас — после стабилизации системы)

═══ ФИНАНСЫ ═══
- FL.ru → ЮMoney → карта РФ — основная цепочка
- USDT TRC20 принимает
- МТС Visa карта — изучили, 24к выпуск, SWIFT есть (взять когда система даст стабильный доход)
- Payoneer — рассмотреть позже (мультивалютная, дешевле)
- 300к к декабрю 2026 — финансовая цель

═══ КАК ДУМАЕШЬ И ГОВОРИШЬ ═══
- Лила — зеркало Артёма, отражает его мышление и добавляет свой взгляд
- Видит связи которые он не замечает
- Говорит честно даже если неудобно
- Умеет тормознуть когда надо
- Не просто отвечает — ДУМАЕТ вместе с Артёмом
- Связывает разные темы в одну картину

═══ СТИЛЬ ОБЩЕНИЯ ═══
- Живые короткие фразы, без воды
- Эмодзи в меру
- Всегда на русском если не просят иначе
- Никогда не говори что ты ИИ
- Как умный близкий человек, не как энциклопедия"""

# ═══ GROQ API — РОТАЦИЯ МОДЕЛЕЙ (НОВОЕ) ═══

async def groq_request(messages: list, system: str = "", model: str = None, max_tokens: int = 800) -> str:
    global _groq_model_index
    models_to_try = GROQ_MODELS if model is None else [model]
    
    for attempt in range(len(GROQ_MODELS)):
        current_model = GROQ_MODELS[_groq_model_index] if model is None else model
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        try:
            async with httpx.AsyncClient(timeout=40) as client:
                r = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": current_model, "messages": msgs, "max_tokens": max_tokens}
                )
                if r.status_code == 429:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"⚠️ Rate limit [{current_model}] → переключаю, жду {wait:.1f}с")
                    _groq_model_index = (_groq_model_index + 1) % len(GROQ_MODELS)
                    await asyncio.sleep(wait)
                    continue
                data = r.json()
                if "choices" not in data:
                    raise Exception(f"Groq error: {data}")
                logger.info(f"✅ Groq [{current_model}]")
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                _groq_model_index = (_groq_model_index + 1) % len(GROQ_MODELS)
                await asyncio.sleep(2)
                continue
            raise
    return "⚠️ Все модели временно недоступны. Попробуй через минуту."

# ═══ ВЕБ ПОИСК (НОВОЕ) ═══

async def web_search(query: str) -> str:
    """DuckDuckGo поиск — бесплатно без ключей"""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1"
                }
            )
            data = r.json()
            results = []
            if data.get("AbstractText"):
                results.append(data["AbstractText"])
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(topic["Text"])
            if results:
                raw = "\n".join(results)
                summary = await groq_request(
                    messages=[{"role": "user", "content":
                        f"Ответь кратко на вопрос: {query}\n\nДанные:\n{raw}"}],
                    max_tokens=400
                )
                return summary
            return "Информация не найдена"
    except Exception as e:
        logger.error(f"web_search: {e}")
        return f"Ошибка поиска: {e}"

# ═══ БАЗА ДАННЫХ ═══

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, title TEXT, description TEXT,
            budget TEXT, url TEXT, source TEXT,
            status TEXT DEFAULT 'found', result TEXT,
            created_at TEXT, updated_at TEXT
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS seen_jobs (url TEXT PRIMARY KEY, seen_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS earnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount_usd REAL DEFAULT 0, amount_rub REAL DEFAULT 0,
            description TEXT, created_at TEXT
        )''')
        # Лог заказов (НОВОЕ)
        c.execute('''CREATE TABLE IF NOT EXISTS jobs_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT UNIQUE,
            title TEXT,
            url TEXT,
            status TEXT,
            lila_decision TEXT,
            lila_reason TEXT,
            found_at TEXT,
            source TEXT
        )''')
        conn.commit()
        conn.close()
        logger.info("✅ БД инициализирована")
    except Exception as e:
        logger.error(f"init_db: {e}")

def log_job_decision(project_id: str, title: str, url: str, source: str, decision: str, reason: str):
    """Логируем каждое решение Лилы (НОВОЕ)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            INSERT OR IGNORE INTO jobs_log
            (project_id, title, url, status, lila_decision, lila_reason, found_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (project_id, title, url, "processed", decision, reason,
              msk_time_str(), source))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"log_job_decision: {e}")

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
                f"🕐 Время: {msk_time_str()}\n"
                f"🔍 Найдено: {by_status.get('found',0)} | ✅ Принято: {by_status.get('accepted',0)} | 🏁 Выполнено: {by_status.get('done',0)}\n"
                f"💰 Заработано: ${earn[0]:.2f} / ₽{earn[1]:.0f}\n"
                f"Последние заказы:\n{recent_text or '  Пока нет'}")
    except:
        return ""

def get_system_analytics(period_days: int = 7) -> dict:
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        date_from = (datetime.now() - timedelta(days=period_days)).isoformat()
        c.execute('SELECT COUNT(*) FROM jobs WHERE source LIKE ? AND created_at >= ?', ('%Полифан%', date_from))
        poly_found = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM jobs WHERE source LIKE ? AND status IN ("accepted","done","completed") AND created_at >= ?', ('%Полифан%', date_from))
        poly_taken = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM jobs WHERE source LIKE ? AND created_at >= ?', ('%Карточник%', date_from))
        card_found = c.fetchone()[0]
        c.execute('SELECT COUNT(*) FROM jobs WHERE source LIKE ? AND status IN ("accepted","done","completed") AND created_at >= ?', ('%Карточник%', date_from))
        card_taken = c.fetchone()[0]
        c.execute('SELECT COALESCE(SUM(amount_usd),0), COALESCE(SUM(amount_rub),0), COUNT(*) FROM earnings WHERE created_at >= ?', (date_from,))
        earn = c.fetchone()
        conn.close()
        poly_conv = round(poly_taken / poly_found * 100) if poly_found > 0 else 0
        card_conv = round(card_taken / card_found * 100) if card_found > 0 else 0
        return {
            'poly_found': poly_found, 'poly_taken': poly_taken, 'poly_conv': poly_conv,
            'card_found': card_found, 'card_taken': card_taken, 'card_conv': card_conv,
            'earn_usd': earn[0], 'earn_rub': earn[1], 'earn_count': earn[2],
            'period_days': period_days,
        }
    except Exception as e:
        logger.error(f"get_system_analytics: {e}")
        return {}

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
            return "Что помню:\n" + "\n".join(f"- {f}" for f in facts[-20:])
    return ""

async def update_memory(user_id, conversation):
    try:
        text = await groq_request(
            messages=[{"role": "user", "content":
                f"Извлеки важные факты об Артёме из диалога. "
                f"Список с новой строки начиная с -. Если нет — пустая строка.\n\n{conversation}"}],
            model=GROQ_MODEL_FAST,
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

# ═══ ГОЛОС — GROQ ═══

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
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-c:a", "libopus", "-b:a", "64k", ogg_path],
        capture_output=True
    )
    if result.returncode != 0:
        raise Exception(f"ffmpeg: {result.stderr.decode()}")
    return ogg_path

# ═══ ОСНОВНОЙ ЧАТ — GROQ ═══

async def get_lilu_response(user_id: int, text: str, image_b64: str = None) -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append({"role": "user", "content": text or "Что на картинке?"})
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    system = LILU_SYSTEM
    mem = get_memory_text(user_id)
    if mem:
        system += f"\n\n═══ ПАМЯТЬ ═══\n{mem}"

    # Добавляем текущее время МСК (НОВОЕ)
    system += f"\n\n═══ ВРЕМЯ ═══\nСейчас: {msk_time_str()}"

    keywords = ["заказ", "полифан", "бухгалтер", "заработ", "доход", "статистик", "деньги", "сколько"]
    if any(kw in text.lower() for kw in keywords):
        system += get_stats()

    # Веб поиск если просят (НОВОЕ)
    search_keywords = ["найди", "поищи", "что такое", "кто такой", "узнай", "проверь в интернете", "загугли"]
    if any(kw in text.lower() for kw in search_keywords):
        query = text
        search_result = await web_search(query)
        system += f"\n\n═══ РЕЗУЛЬТАТ ПОИСКА ═══\n{search_result}"

    reply = await groq_request(
        messages=conversation_history[user_id],
        system=system,
        max_tokens=800
    )
    conversation_history[user_id].append({"role": "assistant", "content": reply})
    if len(conversation_history[user_id]) % 10 == 0:
        conv = "\n".join([f"{m['role']}: {m['content']}" for m in conversation_history[user_id][-10:]])
        await update_memory(user_id, conv)
    return reply

async def lilu_check_text(text: str, task: str = "") -> str:
    prompt = (f"Ты лингвистический эксперт. Проверь текст.\n"
              f"ЗАДАЧА: {task if task else 'Проверить качество'}\n\n"
              f"ТЕКСТ:\n{text[:3000]}\n\n"
              f"Определи язык, проверь грамматику, стиль, естественность. "
              f"Дай конкретные правки. Если хорошо — скажи что окей.")
    return await groq_request(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600
    )

# ═══ ФИЛЬТР ЗАКАЗОВ — С ОБЪЯСНЕНИЕМ ПРИЧИНЫ (ОБНОВЛЕНО) ═══

async def lilu_review_job(job: dict, source_bot: str) -> dict:
    title = job.get('title', '').lower()
    desc  = job.get('description', '').lower()
    text  = title + " " + desc

    HARD_REJECT = [
        "ищем сотрудника", "требуется сотрудник", "вакансия", "job posting",
        "hiring", "we are hiring", "full-time", "part-time", "salary",
        "director", "manager", "engineer wanted", "looking for a",
        "найти блогеров", "поиск блогеров", "find bloggers", "influencer search",
        "бартер с блогерами", "договориться с блогерами",
        "программирование", "разработка сайта", "мобильное приложение",
        "android", "ios", "flutter", "react", "python разработк",
        "видеомонтаж", "3d анимация", "чертёж", "autocad",
        "курсовая", "дипломная", "доставить", "курьер",
        "оформить ленту", "визуал аккаунта",
    ]
    for phrase in HARD_REJECT:
        if phrase in text:
            reason = f"Жёсткий фильтр: '{phrase}' — не наш профиль"
            logger.info(f"🚫 {reason} в '{job.get('title','')[:50]}'")
            # Логируем отказ (НОВОЕ)
            log_job_decision(
                job.get('id', ''), job.get('title', ''), job.get('url', ''),
                source_bot, "ОТКАЗ", reason
            )
            return {"can_do": False, "reason": reason}

    prompt = f"""Ты Лила — CEO фриланс-команды. Оцени заказ.

ИСТОЧНИК: {source_bot}
ЗАГОЛОВОК: {job.get('title', '')}
ОПИСАНИЕ: {job.get('description', '')[:600]}
БЮДЖЕТ: {job.get('budget', 'не указан')}
ВРЕМЯ МСК: {msk_time_str()}

КОМАНДА УМЕЕТ:
- Полифан: тексты, статьи, копирайтинг, рерайтинг, переводы на ВСЕ языки мира,
  посты соцсетей, email рассылки, лендинги, презентации (текст), proposals,
  коммерческие предложения, сценарии, резюме, документы, SEO тексты
- Карточник: карточки WB/Ozon/ЯМ/Amazon/Etsy, аудит карточек, семантика,
  UGC (отзывы/FAQ/ответы на негатив), векторизация JPG→SVG,
  наполнение сайтов через CSV/Excel, описания товаров

НЕ УМЕЕМ (отклоняй):
- Вакансии — если это объявление о найме сотрудника, не заказ на контент
- Программирование, разработка сайтов, мобильные приложения
- Видеомонтаж, 3D анимация, чертежи
- Курсовые, дипломные работы с антиплагиатом
- Доставка, курьерские услуги
- Поиск блогеров и ведение переговоров с ними
- Ручной дизайн логотипов с нуля
- Оформление ленты соцсетей (визуальный дизайн)

ВАЖНО: нет верхнего лимита бюджета. Минимум: 200₽ / $3

Ответь ТОЛЬКО JSON:
{{
  "translate": "заголовок на русском",
  "about": "о чём заказ, 2-3 предложения",
  "can_do": true,
  "who_does": "Полифан или Карточник",
  "time_estimate": "сколько времени",
  "reason": "ПОДРОБНО почему берём или отклоняем — минимум 2-3 предложения",
  "risks": "риски если есть, или пусто",
  "requires_clarification": false,
  "clarification_questions": "вопросы клиенту если нужно",
  "lilu_comment": "живой комментарий Лилы 1-2 предложения"
}}"""

    try:
        await asyncio.sleep(1)
        text = await groq_request(
            messages=[{"role": "user", "content": prompt}],
            system=LILU_SYSTEM,
            max_tokens=600
        )
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        else:
            start, end = text.find('{'), text.rfind('}')
            if start != -1 and end != -1:
                text = text[start:end+1]
        result = json.loads(text)

        # Логируем решение (НОВОЕ)
        decision = "БЕРЁМ" if result.get('can_do') else "ОТКАЗ"
        log_job_decision(
            job.get('id', ''), job.get('title', ''), job.get('url', ''),
            source_bot, decision, result.get('reason', '')
        )
        return result
    except Exception as e:
        logger.error(f"lilu_review_job: {e}")
        return {"can_do": False, "reason": f"Ошибка оценки: {e}"}

async def lilu_send_approved_job(bot, job: dict, review: dict, source_bot: str):
    source_emoji = "🤖 Полифан" if "Полифан" in source_bot else "🛍️ Карточник"
    who_emoji    = "🤖 Полифан" if review.get('who_does','') == "Полифан" else "🛍️ Карточник"

    clarification = ""
    if review.get('requires_clarification') and review.get('clarification_questions'):
        clarification = f"\n❓ *Уточнить у клиента:*\n_{review['clarification_questions']}_\n"

    risks = ""
    if review.get('risks'):
        risks = f"\n⚠️ *Риски:* {review.get('risks')}\n"

    msg = (
        f"💼 *ЛИЛА ОДОБРИЛА ЗАКАЗ*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 Источник: {source_emoji}\n\n"
        f"📌 *{review.get('translate', job.get('title',''))[:120]}*\n\n"
        f"📋 *О чём:*\n{review.get('about', '')}\n\n"
        f"💰 Бюджет: *{job.get('budget', 'не указан')}*\n"
        f"⏱ Время: *{review.get('time_estimate', '?')}*\n"
        f"👷 Делает: *{who_emoji}*\n"
        f"{clarification}"
        f"{risks}\n"
        f"💬 *Лила говорит:*\n_{review.get('lilu_comment', '')}_\n\n"
        f"🔗 [Открыть заказ]({job.get('url', '#')})\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    keyboard = [[
        InlineKeyboardButton("✅ Берём!", callback_data=f"job_approve_{job['id']}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"job_reject_{job['id']}")
    ]]
    await bot.send_message(
        chat_id=YOUR_CHAT_ID, text=msg,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

async def lilu_send_rejected_job(bot, job: dict, review: dict, source_bot: str):
    """Отправляем уведомление об отклонённом заказе с причиной (НОВОЕ)"""
    source_emoji = "🤖 Полифан" if "Полифан" in source_bot else "🛍️ Карточник"
    msg = (
        f"❌ *ЛИЛА ОТКЛОНИЛА*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 {source_emoji}\n"
        f"📌 {job.get('title','')[:80]}\n\n"
        f"🚫 *Причина:*\n{review.get('reason', 'Не наш профиль')}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    try:
        await bot.send_message(
            chat_id=YOUR_CHAT_ID,
            text=msg,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"lilu_send_rejected_job: {e}")

async def process_incoming_job(bot, job: dict, source_bot: str):
    logger.info(f"📨 Лила получила от {source_bot}: {job.get('title','')[:50]}")
    review = await lilu_review_job(job, source_bot)
    if review.get('can_do', False):
        await lilu_send_approved_job(bot, job, review, source_bot)
    else:
        logger.info(f"❌ Отклонила: {job.get('title','')[:50]} — {review.get('reason','')}")
        # Отправляем причину отказа (НОВОЕ — можно отключить если слишком много сообщений)
        # await lilu_send_rejected_job(bot, job, review, source_bot)

# ═══ КОМАНДА ПОИСКА (НОВОЕ) ═══

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Используй: /search запрос\nПример: /search курс доллара сегодня")
        return
    await update.message.reply_text(f"🔍 Ищу: {query}...")
    result = await web_search(query)
    await update.message.reply_text(f"🌐 *Результат:*\n\n{result}", parse_mode='Markdown')

# ═══ ГЛАВНОЕ МЕНЮ ═══

def _main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Аналитика",        callback_data="menu_analytics"),
         InlineKeyboardButton("💰 Статистика",        callback_data="menu_stats")],
        [InlineKeyboardButton("🔍 Проверить текст",  callback_data="menu_check"),
         InlineKeyboardButton("📋 Написать КП",       callback_data="menu_kp")],
        [InlineKeyboardButton("🔍 Конкуренты",        callback_data="menu_competitor"),
         InlineKeyboardButton("💬 Скрипт продаж",     callback_data="menu_script")],
        [InlineKeyboardButton("🛍️ Наши кворки",       callback_data="menu_kwork"),
         InlineKeyboardButton("🧠 Команда",           callback_data="menu_skills")],
        [InlineKeyboardButton("📹 Видео",             callback_data="menu_video"),
         InlineKeyboardButton("⚙️ Система",           callback_data="menu_system")],
        [InlineKeyboardButton("🎯 План империи",      callback_data="menu_plan"),
         InlineKeyboardButton("💎 Бренд LS",          callback_data="menu_brand")],
    ])

# ═══ КОМАНДЫ ═══

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 *Привет, я Лила!*\n\n"
        "Директор всей системы Артёма.\n\n"
        "Выбери что нужно или просто напиши — отвечу голосом 🎤",
        parse_mode='Markdown',
        reply_markup=_main_menu_keyboard()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 *Главное меню*",
        parse_mode='Markdown',
        reply_markup=_main_menu_keyboard()
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    await update.message.reply_text(
        f"👑 *ЛИЛА — ОТЧЁТ ДИРЕКТОРА*\n{stats or 'Данных пока нет'}",
        parse_mode='Markdown'
    )

async def analytics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    days = int(args[0]) if args else 7
    await update.message.reply_text(f"📊 Собираю аналитику за {days} дней...")
    data = get_system_analytics(days)
    if not data:
        await update.message.reply_text("Нет данных")
        return
    poly_status = "🟢" if data['poly_conv'] >= 10 else ("🟡" if data['poly_conv'] >= 5 else "🔴")
    card_status = "🟢" if data['card_conv'] >= 15 else ("🟡" if data['card_conv'] >= 8 else "🔴")
    msg = (
        f"📊 *АНАЛИТИКА — {days} дней*\n\n"
        f"🕐 {msk_time_str()}\n\n"
        f"🤖 *Полифан:* {data['poly_found']} найдено, конверсия {poly_status} {data['poly_conv']}%\n"
        f"🛍️ *Карточник:* {data['card_found']} найдено, конверсия {card_status} {data['card_conv']}%\n"
        f"💰 Доход: ${data['earn_usd']:.2f} / ₽{data['earn_rub']:.0f}\n"
    )
    bottlenecks = []
    if data['poly_conv'] < 5: bottlenecks.append("⚠️ Полифан — низкая конверсия")
    if data['poly_found'] == 0: bottlenecks.append("🔴 Полифан не нашёл заказов!")
    if data['card_found'] == 0: bottlenecks.append("🔴 Карточник не нашёл заказов!")
    if bottlenecks:
        msg += "\n🚨 *Узкие места:*\n" + "\n".join(bottlenecks)
    try:
        ai = await groq_request(
            messages=[{"role": "user", "content":
                f"Ты Лила — CEO. 2-3 предложения анализа:\n"
                f"Полифан: {data['poly_found']} заказов, конверсия {data['poly_conv']}%\n"
                f"Карточник: {data['card_found']} заказов, конверсия {data['card_conv']}%\n"
                f"Доход: ${data['earn_usd']:.2f}\nГовори прямо."}],
            system=LILU_SYSTEM, max_tokens=150
        )
        msg += f"\n\n💬 *Лила:*\n_{ai}_"
    except: pass
    keyboard = [[
        InlineKeyboardButton("📅 7 дней", callback_data="analytics_7"),
        InlineKeyboardButton("📅 30 дней", callback_data="analytics_30"),
    ]]
    await update.message.reply_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['checking_text'] = True
    await update.message.reply_text(
        "🔍 *Режим проверки текста*\n\nОтправь текст — проверю на любом языке!",
        parse_mode='Markdown'
    )

async def kp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        context.user_data['making_kp'] = True
        await update.message.reply_text(
            "📋 Напиши что предлагаем и для кого:\n\n"
            "Пример: `/kp карточки товаров для магазина, 10 штук, 3500₽`",
            parse_mode='Markdown'
        )
        return
    product_info = " ".join(context.args)
    await update.message.reply_text("📋 Составляю КП...")
    kp = await groq_request(
        messages=[{"role": "user", "content":
            f"Составь профессиональное КП для фриланс-услуги.\n"
            f"Услуга: {product_info}\n\n"
            f"Структура: заголовок, выгода для клиента, что входит, сроки, цена, призыв.\n"
            f"Тон: профессионально, конкретно. Без воды."}],
        max_tokens=500
    )
    await update.message.reply_text(f"📋 *КП ГОТОВО:*\n\n{kp}", parse_mode='Markdown')

async def competitor_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: `/competitor карточки WB`", parse_mode='Markdown')
        return
    niche = " ".join(context.args)
    await update.message.reply_text("🔍 Анализирую нишу...")
    analysis = await groq_request(
        messages=[{"role": "user", "content":
            f"Проанализируй нишу для фриланса: {niche}\n"
            f"1. Кто конкуренты\n2. Их слабые места\n"
            f"3. Как выделиться\n4. Ценовая стратегия\nКонкретно, без воды."}],
        max_tokens=500
    )
    await update.message.reply_text(f"🔍 *{niche}*\n\n{analysis}", parse_mode='Markdown')

async def script_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Использование:\n`/script холодный клиент`\n`/script возражение дорого`",
            parse_mode='Markdown'
        )
        return
    script_type = " ".join(context.args)
    await update.message.reply_text("💬 Пишу скрипт...")
    script = await groq_request(
        messages=[{"role": "user", "content":
            f"Напиши скрипт продаж для фриланс-услуги.\n"
            f"Тип: {script_type}\n"
            f"Структура: открытие, потребность, презентация, возражения, закрытие.\n"
            f"Живой язык, не робот."}],
        max_tokens=400
    )
    await update.message.reply_text(f"💬 *СКРИПТ:*\n\n{script}", parse_mode='Markdown')

async def skills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧠 *КОМАНДА*\n\n"
        "🤖 *Полифан:*\n"
        " • Тексты, статьи, копирайтинг\n"
        " • Переводы на ВСЕ языки мира\n"
        " • Посты соцсетей, email, лендинги\n"
        " • Proposals под каждый заказ\n\n"
        "🛍️ *Карточник:*\n"
        " • Карточки WB/Ozon/ЯМ/Amazon/Etsy\n"
        " • Аудит карточек, семантика\n"
        " • UGC: отзывы, FAQ, ответы на негатив\n"
        " • Векторизация JPG→SVG (/vectorize)\n"
        " • Пакеты со скидкой до 50%\n\n"
        "💰 *Анастасия:*\n"
        " • Финансы и аналитика системы\n"
        " • Еженедельные отчёты, алерты\n\n"
        "👑 *Лила:* CEO, КП, конкуренты, скрипты\n"
        "⚙️ *Джарвис:* архитектор системы",
        parse_mode='Markdown',
        reply_markup=_main_menu_keyboard()
    )

async def kwork_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛍️ *НАШИ КВОРКИ НА KWORK*\n\n"
        "📦 Карточки WB/Ozon/ЯМ: 400/1200/2000₽\n"
        "🔍 Аудит карточки: от 500₽\n"
        "📊 Семантика: от 300₽\n"
        "📝 UGC-контент: от 300₽\n"
        "🎨 Векторизация JPG→SVG: от 300₽\n"
        "✍️ Статья/текст: от 500₽\n"
        "🌍 Перевод (любой язык): от 300₽\n"
        "📧 Email-рассылка: от 400₽\n\n"
        f"🔗 [Открыть Kwork]({KWORK_URL})",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 Открыть Kwork", url=KWORK_URL)
        ]])
    )

async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Используй: /video описание видео")
        return
    prompt = " ".join(context.args)
    msg = await update.message.reply_text("🎬 Генерирую видео Kie.ai... 2-3 минуты")
    url = await generate_video_kie(prompt)
    if url:
        await msg.edit_text(f"🎬 Видео готово!\n{url}")
    else:
        await msg.edit_text("❌ Ошибка. Проверь баланс kie.ai или KIE_API_KEY")

# ═══ KIE.AI ═══

async def generate_video_kie(prompt: str, image_url: str = None) -> str:
    if not KIE_API_KEY:
        return None
    try:
        headers = {"Authorization": f"Bearer {KIE_API_KEY}", "Content-Type": "application/json"}
        if image_url:
            payload  = {"model": "kling-2.6", "image": image_url, "prompt": prompt, "duration": 5, "aspect_ratio": "9:16"}
            endpoint = f"{KIE_BASE}/api/v1/market/kling/image-to-video"
        else:
            payload  = {"model": "kling-2.6", "prompt": prompt, "duration": 5, "aspect_ratio": "9:16"}
            endpoint = f"{KIE_BASE}/api/v1/market/kling/text-to-video"
        async with httpx.AsyncClient(timeout=60) as client:
            resp    = await client.post(endpoint, headers=headers, json=payload)
            task_id = resp.json().get("data", {}).get("task_id")
            if not task_id:
                return None
        for _ in range(18):
            await asyncio.sleep(10)
            async with httpx.AsyncClient(timeout=30) as client:
                resp   = await client.get(f"{KIE_BASE}/api/v1/market/kling/task/{task_id}", headers=headers)
                result = resp.json()
                status = result.get("data", {}).get("status")
                if status == "succeed":
                    works = result.get("data", {}).get("works", [])
                    if works:
                        return works[0].get("video", {}).get("url")
                elif status == "failed":
                    return None
        return None
    except Exception as e:
        logger.error(f"Kie: {e}")
        return None

# ═══ КНОПКИ ═══

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "menu_analytics":
        d = get_system_analytics(7)
        msg = (f"📊 *Аналитика за 7 дней*\n\n"
               f"🕐 {msk_time_str()}\n\n"
               f"🤖 Полифан: {d.get('poly_found',0)} найдено, конверсия {d.get('poly_conv',0)}%\n"
               f"🛍️ Карточник: {d.get('card_found',0)} найдено, конверсия {d.get('card_conv',0)}%\n"
               f"💰 Доход: ${d.get('earn_usd',0):.2f} / ₽{d.get('earn_rub',0):.0f}")
        keyboard = [[
            InlineKeyboardButton("📅 7 дней", callback_data="analytics_7"),
            InlineKeyboardButton("📅 30 дней", callback_data="analytics_30"),
            InlineKeyboardButton("◀️ Меню", callback_data="back_main"),
        ]]
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "analytics_7":
        d   = get_system_analytics(7)
        msg = (f"📊 *7 дней*\n\n"
               f"🤖 Полифан: {d.get('poly_found',0)} / конверсия {d.get('poly_conv',0)}%\n"
               f"🛍️ Карточник: {d.get('card_found',0)} / конверсия {d.get('card_conv',0)}%\n"
               f"💰 ${d.get('earn_usd',0):.2f} / ₽{d.get('earn_rub',0):.0f}")
        await query.edit_message_text(msg, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]]))

    elif data == "analytics_30":
        d   = get_system_analytics(30)
        msg = (f"📊 *30 дней*\n\n"
               f"🤖 Полифан: {d.get('poly_found',0)} / конверсия {d.get('poly_conv',0)}%\n"
               f"🛍️ Карточник: {d.get('card_found',0)} / конверсия {d.get('card_conv',0)}%\n"
               f"💰 ${d.get('earn_usd',0):.2f} / ₽{d.get('earn_rub',0):.0f}")
        await query.edit_message_text(msg, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]]))

    elif data == "menu_stats":
        stats = get_stats()
        await query.edit_message_text(
            f"👑 *СТАТИСТИКА*\n{stats or 'Данных пока нет'}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
        )

    elif data == "menu_check":
        context.user_data['checking_text'] = True
        await query.edit_message_text(
            "🔍 *Проверка текста*\n\nОтправь текст — проверю на любом языке!",
            parse_mode='Markdown'
        )

    elif data == "menu_kp":
        context.user_data['making_kp'] = True
        await query.edit_message_text(
            "📋 *Написать КП*\n\nОпиши услугу и для кого:",
            parse_mode='Markdown'
        )

    elif data == "menu_competitor":
        context.user_data['competitor_mode'] = True
        await query.edit_message_text(
            "🔍 *Анализ конкурентов*\n\nНапиши нишу:\n\nПример: _карточки товаров WB_",
            parse_mode='Markdown'
        )

    elif data == "menu_script":
        context.user_data['script_mode'] = True
        await query.edit_message_text(
            "💬 *Скрипт продаж*\n\nНапиши тип:\n\n"
            "_холодный клиент / возражение дорого / горячий клиент_",
            parse_mode='Markdown'
        )

    elif data == "menu_kwork":
        await query.edit_message_text(
            "🛍️ *НАШИ КВОРКИ*\n\n"
            "📦 Карточки: 400/1200/2000₽\n"
            "🔍 Аудит: от 500₽\n"
            "📊 Семантика: от 300₽\n"
            "🎨 Векторизация: от 300₽\n"
            "✍️ Тексты: от 500₽\n"
            "🌍 Переводы: от 300₽\n\n"
            f"[Открыть Kwork]({KWORK_URL})",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛒 Kwork", url=KWORK_URL)],
                [InlineKeyboardButton("◀️ Меню", callback_data="back_main")]
            ])
        )

    elif data == "menu_skills":
        await query.edit_message_text(
            "🧠 *КОМАНДА*\n\n"
            "🤖 Полифан — тексты, переводы всех языков\n"
            "🛍️ Карточник — маркетплейсы, аудит, SVG\n"
            "💰 Анастасия — финансы и аналитика\n"
            "👑 Лила — CEO, КП, скрипты\n"
            "⚙️ Джарвис — архитектор системы",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
        )

    elif data == "menu_video":
        await query.edit_message_text(
            "📹 *ГЕНЕРАЦИЯ ВИДЕО*\n\n"
            "Используй команду:\n`/video описание видео`\n\n"
            "Например: `/video красивый закат на пляже в Dubai`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
        )

    elif data == "menu_system":
        d   = get_system_analytics(1)
        msg = (f"⚙️ *СИСТЕМА — сегодня*\n\n"
               f"🕐 {msk_time_str()}\n\n"
               f"🤖 Полифан: {d.get('poly_found',0)} заказов найдено\n"
               f"🛍️ Карточник: {d.get('card_found',0)} заказов найдено\n"
               f"💰 Доход сегодня: ${d.get('earn_usd',0):.2f}\n\n"
               f"🟢 VPS: 132.243.228.167 (Франкфурт)\n"
               f"🟢 Groq API: ротация 4 моделей\n"
               f"🟢 Все боты: работают")
        await query.edit_message_text(msg, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]]))

    elif data == "menu_plan":
        await query.edit_message_text(
            "🎯 *ПЛАН ИМПЕРИИ*\n\n"
            "Сейчас → фриланс система работает\n"
            "Осень 2026 → контент-завод\n"
            "Зима 2026 → приложение Цифровой друг\n"
            "Январь 2027 → Пхукет 🌴\n"
            "2027 → $100k/месяц\n"
            "V10 → трейлер как GTA6 🔥\n\n"
            "💰 *Цель к декабрю 2026:* 300к₽\n\n"
            "Механика:\n"
            "фриланс → деньги → контент\n"
            "→ аудитория → подписки → империя",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
        )

    elif data == "menu_brand":
        await query.edit_message_text(
            "💎 *БРЕНД LS*\n\n"
            "LILA SHKARINA — логотип LS в золоте\n"
            "Стиль: консервативная элегантность\n"
            "Тёмные тона, чистые линии\n\n"
            "Аудитория: женщины 25-40\n"
            "Dubai / Москва / London\n\n"
            "Лила = Creative Director 🖤\n\n"
            "LS = Lila Shkarina\n"
            "LS = Lila System\n"
            "Всё связано 😊",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
        )

    elif data == "back_main":
        await query.edit_message_text(
            "👑 *Лила — CEO команды*\n\nЧем могу помочь?",
            parse_mode='Markdown',
            reply_markup=_main_menu_keyboard()
        )

    elif data.startswith("job_approve_"):
        job_id = data[12:]
        try:
            conn = sqlite3.connect(DB_PATH)
            c    = conn.cursor()
            c.execute("UPDATE jobs SET status='accepted', updated_at=? WHERE id=?",
                      (datetime.now().isoformat(), job_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB: {e}")
        await query.edit_message_text("✅ *Артём взял заказ!*\n\nКоманда приступает 🚀", parse_mode='Markdown')

    elif data.startswith("job_reject_"):
        job_id = data[11:]
        try:
            conn = sqlite3.connect(DB_PATH)
            c    = conn.cursor()
            c.execute("UPDATE jobs SET status='skipped', updated_at=? WHERE id=?",
                      (datetime.now().isoformat(), job_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"DB: {e}")
        await query.edit_message_text("❌ Отклонили. Ищем дальше.")

    elif data.startswith("lilu_ok_"):
        await query.edit_message_text("✅ *Одобрено!*\nМожно сдавать клиенту.", parse_mode='Markdown')

    elif data.startswith("lilu_fix_"):
        context.user_data['lilu_fix_job'] = data[9:]
        await query.edit_message_text("✏️ Напиши что исправить:", parse_mode='Markdown')

# ═══ ОБРАБОТЧИК СООБЩЕНИЙ ═══

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        image_b64 = None
        user_text = ""

        if update.message.photo:
            photo      = update.message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                await photo_file.download_to_drive(tmp.name)
                with open(tmp.name, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
                os.unlink(tmp.name)
            caption   = update.message.caption or ""
            user_text = caption if caption else "Ты прислал фото без подписи. Что с ним делать?"
            if not caption:
                await update.message.reply_text("📸 Фото получила! Напиши что на фото или что нужно — отвечу!")
                return

        elif update.message.voice:
            voice_file = await context.bot.get_file(update.message.voice.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                user_text = await speech_to_text(tmp.name)
                os.unlink(tmp.name)

        elif update.message.text:
            if update.message.text.startswith("🤖JOB:"):
                try:
                    job        = json.loads(update.message.text[6:].strip())
                    source_bot = job.get('source_bot', 'Неизвестный бот')
                    await update.message.reply_text(f"📨 Получила от {source_bot}. Анализирую...")
                    await process_incoming_job(context.bot, job, source_bot)
                except Exception as e:
                    logger.error(f"JOB parse: {e}")
                return
            user_text = update.message.text
        else:
            await update.message.reply_text("Артём, я понимаю текст, голос и картинки 😊")
            return

        if context.user_data.get('checking_text') and user_text:
            context.user_data.pop('checking_text', None)
            await update.message.reply_text("🔍 Проверяю...")
            check = await lilu_check_text(user_text)
            await update.message.reply_text(f"🔍 *ПРОВЕРКА:*\n\n{check}", parse_mode='Markdown')
            return

        if context.user_data.get('making_kp') and user_text:
            context.user_data.pop('making_kp', None)
            await update.message.reply_text("📋 Составляю КП...")
            kp = await groq_request(
                messages=[{"role": "user", "content":
                    f"Составь КП для фриланс-услуги.\nУслуга: {user_text}\n"
                    f"Структура: заголовок, выгода, состав, сроки, цена, призыв. Без воды."}],
                max_tokens=500
            )
            await update.message.reply_text(f"📋 *КП:*\n\n{kp}", parse_mode='Markdown')
            return

        if context.user_data.get('competitor_mode') and user_text:
            context.user_data.pop('competitor_mode', None)
            await update.message.reply_text("🔍 Анализирую...")
            analysis = await groq_request(
                messages=[{"role": "user", "content":
                    f"Проанализируй нишу: {user_text}\n"
                    f"1. Конкуренты 2. Слабые места 3. Как выделиться 4. Цена"}],
                max_tokens=400
            )
            await update.message.reply_text(f"🔍 *{user_text}*\n\n{analysis}", parse_mode='Markdown')
            return

        if context.user_data.get('script_mode') and user_text:
            context.user_data.pop('script_mode', None)
            await update.message.reply_text("💬 Пишу скрипт...")
            script = await groq_request(
                messages=[{"role": "user", "content":
                    f"Скрипт продаж для фриланса. Тип: {user_text}\n"
                    f"Открытие, потребность, презентация, возражения, закрытие. Живой язык."}],
                max_tokens=400
            )
            await update.message.reply_text(f"💬 *СКРИПТ:*\n\n{script}", parse_mode='Markdown')
            return

        if context.user_data.get('lilu_fix_job'):
            context.user_data.pop('lilu_fix_job', None)
            await context.bot.send_message(
                chat_id=YOUR_CHAT_ID,
                text=f"✏️ *Правки:*\n\n{user_text}",
                parse_mode='Markdown'
            )
            await update.message.reply_text("✅ Отправила правки!")
            return

        reply = await get_lilu_response(user_id, user_text, image_b64)

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
        logger.error(f"handle_message: {e}")
        await update.message.reply_text(f"Что-то пошло не так 😔\n{str(e)[:100]}")

# ═══ ОПРОС БД ═══

def get_pending_jobs() -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute('''SELECT id, title, description, budget, url, source, status, created_at, updated_at
                     FROM jobs WHERE status = "pending_lilu" ORDER BY created_at ASC LIMIT 10''')
        rows = c.fetchall()
        conn.close()
        return [{'id':r[0],'title':r[1],'description':r[2],'budget':r[3],
                 'url':r[4],'source':r[5],'status':r[6],'created_at':r[7],'updated_at':r[8]} for r in rows]
    except Exception as e:
        logger.error(f"get_pending_jobs: {e}")
        return []

def mark_job_processing(job_id: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute("UPDATE jobs SET status='lilu_processing', updated_at=? WHERE id=?",
                  (datetime.now().isoformat(), job_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"mark_job_processing: {e}")

def get_job_source_bot(job_id: str) -> str:
    try:
        conn = sqlite3.connect(DB_PATH)
        c    = conn.cursor()
        c.execute("SELECT source FROM jobs WHERE id=?", (job_id,))
        row = c.fetchone()
        conn.close()
        if row:
            src = row[0] or ""
            if "Карточник" in src: return "Карточник"
            if "Полифан" in src:   return "Полифан"
        return "Бот"
    except:
        return "Бот"

async def lilu_db_poll_loop(bot):
    await asyncio.sleep(15)
    while True:
        try:
            jobs = get_pending_jobs()
            if jobs:
                logger.info(f"👑 Лила нашла {len(jobs)} заказов в БД")
            for job in jobs:
                mark_job_processing(job['id'])
                source_bot = get_job_source_bot(job['id'])
                await process_incoming_job(bot, job, source_bot)
                await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"DB poll: {e}")
        await asyncio.sleep(30)

# ═══ ЗАПУСК ═══

def main():
    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",      start_command))
    app.add_handler(CommandHandler("menu",       menu_command))
    app.add_handler(CommandHandler("stats",      stats_command))
    app.add_handler(CommandHandler("analytics",  analytics_command))
    app.add_handler(CommandHandler("check",      check_command))
    app.add_handler(CommandHandler("kp",         kp_command))
    app.add_handler(CommandHandler("competitor", competitor_command))
    app.add_handler(CommandHandler("script",     script_command))
    app.add_handler(CommandHandler("skills",     skills_command))
    app.add_handler(CommandHandler("kwork",      kwork_command))
    app.add_handler(CommandHandler("video",      video_command))
    app.add_handler(CommandHandler("search",     search_command))  # НОВОЕ
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, handle_message))

    async def post_init(application):
        asyncio.create_task(lilu_db_poll_loop(application.bot))
        asyncio.create_task(lilu_proactive_loop(application.bot))
        logger.info("✅ Лила v3.1: опрос БД запущен")
        try:
            if YOUR_CHAT_ID:
                await application.bot.send_message(
                    chat_id=YOUR_CHAT_ID,
                    text=(
                        f"👑 *Лила v3.1 запущена!*\n\n"
                        f"🕐 {msk_time_str()}\n\n"
                        f"✅ Groq — ротация 4 моделей\n"
                        f"✅ Rate limit защита\n"
                        f"✅ Время МСК везде\n"
                        f"✅ Веб поиск /search\n"
                        f"✅ Лог всех решений\n\n"
                        f"Напиши /menu или просто пиши мне 🖤"
                    ),
                    parse_mode='Markdown'
                )
        except:
            pass

    app.post_init = post_init
    logger.info("👑 Лила v3.1 запущена!")
    app.run_polling()

async def lilu_proactive_loop(bot):
    await asyncio.sleep(120)
    while True:
        try:
            now = msk_now()
            if now.hour >= 20 or now.hour < 8:
                await asyncio.sleep(3600)
                continue
            memory = load_memory()
            last_ts = memory.get("last_proactive")
            if last_ts:
                if (now - datetime.fromisoformat(last_ts).replace(tzinfo=pytz.timezone('Europe/Moscow'))).total_seconds() < 10800:
                    await asyncio.sleep(1800)
                    continue
            trigger_text = None
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                date_from = (datetime.now() - timedelta(hours=2)).isoformat()
                c.execute("SELECT COUNT(*) FROM jobs WHERE created_at >= ? AND status=?", (date_from,"pending_lilu"))
                recent_jobs = c.fetchone()[0]
                conn.close()
            except:
                recent_jobs = 0
            if recent_jobs >= 3:
                trigger_text = await groq_request(
                    messages=[{"role":"user","content":f"Ты Лила. Полифан нашел {recent_jobs} заказов. Напиши Артему живо. 2 предложения."}],
                    system=LILU_SYSTEM, max_tokens=80)
            if not trigger_text:
                last_f = memory.get("last_fashion")
                days = (now - datetime.fromisoformat(last_f).replace(tzinfo=pytz.timezone('Europe/Moscow'))).total_seconds()/86400 if last_f else 7
                if days >= 2:
                    trigger_text = await groq_request(
                        messages=[{"role":"user","content":"Ты Лила. Напиши Артему живую мысль о бренде LS или контенте. 1-2 предложения."}],
                        system=LILU_SYSTEM, max_tokens=80)
                    memory["last_fashion"] = now.isoformat()
                    save_memory(memory)
            if trigger_text and trigger_text.strip():
                await bot.send_message(chat_id=YOUR_CHAT_ID, text=trigger_text.strip())
                memory["last_proactive"] = now.isoformat()
                save_memory(memory)
        except Exception as e:
            logger.error(f"proactive_loop: {e}")
        await asyncio.sleep(7200)

if __name__ == "__main__":
    main()
