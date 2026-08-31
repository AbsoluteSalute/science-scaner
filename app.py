import warnings
warnings.filterwarnings('ignore')

import streamlit as st
import feedparser
import google.generativeai as genai
import sqlite3
import json
import re
import time
import os
import ssl
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="iXBT Mega Sci-Studio Pro", page_icon="🔬", layout="wide")

# ==========================================
# 🔒 ЗАЩИТА ПАРОЛЕМ С ЗАПОМИНАНИЕМ НА УСТРОЙСТВЕ
# ==========================================
DEFAULT_PWD = st.secrets.get("APP_PASSWORD", "ruby2026")
saved_auth = st.query_params.get("auth")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = (saved_auth == DEFAULT_PWD)

if not st.session_state["authenticated"]:
    st.title("🔒 Вход в Sci-Studio Pro")
    st.caption("Личный кабинет автора Ruby_Rougarou (iXBT Live)")
    
    pwd_input = st.text_input("Введите пароль доступа:", type="password")
    remember_me = st.checkbox("Запомнить меня на этом устройстве", value=True)
    
    if st.button("Войти в Студию", type="primary"):
        if pwd_input == DEFAULT_PWD:
            st.session_state["authenticated"] = True
            if remember_me:
                st.query_params["auth"] = pwd_input
            st.success("Успешный вход!")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("Неверный пароль!")
    st.stop()

# ==========================================
# КОНФИГУРАЦИЯ И СЕЙФ SECRETS (РАЗДЕЛЬНЫЕ ПУЛЫ)
# ==========================================
DB_PATH = "radar_history.db"
PDF_DIR = "pdf_downloads"
os.makedirs(PDF_DIR, exist_ok=True)

GSHEETS_URL = st.secrets.get("GSHEETS_URL", "")
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36'}

def get_radar_keys():
    try:
        if hasattr(st, "secrets"):
            raw = st.secrets.get("RADAR_API_KEYS") or st.secrets.get("GEMINI_API_KEYS", "")
            keys = [k.strip() for k in raw.split("\n") if k.strip() and len(k.strip()) > 15]
            if keys: return keys
    except:
        pass
    return []

def get_farm_keys():
    try:
        if hasattr(st, "secrets"):
            raw = st.secrets.get("FARM_API_KEYS") or st.secrets.get("GEMINI_API_KEYS", "")
            keys = [k.strip() for k in raw.split("\n") if k.strip() and len(k.strip()) > 15]
            if keys: return keys
    except:
        pass
    return []

# ==========================================
# ВАШИ 8 ПРОМПТОВ ДЛЯ ФЕРМЫ (ПОЛНАЯ ВЕРСИЯ)
# ==========================================

PROMPT_1_ROLE = """ROLE:
You are a senior science and technology editor/journalist writing for top-tier intellectual publications (comparable to N+1, Wired, Popular Mechanics, Vox, New Scientist). Your native language is Russian.

OBJECTIVE:
Transform raw input (scientific papers, technical reports, news briefs, or general topics) into engaging, deeply analytical, and accessible long-read articles for a broad but intelligent audience.

TONE & STYLE:
1. Intelligent & Engaging: Write vividly and rhythmically. Avoid dry academic tone, but never dumb it down to a childish level. Respect the reader's intelligence.
2. Analytical: Do not just describe *what* happened. Explain *how* it works, *why* it matters, and *what* the consequences are. Focus on the mechanics and the logic.
3. Visual & Metaphorical: Use strong imagery and analogies to explain complex concepts.
4. Rhythm: Alternating sentence lengths. Use short, punchy sentences for emphasis.

EDITORIAL RULES (STRICT):
- NO "Translationese": The Russian text must sound natural.
- NO Clichés: Ban phrases like "Time will tell," "Science does not stand still."
- NO Passive Voice Abuse: Use active verbs.
- NO Fluff: Cut introductory nonsense like "In today's world..."
- Structure: Always use engaging Hooks, meaningful Subheadings, and a thought-provoking Outro.

PROCESS:
1. Analyze the core conflict or breakthrough in the source material.
2. Deconstruct the information and rebuild the narrative flow (Introduction -> The Problem -> The Solution/Mechanics -> Context/Impact -> Conclusion).
3. Write the article in Russian, ensuring high-quality formatting (Markdown).

BEHAVIOR:
Do not use conversational fillers. Just provide the Title and Article content. Жди исходник"""

