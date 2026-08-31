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
# КОНФИГУРАЦИЯ И СЕЙФ SECRETS
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
- Structure: Always use engaging Hooks (intros), meaningful Subheadings, and a thought-provoking Outro.

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
# ЧИСТЫЙ КОНВЕРТЕР РАЗМЕТКИ ДЛЯ iXBT LIVE
# ==========================================

def format_inline(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.*?)__', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.*?)_', r'<em>\1</em>', text)
    text = re.sub(r'`(.*?)`', r'<code>\1</code>', text)
    return text

def md_to_ixbt_html(md_text):
    lines = md_text.split('\n')
    html_lines = []
    in_ul = False
    in_ol = False
    in_blockquote = False
    
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            if in_ul: html_lines.append("</ul>"); in_ul = False
            if in_ol: html_lines.append("</ol>"); in_ol = False
            if in_blockquote: html_lines.append("</blockquote>"); in_blockquote = False
            continue
            
        if stripped.startswith('### '):
            if in_ul: html_lines.append("</ul>"); in_ul = False
            if in_ol: html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h3>{format_inline(stripped[4:])}</h3>")
            continue
        elif stripped.startswith('## '):
            if in_ul: html_lines.append("</ul>"); in_ul = False
            if in_ol: html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h2>{format_inline(stripped[3:])}</h2>")
            continue
        elif stripped.startswith('# '):
            if in_ul: html_lines.append("</ul>"); in_ul = False
            if in_ol: html_lines.append("</ol>"); in_ol = False
            html_lines.append(f"<h2>{format_inline(stripped[2:])}</h2>")
            continue
            
        if stripped.startswith('> '):
            if not in_blockquote:
                html_lines.append("<blockquote>")
                in_blockquote = True
            html_lines.append(f"<p>{format_inline(stripped[2:])}</p>")
            continue
        elif in_blockquote:
            html_lines.append("</blockquote>")
            in_blockquote = False
            
        ul_match = re.match(r'^[\*\-\•]\s+(.*)$', stripped)
        if ul_match:
            if not in_ul:
                if in_ol: html_lines.append("</ol>"); in_ol = False
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{format_inline(ul_match.group(1))}</li>")
            continue
            
        ol_match = re.match(r'^\d+[\.\)]\s+(.*)$', stripped)
        if ol_match:
            if not in_ol:
                if in_ul: html_lines.append("</ul>"); in_ul = False
                html_lines.append("<ol>")
                in_ol = True
            html_lines.append(f"<li>{format_inline(ol_match.group(1))}</li>")
            continue
            
        if in_ul: html_lines.append("</ul>"); in_ul = False
        if in_ol: html_lines.append("</ol>"); in_ol = False
        
        if stripped in ['---', '***', '___']:
            html_lines.append("<hr>")
            continue
            
        html_lines.append(f"<p>{format_inline(stripped)}</p>")
        
    if in_ul: html_lines.append("</ul>")
    if in_ol: html_lines.append("</ol>")
    if in_blockquote: html_lines.append("</blockquote>")
    
    return "\n".join(html_lines)

# ==========================================
# ПАМЯТЬ И ПОЛНАЯ ДЕДУПЛИКАЦИЯ ЧЕРЕЗ GOOGLE ТАБЛИЦУ
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

def get_all_scanned_urls():
    """Собирает список всех когда-либо просканированных ссылок из Google Таблицы и сессии"""
    known = set()
    
    # 1. Из Google Таблицы (вечный архив)
    gs_items = fetch_from_gsheets()
    for item in gs_items:
        l = item.get("link", "").strip()
        if l: known.add(l)
        
    # 2. Из кэша текущей сессии
    if "session_scanned_urls" in st.session_state:
        known.update(st.session_state["session_scanned_urls"])
        
    return known

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

def fetch_single_feed(feed_name, feed_url, items_per_feed, known_urls):
    articles = []
    status = "ok"
    err = ""
    try:
        req = urllib.request.Request(feed_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=6) as response:
            parsed = feedparser.parse(response.read())
            if parsed.entries:
                for entry in parsed.entries[:items_per_feed]:
                    link = entry.get("link", "").strip()
                    # СВЕРКА: ЕСЛИ СТАТЬЯ УЖЕ ЕСТЬ В GOOGLE ТАБЛИЦЕ — ПРОПУСКАЕМ!
                    if link in known_urls:
                        continue
                    title = entry.get("title", "").replace("\n", " ").strip()
                    summary = re.sub(r'<[^>]+>', '', entry.get("summary", entry.get("description", ""))).replace("\n", " ").strip()
                    articles.append({"source": feed_name, "title": title, "summary": summary[:1200], "link": link})
            else:
                status = "empty"
                err = "Лента пуста"
    except Exception as e:
        status = "error"
        err = str(e)
    return {"name": feed_name, "status": status, "error": err, "articles": articles}

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

