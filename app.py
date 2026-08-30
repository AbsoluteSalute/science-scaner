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
import urllib.error
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="iXBT Mega Sci-Radar Pro", page_icon="🔬", layout="wide")

DB_PATH = "radar_history.db"

SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# ==========================================
# БАЗА ДАННЫХ (SQLite)
# ==========================================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                original_title TEXT,
                source TEXT,
                category TEXT,
                score INTEGER,
                score_reason TEXT,
                ru_tldr TEXT,
                titles_json TEXT,
                hook_angle TEXT,
                nano_banana_prompt TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()

init_db()

def get_config(key, default=""):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

def set_config(key, value):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def get_api_keys_pool():
    raw = get_config("api_keys_pool", "")
    if not raw.strip():
        single = get_config("gemini_api_key", "")
        return [single.strip()] if single.strip() else []
    return [k.strip() for k in raw.split("\n") if k.strip()]

def save_api_keys_pool(keys_list):
    raw = "\n".join([k.strip() for k in keys_list if k.strip()])
    set_config("api_keys_pool", raw)

def is_article_processed(url):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
        return cur.fetchone() is not None

def save_article_to_db(item):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute('''
            INSERT OR IGNORE INTO articles 
            (url, original_title, source, category, score, score_reason, ru_tldr, titles_json, hook_angle, nano_banana_prompt, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            item.get("link", ""),
            item.get("title", ""),
            item.get("source", ""),
            item.get("category", "Наука"),
            int(item.get("score", 0)),
            item.get("score_reason", ""),
            item.get("ru_tldr", ""),
            json.dumps(item.get("titles", []), ensure_ascii=False),
            item.get("hook_angle", ""),
            item.get("nano_banana_prompt", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M")
        ))
        conn.commit()

def get_history(min_score=0, search_query="", category="Все"):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        query = "SELECT url, original_title, source, category, score, score_reason, ru_tldr, titles_json, hook_angle, nano_banana_prompt, created_at FROM articles WHERE score >= ?"
        params = [min_score]
        
        if category and category != "Все":
            query += " AND category = ?"
            params.append(category)
            
        if search_query:
            query += " AND (original_title LIKE ? OR ru_tldr LIKE ? OR titles_json LIKE ?)"
            wild = f"%{search_query}%"
            params.extend([wild, wild, wild])
            
        query += " ORDER BY id DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        
        res = []
        for r in rows:
            res.append({
                "link": r[0],
                "title": r[1],
                "source": r[2],
                "category": r[3],
                "score": r[4],
                "score_reason": r[5],
                "ru_tldr": r[6],
                "titles": json.loads(r[7]),
                "hook_angle": r[8],
                "nano_banana_prompt": r[9],
                "created_at": r[10]
            })
        return res

def clear_db():
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM articles")
        conn.commit()

# ==========================================
# ПОЛНАЯ БАЗА НАУЧНЫХ ЖУРНАЛОВ
# ==========================================
SCIENCE_DATABASE = {
    "🏛️ Топ-журналы (Nature & Пресс-релизы)": {
        "🏆 Nature (Главные исследования)": "https://www.nature.com/nature.rss",
        "🏆 Nature Communications": "https://www.nature.com/ncomms.rss",
        "🌐 Scientific Reports": "https://www.nature.com/srep.rss",
        "📢 EurekAlert! Science News": "https://www.eurekalert.org/rss/technology_engineering.xml"
    },
    "🦖 Динозавры, Палеонтология и Древности": {
        "🦖 Динозавры и Окаменелости (Phys.org)": "https://phys.org/rss-feed/earth-news/archaeology-fossils/",
        "🦴 Окаменелости и Эволюция (ScienceDaily)": "https://www.sciencedaily.com/rss/plants_animals/fossils.xml",
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
        "📜 arXiv: Астрофизика (astro-ph)": "http://export.arxiv.org/rss/astro-ph",
        "🚀 NASA News": "https://www.nasa.gov/news-release/feed/"
    },
    "⚛️ Физика и Кванты": {
        "🔬 Nature Physics": "https://www.nature.com/nphys.rss",
        "📜 arXiv: Квантовая физика (quant-ph)": "http://export.arxiv.org/rss/quant-ph",
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
        "📜 arXiv: AI и Компьютерные науки": "http://export.arxiv.org/rss/cs.AI"
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
Ты — шеф-редактор научпоп блога на iXBT Live (автор Ruby_Rougarou). 
Твоя аудитория: умные читатели, гики, любители науки, динозавров, космоса и физики.
Твоя задача — проанализировать пачку научных статей и вернуть JSON-массив с анализом каждой статьи.

Верни СТРОГО валидный JSON-массив объектов:
[
  {
    "id": 1,
    "score": 8,
    "score_reason": "кратко почему это зайдет читателям iXBT",
    "category": "Динозавры/Космос/Кванты/Геология/Биология/AI/Материалы",
    "ru_tldr": "суть открытия простыми словами на русском в 2 предложениях",
    "titles": [
      "Заголовок 1 (Парадокс или шок-факт)",
      "Заголовок 2 (Открытие/Масштаб)",
      "Заголовок 3 (Вопрос-интрига)"
    ],
    "hook_angle": "главный парадокс для споров в комментариях",
    "nano_banana_prompt": "cinematic sci-fi/scientific photorealistic illustration, 8k, dynamic lighting, horizontal 2:1 aspect ratio"
  }
]
"""

def fetch_single_feed(feed_name, feed_url, items_per_feed):
    articles = []
    status = "ok"
    err_msg = ""
    try:
        req = urllib.request.Request(
            feed_url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=5) as response:
            xml_data = response.read()
            parsed = feedparser.parse(xml_data)
            
            if not parsed.entries:
                status = "empty"
                err_msg = "Лента пуста"
            else:
                for entry in parsed.entries[:items_per_feed]:
                    link = entry.get("link", "")
                    if is_article_processed(link):
                        continue
                    summary_text = entry.get("summary", entry.get("description", ""))
                    clean_summary = re.sub(r'<[^>]+>', '', summary_text).strip()
                    articles.append({
                        "source": feed_name,
                        "title": entry.get("title", "Без названия"),
                        "summary": clean_summary[:1200],
                        "link": link
                    })
    except urllib.error.HTTPError as e:
        status = "error"
        err_msg = f"HTTP {e.code}: Защита Cloudflare"
    except Exception as e:
        status = "error"
        err_msg = str(e)
        
    return {"name": feed_name, "status": status, "error": err_msg, "articles": articles}

def get_available_gemini_models(api_keys_pool):
    for key in api_keys_pool:
        try:
            genai.configure(api_key=key)
            models = [
                m.name.replace("models/", "") 
                for m in genai.list_models() 
                if "generateContent" in m.supported_generation_methods
            ]
            gemini_only = [m for m in models if "gemini" in m]
            if gemini_only:
                return gemini_only
        except Exception:
            continue
    return ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

def clean_and_parse_json(raw_text):
    text = raw_text.strip()
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    m = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(text)

def analyze_batch_with_rotator(keys_pool, model_name, batch_items, start_key_index=0):
    """Анализирует статьи с автоматической ротацией ключей при 429 / Quota Error"""
    if not keys_pool:
        return {"error": "Нет доступных API-ключей в пуле. Добавьте их во вкладке 'Пул API-ключей'!"}, start_key_index
        
    prompt_content = "Проанализируй следующие статьи и верни JSON массив объектов:\n\n"
    for idx, item in enumerate(batch_items):
        prompt_content += f"--- СТАТЬЯ #{idx+1} ---\nЗаголовок: {item['title']}\nТекст: {item['summary']}\n\n"
        
    total_keys = len(keys_pool)
    last_error = ""
    
    # Пробуем по очереди все ключи из пула, начиная с текущего
    for attempt in range(total_keys):
        key_idx = (start_key_index + attempt) % total_keys
        active_key = keys_pool[key_idx]
        
        try:
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=BATCH_SYSTEM_PROMPT,
                generation_config={"response_mime_type": "application/json", "temperature": 0.2}
            )
            response = model.generate_content(prompt_content)
            res = clean_and_parse_json(response.text)
            if isinstance(res, list):
                return res, key_idx
        except Exception as e:
            last_error = str(e)
            # Если 429 / Quota / ResourceExhausted — мгновенно берем следующий ключ
            if "429" in last_error or "quota" in last_error.lower() or "resource" in last_error.lower():
                continue
            else:
                continue
                
    return {"error": last_error}, start_key_index

def generate_html_report(results, report_title="Sci-Radar Report"):
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    cards_html = ""
    for r in results:
        score = r.get("score", 0)
        score_color = "#10b981" if score >= 8 else ("#f59e0b" if score >= 6 else "#64748b")
        titles_list = "".join([
            f'<li class="title-item"><span>{t}</span> <button class="btn-copy" onclick="copyText(\'{t.replace(chr(39), chr(92)+chr(39))}\')">📋</button></li>' 
            for t in r.get("titles", [])
        ])
        prompt_escaped = r.get("nano_banana_prompt", "").replace("'", "\\'").replace('"', '&quot;')
        
        cards_html += f"""
        <div class="card">
            <div class="card-header">
                <span class="badge-cat">{r.get('category', 'Наука')}</span>
                <span class="badge-score" style="background: {score_color};">{score}/10</span>
                <span class="source-tag">{r.get('source')}</span>
                <span class="date-tag">📅 {r.get('created_at', '')}</span>
            </div>
            <h2 class="main-title">{r.get('titles', [''])[0]}</h2>
            <div class="tldr-box"><strong>💡 Суть открытия:</strong> {r.get('ru_tldr')}</div>
            <div class="hook-box"><strong>🔥 Крючок / Интрига:</strong> {r.get('hook_angle')}</div>
            <div class="section-block">
                <h4>🎯 Варианты заголовков для iXBT:</h4>
                <ul class="titles-list">{titles_list}</ul>
            </div>
            <div class="prompt-box">
                <div class="prompt-header">
                    <span>🎨 <strong>Промпт для Nano Banana:</strong></span>
                    <button class="btn-copy" onclick="copyText('{prompt_escaped}')">📋 Скопировать промпт</button>
                </div>
                <code>{r.get('nano_banana_prompt')}</code>
            </div>
            <div class="card-footer">
                <a href="{r.get('link')}" target="_blank" class="source-link">🔗 Первоисточник исследования &rarr;</a>
                <span class="score-reason"><em>{r.get('score_reason')}</em></span>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>{report_title} | Ruby_Rougarou</title>
    <style>
        :root {{ --bg: #0f172a; --card-bg: #1e293b; --text: #f8fafc; --text-muted: #94a3b8; --accent: #38bdf8; --border: #334155; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; background-color: var(--bg); color: var(--text); margin: 0; padding: 24px; line-height: 1.6; }}
        .container {{ max-width: 1050px; margin: 0 auto; }}
        header {{ border-bottom: 1px solid var(--border); padding-bottom: 20px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; }}
        h1 {{ margin: 0; font-size: 26px; color: var(--accent); }}
        .meta {{ color: var(--text-muted); font-size: 14px; }}
        .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin-bottom: 24px; }}
        .card-header {{ display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }}
        .badge-score {{ color: #fff; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 14px; }}
        .badge-cat {{ background: #475569; color: #fff; padding: 4px 10px; border-radius: 6px; font-size: 12px; text-transform: uppercase; }}
        .source-tag, .date-tag {{ color: var(--text-muted); font-size: 13px; margin-left: auto; }}
        .main-title {{ margin: 8px 0 16px 0; font-size: 21px; color: #fff; }}
        .tldr-box {{ background: #0f172a; padding: 12px 16px; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid var(--accent); }}
        .hook-box {{ background: #1e1b4b; color: #c7d2fe; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; border-left: 4px solid #818cf8; }}
        .titles-list {{ list-style: none; padding-left: 0; margin: 8px 0; }}
        .title-item {{ background: #0f172a; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; }}
        .prompt-box {{ background: #090d16; padding: 14px; border-radius: 8px; border: 1px dashed var(--border); margin-top: 16px; }}
        .prompt-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
        code {{ color: #38bdf8; font-family: Consolas, monospace; font-size: 13px; word-break: break-all; }}
        .btn-copy {{ background: #334155; color: #fff; border: none; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; transition: 0.2s; }}
        .btn-copy:hover {{ background: var(--accent); color: #000; }}
        .card-footer {{ display: flex; justify-content: space-between; align-items: center; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); font-size: 13px; }}
        .source-link {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
        .score-reason {{ color: var(--text-muted); }}
    </style>
    <script>
        function copyText(text) {{
            navigator.clipboard.writeText(text).then(() => alert('Скопировано в буфер!'));
        }}
    </script>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>🔬 {report_title}</h1>
                <div class="meta">Блог: <strong>Ruby_Rougarou</strong></div>
            </div>
            <div class="meta">{date_str} | Записей: {len(results)}</div>
        </header>
        {cards_html}
    </div>
</body>
</html>"""

# ==========================================
# СИНХРОНИЗАЦИЯ ЧЕКБОКСОВ
# ==========================================
def toggle_category(cat_name):
    val = st.session_state[f"master_{cat_name}"]
    for feed_name in SCIENCE_DATABASE[cat_name]:
        st.session_state[f"chk_{feed_name}"] = val

def select_all_feeds():
    for cat_name, feeds in SCIENCE_DATABASE.items():
        st.session_state[f"master_{cat_name}"] = True
        for feed_name in feeds:
            st.session_state[f"chk_{feed_name}"] = True

def deselect_all_feeds():
    for cat_name, feeds in SCIENCE_DATABASE.items():
        st.session_state[f"master_{cat_name}"] = False
        for feed_name in feeds:
            st.session_state[f"chk_{feed_name}"] = False

for cat_name, feeds in SCIENCE_DATABASE.items():
    if f"master_{cat_name}" not in st.session_state:
        st.session_state[f"master_{cat_name}"] = ("🛡️" not in cat_name)
    for feed_name in feeds:
        if f"chk_{feed_name}" not in st.session_state:
            st.session_state[f"chk_{feed_name}"] = st.session_state[f"master_{cat_name}"]

# ==========================================
# САЙДБАР
# ==========================================
keys_pool = get_api_keys_pool()

with st.sidebar:
    st.title("⚙️ Настройки")
    
    if keys_pool:
        st.success(f"🔑 **Ключей в пуле ротации:** `{len(keys_pool)}`")
    else:
        st.warning("⚠️ Пул ключей пуст! Добавьте ключи во вкладке '🔑 Пул API-ключей'.")
        
    available_models = get_available_gemini_models(keys_pool)
    selected_model = st.selectbox("🤖 Модель Gemini:", available_models, index=0)

    st.markdown("---")
    st.markdown("### 📚 Выбор направлений науки")
    
    c_all, c_none = st.columns(2)
    with c_all:
        st.button("✨ Выбрать всё", on_click=select_all_feeds, use_container_width=True)
    with c_none:
        st.button("🧹 Снять всё", on_click=deselect_all_feeds, use_container_width=True)
    
    for cat_name, feeds in SCIENCE_DATABASE.items():
        is_protected = "🛡️" in cat_name
        with st.expander(f"{cat_name} ({len(feeds)})", expanded=False):
            if is_protected:
                st.warning("⚠️ Защищены Cloudflare (HTTP 403). Нужен рабочий VPN.")
                
            st.checkbox(
                "✅ Выбрать все в этом разделе", 
                key=f"master_{cat_name}", 
                on_change=toggle_category, 
                args=(cat_name,)
            )
            for feed_name in feeds:
                st.checkbox(feed_name, key=f"chk_{feed_name}")

    active_feed_dict = {}
    for cat_name, feeds in SCIENCE_DATABASE.items():
        for feed_name, url in feeds.items():
            if st.session_state.get(f"chk_{feed_name}", False):
                active_feed_dict[feed_name] = url

    st.info(f"🎯 **Выбрано журналов:** `{len(active_feed_dict)}`")
    
    st.markdown("---")
    items_per_feed = st.slider("Статей с каждого журнала", 1, 5, 2)
    min_score = st.slider("Показывать оценку от", 1, 10, 6)

# ==========================================
# ОСНОВНЫЕ ВКЛАДКИ
# ==========================================
tab_live, tab_history, tab_keys, tab_db_info = st.tabs([
    "🔭 Свежий Радар", 
    "📜 История и Архив", 
    "🔑 Пул API-ключей (Ротация)", 
    "💾 База данных"
])

# ----------------- ВКЛАДКА 1: СВЕЖИЙ РАДАР -----------------
with tab_live:
    st.title("🔭 Свежий Sci-Radar")
    st.caption("Автоматическая ротация API-ключей ➔ Параллельный сбор ➔ Без остановок по лимитам")

    if not keys_pool:
        st.warning("⚠️ Добавьте хотя бы один API-ключ во вкладке **'🔑 Пул API-ключей (Ротация)'** вверху.")
        st.stop()

    if not active_feed_dict:
        st.info("Выберите хотя бы один научный журнал в меню слева.")
        st.stop()

    if st.button("🚀 Сканировать свежую науку", type="primary"):
        raw_articles = []
        feed_reports = []
        
        with st.spinner("Параллельно опрашиваем выбранные научные журналы..."):
            with ThreadPoolExecutor(max_workers=15) as executor:
                futures = [
                    executor.submit(fetch_single_feed, name, active_feed_dict[name], items_per_feed)
                    for name in active_feed_dict.keys()
                ]
                for future in as_completed(futures):
                    res = future.result()
                    feed_reports.append(res)
                    if res["status"] == "ok":
                        raw_articles.extend(res["articles"])
        
        seen_links = set()
        all_articles = []
        for item in raw_articles:
            link = item.get("link", "")
            if link and link not in seen_links:
                seen_links.add(link)
                all_articles.append(item)
        
        ok_feeds = [f for f in feed_reports if f["status"] == "ok"]
        failed_feeds = [f for f in feed_reports if f["status"] != "ok"]
        
        st.session_state["feed_diagnostic"] = {
            "ok": ok_feeds,
            "failed": failed_feeds,
            "total": len(active_feed_dict)
        }
        
        if not all_articles:
            st.warning("Все статьи из ответивших журналов уже есть в базе данных!")
        else:
            st.write(f"Найдено **{len(all_articles)}** уникальных новых статей. Анализируем через **`{selected_model}`** с ротацией ключей...")
            
            results = []
            errors_log = []
            progress_bar = st.progress(0)
            
            batch_size = 5
            batches = [all_articles[i:i + batch_size] for i in range(0, len(all_articles), batch_size)]
            
            active_key_idx = 0
            for b_idx, batch in enumerate(batches):
                batch_analysis, active_key_idx = analyze_batch_with_rotator(
                    keys_pool, selected_model, batch, start_key_index=active_key_idx
                )
                
                if isinstance(batch_analysis, list):
                    for i, res_item in enumerate(batch_analysis):
                        if i < len(batch) and isinstance(res_item, dict):
                            orig_item = batch[i].copy()
                            orig_item.update(res_item)
                            results.append(orig_item)
                            save_article_to_db(orig_item)
                elif isinstance(batch_analysis, dict) and "error" in batch_analysis:
                    errors_log.append(f"Пачка #{b_idx+1}: {batch_analysis['error']}")
                            
                progress_bar.progress((b_idx + 1) / len(batches))
                time.sleep(0.8)
                
            if errors_log and len(results) == 0:
                st.error(f"❌ Ошибка:\n\n`{errors_log[0]}`")
            else:
                results = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
                st.session_state["latest_results"] = results
                st.success(f"Готово! Обработано и добавлено в базу: **{len(results)}** тем (использовался ключ #{active_key_idx + 1}).")

    # Диагностика источников
    if "feed_diagnostic" in st.session_state:
        diag = st.session_state["feed_diagnostic"]
        with st.expander(f"📊 Статус опроса источников: Успешно ({len(diag['ok'])}) | Проблемных ({len(diag['failed'])})", expanded=False):
            if diag["failed"]:
                st.error("Следующие журналы не ответили:")
                for f in diag["failed"]:
                    st.markdown(f"- **{f['name']}** ➔ `{f['error']}`")
            st.success(f"Успешно ответили ({len(diag['ok'])} журналов):")
            st.markdown(" • ".join([f"**{f['name']}** ({len(f['articles'])} новых)" for f in diag["ok"]]))

    # Вывод результатов
    if "latest_results" in st.session_state and st.session_state["latest_results"]:
        all_latest = st.session_state["latest_results"]
        latest_filtered = [r for r in all_latest if r.get("score", 0) >= min_score]
        
        st.markdown("---")
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader(f"Свежие находки (Оценка ≥ {min_score}) — показано {len(latest_filtered)} из {len(all_latest)}")
        with c2:
            if latest_filtered:
                html_data = generate_html_report(latest_filtered, "Свежий выпуск Sci-Radar")
                st.download_button(
                    label="📥 Скачать этот выпуск в HTML",
                    data=html_data,
                    file_name=f"fresh_radar_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                    mime="text/html"
                )
                
        if not latest_filtered:
            st.warning(f"Найдено {len(all_latest)} тем, но их оценка ниже {min_score}. Сдвиньте ползунок оценки в сайдбаре влево.")
                
        for idx, res in enumerate(latest_filtered):
            score = res.get("score", 0)
            icon = "🔥" if score >= 8 else ("💡" if score >= 6 else "📌")
            cat = res.get("category", "Наука")
            
            with st.expander(f"{icon} [{score}/10] [{cat}] {res.get('titles', [''])[0]} — {res['source']}", expanded=(score >= 8)):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**Суть открытия:**\n{res.get('ru_tldr')}")
                    st.markdown(f"**🔥 Крючок / Парадокс:**\n{res.get('hook_angle')}")
                    st.markdown("**Варианты заголовков:**")
                    for t in res.get("titles", []):
                        st.markdown(f"- `{t}`")
                    st.markdown(f"[🔗 Первоисточник]({res['link']})")
                with col2:
                    st.markdown("**🎨 Промпт для Nano Banana:**")
                    st.text_area("Обложка 2:1:", value=res.get("nano_banana_prompt", ""), height=110, key=f"p_live_{idx}_{res.get('link', '')[:30]}")
                    st.caption(f"**Оценка {score}/10:** {res.get('score_reason')}")

# ----------------- ВКЛАДКА 2: ИСТОРИЯ И АРХИВ -----------------
with tab_history:
    st.title("📜 Архив всех исследований")
    st.caption("Поиск по всем ранее обработанным статьям в вашей локальной базе")
    
    col_s1, col_s2, col_s3 = st.columns([2, 1, 1])
    with col_s1:
        search_kw = st.text_input("🔍 Поиск по слову:", placeholder="динозавры, гравитация, Марс...")
    with col_s2:
        cat_filter = st.selectbox("Категория:", ["Все", "Динозавры", "Космос", "Кванты", "Геология", "Археология", "Биология", "Материалы", "AI"])
    with col_s3:
        hist_min_score = st.slider("Оценка от:", 1, 10, 1, key="hist_score")

    history_items = get_history(min_score=hist_min_score, search_query=search_kw, category=cat_filter)
    
    c_h1, c_h2 = st.columns([2, 1])
    with c_h1:
        st.write(f"Найдено в архиве: **{len(history_items)}** статей")
    with c_h2:
        if history_items:
            archive_html = generate_html_report(history_items, "Полный архив исследований")
            st.download_button(
                label="📥 Скачать весь архив в HTML",
                data=archive_html,
                file_name=f"archive_radar_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                key="dl_archive"
            )
            
    for idx, res in enumerate(history_items):
        score = res.get("score", 0)
        icon = "🔥" if score >= 8 else ("💡" if score >= 6 else "📌")
        cat = res.get("category", "Наука")
        
        with st.expander(f"{icon} [{score}/10] [{cat}] {res.get('titles', [''])[0]} | 📅 {res.get('created_at', '')}"):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**Суть открытия:**\n{res.get('ru_tldr')}")
                st.markdown(f"**🔥 Крючок:**\n{res.get('hook_angle')}")
                st.markdown("**Заголовки:**")
                for t in res.get("titles", []):
                    st.markdown(f"- `{t}`")
                st.markdown(f"[🔗 Ссылка на источник]({res['link']})")
            with col2:
                st.markdown("**🎨 Промпт для Nano Banana:**")
                st.text_area("Промпт:", value=res.get("nano_banana_prompt", ""), height=100, key=f"hist_p_{idx}_{res.get('link', '')[:30]}")

# ----------------- ВКЛАДКА 3: ПУЛ API КЛЮЧЕЙ -----------------
with tab_keys:
    st.title("🔑 Управление пулом API-ключей (Ротация)")
    st.caption("Вставьте сюда несколько ключей (по одному на строку). Радар будет автоматически переключаться между ними при исчерпании лимитов.")
    
    current_raw_keys = get_config("api_keys_pool", "")
    if not current_raw_keys.strip():
        current_raw_keys = get_config("gemini_api_key", "")
        
    keys_input = st.text_area(
        "Список API-ключей Google Gemini (каждый ключ с новой строки):",
        value=current_raw_keys,
        height=180,
        placeholder="AIzaSyA1b2c3d4e5...\nAIzaSyB6c7d8e9f0...\nAIzaSyC1d2e3f4g5..."
    )
    
    if st.button("💾 Сохранить пул ключей", type="primary"):
        parsed_keys = [k.strip() for k in keys_input.split("\n") if k.strip()]
        save_api_keys_pool(parsed_keys)
        st.success(f"Сохранено **{len(parsed_keys)}** ключей в базу! Они будут использоваться для ротации.")
        time.sleep(1)
        st.rerun()
        
    st.markdown("---")
    st.subheader("📋 Активные ключи в памяти:")
    current_pool = get_api_keys_pool()
    if current_pool:
        for idx, k in enumerate(current_pool):
            masked = k[:8] + "..." + k[-4:] if len(k) > 12 else "********"
            st.markdown(f"- **Ключ #{idx+1}:** `{masked}`")
    else:
        st.info("Пока не добавлено ни одного ключа.")

# ----------------- ВКЛАДКА 4: БАЗА ДАННЫХ -----------------
with tab_db_info:
    st.title("💾 Управление локальной базой данных")
    total_articles = len(get_history(min_score=0))
    st.metric("Всего статей в памяти:", total_articles)
    st.write(f"Файл базы: `{os.path.abspath(DB_PATH)}`")
    st.markdown("---")
    if st.button("🗑️ Полностью очистить базу статей", type="secondary"):
        clear_db()
        st.success("База данных очищена!")
        st.rerun()