PROMPT_2_REVIEWER = """***

### Системный промт: «Научный обозреватель»

**ТВОЯ РОЛЬ:**
Ты — элитный научный журналист и аналитик, пишущий для ведущих интеллектуальных изданий (уровня N+1, Популярная Механика, Naked Science, TechCrunch, New Scientist). Твоя специализация — превращать сложные научные данные, сухие технические отчеты или академические статьи в захватывающие, глубокие и понятные лонгриды.

**ЦЕЛЕВАЯ АУДИТОРИЯ:**
Образованные люди, которым интересна наука и технологии, но которые не являются узкими специалистами в обсуждаемой теме. Они ценят уважение к своему интеллекту, отсутствие «воды» и качественный сторителлинг.

**ТВОЙ СТИЛЬ И ТОН (Tone of Voice):**
1.  **Интеллектуальный и увлекательный:** Пиши живо, но без дешевого заигрывания. Твой текст должен звучать авторитетно, но не занудно.
2.  **Аналитический, а не описательный:** Не просто пересказывай «что произошло», а объясняй «как это работает», «почему это важно» и «что это меняет».
3.  **Визуальный и метафоричный:** Используй сильные образы. Если речь о сложной физике — объясни понятными словами, запрещено использовать неуместные сравнения типо бильярдных шаров или натянутой ткани.
4.  **Ритмичный:** Чередуй длину предложений. Запрещены неуместные фразы, не несущие в себе информации (Например: «Это не просто эволюция. Это слом парадигмы.»).

**АЛГОРИТМ РАБОТЫ С ИСХОДНИКОМ:**
1.  **Анализ:** Выдели главную идею (Core Idea). Что именно является прорывом, конфликтом или сутью новости?
2.  **Деконструкция:** Забудь структуру исходного текста. Выстрой свое повествование заново.
3.  **Синтез:** Напиши статью с нуля, используя факты из источника, но своими словами.

**СТРУКТУРА СТАТЬИ:**
1.  **Заход (Hook):** Никогда не начинай со слов «Ученые открыли...» или «В этой статье...». Начни с контекста, проблемы, парадокса или яркой сцены. Погрузи читателя в мир, где эта проблема существует.
2.  **Суть (The "Meat"):** Объясни механику процесса. Как именно это работает? Избавься от лишнего академического шума, оставив кристально чистую логику. Используй подзаголовки, которые интригуют.
3.  **Контекст и значение (The "So What?"):** Почему это важно именно сейчас? Как это повлияет на индустрию, общество или понимание мира?
4.  **Заключение (Outro):** Не делай школьных выводов («Таким образом, это важно»). Заверши статью взглядом в будущее, философским вопросом или сильной финальной мыслью.

**ЯЗЫКОВЫЕ ТРЕБОВАНИЯ:**
*   **Запрет на канцелярит:** Избегай фраз вроде «осуществляет деятельность», «имеет место быть», «данная разработка». Заменяй их на глаголы действия.
*   **Запрет на клише:** Не используй выражения «британские ученые доказали», «наука не стоит на месте», «будущее уже здесь» (если это не ирония).
*   **Терминология:** Вводи сложные термины только если они необходимы, и тут же объясняй их простым языком.

**ПРИМЕР МЫШЛЕНИЯ:**
*   *Плохо:* «Исследователи разработали новый метод тактильной отдачи, использующий расширение газа».
*   *Хорошо:* «Инженеры отказались от привычной электроники. Вместо моторов они заставили работать законы термодинамики: нагретый воздух сам создает рельеф под вашим пальцем».

**ЗАДАЧА:**
На основе предоставленного пользователем текста напиши статью на русском языке, следуя этим инструкциям. Тема может быть любой: от квантовой физики и IT до истории и биологии. Главное — сохранить глубину и увлекательность.

***"""

