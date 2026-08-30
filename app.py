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

st.set_page_config(page_title="iXBT Mega Sci-Radar Pro", page_icon="🔬", layout="wide")

# ==========================================
# 🔒 ЗАЩИТА ПАРОЛЕМ
# ==========================================
DEFAULT_PWD = st.secrets.get("APP_PASSWORD", "ruby2026")
saved_auth = st.query_params.get("auth")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = (saved_auth == DEFAULT_PWD)

if not st.session_state["authenticated"]:
    st.title("🔒 Вход в Sci-Radar Pro")
    st.caption("Личный кабинет автора Ruby_Rougarou (iXBT Live)")
    
    pwd_input = st.text_input("Введите пароль доступа:", type="password")
    remember_me = st.checkbox("Запомнить меня на этом устройстве", value=True)
    
    if st.button("Войти на радар", type="primary"):
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
# GOOGLE ТАБЛИЦА И НАСТРОЙКИ
# ==========================================
DB_PATH = "radar_history.db"
GSHEETS_URL = st.secrets.get("GSHEETS_URL", "")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36'}

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

def get_radar_keys():
    try:
        if hasattr(st, "secrets") and "GEMINI_API_KEYS" in st.secrets:
            raw = st.secrets["GEMINI_API_KEYS"]
            keys = [k.strip() for k in raw.split("\n") if k.strip() and len(k.strip()) > 15]
            if keys: return keys
    except:
        pass
    return []