def safe_send_step(chat, keys, model_name, key_idx, msg):
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
# САЙДБАР
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
tab_live, tab_farm, tab_history = st.tabs(["🔭 Свежий Радар", "🏭 Контент-Ферма (iXBT Studio)", "📊 Вечный архив (Google Таблица)"])

# ----------------- ВКЛАДКА 1: РАДАР (С ДЕДУПЛИКАЦИЕЙ ПО GOOGLE ТАБЛИЦЕ) -----------------
with tab_live:
    st.title("🔭 Свежий Sci-Radar")
    st.caption("Сверка с Google Таблицей ➔ Анализ новых статей через Gemini 3.6 Flash ➔ Сохранение в архив")

    if not radar_keys:
        st.warning("⚠️ Добавьте ключи `RADAR_API_KEYS` в Secrets приложения!")
        st.stop()

    if st.button("🚀 Сканировать свежую науку", type="primary"):
        all_articles = []
        feed_reports = []
        
        # Получаем полный список всех когда-либо просканированных ссылок
        known_urls = get_all_scanned_urls()
        
        with st.spinner("Опрос выбранных научных журналов и сверка с архивом..."):
            with ThreadPoolExecutor(max_workers=15) as ex:
                futures = [ex.submit(fetch_single_feed, name, active_feeds[name], items_per_feed, known_urls) for name in active_feeds.keys()]
                for f in as_completed(futures):
                    res = f.result()
                    feed_reports.append(res)
                    if isinstance(res, dict) and res.get("status") == "ok":
                        all_articles.extend(res.get("articles", []))

        seen = set()
        unique = [x for x in all_articles if x["link"] not in seen and not seen.add(x["link"])]

        ok_feeds = [f for f in feed_reports if isinstance(f, dict) and f.get("status") == "ok"]
        failed_feeds = [f for f in feed_reports if isinstance(f, dict) and f.get("status") != "ok"]
        st.session_state["feed_diag"] = {"ok": ok_feeds, "failed": failed_feeds}

        if not unique:
            st.warning("🎉 Все статьи из выбранных журналов уже есть в вашей Google Таблице! Новых публикаций пока нет.")
        else:
            st.write(f"Найдено **{len(unique)}** новых уникальных статей. Анализируем через **{selected_model}**...")
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
            
            # Сохраняем в кэш сессии и отправляем в Google Таблицу
            if "session_scanned_urls" not in st.session_state:
                st.session_state["session_scanned_urls"] = set()
            for r in sorted_res:
                st.session_state["session_scanned_urls"].add(r.get("link", "").strip())
                
            sync_to_gsheets(sorted_res)
            st.success(f"Готово! Обработано {len(sorted_res)} новых тем и записано в Google Таблицу.")

    if "feed_diag" in st.session_state:
        diag = st.session_state["feed_diag"]
        with st.expander(f"📊 Статус опроса источников: Успешно ({len(diag['ok'])}) | Проблемных ({len(diag['failed'])})", expanded=False):
            if diag["failed"]:
                st.error("Следующие журналы не ответили:")
                for f in diag["failed"]:
                    st.markdown(f"- **{f['name']}** ➔ `{f['error']}`")
            st.success(f"Успешно ответили ({len(diag['ok'])} журналов):")
            st.markdown(" • ".join([f"**{f['name']}** ({len(f['articles'])} новых)" for f in diag["ok"]]))

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
    st.title("🏭 Контент-Ферма (Студия iXBT Live)")
    st.caption("8-шаговый пайплайн Ruby_Rougarou ➔ Форматирование в чистый HTML iXBT Live")

    if not farm_keys:
        st.warning("⚠️ Добавьте выделенные ключи `FARM_API_KEYS` в Secrets приложения!")
        st.stop()

    farm_mode = st.radio(
        "Выберите режим работы:",
        [
            "⚡ Автопилот (Взять Топ-1 тему из базы)", 
            "🔗 Написать по моей ссылке",
            "📄 Загрузить PDF вручную с устройства"
        ],
        horizontal=True
    )

    target_url = ""
    target_title = ""
    target_summary = ""
    uploaded_pdf_bytes = None
    source_label = ""

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
            source_label = "Авто-выбор из базы"
        else:
            st.warning("В базе пока нет тем. Сначала запустите сканирование во вкладке '🔭 Свежий Радар' или переключитесь на ручной ввод.")
    elif farm_mode == "🔗 Написать по моей ссылке":
        target_url = st.text_input("Вставьте ссылку на исследование (Nature, arXiv, DOI или новость СМИ):", placeholder="https://www.nature.com/articles/s41567-...")
        target_title = "Научное исследование"
        target_summary = ""
        source_label = "Ссылка из интернета"
    else:
        uploaded_file = st.file_uploader(
            "Загрузите PDF файл исследования (любая закрытая статья с вашего ПК/телефона):", 
            type=["pdf"],
            help="Нейросеть прочитает весь документ от корки до корки, включая графики и таблицы!"
        )
        if uploaded_file is not None:
            uploaded_pdf_bytes = uploaded_file.read()
            target_title = uploaded_file.name.replace(".pdf", "").replace("_", " ")
            target_url = "Локальный PDF файл пользователя"
            source_label = f"Загруженный вручную PDF ({uploaded_file.name}, {len(uploaded_pdf_bytes)//1024} КБ)"
            st.success(f"✅ Файл готов к анализу: **{uploaded_file.name}** ({len(uploaded_pdf_bytes)//1024} КБ)")

    can_generate = bool(target_url or uploaded_pdf_bytes)

    if st.button("🚀 Сгенерировать статью для iXBT Live", type="primary", disabled=not can_generate):
        st.markdown("---")
        progress_bar = st.progress(0)
        status_text = st.empty()

        if uploaded_pdf_bytes:
            status_text.write(f"📄 **[0/8] Загружаем ваш PDF напрямую в {selected_model}...**")
            payload = {"mime_type": "application/pdf", "data": uploaded_pdf_bytes}
            payload_type = source_label
        else:
            status_text.write("🌐 **[0/8] Загружаем оригинальный PDF / материалы статьи...**")
            payload, payload_type = get_paper_payload(target_url, target_title, target_summary)
            
        progress_bar.progress(10)

        current_k_idx = 0
        genai.configure(api_key=farm_keys[current_k_idx])
        model = genai.GenerativeModel(selected_model, generation_config={"temperature": 0.25, "max_output_tokens": 8192})
        chat = model.start_chat(history=[])

        try:
            status_text.write("🔹 **[1/8] Отправка роли научного редактора...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_1_ROLE)
            progress_bar.progress(25)
            time.sleep(2)

            status_text.write(f"🔹 **[2/8] Черновик статьи (Научный обозреватель + анализ: {payload_type})...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, [payload, PROMPT_2_REVIEWER])
            progress_bar.progress(40)
            time.sleep(2)

            status_text.write("🔹 **[3/8] Перепиши строго, без сравнений...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_3_STRICT)
            progress_bar.progress(55)
            time.sleep(2)

            status_text.write("🔹 **[4/8] Понятными словами, не менее 8000 знаков...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_4_LENGTH)
            progress_bar.progress(70)
            time.sleep(2)

            status_text.write("🔹 **[5/8] Зачистка формул и LaTeX-разметки...**")
            r5, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_5_FORMULAS)
            article_text = r5.text.strip()
            progress_bar.progress(80)
            time.sleep(2)

            status_text.write("🔹 **[6/8] Генерация заголовков Discover «на грани»...**")
            _, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_6A_TITLES)
            time.sleep(1)
            r6b, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_6B_TITLES_EDGE)
            final_titles = r6b.text.strip()
            progress_bar.progress(90)
            time.sleep(2)

            status_text.write("🔹 **[7/8] Анализ оригинальных рисунков из исследования...**")
            r7, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_7_FIGURES)
            figures_placement = r7.text.strip()
            time.sleep(2)

            status_text.write("🔹 **[8/8] Промпты для Reve (EN + RU, Фотореализм)...**")
            r8, chat, current_k_idx = safe_send_step(chat, farm_keys, selected_model, current_k_idx, PROMPT_8_REVE)
            reve_prompts = r8.text.strip()
            progress_bar.progress(100)

            status_text.success(f"🎉 СТАТЬЯ УСПЕШНО СОЗДАНА! (Объем: {len(article_text)} знаков | Источник: {payload_type})")

            article_ixbt_html = md_to_ixbt_html(article_text)

            html_ready = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{target_title} | Ruby_Rougarou</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #f8fafc; --accent: #38bdf8; --border: #334155; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 30px; line-height: 1.7; }}
        .container {{ max-width: 950px; margin: 0 auto; background: var(--card); padding: 40px; border-radius: 14px; border: 1px solid var(--border); }}
        h1 {{ color: #fff; font-size: 26px; line-height: 1.3; margin-bottom: 20px; }}
        h2 {{ color: var(--accent); font-size: 22px; margin-top: 35px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
        h3 {{ color: #7dd3fc; font-size: 18px; margin-top: 20px; }}
        .box {{ background: #090d16; border: 1px dashed var(--accent); padding: 20px; border-radius: 10px; margin: 25px 0; }}
        .box-t {{ color: var(--accent); font-weight: bold; font-size: 16px; margin-bottom: 10px; display: block; }}
        .btn {{ background: var(--accent); color: #000; font-weight: bold; border: none; padding: 14px 24px; border-radius: 8px; cursor: pointer; font-size: 15px; display: inline-block; margin-bottom: 20px; transition: 0.2s; }}
        .btn:hover {{ opacity: 0.9; transform: scale(1.01); }}
        pre {{ white-space: pre-wrap; font-family: inherit; margin: 0; }}
        
        ul, ol {{ margin: 16px 0 20px 24px; padding-left: 10px; }}
        li {{ margin-bottom: 8px; line-height: 1.6; }}
        ul li {{ list-style-type: disc; }}
        ol li {{ list-style-type: decimal; }}
        blockquote {{ background: #0f2744; border-left: 4px solid var(--accent); margin: 20px 0; padding: 14px 20px; border-radius: 6px; font-style: italic; }}
        p {{ margin-bottom: 16px; }}
    </style>
    <script>
        function copyFormattedForIXBT() {{
            const articleEl = document.getElementById('ixbt-article-content');
            if (!articleEl) return;

            try {{
                const range = document.createRange();
                range.selectNodeContents(articleEl);
                const sel = window.getSelection();
                sel.removeAllRanges();
                sel.addRange(range);
                document.execCommand('copy');
                sel.removeAllRanges();
                showSuccess();
                return;
            }} catch(e) {{}}

            if (navigator.clipboard) {{
                const blobHtml = new Blob([articleEl.innerHTML], {{ type: 'text/html' }});
                const blobText = new Blob([articleEl.innerText], {{ type: 'text/plain' }});
                navigator.clipboard.write([new ClipboardItem({{ 'text/html': blobHtml, 'text/plain': blobText }})])
                    .then(showSuccess)
                    .catch(() => navigator.clipboard.writeText(articleEl.innerText).then(showSuccess));
            }}
        }}

        function showSuccess() {{
            const btn = document.getElementById('btn-copy-main');
            if (btn) {{
                const old = btn.innerText;
                btn.innerText = '✅ СКОПИРОВАНО В ФОРМАТЕ iXBT!';
                btn.style.background = '#10b981';
                setTimeout(() => {{
                    btn.innerText = old;
                    btn.style.background = '#38bdf8';
                }}, 3000);
            }}
        }}
    </script>
</head>
<body>
    <div class="container">
        <button id="btn-copy-main" class="btn" onclick="copyFormattedForIXBT()">📋 Скопировать форматированную статью для iXBT Live (Ctrl+V)</button>
        <div style="color: #94a3b8; font-size: 14px; margin-bottom: 25px;">Автор: <strong>Ruby_Rougarou</strong> | Модель: <strong>{selected_model}</strong> | Объем: <strong>{len(article_text)} знаков</strong></div>

        <!-- ШПАРАГАЛКА 1: ЗАГОЛОВКИ -->
        <div class="box">
            <span class="box-t">🎯 Заголовки Google Discover:</span>
            <pre>{final_titles}</pre>
        </div>

        <!-- ШПАРАГАЛКА 2: ПРОМПТЫ ДЛЯ REVE -->
        <div class="box">
            <span class="box-t">🎨 Промпты для Reve (EN + RU):</span>
            <pre>{reve_prompts}</pre>
        </div>

        <!-- ШПАРАГАЛКА 3: РИСУНКИ ИЗ PDF -->
        <div class="box">
            <span class="box-t">📊 Рисунки из исследования (где и какие брать):</span>
            <pre>{figures_placement}</pre>
        </div>

        <hr style="border-color: var(--border); margin: 35px 0;">

        <!-- ТОЛЬКО ЧИСТЫЙ ТЕКСТ СТАТЬИ ДЛЯ ВСТАВКИ -->
        <div id="ixbt-article-content">
            {article_ixbt_html}
        </div>
    </div>
</body>
</html>"""

            st.download_button(
                label="📥 Скачать готовую статью в HTML",
                data=html_ready,
                file_name=f"ixbt_article_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                type="primary"
            )

            c1, c2 = st.columns(2)
            with c1:
                st.subheader("🎯 Заголовки Google Discover")
                st.text_area("Названия:", value=final_titles, height=160)
            with c2:
                st.subheader("🎨 Промпты для Reve (EN + RU)")
                st.text_area("Иллюстрации:", value=reve_prompts, height=160)

            st.subheader("📊 Рисунки из исследования")
            st.info(figures_placement)

            st.markdown("---")
            st.subheader("📄 Текст статьи (Готово для iXBT Live)")
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