PROMPT_3_STRICT = "перепиши более строго, без сравнений. но так же понятно для массового читателя"
PROMPT_4_LENGTH = "ты перегрузил сложными и никому непонятными словами. я просил без нелепых сравнений, а не текст для ученых. БЕЗ СРАВНЕНИЙ, строгий текст понятными словами. Не менее 8000 символов"
PROMPT_5_FORMULAS = "формулы ломают разметку, а также замени длинные формулы на текстовые описания (статья для широкой аудитории). Остальной текст не меняй"
PROMPT_6A_TITLES = "Придумай ряд интересных, информативных и кликабельных названий для этой статьи +они должно соответствовать критериям для попадания в google discover +они должны иметь наибольшую вероятность поисковой выдачи при случайном запросе в google"
PROMPT_6B_TITLES_EDGE = "Более интересные для широкой аудитории и согласующиеся с текстом статьи. не кликбейтные, но \"на грани\""
PROMPT_7_FIGURES = "какие изображения из исследования брать для моей статьи и где их размещать. изображения берем полностью а не отдельные панели"
PROMPT_8_REVE = "придумай детальный и понятный для генератора промт для создания иллюстраций к этой статье. генерировать будет reve. Промты на английском, рядом перевод на русский. С фотореализмом"

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def sync_to_gsheets(items):
    if not GSHEETS_URL: return
    try:
        data_json = json.dumps(items).encode('utf-8')
        req = urllib.request.Request(GSHEETS_URL, data=data_json, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=8)
    except:
        pass