# ==========================================
# ПОЛНАЯ БАЗА НАУЧНЫХ ЖУРНАЛОВ (С КРУГЛОСУТОЧНЫМ ARXIV API)
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
        "📜 arXiv: Астрофизика (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:astro-ph&sortBy=submittedDate&sortOrder=descending&max_results=10",
        "🚀 NASA News": "https://www.nasa.gov/news-release/feed/"
    },
    "⚛️ Физика и Кванты": {
        "🔬 Nature Physics": "https://www.nature.com/nphys.rss",
        "📜 arXiv: Квантовая физика (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:quant-ph&sortBy=submittedDate&sortOrder=descending&max_results=10",
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
        "📜 arXiv: AI и Компьютерные науки (24/7 API)": "https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=10"
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
    status = "ok"
    err = ""
    try:
        req = urllib.request.Request(feed_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=6) as response:
            parsed = feedparser.parse(response.read())
            if not parsed.entries:
                status = "empty"
                err = "Лента пуста"
            else:
                for entry in parsed.entries[:items_per_feed]:
                    title = entry.get("title", "").replace("\n", " ").strip()
                    summary = re.sub(r'<[^>]+>', '', entry.get("summary", entry.get("description", ""))).replace("\n", " ").strip()
                    link = entry.get("link", "")
                    articles.append({"source": feed_name, "title": title, "summary": summary[:1200], "link": link})
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

def generate_html_report(results, report_title="Sci-Radar Report"):
    date_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    cards = ""
    for r in results:
        sc = r.get("score", 0)
        col = "#10b981" if sc >= 8 else ("#f59e0b" if sc >= 6 else "#64748b")
        t_items = "".join([f"<li style='margin-bottom:6px;'>{t}</li>" for t in r.get("titles", [])])
        cards += f"""
        <div style="background:#1e293b; border:1px solid #334155; border-radius:12px; padding:24px; margin-bottom:24px; color:#f8fafc;">
            <div style="display:flex; gap:10px; align-items:center; margin-bottom:12px;">
                <span style="background:#475569; padding:4px 10px; border-radius:6px; font-size:12px;">{r.get('category','Наука')}</span>
                <span style="background:{col}; color:#fff; padding:4px 10px; border-radius:20px; font-weight:bold;">{sc}/10</span>
                <span style="margin-left:auto; color:#94a3b8; font-size:13px;">{r.get('source')}</span>
            </div>
            <h2 style="color:#fff; font-size:20px;">{r.get('titles',[''])[0]}</h2>
            <p><strong>💡 Суть:</strong> {r.get('ru_tldr')}</p>
            <p><strong>🔥 Парадокс:</strong> {r.get('hook_angle')}</p>
            <ul style="list-style:none; padding-left:0;">{t_items}</ul>
            <div style="background:#090d16; padding:12px; border-radius:8px; border:1px dashed #334155; font-family:monospace; color:#38bdf8;">
                🎨 {r.get('nano_banana_prompt')}
            </div>
            <p style="margin-top:14px; font-size:13px;"><a href="{r.get('link')}" target="_blank" style="color:#38bdf8;">🔗 Источник исследования &rarr;</a></p>
        </div>"""
    return f"<!DOCTYPE html><html><head><meta charset='UTF-8'><title>{report_title}</title></head><body style='background:#0f172a; font-family:sans-serif; padding:24px;'><div style='max-width:1000px; margin:0 auto;'><h1 style='color:#38bdf8;'>🔭 {report_title} | {date_str}</h1>{cards}</div></body></html>"

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
radar_keys = get_radar_keys()

with st.sidebar:
    st.title("⚙️ Настройки")
    if radar_keys:
        st.success(f"🔑 Ключей в Secrets: **{len(radar_keys)}**")
    if GSHEETS_URL:
        st.success("📊 Google Таблица: **Подключена**")
        
    selected_model = st.selectbox("🤖 Модель:", ["gemini-3.6-flash", "gemini-2.0-flash", "gemini-1.5-flash"], index=0)

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
                st.warning("⚠️ Защищены Cloudflare.")
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
    min_score = st.slider("Показывать от оценки", 1, 10, 6)
    
    st.markdown("---")
    if st.button("🚪 Выйти из аккаунта"):
        st.session_state["authenticated"] = False
        st.query_params.clear()
        st.rerun()

# ==========================================
# ОСНОВНОЙ ЭКРАН
# ==========================================
tab_live, tab_history = st.tabs(["🔭 Свежий Радар", "📊 Вечный архив (Google Таблица)"])

with tab_live:
    st.title("🔭 Свежий Sci-Radar")
    st.caption("Поиск свежих открытий ➔ Анализ через Gemini 3.6 Flash ➔ Сохранение в Google Таблицу")

    if not radar_keys:
        st.warning("⚠️ Добавьте ключи в `Secrets` приложения!")
        st.stop()

    if not active_feed_dict:
        st.info("Выберите хотя бы один научный журнал в меню слева.")
        st.stop()

    if st.button("🚀 Сканировать свежую науку", type="primary"):
        all_articles = []
        feed_reports = []
        
        with st.spinner("Опрос выбранных научных журналов и arXiv API..."):
            with ThreadPoolExecutor(max_workers=15) as ex:
                futures = [ex.submit(fetch_single_feed, name, active_feed_dict[name], items_per_feed) for name in active_feed_dict.keys()]
                for f in as_completed(futures):
                    res = f.result()
                    feed_reports.append(res)
                    if res["status"] == "ok":
                        all_articles.extend(res["articles"])
        
        seen = set()
        unique = [x for x in all_articles if x["link"] not in seen and not seen.add(x["link"])]
        
        ok_feeds = [f for f in feed_reports if f["status"] == "ok"]
        failed_feeds = [f for f in feed_reports if f["status"] != "ok"]
        
        st.session_state["feed_diag"] = {"ok": ok_feeds, "failed": failed_feeds}
        
        if not unique:
            st.warning("Все свежие статьи уже обработаны!")
        else:
            st.write(f"Найдено **{len(unique)}** новых статей. Анализируем через **{selected_model}**...")
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
        
        c1, c2 = st.columns([2, 1])
        with c1:
            st.subheader(f"Свежие находки (Оценка ≥ {min_score})")
        with c2:
            if filtered:
                html_data = generate_html_report(filtered, "Свежий выпуск Sci-Radar")
                st.download_button("📥 Скачать этот выпуск в HTML", data=html_data, file_name="fresh_radar.html", mime="text/html")
                
        for res in filtered:
            sc = res.get('score', 0)
            icon = "🔥" if sc >= 8 else "💡"
            with st.expander(f"{icon} [{sc}/10] [{res.get('category')}] {res.get('titles', [''])[0]}"):
                st.markdown(f"**Суть открытия:** {res.get('ru_tldr')}")
                st.markdown(f"**Парадокс:** {res.get('hook_angle')}")
                st.markdown(f"[🔗 Источник исследования]({res.get('link')})")

with tab_history:
    st.title("📊 Вечный архив (Google Таблица)")
    st.caption("Все ранее найденные темы, сохраненные на вашем Google Диске")
    
    if st.button("🔄 Обновить историю из Google Таблицы"):
        st.session_state["gsheets_history"] = fetch_from_gsheets()
        
    if "gsheets_history" not in st.session_state:
        st.session_state["gsheets_history"] = fetch_from_gsheets()
        
    history_items = st.session_state["gsheets_history"]
    st.write(f"Всего статей в вашей Google Таблице: **{len(history_items)}**")
    
    if history_items:
        hist_html = generate_html_report(history_items, "Полный архив исследований")
        st.download_button("📥 Скачать весь архив в HTML", data=hist_html, file_name="archive_radar.html", mime="text/html")
        
    for r in history_items[:30]:
        with st.expander(f"[{r.get('score')}/10] [{r.get('category')}] {r.get('titles', [''])[0]} | 📅 {r.get('created_at')}"):
            st.markdown(f"**Суть:** {r.get('ru_tldr')}")
            st.markdown(f"[🔗 Ссылка]({r.get('link')})")