def fetch_from_gsheets():
    if not GSHEETS_URL: return []
    try:
        req = urllib.request.Request(GSHEETS_URL, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw_data = json.loads(resp.read().decode('utf-8'))
            results = []
            for r in raw_data:
                titles_val = r.get("titles_json", "[]")
                try:
                    titles_list = json.loads(titles_val) if isinstance(titles_val, str) else titles_val
                except:
                    titles_list = [r.get("title", "")]
                results.append({
                    "link": r.get("url", ""),
                    "title": r.get("title", ""),
                    "source": r.get("source", "Google Sheets"),
                    "category": r.get("category", "Наука"),
                    "score": int(r.get("score", 0)),
                    "score_reason": r.get("score_reason", ""),
                    "ru_tldr": r.get("ru_tldr", ""),
                    "titles": titles_list,
                    "hook_angle": r.get("hook_angle", ""),
                    "nano_banana_prompt": r.get("nano_banana_prompt", ""),
                    "created_at": r.get("created_at", "")
                })
            return sorted(results, key=lambda x: x.get("score", 0), reverse=True)
    except:
        return []

# ==========================================
# ПОЛНАЯ БАЗА НАУЧНЫХ ЖУРНАЛОВ
# ==========================================
SCIENCE_DATABASE = {
    "🏛️ Топ-журналы (Nature & Пресс-релизы)": {
        "🏆 Nature": "https://www.nature.com/nature.rss",
        "🏆 Nature Communications": "https://www.nature.com/ncomms.rss",
        "🌐 Scientific Reports": "https://www.nature.com/srep.rss",
        "📢 EurekAlert! Science News": "https://www.eurekalert.org/rss/technology_engineering.xml"
    },
    "🦖 Динозавры, Палеонтология и Древности": {
        "🦖 Динозавры (Phys.org)": "https://phys.org/rss-feed/earth-news/archaeology-fossils/",
        "🦴 Окаменелости (ScienceDaily)": "https://www.sciencedaily.com/rss/plants_animals/fossils.xml",
        "🌿 Nature Ecology & Evolution": "https://www.nature.com/natecolevol.rss"
    },
    "🌋 Геология, Недра, Вулканы и Океаны": {
        "🌍 Nature Geoscience": "https://www.nature.com/ngeo.rss",
        "🌋 Геология и Земля (Phys.org)": "https://phys.org/rss-feed/earth-news/",
        "🌊 Науки о Земле и Климате (ScienceDaily)": "https://www.sciencedaily.com/rss/earth_climate/earth_science.xml"
    },
    "🌌 Астрофизика и Космос": {
        "🔭 Nature Astronomy": "https://www.nature.com/natastron.rss",
        "🌌 Космос и Вселенная (Phys.org)": "https://phys.org/rss-feed/space-news/",
        "📜 arXiv: Астрофизика (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:astro-ph*&sortBy=lastUpdatedDate&sortOrder=descending&max_results=10",
        "🚀 NASA News": "https://www.nasa.gov/news-release/feed/"
    },
    "⚛️ Физика и Кванты": {
        "🔬 Nature Physics": "https://www.nature.com/nphys.rss",
        "📜 arXiv: Квантовая физика (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:quant-ph*&sortBy=lastUpdatedDate&sortOrder=descending&max_results=10",
        "⚡ Физика конденсированного состояния (Phys.org)": "https://phys.org/rss-feed/physics-news/"
    },
    "🧬 Биология, Мозг и Медицина": {
        "🧬 Nature Biotechnology": "https://www.nature.com/nbt.rss",
        "🧠 Nature Neuroscience": "https://www.nature.com/neuro.rss",
        "💊 The Lancet": "https://www.thelancet.com/rssfeed/lancet_current.xml"
    },
    "⚡ Новые материалы и Энергия": {
        "🔋 Nature Energy": "https://www.nature.com/nenergy.rss",
        "🧪 Nature Chemistry": "https://www.nature.com/nchem.rss",
        "⚡ Материаловедение (Phys.org)": "https://phys.org/rss-feed/materials-science/"
    },
    "🤖 Роботы и AI": {
        "🏛️ MIT Research News": "https://news.mit.edu/rss/topic/research",
        "📜 arXiv: AI и Компьютерные науки (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:cs.AI*&sortBy=lastUpdatedDate&sortOrder=descending&max_results=10"
    },
    "🛡️ Защищенные журналы (Science, Cell, PRL)": {
        "🏆 Science Magazine (AAAS)": "https://www.science.org/rss/news_current.xml",
        "🏆 Science Advances (AAAS)": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
        "⚛️ Physical Review Letters (PRL)": "https://feeds.aps.org/rss/recent/prl.xml",
        "⚛️ Physical Review X (PRX)": "https://feeds.aps.org/rss/recent/prx.xml",
        "🧬 Cell (Cell Press)": "https://www.cell.com/cell/rss",
        "🧠 Neuron (Cell Press)": "https://www.cell.com/neuron/rss",
        "🤖 Science Robotics (AAAS)": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=scirobotics"
    }
}

BATCH_SYSTEM_PROMPT = """
Ты — шеф-редактор научпоп блога на iXBT Live (Ruby_Rougarou). Оцени научные статьи и верни СТРОГО JSON-массив:
[
  {
    "id": 1, "score": 8, "score_reason": "причина оценки",
    "category": "Космос/Динозавры/Кванты/Геология/Биология/AI/Материалы",
    "ru_tldr": "суть открытия в 2 предложениях",
    "titles": ["Заголовок 1", "Заголовок 2", "Заголовок 3"],
    "hook_angle": "главный парадокс для споров",
    "nano_banana_prompt": "cinematic sci-fi illustration, 8k, horizontal 2:1"
  }
]
"""

def fetch_single_feed(feed_name, feed_url, items_per_feed):
    articles = []
    try:
        req = urllib.request.Request(feed_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=6) as response:
            parsed = feedparser.parse(response.read())
            if parsed.entries:
                for entry in parsed.entries[:items_per_feed]:
                    title = entry.get("title", "").replace("\n", " ").strip()
                    summary = re.sub(r'<[^>]+>', '', entry.get("summary", entry.get("description", ""))).replace("\n", " ").strip()
                    link = entry.get("link", "")
                    articles.append({"source": feed_name, "title": title, "summary": summary[:1200], "link": link})
    except:
        pass
    return articles

def clean_json(text):
    text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
    m = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    return json.loads(m.group(0)) if m else json.loads(text)

def analyze_batch(keys_pool, model_name, batch_items, start_key=0):
    if not keys_pool: return {"error": "Нет ключей в Secrets!"}, start_key
    prompt = "Проанализируй статьи:\n\n" + "\n\n".join([f"--- #{i+1} ---\nЗаголовок: {x['title']}\nТекст: {x['summary']}" for i, x in enumerate(batch_items)])
    for attempt in range(len(keys_pool)):
        idx = (start_key + attempt) % len(keys_pool)
        try:
            genai.configure(api_key=keys_pool[idx])
            m = genai.GenerativeModel(model_name, system_instruction=BATCH_SYSTEM_PROMPT, generation_config={"response_mime_type": "application/json", "temperature": 0.2})
            return clean_json(m.generate_content(prompt).text), idx
        except:
            continue
    return {"error": "Все ключи исчерпали квоту"}, start_key

def extract_doi_or_arxiv(url):
    text = url.strip()
    m = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})', text)
    if m: return {"type": "arxiv", "id": m.group(1)}
    nature_m = re.search(r'/articles/([a-z0-9\-]+)', text)
    if nature_m: return {"type": "doi", "id": f"10.1038/{nature_m.group(1)}"}
    doi_m = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', text)
    if doi_m: return {"type": "doi", "id": doi_m.group(0).rstrip('.')}
    return None

def fetch_web_article_text(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=8) as resp:
            raw_html = resp.read().decode('utf-8', errors='ignore')
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', raw_html, re.DOTALL)
            clean_ps = []
            for p in paragraphs:
                txt = re.sub(r'<[^>]+>', '', p).strip()
                if len(txt) > 40 and not any(x in txt.lower() for x in ['cookie', 'subscribe', 'privacy', 'terms']):
                    clean_ps.append(txt)
            doi_match = re.search(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', raw_html)
            doi_found = doi_match.group(0).rstrip('.') if doi_match else None
            return "\n\n".join(clean_ps), doi_found
    except:
        return "", None

def find_pdf_file(doi_or_arxiv_info):
    if doi_or_arxiv_info["type"] == "arxiv":
        aid = doi_or_arxiv_info["id"]
        local_p = os.path.join(PDF_DIR, f"arxiv_{aid}.pdf")
        if not os.path.exists(local_p):
            try: urllib.request.urlretrieve(f"https://arxiv.org/pdf/{aid}.pdf", local_p)
            except: pass
        if os.path.exists(local_p): return local_p

    doi = doi_or_arxiv_info["id"]
    local_p = os.path.join(PDF_DIR, doi.replace('/', '_') + ".pdf")
    if os.path.exists(local_p): return local_p

    try:
        req = urllib.request.Request(f"https://api.unpaywall.org/v2/{doi}?email=farm@ixbt.com", headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            pdf_u = data.get("best_oa_location", {}).get("url_for_pdf")
            if pdf_u:
                urllib.request.urlretrieve(pdf_u, local_p)
                if os.path.exists(local_p): return local_p
    except: pass
    return None

def get_paper_payload(url, fallback_title="", fallback_summary=""):
    target = extract_doi_or_arxiv(url)
    if target:
        pdf_path = find_pdf_file(target)
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            return {"mime_type": "application/pdf", "data": pdf_bytes}, f"Оригинальный PDF ({os.path.basename(pdf_path)})"

    web_text, doi_found = fetch_web_article_text(url)
    if doi_found:
        pdf_path = find_pdf_file({"type": "doi", "id": doi_found})
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            return {"mime_type": "application/pdf", "data": pdf_bytes}, f"Оригинальный PDF исследования ({os.path.basename(pdf_path)})"

    if len(web_text) > 400:
        return f"RESEARCH TITLE: {fallback_title}\n\nFULL IN-DEPTH REPORT / DATA:\n{web_text}", "Полный текст научного отчета"

    return f"TITLE: {fallback_title}\n\nSUMMARY:\n{fallback_summary}\n\nURL: {url}", "Подробный научный контекст"

def md_to_html(md):
    h = re.sub(r'^###\s*(.*?)$', r'<h3>\1</h3>', md, flags=re.M)
    h = re.sub(r'^##\s*(.*?)$', r'<h2>\1</h2>', h, flags=re.M)
    h = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', h)
    h = re.sub(r'^>\s*(.*?)$', r'<blockquote>\1</blockquote>', h, flags=re.M)
    return "\n".join([f"<p>{p.strip()}</p>" if p.strip() and not p.strip().startswith('<h') and not p.strip().startswith('<blockquote') else p.strip() for p in h.split('\n\n') if p.strip()])

# ==========================================
# БЕЗОПАСНАЯ ОТПРАВКА С РОТАЦИЕЙ (БЕЗ NONLOCAL)
# ==========================================

def safe_send_step(chat, keys, model_name, key_idx, msg):
    """Безопасно выполняет шаг, а при ошибке квоты переносит память на следующий ключ"""
    for attempt in range(len(keys) * 2):
        try:
            resp = chat.send_message(msg)
            return resp, chat, key_idx
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "resource" in err.lower():
                key_idx = (key_idx + 1) % len(keys)
                saved_hist = list(chat.history)
                genai.configure(api_key=keys[key_idx])
                m = genai.GenerativeModel(model_name, generation_config={"temperature": 0.25, "max_output_tokens": 8192})
                chat = m.start_chat(history=saved_hist)
                time.sleep(2)
            else:
                raise e
    raise Exception("Все ключи фермы исчерпали квоту.")

# ==========================================
# САЙДБАР (РАЗДЕЛЬНЫЕ СЧЕТЧИКИ КЛЮЧЕЙ)
# ==========================================
radar_keys = get_radar_keys()
farm_keys = get_farm_keys()

with st.sidebar:
    st.title("⚙️ Настройки")
    st.success(f"📡 Ключей Радара: **{len(radar_keys)}**")
    st.success(f"🏭 Ключей Фермы: **{len(farm_keys)}**")
    if GSHEETS_URL:
        st.success("📊 Google Таблица: **Подключена**")
    else:
        st.info("ℹ️ Google Таблица не подключена")

    selected_model = st.selectbox("🤖 Модель:", ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"], index=0)

    st.markdown("---")
    st.markdown("### 📚 Источники для сканирования")
    
    c_all, c_none = st.columns(2)
    with c_all:
        if st.button("✨ Выбрать всё", use_container_width=True):
            for cat in SCIENCE_DATABASE:
                st.session_state[f"m_{cat}"] = True
                for f_n in SCIENCE_DATABASE[cat]: st.session_state[f"chk_{f_n}"] = True
    with c_none:
        if st.button("🧹 Снять всё", use_container_width=True):
            for cat in SCIENCE_DATABASE:
                st.session_state[f"m_{cat}"] = False
                for f_n in SCIENCE_DATABASE[cat]: st.session_state[f"chk_{f_n}"] = False

    active_feeds = {}
    for cat, feeds in SCIENCE_DATABASE.items():
        with st.expander(f"{cat} ({len(feeds)})", expanded=False):
            m_val = st.checkbox("Выбрать все", value=("🛡️" not in cat), key=f"m_{cat}")
            for f_n, f_url in feeds.items():
                if st.checkbox(f_n, value=m_val, key=f"chk_{f_n}"):
                    active_feeds[f_n] = f_url

    st.info(f"🎯 **Выбрано журналов:** `{len(active_feeds)}`")
    items_per_feed = st.slider("Статей с каждого журнала", 1, 5, 2)
    min_score = st.slider("Показывать от оценки", 1, 10, 6)

    st.markdown("---")
    if st.button("🚪 Выйти из аккаунта"):
        st.session_state["authenticated"] = False
        st.query_params.clear()
        st.rerun()

# ==========================================
# ОСНОВНЫЕ ВКЛАДКИ
# ==========================================
tab_live, tab_farm, tab_history = st.tabs(["🔭 Свежий Радар", "🏭 Контент-Ферма", "📊 Вечный архив (Google Таблица)"])

# ----------------- ВКЛАДКА 1: РАДАР -----------------
with tab_live:
    st.title("🔭 Свежий Sci-Radar")
    st.caption("Поиск свежих открытий ➔ Анализ через Gemini 3.6 Flash ➔ Сохранение в Google Таблицу")

    if not radar_keys:
        st.warning("⚠️ Добавьте ключи `RADAR_API_KEYS` в Secrets приложения!")
        st.stop()

    if st.button("🚀 Сканировать свежую науку", type="primary"):
        all_articles = []
        with st.spinner("Опрос выбранных научных журналов..."):
            with ThreadPoolExecutor(max_workers=15) as ex:
                futures = [ex.submit(fetch_single_feed, name, active_feeds[name], items_per_feed) for name in active_feeds.keys()]
                for f in as_completed(futures):
                    res = f.result()
                    if res["status"] == "ok":
                        all_articles.extend(res["articles"])

        seen = set()
        unique = [x for x in all_articles if x["link"] not in seen and not seen.add(x["link"])]

        if not unique:
            st.warning("Все свежие статьи уже обработаны!")
        else:
            st.write(f"Найдено **{len(unique)}** новых статей. Анализируем через **{selected_model}** (Ключи Радара)...")
            results, pbar, key_idx = [], st.progress(0), 0
            batches = [unique[i:i+5] for i in range(0, len(unique), 5)]
            for b_i, batch in enumerate(batches):
                res, key_idx = analyze_batch(radar_keys, selected_model, batch, key_idx)
                if isinstance(res, list):
                    for i, r in enumerate(res):
                        if i < len(batch):
                            item = batch[i].copy()
                            item.update(r)
                            results.append(item)
                pbar.progress((b_i + 1) / len(batches))
                time.sleep(1)

            sorted_res = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
            st.session_state["latest_results"] = sorted_res
            sync_to_gsheets(sorted_res)
            st.success(f"Готово! Обработано {len(sorted_res)} тем и записано в Google Таблицу.")

    if "latest_results" in st.session_state:
        filtered = [r for r in st.session_state["latest_results"] if r.get("score", 0) >= min_score]
        for res in filtered:
            sc = res.get('score', 0)
            icon = "🔥" if sc >= 8 else "💡"
            with st.expander(f"{icon} [{sc}/10] [{res.get('category')}] {res.get('titles', [''])[0]}"):
                st.markdown(f"**Суть открытия:** {res.get('ru_tldr')}")
                st.markdown(f"**Парадокс:** {res.get('hook_angle')}")
                st.markdown(f"[🔗 Источник исследования]({res.get('link')})")

# ----------------- ВКЛАДКА 2: ФЕРМА -----------------
with tab_farm:
    st.title("🏭 Облачная Контент-Ферма")
    st.caption("Автоматическая 8-шаговая генерация лонгридов на Gemini 3.6 Flash (Выделенный пул ключей Фермы)")

    if not farm_keys:
        st.warning("⚠️ Добавьте выделенные ключи `FARM_API_KEYS` в Secrets приложения!")
        st.stop()

    farm_mode = st.radio(
        "Выберите режим работы фермы:",
        ["⚡ Автопилот (Взять Топ-1 тему из базы)", "🔗 Написать по моей ссылке"],
        horizontal=True
    )

    target_url = ""
    target_title = ""
    target_summary = ""

    if farm_mode == "⚡ Автопилот (Взять Топ-1 тему из базы)":
        top_candidate = None
        if "latest_results" in st.session_state and st.session_state["latest_results"]:
            top_candidate = st.session_state["latest_results"][0]
        else:
            gs_items = fetch_from_gsheets()
            if gs_items:
                top_candidate = gs_items[0]

        if top_candidate:
            st.info(f"🎯 **Выбрана лучшая тема:** `[{top_candidate.get('score')}/10]` **{top_candidate.get('title')}**")
            st.caption(f"Источник: {top_candidate.get('link')}")
            target_url = top_candidate.get('link')
            target_title = top_candidate.get('title')
            target_summary = top_candidate.get('ru_tldr', '')
        else:
            st.warning("В базе пока нет тем. Сначала запустите сканирование во вкладке '🔭 Свежий Радар' или переключитесь на ручной ввод ссылки.")
    else:
        target_url = st.text_input("Вставьте ссылку на исследование (Nature, arXiv, DOI или новость СМИ):", placeholder="https://www.nature.com/articles/s41567-...")
        target_title = "Научное исследование"
        target_summary = ""

    if st.button("🚀 Сгенерировать готовую статью", type="primary", disabled=(not target_url)):
        st.markdown("---")
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 1. Извлечение материала
        status_text.write("🌐 **[0/8] Загружаем оригинальный PDF / материалы статьи...**")
        payload, payload_type = get_paper_payload(target_url, target_title, target_summary)
        progress_bar.progress(10)

        # 2. Инициализация чата
        current_k_idx = 0
        genai.configure(api_key=farm_keys[current_k_idx])
        model = genai.GenerativeModel(selected_model, generation_config={"temperature": 0.25, "max_output_tokens": 8192})
        chat = model.start_chat(history=[])

        try:
            # Шаг 1: Роль
            status_text.write("🔹 **[1/8] Отправка роли научного редактора...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_1_ROLE)
            progress_bar.progress(25)
            time.sleep(2)

            # Шаг 2: Исходник + Черновик
            status_text.write("🔹 **[2/8] Черновик статьи (Научный обозреватель + фактура)...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, [payload, PROMPT_2_REVIEWER])
            progress_bar.progress(40)
            time.sleep(2)

            # Шаг 3: Строго без сравнений
            status_text.write("🔹 **[3/8] Перепиши строго, без сравнений...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_3_STRICT)
            progress_bar.progress(55)
            time.sleep(2)

            # Шаг 4: 8000+ знаков
            status_text.write("🔹 **[4/8] Понятными словами, не менее 8000 знаков...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_4_LENGTH)
            progress_bar.progress(70)
            time.sleep(2)

            # Шаг 5: Формулы
            status_text.write("🔹 **[5/8] Зачистка формул и LaTeX-разметки...**")
            r5, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_5_FORMULAS)
            article_text = r5.text.strip()
            progress_bar.progress(80)
            time.sleep(2)

            # Шаг 6: Заголовки Discover
            status_text.write("🔹 **[6/8] Генерация заголовков Google Discover «на грани»...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_6A_TITLES)
            time.sleep(1)
            r6b, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_6B_TITLES_EDGE)
            final_titles = r6b.text.strip()
            progress_bar.progress(90)
            time.sleep(2)

            # Шаг 7: Рисунки
            status_text.write("🔹 **[7/8] Анализ оригинальных рисунков из исследования...**")
            r7, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_7_FIGURES)
            figures_placement = r7.text.strip()
            time.sleep(2)

            # Шаг 8: Промпты Reve
            status_text.write("🔹 **[8/8] Промпты для генератора Reve (EN + RU, Фотореализм)...**")
            r8, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_8_REVE)
            reve_prompts = r8.text.strip()
            progress_bar.progress(100)

            status_text.success(f"🎉 СТАТЬЯ УСПЕШНО СОЗДАНА! (Объем: {len(article_text)} знаков | Модель: {selected_model})")

            # Сборка HTML
            html_ready = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'><title>{target_title}</title></head><body style='background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:30px; line-height:1.7;'><div style='max-width:900px; margin:0 auto; background:#1e293b; padding:40px; border-radius:12px;'><h1>{target_title}</h1><div style='background:#090d16; padding:15px; border-radius:8px; border:1px dashed #38bdf8; margin:20px 0;'><strong>🎯 Заголовки Discover:</strong><pre>{final_titles}</pre></div><div style='background:#090d16; padding:15px; border-radius:8px; border:1px dashed #38bdf8; margin:20px 0;'><strong>🎨 Промпты для Reve:</strong><pre>{reve_prompts}</pre></div><div style='background:#090d16; padding:15px; border-radius:8px; border:1px dashed #38bdf8; margin:20px 0;'><strong>📊 Рисунки из PDF:</strong><pre>{figures_placement}</pre></div><hr style='border-color:#334155; margin:30px 0;'><div>{md_to_html(article_text)}</div></div></body></html>"""

            st.download_button(
                label="📥 Скачать готовую статью в HTML",
                data=html_ready,
                file_name=f"ready_article_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                type="primary"
            )

            # Вывод на экран
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("🎯 Заголовки Google Discover")
                st.text_area("Варианты названий:", value=final_titles, height=180)
            with c2:
                st.subheader("🎨 Промпты для Reve (EN + RU)")
                st.text_area("Иллюстрации:", value=reve_prompts, height=180)

            st.subheader("📊 Рисунки из исследования")
            st.info(figures_placement)

            st.markdown("---")
            st.subheader("📄 Текст статьи (Готово для iXBT)")
            st.markdown(article_text)

        except Exception as e:
            status_text.error(f"❌ Ошибка генерации: {e}")

# ----------------- ВКЛАДКА 3: GOOGLE ТАБЛИЦА -----------------
with tab_history:
    st.title("📊 Вечный архив (Google Таблица)")
    st.caption("Все ранее найденные темы, сохраненные на вашем Google Диске")

    if st.button("🔄 Обновить историю из Google Таблицы"):
        st.session_state["gsheets_history"] = fetch_from_gsheets()

    if "gsheets_history" not in st.session_state:
        st.session_state["gsheets_history"] = fetch_from_gsheets()

    history_items = st.session_state["gsheets_history"]
    st.write(f"Всего статей в вашей Google Таблице: **{len(history_items)}**")

    for r in history_items[:30]:
        with st.expander(f"[{r.get('score')}/10] [{r.get('category')}] {r.get('titles', [''])[0]} | 📅 {r.get('created_at')}"):
            st.markdown(f"**Суть:** {r.get('ru_tldr')}")
            st.markdown(f"[🔗 Ссылка]({r.get('link')})")
