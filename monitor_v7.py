#!/usr/bin/env python3
"""
monitor.py v7.7.2 — OkaFloodMonitor
HTML-генерация + аналитика + Telegram-оповещения
Источники: serpuhov.ru (PRIMARY) | КИМ API | ЦУГМС | Open-Meteo | GloFAS

v7.6.1 changelog:
- NEW_IMAGES_B64: встроены 17 новых изображений из new_images_b64.py
- Hero section: белый полупрозрачный фон для читаемости текста
- Заменён водный паттерн на пузырьковый
- Английская физика волны заменена на русскую версию
- Переработан блок GloFAS (карточки станций)
- Добавлены изображения ко всем 9 секциям flood-guide
- Добавлены изображения к ключевым секциям history
- Секция снеготаяния и спутникового мониторинга на главной

v7.6.1 changelog:
- Light theme (white/light-grey background, dark text)
- Water pattern background (CSS radial-gradient)
- Hero section gradient + SVG wave divider
- Unified _build_nav() with burger menu (mobile) + dropdown (desktop)
- История паводков: TOC added
- Renamed 'Ликбез' → 'Физика половодья' everywhere
- Wave timeline: alternating label positions to avoid overlap
- SVG map of Oka cities on cities/index.html
- PDF reports: auto-scan reports/ folder
- Fixed flood-guide.html wave icon
- Navigation fixed on ALL pages
"""
import os
import re
import json
import csv
import math
import subprocess
from datetime import datetime, timedelta, timezone, date as date_cls

# === v7.6.1: Новые изображения ===
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from new_images_b64 import NEW_IMAGES_B64
except ImportError:
    NEW_IMAGES_B64 = {}

try:
    from weathermulti import fetch_multi_weather, generate_precip_matrix_html
except ImportError:
    fetch_multi_weather = None
    generate_precip_matrix_html = None

# ─── ИМПОРТЫ ИЗ FETCH_MODULE v3.0 ────────────────────────────────────────────
try:
    from fetch_module import (
        fetch_all_data,
        fetch_weather_extended,
        LUKYANNOVO_ZERO_M_BS,
        LUKYANNOVO_NYA_M_BS,
        LUKYANNOVO_OYA_M_BS,
        ZONE_GREEN_MAX,
        ZONE_YELLOW_MAX,
        ZONE_ORANGE_MAX,
        WAVE_OREL_TO_SERPUHOV,
        WAVE_KALUGA_TO_SERPUHOV,
        WAVE_ALEKSIN_TO_SERPUHOV,
        WAVE_SERPUHOV_TO_ZHERNIVKA,
        GLOFAS_STATIONS,
        _svg_sparkline,
        calculate_wave_arrival,
    )
except ImportError:
    # Fallback-константы если fetch_module не установлен
    def fetch_all_data():
        return {
            "serpuhov": {"level_m": None, "level_cm": None, "daily_change_m": None,
                         "daily_change_cm": None, "nya_m_bs": 113.99, "oya_m_bs": 115.54,
                         "abs_level_m_bs": None, "water_status": "нет данных",
                         "source": "serpuhov.ru", "source_status": "unavailable", "cache_age_h": 0.0},
            "kim": {"_api_status": "unavailable"},
            "cugms": {"source_status": "unavailable"},
            "weather": None,
            "glofas": {"_status": "unavailable"},
            "fetch_time": datetime.now(timezone.utc).isoformat(),
            "sources_ok": [], "sources_failed": ["serpuhov.ru", "kim", "cugms", "weather", "glofas"],
        }

    def fetch_weather_extended():
        return None

    LUKYANNOVO_ZERO_M_BS = 107.54
    LUKYANNOVO_NYA_M_BS  = 113.99
    LUKYANNOVO_OYA_M_BS  = 115.54
    ZONE_GREEN_MAX  = 400
    ZONE_YELLOW_MAX = 600
    ZONE_ORANGE_MAX = 800
    WAVE_OREL_TO_SERPUHOV      = (5, 7)
    WAVE_KALUGA_TO_SERPUHOV    = (2, 3)
    WAVE_ALEKSIN_TO_SERPUHOV   = (1, 2)
    WAVE_SERPUHOV_TO_ZHERNIVKA = (0.25, 0.5)
    GLOFAS_STATIONS = {}

    def _svg_sparkline(values, width=80, height=24, color="#3b82f6"):
        return ""

    def calculate_wave_arrival(glofas_data):
        return {}


# ─── ENV VARS ──────────────────────────────────────────────────────────────────
TG_TOKEN       = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN     = os.environ.get("TG_CHAT_ID", "49747475")
CHAT_MY_GROUP  = os.environ.get("TG_GROUP_ID", "-5234360275")
CHAT_NEIGHBORS = os.environ.get("TG_NEIGHBORS_ID", "-1001672586477")
CHAT_ZMSS      = os.environ.get("TG_CHAT_ZMSS", "")   # вторая группа соседей

# ─── ПУТИ ──────────────────────────────────────────────────────────────────────
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
DATA_DIR          = os.path.join(BASE_DIR, "data")
DOCS_DIR          = os.path.join(BASE_DIR, "docs")
HISTORY_JSON      = os.path.join(DATA_DIR, "history.json")
HISTORY_CSV       = os.path.join(DOCS_DIR, "history.csv")
DATA_JSON         = os.path.join(DOCS_DIR, "data.json")
INDEX_HTML        = os.path.join(DOCS_DIR, "index.html")
LINKS_HTML        = os.path.join(DOCS_DIR, "links.html")
INSTRUCTIONS_HTML = os.path.join(DOCS_DIR, "instructions.html")
HISTORY_HTML      = os.path.join(DOCS_DIR, "history.html")
FLOOD_GUIDE_HTML  = os.path.join(DOCS_DIR, "flood-guide.html")
ALERTS_FILE       = os.path.join(DATA_DIR, "alerts_sent.json")   # НЕ в docs/!
MAILING_LIST      = os.path.join(DATA_DIR, "mailing_list.json")
REF_2024          = os.path.join(DATA_DIR, "2024_ref.json")
MCHS_FORECAST     = os.path.join(DATA_DIR, "mchs_forecast.json")
GROUP_DRAFT       = os.path.join(DOCS_DIR, "group_draft.txt")

# ─── ПОРОГИ АЛЕРТОВ (в СМ от нуля поста) ────────────────────────────────────
ALERT_ATTENTION = 400
ALERT_DANGER    = 600
ALERT_CRITICAL  = 800
ALERT_EMERGENCY = 900

ALERT_THRESHOLDS = [
    (400, "ALERT_400", "🟡 L1 Внимание",        "Уровень достиг 400 см — паводок в активной фазе.", 6),
    (600, "ALERT_600", "🟠 L2 Опасность",        "600 см — пойма заполняется. Следите.", 6),
    (800, "ALERT_800", "🔴 L3 Критично",          "800 см — критический уровень. Дачи под угрозой.", 4),
    (900, "ALERT_900", "🆘 L4 ЧРЕЗВЫЧАЙНАЯ",     "900 см! Немедленно принять меры!", 4),
]

# ─── Личные пороги автора проекта (v7.7) ────────────────────────────────
AUTHOR_OYA_CM = 867   # 2024 пик (846) + 21 см запас = уровень входа воды
AUTHOR_BYA_CM = 967   # ОЯ_личный + 100 см = предел защитной дамбы
AUTHOR_WAVE_DELAY_HOURS = 7  # от Лукьяново до Жерновки ~28 км, ~7 ч

# ─── КОЛОНКИ HISTORY.CSV (v7 — расширены GloFAS) ─────────────────────────────
HISTORY_COLS = [
    "datetime",
    "serp_level_m", "serp_level_cm", "serp_daily_change_cm",
    "serp_abs_m_bs", "serp_source",
    "kim_kashira_cm", "kim_kaluga_cm", "kim_ryazan_cm",
    "cugms_serp_change_cm", "cugms_kashira_change_cm", "cugms_review_number",
    "temp", "precip_mm", "snow_depth_cm", "flood_weather_index",
    "alert_level", "days_to_nya", "days_to_oya",
    # NEW v7 GloFAS columns:
    "glofas_belev_discharge", "glofas_kaluga_discharge", "glofas_tarusa_discharge",
    "glofas_peak_station", "glofas_peak_date", "glofas_serpukhov_arrival",
    "notes",
]


# ─── ГОРОДА НА РЕКЕ ОКА (от истока к устью) ───────────────────────────────────
OKA_CITIES = [
    {
        "slug": "orel",
        "name": "Орёл",
        "lat": 52.9651, "lon": 36.0785,
        "population": 289503,
        "founded": 1566,
        "river": "р. Ока (слияние с р. Орлик)",
        "bank": "оба берега (слияние Оки и Орлика)",
        "km_from_source": 111,
        "glofas_slug": "orel",
        "hydro_post": {
            "name": "г. Орёл на р. Ока",
            "zero_m_bs": 146.31,
            "operator": "ФГБУ «Центрально-Чернозёмное УГМС»",
            "critical_levels": [
                (750, "режим повышенной готовности"),
                (880, "неблагоприятное явление"),
                (892, "опасный уровень"),
            ],
        },
        "flood_risk": "Низины Заводского и Железнодорожного районов, набережные; д. Тайное и Гать — первые принимают удар",
        "notable_floods": [
            (1908, "1005 см", "Крупное наводнение, дома по первый этаж в воде"),
            (1970, "1010 см", "29 улиц, 913 домов, 21 предприятие; эвакуировано 1195 чел."),
            (1979, "985 см", "Одно из крупнейших за историю наблюдений"),
            (2003, "866 см", "29 улиц, 223 дома, 1048 чел. в зоне подтопления"),
        ],
        "description": (
            "Столица Орловской области стоит там, где Ока встречается с Орликом — и этот союз двух рек в половодье "
            "оборачивается против горожан. Здесь Ока ещё молода и узка, но характер уже виден: при высоком паводке "
            "вода поднимается на восемь–десять метров, накрывая пойменные кварталы с нескрываемым удовольствием.",
            "Основанный в 1566 году по указу Ивана Грозного как сторожевая крепость, Орёл и сейчас несёт службу — "
            "в роли первого значительного гидрологического поста на всей реке. Данные отсюда служат ранним "
            "предупреждением для Белёва, Калуги и всех городов до самой Коломны.",
            "Самый суровый удар пришёлся на 1970 год: вода перевалила за десять метров, затопила 29 улиц и "
            "913 домов, в городе ввели режим ЧП. Орловский обком написал в ЦК с просьбой отменить "
            "первомайские торжества — Ока оказалась неплохим организатором нерабочих дней."
        ),
        "serpuhov_km_river": 411,
        "serpuhov_wave_days": (5, 7),
    },
    {
        "slug": "mtsensk",
        "name": "Мценск",
        "lat": 53.2821, "lon": 36.5703,
        "population": 36070,
        "founded": 1146,
        "river": "р. Зуша (приток Оки)",
        "bank": "оба берега р. Зуша",
        "km_from_source": None,
        "glofas_slug": None,
        "hydro_post": None,
        "nearest_hydro_post": "Орёл (выше по Оке) и Белёв (ниже по Оке)",
        "flood_risk": "Правобережные кварталы на низком берегу Зуши, СНТ в пойме",
        "notable_floods": [
            (0, "7–8 м", "Зуша ежегодно поднимается на 7–8 м, затапливая пойменные территории"),
        ],
        "description": (
            "Мценск — один из древнейших городов Орловской области, ровесник Москвы по первому летописному "
            "упоминанию (1146 г.). Он стоит не на самой Оке, а на Зуше — правом притоке, впадающем в Оку "
            "несколькими десятками километров ниже. Это придаёт городу особую гидрологическую роль: паводок "
            "на Зуше у Мценска предшествует подъёму Оки ниже слияния.",
            "Старый центр занимает высокий левый берег — крутой мыс над рекой, откуда открывается "
            "панорама, достойная пейзажного художника. Современные кварталы расположились напротив, "
            "на низком правом берегу, и каждую весну именно они принимают воду гостеприимно и "
            "без особого выбора.",
            "Зуша при сильном паводке поднимается до семи-восьми метров. Мониторинг здесь ведут "
            "ФГБУ «Центрально-Чернозёмное УГМС» и ГУ МЧС по Орловской области — "
            "отдельного гидропоста на самой реке нет, но пропустить разлив всё равно не получится."
        ),
        "serpuhov_km_river": None,
        "serpuhov_wave_days": None,
    },
    {
        "slug": "belev",
        "name": "Белёв",
        "lat": 53.8062, "lon": 36.1457,
        "population": 12382,
        "founded": 1147,
        "river": "р. Ока",
        "bank": "левый (высокий) берег",
        "km_from_source": 258,
        "glofas_slug": "belev",
        "hydro_post": {
            "name": "г. Белёв на р. Ока",
            "zero_m_bs": 127.15,
            "operator": "Центр регистра и кадастра / ФГБУ «Центрально-Чернозёмное УГМС»",
            "critical_levels": [],
        },
        "flood_risk": "Пойма правого берега, низководный мост у Николо-Гастуни, СНТ и дачи в пойме",
        "notable_floods": [
            (2003, "1100 см", "Абсолютный максимум (11 м): рекорд гидропоста"),
            (2024, "~685 см", "Затоплен мост у Николо-Гастуни, отрезано 5 сёл"),
        ],
        "description": (
            "Белёв — небольшой, но исторически важный город Тульской области, стоящий на высоком левом "
            "берегу Оки с 1147 года. В XIX веке через него проходило до полутора тысяч судов в год — "
            "речная торговля кипела здесь, как чайник у хозяйственной хозяйки.",
            "Гидрологический пост в Белёве — ключевой промежуточный пункт между Орлом и Калугой. "
            "Данные отсюда используются калужскими синоптиками и МЧС для предварительных прогнозов. "
            "Паводок в Белёве — это по сути уведомление всему среднему течению: «готовьтесь, едем».",
            "Абсолютный рекорд поста — 1100 сантиметров, установленный 19 апреля 2003 года. Одиннадцать метров "
            "воды над нулём поста. В 2024 году вода скромнее — 685 сантиметров, но и этого хватило, чтобы "
            "затопить низководный мост у Николо-Гастуни и отрезать пять сёл от большой земли."
        ),
        "serpuhov_km_river": 264,
        "serpuhov_wave_days": (3, 5),
    },
    {
        "slug": "chekalin",
        "name": "Чекалин",
        "lat": 54.1000, "lon": 36.2500,
        "population": 935,
        "founded": 1565,
        "river": "р. Ока",
        "bank": "левый (высокий) берег",
        "km_from_source": None,
        "glofas_slug": None,
        "hydro_post": None,
        "nearest_hydro_post": "Белёв (выше) и Алексин (ниже)",
        "flood_risk": "Пойма правого берега, периодически затапливаемые низкие участки",
        "notable_floods": [
            (0, "—", "Ежегодный весенний паводок характерен для этого участка Оки"),
        ],
        "description": (
            "Чекалин — самый маленький город России на Оке и один из наименее населённых городов страны "
            "вообще: около 935 жителей по переписи 2021 года. До 1944 года он назывался Лихвин, "
            "а переименован в честь шестнадцатилетнего партизана Александра Чекалина, казнённого "
            "немецкими оккупантами.",
            "С гидрологической точки зрения Чекалин — промежуточный пункт между Белёвом и Алексином. "
            "Город стоит на высоком крутом левом берегу — именно эта неприступная скала в XVI веке "
            "делала Лихвинскую крепость частью Засечной черты. Высота берега и сегодня защищает "
            "историческое ядро от затопления.",
            "Пойменные территории правого берега затапливаются ежегодно. Официального гидропоста "
            "непосредственно у Чекалина нет — мониторинг ведёт ГУ МЧС по Тульской области, "
            "ориентируясь на соседние посты."
        ),
        "serpuhov_km_river": None,
        "serpuhov_wave_days": None,
    },
    {
        "slug": "kozelsk",
        "name": "Козельск",
        "lat": 54.0378, "lon": 35.7936,
        "population": 16603,
        "founded": 1146,
        "river": "р. Жиздра (левый приток Оки)",
        "bank": "левый берег р. Жиздра",
        "km_from_source": None,
        "glofas_slug": "kozelsk",
        "hydro_post": {
            "name": "г. Козельск на р. Жиздра",
            "zero_m_bs": 130.43,
            "operator": "Центр регистра и кадастра / ФГБУ «Центральное УГМС»",
            "critical_levels": [
                (892, "опасный (критический) уровень"),
            ],
        },
        "flood_risk": "Спортивная ул., Колхозная ул.; Оптина пустынь и сёла в долине Жиздры",
        "notable_floods": [
            (2013, "~940 см", "Окраины затоплены, вода у центра, угроза эвакуации Оптиной пустыни"),
            (2023, "767 см", "Затоплены Спортивная и Колхозная улицы"),
            (2024, "866 см", "Близко к критическому (892 см)"),
        ],
        "description": (
            "«Злой город» — именно так прозвали Козельск воины хана Батыя, семь недель безуспешно "
            "осаждавшие его в 1238 году. С тех пор город носит звание «Города воинской славы» "
            "и всё так же демонстрирует стойкость — теперь уже перед ежегодными разливами Жиздры.",
            "Козельск стоит на Жиздре — левом притоке Оки, впадающем выше Калуги. Жиздра — одна из "
            "наиболее паводкоопасных рек Калужской области: при критическом уровне в 892 сантиметра "
            "вода выходит на улицы города. В 2013 году она поднялась почти до девяти с половиной "
            "метров, и под угрозой эвакуации оказалась Оптина пустынь — знаменитый монастырь "
            "прямо в пойме реки.",
            "Прогноз на 2026 год предупреждал о подъёме до 9,8 метра. Данные козельского поста "
            "регулярно включаются в оперативные гидрометеорологические справки: то, что случается "
            "на Жиздре, через несколько суток скажется на Оке выше Калуги."
        ),
        "serpuhov_km_river": None,
        "serpuhov_wave_days": None,
    },
    {
        "slug": "kaluga",
        "name": "Калуга",
        "lat": 54.4982, "lon": 36.2582,
        "population": 329673,
        "founded": 1371,
        "river": "р. Ока",
        "bank": "исторически левый высокий; новые кварталы — правый",
        "km_from_source": 391,
        "glofas_slug": "kaluga",
        "hydro_post": {
            "name": "г. Калуга на р. Ока",
            "zero_m_bs": 116.72,
            "operator": "ФГУП «Канал имени Москвы»",
            "critical_levels": [
                (1350, "опасный уровень"),
            ],
        },
        "flood_risk": "Поселки Гать и Шопино, правобережные микрорайоны; Окский водозабор (скважины при +4 м)",
        "notable_floods": [
            (1788, "15,3 м", "«Необыкновенное наводнение»"),
            (1908, "16,77 м", "Крупнейшее за 200 лет: по улицам плавали на лодках; затоплен дом Циолковского"),
            (1931, "15,44 м", "Значительный паводок"),
            (1970, "15,25 м", "Затоплены улицы у Воробьёвки и Салтыкова-Щедрина"),
            (1988, "15,3 м", "131 дом подтоплен"),
        ],
        "description": (
            "Калуга — административный центр области и один из главных опорных пунктов гидрологического "
            "мониторинга всей Оки. Систематические наблюдения за уровнем реки здесь ведутся с 1877 года — "
            "поначалу с помощью учащихся Реального училища, которым явно не давали скучать.",
            "Исторический центр разместился на высоком левом берегу и при обычных паводках чувствует "
            "себя вполне спокойно. Другое дело — новые микрорайоны на правобережье: Правград, "
            "Правобережье, Кошелев-проект. Они выросли там, где прежде паслись луга, и каждую весну "
            "напоминают своим жителям об этом факте.",
            "Рекорд Калуги — паводок 1908 года: вода поднялась почти на 17 метров над летним горизонтом. "
            "По улицам ездили на лодках, а дом самого Циолковского оказался в зоне затопления. "
            "Опасный уровень сегодня — 1350 сантиметров от нуля поста; прогноз на 2026 год — "
            "750–1050 сантиметров."
        ),
        "serpuhov_km_river": 131,
        "serpuhov_wave_days": (2, 3),
    },
    {
        "slug": "aleksin",
        "name": "Алексин",
        "lat": 54.4800, "lon": 37.0100,
        "population": 60842,
        "founded": 1348,
        "river": "р. Ока",
        "bank": "оба берега",
        "km_from_source": 452,
        "glofas_slug": "aleksin",
        "hydro_post": {
            "name": "с. Щукина / г. Алексин на р. Ока",
            "zero_m_bs": 111.19,
            "operator": "Центр регистра и кадастра",
            "critical_levels": [
                (1000, "режим повышенной готовности"),
                (1120, "неблагоприятное явление"),
            ],
        },
        "flood_risk": "Пойменные территории обоих берегов, СНТ и дачи в пойме",
        "notable_floods": [
            (2013, "1069 см", "Абсолютный максимум гидропоста (21 апреля)"),
            (2023, "705 см", "Подъём на 55 см за сутки; неблагоприятное явление"),
        ],
        "description": (
            "Алексин стоит на Оке с 1348 года — сначала как пограничная крепость, потом как купеческий "
            "и промышленный город. Расположен на обоих берегах реки, хотя высота над уровнем моря "
            "в 160 метров говорит о том, что рельеф здесь отнюдь не пологий.",
            "Гидрологический пост у с. Щукина — важная промежуточная точка между Калугой и Серпуховым. "
            "Здесь с 2021 года ведутся дноуглубительные работы, которые в теории должны снизить риск "
            "затопления — на практике же паводок 2023 года поднялся на 55 сантиметров за одни сутки, "
            "что официально зафиксировано как неблагоприятное гидрологическое явление.",
            "Рекорд поста — 1069 сантиметров, поставленный 21 апреля 2013 года. Для сравнения: критический "
            "уровень начинается с 1000 сантиметров. В подобные моменты пойменные СНТ обоих берегов "
            "превращаются в острова, а дачники — в невольных мореплавателей."
        ),
        "serpuhov_km_river": 70,
        "serpuhov_wave_days": (1, 2),
    },
    {
        "slug": "tarusa",
        "name": "Таруса",
        "lat": 54.7275, "lon": 37.1693,
        "population": 8785,
        "founded": 1246,
        "river": "р. Ока (при впадении р. Тарусы)",
        "bank": "левый (высокий) берег",
        "km_from_source": None,
        "glofas_slug": "tarusa",
        "hydro_post": None,
        "nearest_hydro_post": "Серпухов (ниже, ~522 км от истока)",
        "flood_risk": "Нижняя часть города у устья р. Тарусы, прибрежные кварталы",
        "notable_floods": [
            (1908, "—", "Вода залила полы Петропавловского собора, здание казначейства, торговые ряды"),
            (1917, "—", "Залита часть города у устья р. Тарусы и часть городской площади"),
        ],
        "description": (
            "Таруса — город, который не захотел становиться промышленным. Без железной дороги, "
            "в статусе природно-архитектурного заповедника, она привлекла Цветаеву, Паустовского, "
            "Ахмадулину. Теперь сюда едут за тишиной, пейзажами и Окой, которая здесь "
            "особенно хороша.",
            "Город стоит на высоком левом берегу — природный амфитеатр над рекой. Большая часть "
            "застройки надёжно защищена рельефом. Уязвимы только нижние кварталы у устья "
            "реки Тарусы — именно там в 1908 году вода добралась до полов собора и "
            "торговых рядов.",
            "Официального гидропоста в Тарусе нет: мониторинг ведётся через ближайшие посты "
            "(Алексин выше и Серпухов ниже) и региональными службами МЧС. Между Тарусой и "
            "Серпуховым — около 36 километров по реке."
        ),
        "serpuhov_km_river": 36,
        "serpuhov_wave_days": (0.5, 1),
    },
    {
        "slug": "serpuhov",
        "name": "Серпухов",
        "lat": 54.9167, "lon": 37.4167,
        "population": 133756,
        "founded": 1339,
        "river": "р. Ока (пристань; город — на р. Нара)",
        "bank": "левый берег Оки у устья р. Нары",
        "km_from_source": 522,
        "glofas_slug": None,
        "hydro_post": {
            "name": "г. Серпухов на р. Ока (пост Лукьяново)",
            "zero_m_bs": 107.54,
            "operator": "ФГУП «Канал имени Москвы» / ФГБУ «Центральное УГМС»",
            "critical_levels": [
                (645, "неблагоприятное явление — выход воды на пойму"),
                (800, "опасное явление — подтопление населённых пунктов"),
            ],
        },
        "flood_risk": "«Окская слобода», пойменные СНТ вдоль Оки, Жерновка и окрестные сёла",
        "notable_floods": [
            (1908, "~2160 см (10 сажен)", "Снесло ст. «Ока», погибли люди; крупнейшее в истории"),
            (1999, "893 см", "Последний значительный подъём до XXI века"),
            (2013, "843 см", "Абсолютный максимум инструментального периода"),
        ],
        "description": (
            "Серпухов — главная мониторинговая точка Оки для всей Московской области. "
            "Именно здесь расположен пост Лукьяново, данные которого используются для "
            "прогнозирования паводка в Кашире и Коломне. Река здесь шириной около 220 метров — "
            "уже настоящая, полноводная.",
            "Сам город стоит на холмах у реки Нары и от прямого затопления Окой защищён рельефом. "
            "Зато в пойме южнее — коттеджные посёлки, СНТ, дачи. Среди них и Жерновка, за уровнем "
            "воды у которой и следит этот монитор.",
            "Историческая память о 1908 годе здесь особенно жива: тогда вода поднялась на "
            "десять сажен (больше двадцати метров), снесло железнодорожную станцию «Ока», "
            "погибли люди. Сегодня критическая отметка — 800 сантиметров; в 2013 году "
            "добрались до 843."
        ),
        "serpuhov_km_river": 0,
        "serpuhov_wave_days": (0, 0),
        "is_main": True,
    },
    {
        "slug": "pushchino",
        "name": "Пущино",
        "lat": 54.8320, "lon": 37.6212,
        "population": 19342,
        "founded": 1966,
        "river": "р. Ока (правый высокий берег)",
        "bank": "правый (высокий) берег",
        "km_from_source": None,
        "glofas_slug": None,
        "hydro_post": None,
        "nearest_hydro_post": "Серпухов — д. Лукьяново (522-й км от истока Оки, ≈17 км выше по течению от Пущино) и Кашира (573-й км от истока, ≈40 км ниже по течению)",
        "flood_risk": "Сам наукоград на высоком берегу; СНТ и дачи в пойме ниже по течению",
        "notable_floods": [
            (2013, "(Серпухов: 843 см)", "Высокий берег защитил наукоград; пойма левого берега затоплена"),
        ],
        "description": (
            "Пущино (Пущино-на-Оке) — один из немногих биологических наукоградов России. В советское время здесь зарождалась "
            "и вставала на ноги отечественная генная инженерия. Город расположен на высоком правом берегу Оки, "
            "откуда открывается знаменитая панорама на пойму.",
            "С Пущино связано имя Александра Алябьева — друга Пушкина, автора знаменитого романса «Соловей, мой соловей». "
            "Неподалёку сохранилась усадьба, где Никита Михалков снимал «Неоконченную пьесу для механического пианино». "
            "По берегам Оки здесь действительно очень много соловьёв и других певчих птиц — весной их трели звучат "
            "от заката до рассвета.",
            "Многие коренные пущинцы искренне считают свой родной город «Пупом Земли».",
            "Ширина поймы Оки у Пущино — до 3–5 км в половодье. "
            "Ближайший гидропост — д. Лукьяново (17 км вверх по реке, ~4–5 ч волны). "
            "Напротив — Приокско-Террасный заповедник (зубры, реликтовые степные растения)."
        ),
        "serpuhov_km_river": 51,
        "serpuhov_wave_days": (0.5, 1.5),
    },
    {
        "slug": "kashira",
        "name": "Кашира",
        "lat": 54.8442, "lon": 38.1484,
        "population": 44551,
        "founded": 1356,
        "river": "р. Ока",
        "bank": "правый (высокий) берег",
        "km_from_source": 573,
        "glofas_slug": None,
        "hydro_post": {
            "name": "г. Кашира на р. Ока",
            "zero_m_bs": 103.82,
            "operator": "ФГУП «Канал имени Москвы»",
            "critical_levels": [],
        },
        "flood_risk": "Левобережные территории (Старая Кашира — сёла Городище и Старая Кашира), СНТ в пойме",
        "notable_floods": [
            (2022, "—", "Режим повышенной готовности; высокая вероятность подтопления"),
            (0, "—", "С 1950-х гг. Ока обмелела на 2 м — снизила абсолютный риск"),
        ],
        "description": (
            "Кашира — один из старейших городов Подмосковья, известный с 1356 года. Любопытная деталь: "
            "первоначально он стоял на левом берегу (Старая Кашира), но к 1619 году перебрался на "
            "правый — высокий и крутой. Не исключено, что именно паводки ускорили это решение.",
            "С 1950-х годов Ока в районе Каширы обмелела на два метра — это снизило абсолютный риск "
            "экстремальных паводков, зато сделало затруднённым судоходство в засушливые годы. "
            "Каширская ГРЭС в этом контексте — важный объект, за состоянием которого следят отдельно.",
            "Исторические земли Старой Каширы на левом берегу — пойменные территории — ежегодно "
            "затапливаются. В 2022 году МЧС Московской области предупреждало о возможном "
            "«одном из самых сильных паводков» на этом участке, и население призывали "
            "следить за уровнем воды особенно внимательно."
        ),
        "serpuhov_km_river": 51,
        "serpuhov_wave_days": (1, 2),
    },
    {
        "slug": "kolomna",
        "name": "Коломна",
        "lat": 55.0794, "lon": 38.7783,
        "population": 132247,
        "founded": 1177,
        "river": "р. Ока (слияние с р. Москвой)",
        "bank": "правый берег у слияния Оки и Москвы-реки",
        "km_from_source": 645,
        "glofas_slug": None,
        "hydro_post": {
            "name": "г. Коломна на р. Ока",
            "zero_m_bs": 100.26,
            "operator": "Центр регистра и кадастра",
            "critical_levels": [],
        },
        "flood_risk": "Пойма ниже слияния с Москвой-рекой, Щурово (левый берег), СНТ в районе Коломны и Озёр",
        "notable_floods": [
            (2026, "+10 см/сут", "Активный весенний паводок, МЧС предупреждает о рисках"),
            (0, "—", "Ежегодные разливы при слиянии двух рек"),
        ],
        "description": (
            "Коломна — последний крупный мониторинговый пункт на Оке в Московской области и один из "
            "древнейших городов региона. Здесь Ока принимает Москву-реку — и это слияние двух рек "
            "создаёт особый риск: паводок на Москве-реке накладывается на половодье Оки, "
            "усиливая эффект.",
            "Исторический центр и кремль расположены на возвышенном правом берегу у стрелки. "
            "Левобережная часть — бывшее Щурово, присоединённое в 1959 году, — лежит ниже и "
            "более уязвима. Ниже по течению от Коломны начинаются Луховицы, Рязань и среднее "
            "течение Оки.",
            "Гидропост Коломны находится на 645-м километре от истока и служит последним "
            "предупреждением для нижнего течения. Данные поста используются для прогнозирования "
            "ситуации вплоть до Нижнего Новгорода."
        ),
        "serpuhov_km_river": 123,
        "serpuhov_wave_days": (2, 4),
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# ЗАГРУЗКА / СОХРАНЕНИЕ ДАННЫХ
# ══════════════════════════════════════════════════════════════════════════════

def load_history() -> list:
    """Читает data/history.json. Возвращает [] если файл не существует."""
    try:
        with open(HISTORY_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_history(history: list) -> None:
    """Сохраняет data/history.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def append_history_row(history: list, data: dict, analytics: dict, wext) -> list:
    """
    Добавляет новую запись в историю.
    v7: добавлены GloFAS-поля. Dedup по часу (datetime[:13]).
    """
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})
    cugms  = data.get("cugms", {})
    glofas = data.get("glofas", {})

    now_iso  = datetime.now(timezone.utc).isoformat()
    hour_key = now_iso[:13]

    if history and history[-1].get("datetime", "")[:13] == hour_key:
        print(f"[history] Дубликат пропущен: {hour_key}")
        return history

    today_day = {}
    if wext and wext.get("days"):
        for d in wext["days"]:
            if not d.get("is_forecast", True):
                today_day = d

    # GloFAS данные для CSV
    glofas_belev   = (glofas.get("belev") or {}).get("current_discharge")
    glofas_kaluga  = (glofas.get("kaluga") or {}).get("current_discharge")
    glofas_tarusa  = (glofas.get("tarusa") or {}).get("current_discharge")

    # Определяем ключевую станцию (наибольший расход)
    glofas_peak_station = None
    glofas_peak_date    = None
    max_q = 0
    for slug in ["belev", "kaluga", "tarusa", "aleksin", "mtsensk", "orel"]:
        st = glofas.get(slug, {})
        q = st.get("peak_discharge") or 0
        if q > max_q:
            max_q = q
            glofas_peak_station = st.get("name", slug)
            glofas_peak_date    = st.get("peak_date")

    # Расчёт прихода волны в Серпухов
    wave_info  = calculate_wave_arrival(glofas)
    serp_arr   = wave_info.get("serpukhov_arrival", {})
    glofas_serp_arrival = (
        f"{serp_arr.get('earliest','')[:10]}–{serp_arr.get('latest','')[:10]}"
        if serp_arr else None
    )

    row = {
        "datetime":                now_iso,
        "serp_level_m":            serp.get("level_m"),
        "serp_level_cm":           serp.get("level_cm"),
        "serp_daily_change_cm":    serp.get("daily_change_cm"),
        "serp_abs_m_bs":           serp.get("abs_level_m_bs"),
        "serp_source":             serp.get("source_status", "unknown"),
        "kim_kashira_cm":          (kim.get("kashira") or {}).get("level_cm"),
        "kim_kaluga_cm":           (kim.get("kaluga") or {}).get("level_cm"),
        "kim_ryazan_cm":           (kim.get("ryazan") or {}).get("level_cm"),
        "cugms_serp_change_cm":    cugms.get("serpuhov_change_cm"),
        "cugms_kashira_change_cm": cugms.get("kashira_change_cm"),
        "cugms_review_number":     cugms.get("review_number"),
        "temp":                    today_day.get("tmax"),
        "precip_mm":               today_day.get("precip"),
        "snow_depth_cm":           (wext or {}).get("snow_depth_cm"),
        "flood_weather_index":     (wext or {}).get("flood_index"),
        "alert_level":             analytics.get("alert_level", "НОРМА"),
        "days_to_nya":             analytics.get("days_to_nya"),
        "days_to_oya":             analytics.get("days_to_oya"),
        # NEW GloFAS v7:
        "glofas_belev_discharge":  glofas_belev,
        "glofas_kaluga_discharge": glofas_kaluga,
        "glofas_tarusa_discharge": glofas_tarusa,
        "glofas_peak_station":     glofas_peak_station,
        "glofas_peak_date":        glofas_peak_date,
        "glofas_serpukhov_arrival": glofas_serp_arrival,
        "notes":                   analytics.get("notes", ""),
    }

    history.append(row)
    return history


def export_history_csv(history: list) -> None:
    """Экспортирует последние 365 записей в docs/history.csv."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    recent = history[-365:] if len(history) > 365 else history

    if not recent:
        return

    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction="ignore")
        writer.writeheader()
        for row in recent:
            writer.writerow({k: row.get(k, "") for k in HISTORY_COLS})


def load_alerts() -> dict:
    """Читает data/alerts_sent.json."""
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_alerts(alerts: dict) -> None:
    """Сохраняет data/alerts_sent.json."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def load_mailing_list() -> list:
    """Читает data/mailing_list.json."""
    try:
        with open(MAILING_LIST, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if isinstance(obj, list):
                return obj
            return obj.get("recipients", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_2024_ref():
    """Читает data/2024_ref.json для сравнения с 2024 годом."""
    try:
        with open(REF_2024, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# АНАЛИТИКА
# ══════════════════════════════════════════════════════════════════════════════

def get_level_zone(level_cm) -> tuple:
    """
    Возвращает (zone_name, color, bg_color, label, css_class) по уровню в см.
    v7: 5 зон вместо 4 + css_class как 5-й элемент.

    Зоны:
    GREEN   → safe:      < 400 см
    YELLOW  → watch:     400–600 см
    ORANGE  → warning:   600–800 см
    RED     → danger:    800–900 см
    PURPLE  → emergency: > 900 см
    """
    if level_cm is None:
        return ("UNKNOWN", "#64748b", "#1a2635", "Нет данных", "zone-unknown")
    lc = float(level_cm)
    if lc >= 900:
        return ("EMERGENCY", "#a855f7", "#1a0a2e", "ЧС",         "zone-emergency")
    if lc >= ZONE_ORANGE_MAX:   # 800
        return ("RED",    "#ef4444", "#2d0000", "КРИТИЧНО",  "zone-danger")
    if lc >= ZONE_YELLOW_MAX:   # 600
        return ("ORANGE", "#f97316", "#2a1000", "ОПАСНОСТЬ", "zone-warning")
    if lc >= ZONE_GREEN_MAX:    # 400
        return ("YELLOW", "#f59e0b", "#1f1a00", "ВНИМАНИЕ",  "zone-watch")
    return     ("GREEN",  "#10b981", "#0d1f0d", "НОРМА",     "zone-safe")


def _alert_level_to_russian(al: str) -> str:
    """
    Переводит alert_level из английского в русский.
    ИСПРАВЛЕНИЕ v7: «GREEN» → «НОРМА» и т.д.
    """
    MAP = {
        "GREEN":     "НОРМА",
        "YELLOW":    "ВНИМАНИЕ",
        "ORANGE":    "ОПАСНОСТЬ",
        "RED":       "КРИТИЧНО",
        "EMERGENCY": "ЧС",
        "UNKNOWN":   "НЕТ ДАННЫХ",
        # Уже в русском
        "НОРМА":     "НОРМА",
        "ВНИМАНИЕ":  "ВНИМАНИЕ",
        "ОПАСНОСТЬ": "ОПАСНОСТЬ",
        "КРИТИЧНО":  "КРИТИЧНО",
        "ЧС":        "ЧС",
    }
    return MAP.get((al or "").strip().upper(), al or "—")


def compute_composite_status(serp: dict, wext, glofas: dict, analytics: dict) -> dict:
    """
    Вычисляет Composite Status — интегральная оценка из 4 компонентов.
    v7: заменяет простое сравнение level_cm с порогом.

    Компоненты:
      1. Уровень (level_zone)
      2. Тренд (trend_zone)
      3. Прогноз GloFAS (glofas_zone)
      4. Погода (weather_zone)

    Returns:
        {
          "level":   {zone, label, value, color},
          "trend":   {zone, label, value, color},
          "glofas":  {zone, label, value, color},
          "weather": {zone, label, value, color},
          "verdict": {zone, label, color, emoji},
        }
    """
    ZONE_COLORS = {
        "safe":      "#10b981",
        "watch":     "#f59e0b",
        "warning":   "#f97316",
        "danger":    "#ef4444",
        "emergency": "#a855f7",
        "unknown":   "#64748b",
    }
    ZONE_RANK = {"safe": 0, "watch": 1, "warning": 2, "danger": 3, "emergency": 4, "unknown": -1}

    level_cm  = serp.get("level_cm")
    change_cm = serp.get("daily_change_cm")

    # ── 1. Уровень ────────────────────────────────────────────────
    abs_bs = serp.get("abs_level_m_bs")
    if abs_bs is None and level_cm is not None:
        abs_bs = LUKYANNOVO_ZERO_M_BS + level_cm / 100.0

    if abs_bs is None:
        level_zone = "unknown"
        level_label = "Нет данных"
        level_value = "—"
    else:
        nya_dist_m = LUKYANNOVO_NYA_M_BS - abs_bs
        oya_dist_m = LUKYANNOVO_OYA_M_BS - abs_bs
        level_cm_val = level_cm or 0

        if abs_bs >= LUKYANNOVO_OYA_M_BS:
            level_zone  = "danger"
            level_label = "КРИТИЧНО"
        elif abs_bs >= LUKYANNOVO_NYA_M_BS:
            level_zone  = "warning"
            level_label = "ОПАСНОСТЬ"
        elif nya_dist_m < 0.5:
            level_zone  = "watch"
            level_label = "БДИТЕЛЬНОСТЬ"
        else:
            level_zone  = "safe"
            level_label = "НОРМА"

        level_value = f"{level_cm_val:.0f} см (до НЯ {nya_dist_m*100:.0f} см)"

    # ── 2. Тренд ─────────────────────────────────────────────────
    if change_cm is None:
        trend_zone  = "unknown"
        trend_label = "Нет данных"
        trend_value = "—"
    else:
        change_f = float(change_cm)
        if change_f >= 50:
            trend_zone  = "danger"
            trend_label = "КРИТИЧЕСКИЙ РОСТ"
        elif change_f >= 20:
            trend_zone  = "warning"
            trend_label = "ТРЕВОГА"
        elif change_f >= 5:
            trend_zone  = "watch"
            trend_label = "РОСТ"
        elif change_f <= -10:
            trend_zone  = "safe"
            trend_label = "СПАД"
        else:
            trend_zone  = "safe"
            trend_label = "СТАБИЛЬНО"

        days_to_nya = analytics.get("days_to_nya")
        days_str = f", {days_to_nya:.0f} д до НЯ" if days_to_nya and days_to_nya < 30 else ""
        trend_value = f"{change_f:+.0f} см/сут{days_str}"

    # ── 3. Прогноз GloFAS ────────────────────────────────────────
    glofas_zone  = "unknown"
    glofas_label = "Нет данных"
    glofas_value = "—"

    if glofas and glofas.get("_status") in ("ok", "partial", "cached"):
        key_stations = ["belev", "tarusa", "aleksin", "kaluga"]
        max_ratio = 0.0
        best_station_name = ""
        best_wave_arrival = None
        best_peak_date    = None
        best_peak_q       = None

        for slug in key_stations:
            st = glofas.get(slug, {})
            if st.get("source_status") != "ok":
                continue
            fr = st.get("flood_ratio") or 0
            if fr > max_ratio:
                max_ratio = fr
                best_station_name = st.get("name", slug)
                best_wave_arrival = st.get("wave_arrival_serpukhov")
                best_peak_date    = st.get("peak_date")
                best_peak_q       = st.get("peak_discharge")

        if max_ratio >= 5:
            glofas_zone  = "danger"
            glofas_label = "ЭКСТРЕМАЛЬНЫЙ РАСХОД"
        elif max_ratio >= 3:
            glofas_zone  = "warning"
            glofas_label = "ВЫСОКИЙ РИСК"
        elif max_ratio >= 2:
            glofas_zone  = "watch"
            glofas_label = "ПОВЫШЕННЫЙ РАСХОД"
        elif max_ratio > 0:
            glofas_zone  = "safe"
            glofas_label = "НОРМА"

        if best_peak_date and best_wave_arrival:
            earliest = best_wave_arrival.get("earliest", "?")[:10]
            latest   = best_wave_arrival.get("latest", "?")[:10]
            try:
                e = date_cls.fromisoformat(earliest)
                l = date_cls.fromisoformat(latest)
                glofas_value = (
                    f"{best_station_name} пик {best_peak_date[8:10]}.{best_peak_date[5:7]}"
                    f", волна {e.day}.{e.month:02d}–{l.day}.{l.month:02d}"
                )
            except Exception:
                glofas_value = f"{best_station_name} пик {best_peak_date}, волна {earliest}–{latest}"

    # ── 4. Погода ─────────────────────────────────────────────────
    fl_index = (wext or {}).get("flood_index", 0)
    fl_label = (wext or {}).get("flood_label", "—")

    if fl_index >= 4:
        weather_zone  = "danger"
        weather_label = "КРИТИЧЕСКИЙ"
    elif fl_index >= 3:
        weather_zone  = "warning"
        weather_label = "ВЫСОКИЙ"
    elif fl_index >= 2:
        weather_zone  = "watch"
        weather_label = "ПОВЫШЕННЫЙ"
    else:
        weather_zone  = "safe"
        weather_label = "НОРМА"

    weather_value = f"{fl_index}/4 — {fl_label}"

    # ── Итоговый вердикт ─────────────────────────────────────────
    # ВАЖНО: вердикт НЕ берёт максимум из всех компонентов.
    # Уровень (level) — базовый, остальные могут повысить его на 1 ступень.
    # Пример: уровень НОРМА + погода КРИТИЧЕСКИЙ → вердикт БДИТЕЛЬНОСТЬ, не КРИТИЧЕСКИЙ.
    zones = [level_zone, trend_zone, glofas_zone, weather_zone]
    valid_zones = [z for z in zones if z != "unknown"]

    if not valid_zones:
        verdict_zone  = "unknown"
        verdict_label = "НЕТ ДАННЫХ"
        verdict_emoji = "⚪"
    else:
        # Базовый вердикт = уровень воды (основа)
        base_rank = ZONE_RANK.get(level_zone, 0) if level_zone != "unknown" else 0

        # Факторы усиления: тренд, GloFAS, погода
        amplifiers = [trend_zone, glofas_zone, weather_zone]
        amp_ranks = [ZONE_RANK.get(z, 0) for z in amplifiers if z != "unknown"]

        # Усиление: если 2+ усилителя >= warning → +1 ступень; если 3 усилителя >= warning → +2
        high_amp_count = sum(1 for r in amp_ranks if r >= 2)  # warning+
        any_danger_amp = any(r >= 3 for r in amp_ranks)       # danger+

        boost = 0
        if high_amp_count >= 3:
            boost = 2
        elif high_amp_count >= 2 or any_danger_amp:
            boost = 1

        final_rank = min(base_rank + boost, 4)  # cap at emergency=4

        rank_to_zone = {0: "safe", 1: "watch", 2: "warning", 3: "danger", 4: "emergency"}
        verdict_zone = rank_to_zone.get(final_rank, "safe")

        verdict_map = {
            "safe":      ("🟢 РЕЖИМ: НОРМА",                  "🟢"),
            "watch":     ("🟡 РЕЖИМ: БДИТЕЛЬНОСТЬ",            "🟡"),
            "warning":   ("🟠 РЕЖИМ: РАСТУЩАЯ ОПАСНОСТЬ",      "🟠"),
            "danger":    ("🔴 РЕЖИМ: КРИТИЧЕСКАЯ УГРОЗА",       "🔴"),
            "emergency": ("🟣 РЕЖИМ: ЧРЕЗВЫЧАЙНАЯ СИТУАЦИЯ",    "🟣"),
        }
        verdict_label, verdict_emoji = verdict_map.get(verdict_zone, ("⚪ НЕТ ДАННЫХ", "⚪"))

    def _make_comp(zone, label, value):
        return {"zone": zone, "label": label, "value": value, "color": ZONE_COLORS.get(zone, "#64748b")}

    return {
        "level":   _make_comp(level_zone,   level_label,   level_value),
        "trend":   _make_comp(trend_zone,   trend_label,   trend_value),
        "glofas":  _make_comp(glofas_zone,  glofas_label,  glofas_value),
        "weather": _make_comp(weather_zone, weather_label, weather_value),
        "verdict": {
            "zone":  verdict_zone,
            "label": verdict_label,
            "color": ZONE_COLORS.get(verdict_zone, "#64748b"),
            "emoji": verdict_emoji,
        },
    }


# ── Вспомогательные функции для v7.2 аналитики ─────────────────────────────

def _compute_weighted_change_v72(history, key="serp_daily_change_cm"):
    """Взвешенное среднее прироста за 3 дня (вес 2:1:0.5)."""
    vals = []
    for row in reversed(history[-5:]):
        c = row.get(key)
        if c is None:
            c = row.get("cugms_serp_change_cm")
        if c is not None:
            try:
                vals.append(float(c))
            except (ValueError, TypeError):
                pass
        if len(vals) >= 3:
            break
    if not vals:
        return None
    weights = [2.0, 1.0, 0.5][:len(vals)]
    return sum(v * w for v, w in zip(vals, weights)) / sum(weights)


def _compute_flood_phase_v72(level_cm, change_3d_cm, today_date):
    """
    Определяет текущую фазу паводкового цикла.
    Возвращает (phase_code, phase_label, phase_icon).
    """
    if level_cm is None:
        return ("unknown", "Нет данных", "⚪")

    if level_cm >= 645:  # НЯ
        if change_3d_cm is not None and change_3d_cm > 10:
            return ("peak_zone", "Зона НЯ — рост", "🔴")
        if change_3d_cm is not None and change_3d_cm < -10:
            return ("recession", "Спад после пика", "⬇️")
        return ("peak", "Пик / зона НЯ", "🔴")

    if change_3d_cm is not None and change_3d_cm < -10 and level_cm > 300:
        return ("recession", "Спад", "⬇️")

    if change_3d_cm is not None:
        if change_3d_cm >= 80:
            return ("rapid_rise", "Быстрый рост!", "🚨")
        if change_3d_cm >= 20:
            return ("active_rise", "Активный разгон", "⬆️")
        if change_3d_cm >= 5:
            return ("early_rise", "Начальный подъём", "📊")

    mo, dy = today_date.month, today_date.day
    if level_cm < 150:
        if mo < 3 or (mo == 3 and dy < 15):
            return ("before", "До паводка", "🌨️")
        return ("early_start", "Ранний старт", "🌤️")

    return ("early_rise", "Начальный подъём", "📊")


NYA_SCENARIOS_DEF = [
    {"key": "calm",    "emoji": "🟢", "label": "Слабый",
     "rate_cm_day": 12.5, "note": "маловероятно (как 2020, 2022)"},
    {"key": "typical", "emoji": "🟡", "label": "Типичный",
     "rate_cm_day": 50.0, "note": "как 2023–2024"},
    {"key": "extreme", "emoji": "🔴", "label": "Экстремальный",
     "rate_cm_day": 100.0, "note": "как 2013"},
]


def compute_analytics(serp: dict, kim: dict, cugms: dict, history: list, wext) -> dict:
    """
    Собирает всю аналитику в один словарь.
    v7.2: добавлены сценарии до НЯ, фаза паводка, 3-дневный тренд.
    """
    level_cm  = serp.get("level_cm")
    change_cm = serp.get("daily_change_cm")
    abs_bs    = serp.get("abs_level_m_bs")

    # Расстояние до порогов в метрах
    if abs_bs is not None:
        nya_remaining_m = max(0.0, LUKYANNOVO_NYA_M_BS - abs_bs)
        oya_remaining_m = max(0.0, LUKYANNOVO_OYA_M_BS - abs_bs)
    elif level_cm is not None:
        abs_bs_calc     = LUKYANNOVO_ZERO_M_BS + level_cm / 100.0
        nya_remaining_m = max(0.0, LUKYANNOVO_NYA_M_BS - abs_bs_calc)
        oya_remaining_m = max(0.0, LUKYANNOVO_OYA_M_BS - abs_bs_calc)
    else:
        nya_remaining_m = None
        oya_remaining_m = None

    # Дней до порогов (линейная оценка — для обратной совместимости)
    days_to_nya = None
    days_to_oya = None
    if change_cm and change_cm > 0 and nya_remaining_m is not None:
        change_m_per_day = change_cm / 100.0
        days_to_nya = round(nya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None
        days_to_oya = round(oya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None

    # v7.2: Взвешенный 3-дневный тренд
    change_3d_cm = _compute_weighted_change_v72(history)

    # v7.2: Ускорение / замедление тренда
    change_acceleration = None
    if change_3d_cm is not None and len(history) >= 7:
        change_7d = _compute_weighted_change_v72(history[-7:])
        if change_7d and change_7d != 0:
            ratio = change_3d_cm / change_7d
            if ratio > 1.2:
                change_acceleration = "accelerating"
            elif ratio < 0.8:
                change_acceleration = "decelerating"
            else:
                change_acceleration = "stable"

    # v7.2: Детектор противоречия источников
    source_conflict = False
    cugms_change = cugms.get("serpukhov_change_cm") or cugms.get("serp_change_cm")
    if change_cm is not None and cugms_change is not None:
        try:
            if abs(float(change_cm) - float(cugms_change)) > 15:
                source_conflict = True
        except (ValueError, TypeError):
            pass

    # v7.2: Сценарии до НЯ
    nya_scenarios = []
    if nya_remaining_m is not None and nya_remaining_m > 0:
        today = date_cls.today()
        nya_remaining_cm = nya_remaining_m * 100
        for sc in NYA_SCENARIOS_DEF:
            days = round(nya_remaining_cm / sc["rate_cm_day"], 0)
            try:
                arrival = today + timedelta(days=int(days))
                realistic = arrival <= date_cls(today.year, 4, 26)
                arrival_str = arrival.strftime("%d %b")
            except (ValueError, OverflowError):
                realistic = False
                arrival_str = "—"
            nya_scenarios.append({
                "key":      sc["key"],
                "emoji":    sc["emoji"],
                "label":    sc["label"],
                "days":     int(days),
                "arrival":  arrival_str,
                "note":     sc["note"],
                "realistic": realistic,
            })

    # v7.2: Фаза паводка
    flood_phase, flood_phase_label, flood_phase_icon = _compute_flood_phase_v72(
        level_cm, change_3d_cm, date_cls.today()
    )

    # Уровень опасности
    zone_name, _, _, _, _ = get_level_zone(level_cm)
    alert_level = _alert_level_to_russian(zone_name)

    # Прогресс-бары
    total_nya_range = LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS
    total_oya_range = LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS
    if abs_bs is not None:
        nya_fill_pct = min(100.0, max(0.0, (abs_bs - LUKYANNOVO_ZERO_M_BS) / total_nya_range * 100))
        oya_fill_pct = min(100.0, max(0.0, (abs_bs - LUKYANNOVO_ZERO_M_BS) / total_oya_range * 100))
    elif level_cm is not None:
        abs_bs_calc  = LUKYANNOVO_ZERO_M_BS + level_cm / 100.0
        nya_fill_pct = min(100.0, max(0.0, (abs_bs_calc - LUKYANNOVO_ZERO_M_BS) / total_nya_range * 100))
        oya_fill_pct = min(100.0, max(0.0, (abs_bs_calc - LUKYANNOVO_ZERO_M_BS) / total_oya_range * 100))
    else:
        nya_fill_pct = 0.0
        oya_fill_pct = 0.0

    # Анализ волны
    wave_text = compute_wave_analysis({"serpuhov": serp, "kim": kim, "cugms": cugms})

    # Прогноз пика
    peak = compute_peak_prediction(history)

    # Заметки
    notes_parts = []
    if (wext or {}).get("flood_index", 0) >= 3:
        notes_parts.append(f"Паводковый индекс {wext.get('flood_index')}/4")
    if cugms.get("dangerous_expected"):
        notes_parts.append("ЦУГМС: ожидаются опасные явления")
    notes = "; ".join(notes_parts)

    return {
        # Существующие поля (обратная совместимость)
        "alert_level":      alert_level,
        "days_to_nya":      days_to_nya,      # DEPRECATED — линейная оценка
        "days_to_oya":      days_to_oya,      # DEPRECATED — линейная оценка
        "nya_remaining_m":  nya_remaining_m,
        "oya_remaining_m":  oya_remaining_m,
        "nya_fill_pct":     round(nya_fill_pct, 1),
        "oya_fill_pct":     round(oya_fill_pct, 1),
        "wave_dynamic_text": wave_text,
        "peak_prediction":  peak,
        "notes":            notes,
        # НОВЫЕ поля v7.2
        "nya_scenarios":           nya_scenarios,
        "flood_phase":             flood_phase,
        "flood_phase_label":       flood_phase_label,
        "flood_phase_icon":        flood_phase_icon,
        "change_3d_cm":            change_3d_cm,
        "change_acceleration":     change_acceleration,
        "source_conflict":         source_conflict,
        "cugms_change_cm":         cugms_change,
    }


def compute_wave_analysis(data: dict) -> str:
    """Генерирует текст о движении волны на основе данных ЦУГМС и КИМ."""
    cugms = data.get("cugms", {})
    kim   = data.get("kim", {})
    msgs  = []

    belev_change = cugms.get("belev_change_cm")
    if belev_change and belev_change > 30:
        msgs.append(
            f"На участке у Белёва прирост {belev_change:.0f} см/сут — "
            f"волна дойдёт до Серпухова ориентировочно через 5–7 дней."
        )

    kaluga = (kim.get("kaluga") or {}).get("level_cm")
    if kaluga and kaluga > 400:
        msgs.append(
            f"Уровень в Калуге: {kaluga} см. "
            f"При текущей динамике волна дойдёт до Серпухова через 2–3 дня."
        )

    kashira     = (kim.get("kashira") or {}).get("level_cm")
    kashira_chg = cugms.get("kashira_change_cm")
    if kashira and kashira_chg:
        msgs.append(
            f"Кашира: {kashira} см, прирост +{kashira_chg:.0f} см/сут. "
            f"Волна достигла нижнего участка."
        )

    if not msgs:
        return "Данных по движению волны недостаточно. Следите за обновлениями."

    return " ".join(msgs)


def compute_peak_prediction(history: list) -> dict:
    """Простая модель предсказания пика."""
    if len(history) < 3:
        return {
            "trend": "unknown", "trend_text": "Недостаточно данных",
            "decel_days": 0, "est_peak_days": None, "regression": None,
            "disclaimer": "Требуется минимум 3 записи",
        }

    changes = []
    for row in history[-10:]:
        c = row.get("serp_daily_change_cm") or row.get("cugms_serp_change_cm")
        if c is not None:
            try:
                changes.append(float(c))
            except (ValueError, TypeError):
                pass

    if len(changes) < 2:
        return {
            "trend": "unknown", "trend_text": "Нет данных о приростах",
            "decel_days": 0, "est_peak_days": None, "regression": None,
            "disclaimer": "",
        }

    decel_days = 0
    for i in range(len(changes) - 1, 0, -1):
        if changes[i] < changes[i - 1]:
            decel_days += 1
        else:
            break

    last_change = changes[-1]
    est_days    = None

    if last_change < 0:
        trend = "falling"
        trend_text = f"Спад: уровень снижается ({last_change:+.0f} см/сут)"
    elif decel_days >= 2:
        trend = "decelerating"
        avg_decel = (changes[-(decel_days + 1)] - changes[-1]) / decel_days if decel_days > 0 else 0
        est_days  = int(last_change / avg_decel) if avg_decel > 0 else None
        trend_text = (
            f"Прирост замедляется {decel_days}-й день подряд ({last_change:+.0f} см/сут). "
            + (f"Ожидаемый пик через ~{est_days} дней." if est_days else "")
        )
    elif last_change > 30:
        trend = "accelerating"
        trend_text = f"Активный рост: +{last_change:.0f} см/сут"
    else:
        trend = "stable"
        trend_text = f"Стабильный рост: +{last_change:.0f} см/сут"

    regression = compute_regression(history)

    return {
        "trend":         trend,
        "trend_text":    trend_text,
        "decel_days":    decel_days,
        "est_peak_days": est_days,
        "regression":    regression,
        "disclaimer":    "Модель приблизительная. Реальный пик зависит от погоды и таяния снега.",
    }


def compute_regression(history: list):
    """Линейная регрессия уровня Серпухова за последние 14 дней."""
    points = []
    for row in history[-100:]:
        val = row.get("serp_level_cm") or row.get("serpukhov")
        if val and str(val).strip() not in ("", "None", "null"):
            try:
                points.append((row.get("datetime", ""), float(val)))
            except (ValueError, TypeError):
                pass

    if len(points) < 5:
        return None

    pts = points[-14:]
    n   = len(pts)

    try:
        t0_str = pts[0][0].replace("Z", "+00:00")
        t0     = datetime.fromisoformat(t0_str)
    except Exception:
        return None

    xs = []
    ys = []
    for dt_str, val in pts:
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            xs.append((dt - t0).total_seconds() / 3600.0)
            ys.append(val)
        except Exception:
            pass

    if len(xs) < 5:
        return None

    n   = len(xs)
    sx  = sum(xs)
    sy  = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None

    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    last_x  = xs[-1]
    pred_3d = round(intercept + slope * (last_x + 72), 1)
    pred_7d = round(intercept + slope * (last_x + 168), 1)

    nya_cm      = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    peak_date_str = None
    if slope > 0:
        hours_to_nya = (nya_cm - intercept) / slope if slope != 0 else None
        if hours_to_nya and hours_to_nya > 0:
            try:
                peak_dt   = t0 + timedelta(hours=hours_to_nya)
                peak_date_str = peak_dt.strftime("%d.%m.%Y")
            except Exception:
                pass

    direction     = "рост" if slope > 0 else "спад"
    trend_text_ml = (
        f"Тренд: {direction} {abs(slope * 24):.1f} см/сут "
        f"(R²={r_squared:.2f})"
    )

    return {
        "slope":          round(slope, 4),
        "intercept":      round(intercept, 2),
        "r_squared":      round(r_squared, 3),
        "pred_3d":        pred_3d,
        "pred_7d":        pred_7d,
        "nya_cm":         nya_cm,
        "peak_date":      peak_date_str,
        "trend_text_ml":  trend_text_ml,
        "n_points":       n,
        "current_level":  ys[-1],
    }


def generate_action_block(level_cm, flood_index: int, composite: dict = None) -> tuple:
    """
    Генерирует блок действий.
    v7: использует Composite Status для определения уровня действий.
    ИСПРАВЛЕНИЕ: используем verdict из composite_status, не flood_index >= 4.

    Returns: (icon, title, text, color)
    """
    if composite:
        verdict_zone = composite.get("verdict", {}).get("zone", "safe")
    else:
        if level_cm is None:
            verdict_zone = "unknown"
        elif level_cm >= ZONE_ORANGE_MAX:
            verdict_zone = "danger"
        elif level_cm >= ZONE_YELLOW_MAX:
            verdict_zone = "warning"
        elif level_cm >= ZONE_GREEN_MAX:
            verdict_zone = "watch"
        else:
            verdict_zone = "safe"

    ACTIONS = {
        "safe": (
            "🟢",
            "Норма — Плановое наблюдение",
            "Уровень воды в норме. "
            "<br>• <b>Что происходит:</b> река в пределах типичного весеннего диапазона, паводковая угроза минимальна."
            "<br>• <b>Что делать:</b> проверьте наличие насоса и дренажной системы; убедитесь в доступности дачи; <a href='#cugmsAcc' style='color:var(--accent);text-decoration:underline;'>уточните прогноз ЦУГМС</a> раз в день."
            "<br>• <b>Совет:</b> Ока, как и положено великой реке, не любит спешить — но лучше подготовиться заранее, чем торопиться потом.",
            "#10b981",
        ),
        "watch": (
            "🟡",
            "Бдительность — Готовность к действиям",
            "Уровень повышается или GloFAS фиксирует рост выше по течению. "
            "<br>• <b>Что происходит:</b> начало паводковой фазы; вода пока в русле, но тенденция к росту очевидна."
            "<br>• <b>Что делать:</b> следите за дашбордом каждые 3–4 часа; составьте список имущества для эвакуации; проверьте насос и дренаж; <a href='#cugmsAcc' style='color:var(--accent);text-decoration:underline;'>уточните прогноз ЦУГМС</a>."
            "<br>• <b>Когда обновление:</b> мониторинг обновляется каждые 6 часов автоматически."
            "<br>• <i>Если ваш погреб ещё не подготовлен — самое время это исправить. Вода ждать не будет.</i>",
            "#f59e0b",
        ),
        "warning": (
            "🟠",
            "Опасность — Подготовьтесь немедленно",
            "Уровень быстро растёт и/или GloFAS прогнозирует пик в ближайшие дни. "
            "<br>• <b>Что происходит:</b> паводковая волна в активной фазе, до НЯ остаётся меньше метра."
            "<br>• <b>Что делать:</b> вывезите ценные вещи с нижнего этажа; подготовьте дом к затоплению; договоритесь о временном жилье; зарядите телефон; подготовьте документы и аптечку."
            "<br>• <b>Мониторинг:</b> проверяйте дашборд каждый час; подпишитесь на Telegram-оповещения."
            "<br>• <b>Когда звонить в МЧС:</b> если уровень превысит НЯ (645 см) — звоните на 112.",
            "#f97316",
        ),
        "danger": (
            "🔴",
            "Критично — Действуйте прямо сейчас",
            "Уровень достиг критических значений. Высокий риск затопления. "
            "<br>• <b>Что происходит:</b> уровень превысил НЯ, вода вышла на пойму, подтопление строений вероятно."
            "<br>• <b>Что делать:</b> немедленно эвакуируйте людей, животных, ценное имущество; отключите электричество на даче; перекройте газ и воду."
            "<br>• <b>Связь:</b> свяжитесь с соседями; следите за Telegram-каналом; звоните в ЕДДС Серпухова."
            "<br>• <b>Не рискуйте:</b> не пытайтесь добраться до залитой дачи в одиночку.",
            "#ef4444",
        ),
        "emergency": (
            "🟣",
            "ЧРЕЗВЫЧАЙНАЯ СИТУАЦИЯ",
            "Уровень превысил ОЯ (800 см). Массовое затопление пойменных территорий. "
            "<br>• <b>Что происходит:</b> вода затопила дороги и строения, ситуация чрезвычайная."
            "<br>• <b>Что делать:</b> все должны быть эвакуированы; не пытайтесь добраться до дачи без необходимости; звоните 112."
            "<br>• <b>Документируйте:</b> фиксируйте ущерб фото/видео для страховки и компенсаций."
            "<br>• <b>Следите:</b> ждите официальных сводок МЧС России и администрации Серпухова.",
            "#a855f7",
        ),
        "unknown": (
            "⚪",
            "Нет данных",
            "Данные временно недоступны. "
            "<br>• <b>Что делать:</b> проверьте serpuhov.ru вручную; при необходимости позвоните в ЕДДС Серпухова."
            "<br>• <b>Следующее обновление:</b> мониторинг повторит попытку через 6 часов.",
            "#64748b",
        ),
    }

    return ACTIONS.get(verdict_zone, ACTIONS["unknown"])


# ══════════════════════════════════════════════════════════════════════════════
# АЛЕРТЫ
# ══════════════════════════════════════════════════════════════════════════════

def should_send_alert(alerts: dict, key: str, cooldown_h: float = 6.0) -> bool:
    """Проверяет, нужно ли слать алерт (с учётом cooldown)."""
    last = alerts.get(key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last_dt).total_seconds() > cooldown_h * 3600
    except (ValueError, TypeError):
        return True


def check_level_triggers(serp_level_cm, alerts: dict) -> list:
    """Проверяет пересечение пороговых отметок."""
    if serp_level_cm is None:
        return []

    triggered = []
    for threshold, key, label, text, cooldown_h in ALERT_THRESHOLDS:
        if serp_level_cm >= threshold:
            if should_send_alert(alerts, key, cooldown_h=cooldown_h):
                msg = (
                    f"{label}\n\n"
                    f"Серпухов (д. Лукьяново): <b>{serp_level_cm:.0f} см</b>\n"
                    f"{text}"
                )
                triggered.append((key, msg))

    return triggered


def check_watchdog(data: dict, alerts: dict) -> list:
    """Проверяет доступность источников данных."""
    triggered = []
    serp = data.get("serpuhov", {})

    if serp.get("source_status") == "unavailable":
        key = "WATCHDOG_SERPUHOV"
        if should_send_alert(alerts, key, cooldown_h=6):
            triggered.append((key,
                "❌ <b>WATCHDOG</b>: serpuhov.ru не отвечает!\n"
                "Данные по уровню воды в Серпухове недоступны.\n"
                "Проверьте вручную: https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/"))

    cache_age = serp.get("cache_age_h", 0)
    if serp.get("source_status") == "cached" and cache_age > 36:
        key = "WATCHDOG_STALE_CACHE"
        if should_send_alert(alerts, key, cooldown_h=12):
            triggered.append((key,
                f"⚠️ <b>WATCHDOG</b>: Данные serpuhov.ru устарели на {cache_age:.0f} ч!\n"
                "Возможно, страница не обновлялась или изменилась структура."))

    sources_failed = data.get("sources_failed", [])
    if len(sources_failed) >= 3:
        key = "WATCHDOG_TOTAL"
        if should_send_alert(alerts, key, cooldown_h=6):
            triggered.append((key,
                f"🚨 <b>WATCHDOG TOTAL</b>: Все источники не отвечают!\n"
                f"Сбой: {', '.join(sources_failed)}"))

    return triggered


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def tg_send(chat_id: str, text: str, parse_mode: str = "HTML") -> None:
    """Отправляет сообщение в Telegram. Тихо пропускает ошибки."""
    if not TG_TOKEN or not chat_id:
        return
    try:
        import requests as _req
        url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        resp = _req.post(url, data={
            "chat_id":    str(chat_id),
            "text":       text[:4096],
            "parse_mode": parse_mode,
            "disable_web_page_preview": "true",
        }, timeout=15)
        if not resp.ok:
            print(f"[TG] Ошибка {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[TG] Исключение при отправке: {e}")


def _fmt_delta(d) -> str:
    """Форматирует дельту со знаком: +49 или -12 или —."""
    if d is None:
        return "—"
    try:
        v = float(d)
        return f"{v:+.0f}"
    except (ValueError, TypeError):
        return "—"


def _trend(d) -> str:
    """Возвращает стрелку по значению дельты."""
    if d is None:
        return "→"
    try:
        v = float(d)
        if v > 5:
            return "↑"
        if v < -5:
            return "↓"
        return "→"
    except (ValueError, TypeError):
        return "→"


def _build_glofas_summary(glofas: dict) -> str:
    """Строит однострочную GloFAS-сводку для TG heartbeat."""
    if not glofas or glofas.get("_status") not in ("ok", "partial", "cached"):
        return "нет данных"

    for slug in ["belev", "tarusa", "aleksin", "kaluga"]:
        st = glofas.get(slug, {})
        if st.get("source_status") != "ok":
            continue

        cur = st.get("current_discharge")
        peak = st.get("peak_discharge")
        peak_date = st.get("peak_date", "")
        name = st.get("name", slug)
        wave = st.get("wave_arrival_serpukhov") or {}
        earliest = wave.get("earliest", "")[:10]
        latest   = wave.get("latest", "")[:10]

        cur_str  = f"{cur:.0f}" if cur is not None else "?"
        peak_str = f"{peak:.0f}" if peak is not None else "?"

        MONTHS = {
            "01": "янв", "02": "фев", "03": "мар", "04": "апр",
            "05": "май", "06": "июн", "07": "июл", "08": "авг",
            "09": "сен", "10": "окт", "11": "ноя", "12": "дек",
        }

        def _fmt_dd_mm(d_str):
            if len(d_str) >= 10:
                day = d_str[8:10].lstrip("0") or "0"
                mon = MONTHS.get(d_str[5:7], d_str[5:7])
                return f"{day} {mon}"
            return d_str

        peak_fmt     = _fmt_dd_mm(peak_date)
        earliest_fmt = _fmt_dd_mm(earliest)
        latest_fmt   = _fmt_dd_mm(latest)

        return f"{name} {cur_str}→{peak_str} м³/с пик {peak_fmt}, волна≈{earliest_fmt}–{latest_fmt}"

    return "данные частичны"


def build_heartbeat_message(data: dict, analytics: dict, composite: dict,
                             now_msk: str) -> str:
    """
    Строит heartbeat-сообщение для ADMIN.
    v7: добавлена однострочная сводка GloFAS.
    """
    serp    = data.get("serpuhov", {})
    wext    = data.get("weather") or {}
    glofas  = data.get("glofas", {})

    level_cm  = serp.get("level_cm")
    change_cm = serp.get("daily_change_cm")
    level_str = f"{level_cm:.0f}" if level_cm is not None else "?"
    chg_str   = f"{change_cm:+.0f}" if change_cm is not None else "?"

    verdict_label = (composite.get("verdict") or {}).get("label", "—")
    level_label   = (composite.get("level") or {}).get("label", "—")
    trend_label   = (composite.get("trend") or {}).get("label", "—")
    weather_label = (composite.get("weather") or {}).get("label", "—")
    fl_idx        = wext.get("flood_index", 0)

    glofas_summary = _build_glofas_summary(glofas)

    url = "https://em-from-pu.github.io/oka-flood-monitor"

    return (
        f"🌊 OkaFloodMonitor | {now_msk}\n"
        f"📍 Серпухов: {level_str} см | {chg_str} см/сут\n"
        f"🎯 {verdict_label}\n"
        f"━━━━━━━━━━\n"
        f"📊 Уровень: {level_label} | Тренд: {trend_label}\n"
        f"🌍 GloFAS: {glofas_summary}\n"
        f"☁️ Погода: {weather_label} ({fl_idx}/4)\n"
        f"━━━━━━━━━━\n"
        f"🔗 {url}"
    )


def build_digest_message(data: dict, analytics: dict, composite: dict,
                          wext, glofas: dict, now_msk: str) -> str:
    """
    Полный дайджест v7.6.1 — новый формат.
    """
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})

    now_dt = datetime.now(timezone.utc) + timedelta(hours=3)
    now_date = now_dt.strftime("%d.%m.%Y")
    now_time = now_dt.strftime("%H:%M")
    level_cm  = serp.get("level_cm")
    abs_bs    = serp.get("abs_level_m_bs")
    change    = serp.get("daily_change_cm")

    level_str = f"{level_cm:.0f}" if level_cm is not None else "нет данных"
    abs_str   = f"{abs_bs:.2f} м БС" if abs_bs is not None else "?"
    change_str = f"{change:+.0f}" if change is not None else "?"

    # Композитный статус
    level_comp = composite.get("level", {})
    trend_comp = composite.get("trend", {})
    level_emoji = {"safe": "🟢", "watch": "🟡", "warning": "🟠", "danger": "🔴", "emergency": "🟣"}.get(level_comp.get("zone", "safe"), "⚪")
    trend_emoji = {"safe": "🟢", "watch": "🟡", "warning": "🟠", "danger": "🔴", "emergency": "🟣"}.get(trend_comp.get("zone", "safe"), "⚪")
    level_label = level_comp.get("label", "—")
    trend_label = trend_comp.get("label", "—")

    # Пороги
    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    nya_rem_cm = (nya_cm - level_cm) if level_cm is not None else None
    oya_rem_cm = (oya_cm - level_cm) if level_cm is not None else None

    thresholds_block = ""
    if nya_rem_cm is not None:
        days_to_nya = ""
        if change is not None and change > 0:
            est_days = nya_rem_cm / change
            days_to_nya = f" \u2192 \u2248{est_days:.0f} \u0434\u043d" if est_days < 100 else ""
        thresholds_block = (
            f"\n\u23f3 \u0414\u041e \u041f\u041e\u0420\u041e\u0413\u041e\u0412:\n"
            f"  \u041d\u042f (645 \u0441\u043c): {nya_rem_cm:.0f} \u0441\u043c{days_to_nya}\n"
            f"  \u041e\u042f (800 \u0441\u043c): {oya_rem_cm:.0f} \u0441\u043c\n"
        )

    # Сценарии
    scenarios_block = ""
    sc = analytics.get("scenarios", [])
    if sc:
        sc_lines = []
        for s in sc[:3]:
            emoji = {"weak": "🟢", "typical": "🟡", "extreme": "🔴"}.get(s.get("key", ""), "⚪")
            sc_lines.append(f"  {emoji} {s.get('label', '?')}: ~{s.get('arrival', '?')} (как {s.get('year_ref', '?')})")
        if sc_lines:
            scenarios_block = "\n\ud83d\udcca \u0421\u0426\u0415\u041d\u0410\u0420\u0418\u0418 \u041f\u0418\u041a\u0410:\n" + "\n".join(sc_lines) + "\n"

    # Погода
    weather_block = ""
    if wext:
        snow      = wext.get("snow_depth_cm", 0) or 0
        fl_label  = wext.get("flood_label", "?")
        fl_index  = wext.get("flood_index", 0)
        fl_summary = wext.get("flood_summary", "")
        days      = wext.get("days", [])
        today     = next((d for d in days if not d.get("is_forecast", True)), {})
        tmin      = today.get("tmin", "?")
        weather_block = (
            f"\n\u2601\ufe0f \u041f\u041e\u0413\u041e\u0414\u0410: {fl_index}/4 {fl_label}\n"
            f"  \u2744\ufe0f \u0421\u043d\u0435\u0433: {snow:.0f} \u0441\u043c | \ud83c\udf21 \u041d\u043e\u0447\u044c\u044e {tmin}\u00b0C\n"
        )
        if fl_summary:
            weather_block += f"  {fl_summary}\n"

    # GloFAS
    glofas_block = ""
    if glofas and glofas.get("_status") in ("ok", "partial"):
        glofas_lines = []
        for slug in ["kaluga", "aleksin", "tarusa"]:
            st = glofas.get(slug, {})
            if st.get("source_status") != "ok":
                continue
            name = st.get("name", slug)
            cur  = st.get("current_discharge")
            peak_d = st.get("peak_discharge")
            cur_str = f"{cur:.0f}" if cur is not None else "?"
            peak_str = f"\u2192{peak_d:.0f}" if peak_d is not None else ""
            arr = (st.get("wave_arrival_serpukhov") or {})
            arr_str = ""
            if arr:
                e = arr.get("earliest", "")[:10]
                l = arr.get("latest", "")[:10]
                if len(e) >= 10 and len(l) >= 10:
                    arr_str = f", \u0432\u043e\u043b\u043d\u0430 {e[8:10]}.{e[5:7]}\u2013{l[8:10]}.{l[5:7]}"
            glofas_lines.append(f"  {name}: {cur_str}{peak_str} \u043c\u00b3/\u0441{arr_str}")
        if glofas_lines:
            glofas_block = "\n\ud83c\udf0d \u0412\u0415\u0420\u0425\u041e\u0412\u042c\u042f (GloFAS):\n" + "\n".join(glofas_lines) + "\n"

    # ЦУГМС
    cugms_block = ""
    if cugms.get("review_number"):
        s_chg = cugms.get("serpuhov_change_cm")
        k_chg = cugms.get("kashira_change_cm")
        c_lines = []
        if s_chg is not None:
            c_lines.append(f"  \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432: {s_chg:+.0f} \u0441\u043c/\u0441\u0443\u0442")
        if k_chg is not None:
            c_lines.append(f"  \u041a\u0430\u0448\u0438\u0440\u0430: {k_chg:+.0f} \u0441\u043c/\u0441\u0443\u0442")
        if c_lines:
            cugms_block = "\n\ud83d\udccb \u0426\u0423\u0413\u041c\u0421:\n" + "\n".join(c_lines) + "\n"

    verdict = composite.get("verdict", {})
    verdict_label = verdict.get("label", "—")
    verdict_emoji = verdict.get("emoji", "⚪")

    # Подсказка
    verdict_hint = ""
    vz = verdict.get("zone", "safe")
    if vz == "safe":
        verdict_hint = "\u041e\u0431\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u0441\u043f\u043e\u043a\u043e\u0439\u043d\u0430\u044f."
    elif vz == "watch":
        verdict_hint = "\u0421\u043b\u0435\u0434\u0438\u0442\u0435 \u0437\u0430 \u0434\u0430\u0448\u0431\u043e\u0440\u0434\u043e\u043c. \u0413\u043e\u0442\u043e\u0432\u044c\u0442\u0435 \u043d\u0430\u0441\u043e\u0441."
    elif vz == "warning":
        verdict_hint = "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u043c\u0430\u0440\u0448\u0440\u0443\u0442 \u044d\u0432\u0430\u043a\u0443\u0430\u0446\u0438\u0438. \u0423\u0440\u043e\u0432\u0435\u043d\u044c \u0440\u0430\u0441\u0442\u0451\u0442 \u0431\u044b\u0441\u0442\u0440\u043e."
    elif vz in ("danger", "emergency"):
        verdict_hint = "\u041e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c! \u041d\u0435 \u043f\u043e\u0434\u0445\u043e\u0434\u0438\u0442\u0435 \u043a \u0432\u043e\u0434\u0435. \u041c\u0427\u0421: 112."

    return (
        f"\ud83c\udf0a OkaFloodMonitor | {now_date} {now_time}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n\ud83d\udccd \u0421\u0415\u0420\u041f\u0423\u0425\u041e\u0412 (\u043f\u043e\u0441\u0442 \u041b\u0443\u043a\u044c\u044f\u043d\u043e\u0432\u043e):\n"
        f"  {level_str} \u0441\u043c | {change_str} \u0441\u043c/\u0441\u0443\u0442 | {abs_str}\n"
        f"  {level_emoji} \u0423\u0440\u043e\u0432\u0435\u043d\u044c {level_label} | {trend_emoji} \u0422\u0440\u0435\u043d\u0434 {trend_label}\n"
        f"{thresholds_block}"
        f"{scenarios_block}"
        f"{weather_block}"
        f"{glofas_block}"
        f"{cugms_block}"
        f"\n{verdict_emoji} {verdict_label}\n"
        f"{verdict_hint}\n"
        f"\n\ud83d\udd17 em-from-pu.github.io/oka-flood-monitor"
    )


def build_neighbors_digest(data: dict, analytics: dict, composite: dict,
                            glofas: dict, now_msk: str) -> str:
    """
    Упрощённый дайджест для соседей v7.6.1.
    """
    serp   = data.get("serpuhov", {})
    wext   = data.get("weather") or {}
    level  = serp.get("level_cm")
    change = serp.get("daily_change_cm")

    now_dt = datetime.now(timezone.utc) + timedelta(hours=3)
    now_date = now_dt.strftime("%d.%m.%Y")
    now_time = now_dt.strftime("%H:%M")
    level_str = f"{level:.0f}" if level is not None else "нет данных"
    change_str = f"{change:+.0f}" if change is not None else "?"

    icon, title, text, _ = generate_action_block(level, (wext or {}).get("flood_index", 0), composite)

    fl_label  = (wext or {}).get("flood_label", "нет данных")
    fl_summary = (wext or {}).get("flood_summary", "")
    snow = (wext or {}).get("snow_depth_cm", 0) or 0

    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    nya_rem = (nya_cm - level) if level is not None else None
    oya_rem = (oya_cm - level) if level is not None else None

    thresh_block = ""
    if nya_rem is not None:
        days_est = ""
        if change is not None and change > 0:
            est = nya_rem / change
            days_est = f" \u2192 \u2248{est:.0f} \u0434\u043d" if est < 100 else ""
        thresh_block = (
            f"\n\u23f3 \u0414\u041e \u041f\u041e\u0420\u041e\u0413\u041e\u0412:\n"
            f"  \u041d\u042f (645 \u0441\u043c): {nya_rem:.0f} \u0441\u043c{days_est}\n"
            f"  \u041e\u042f (800 \u0441\u043c): {oya_rem:.0f} \u0441\u043c\n"
        )

    # GloFAS wave
    wave_info = calculate_wave_arrival(glofas or {})
    serp_arr  = wave_info.get("serpukhov_arrival", {})
    wave_block = ""
    if serp_arr:
        e = serp_arr.get("earliest", "")[:10]
        l = serp_arr.get("latest", "")[:10]
        if len(e) >= 10 and len(l) >= 10:
            wave_block = f"\n\ud83c\udf0a \u0412\u043e\u043b\u043d\u0430 \u0432 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432\u0435: {e[8:10]}.{e[5:7]}\u2013{l[8:10]}.{l[5:7]}\n\u0416\u0435\u0440\u043d\u043e\u0432\u043a\u0430: +6\u201312 \u0447\n"

    verdict = composite.get("verdict", {})
    verdict_label = verdict.get("label", "—")
    verdict_emoji = verdict.get("emoji", "⚪")

    return (
        f"\ud83c\udf0a OkaFloodMonitor | {now_date} {now_time}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\n\ud83d\udccd \u0421\u0415\u0420\u041f\u0423\u0425\u041e\u0412 (\u043f\u043e\u0441\u0442 \u041b\u0443\u043a\u044c\u044f\u043d\u043e\u0432\u043e):\n"
        f"  {level_str} \u0441\u043c | {change_str} \u0441\u043c/\u0441\u0443\u0442\n"
        f"{thresh_block}"
        f"\n{icon} <b>{title}</b>\n{text}\n"
        f"\n\u2601\ufe0f \u041f\u043e\u0433\u043e\u0434\u0430: {fl_label}\n"
        f"  \u2744\ufe0f \u0421\u043d\u0435\u0433: {snow:.0f} \u0441\u043c\n"
        f"{wave_block}"
        f"\n{verdict_emoji} {verdict_label}\n"
        f"\n\ud83d\udd17 em-from-pu.github.io/oka-flood-monitor"
    )


def format_group_draft(data: dict, wext) -> str:
    """Текст для ручной публикации в группу."""
    serp  = data.get("serpuhov", {})
    cugms = data.get("cugms", {})

    now_date  = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y")
    level_cm  = serp.get("level_cm")
    change    = serp.get("daily_change_cm")
    level_str = f"{level_cm:.0f}" if level_cm is not None else "нет данных"

    cugms_line = ""
    if cugms.get("review_number"):
        n   = cugms.get("review_number")
        chg = cugms.get("serpuhov_change_cm")
        chg_str = f"{chg:.0f}" if chg is not None else "нет данных"
        cugms_line = f"\nПо данным ЦУГМС (обзор №{n}): прирост +{chg_str} см/сут"

    ice_parts = []
    ice_dict  = cugms.get("ice_status", {})
    for st, st_ice in ice_dict.items():
        ice_parts.append(f"{st}: {st_ice}")
    ice_str = ", ".join(ice_parts) if ice_parts else "нет особых явлений"

    f_intens = cugms.get("forecast_intensity_mps", "нет данных")

    snow      = (wext or {}).get("snow_depth_cm", 0) or 0
    fl_label  = (wext or {}).get("flood_label", "нет данных")

    return (
        f"📊 Серпухов, р. Ока — обновление {now_date}\n"
        f"\nУровень воды у д. Лукьяново: {level_str} см\n"
        f"Изменение за сутки: {_fmt_delta(change)} см"
        f"{cugms_line}\n"
        f"\nЛедовая обстановка: {ice_str}\n"
        f"Прогноз на 3 дня: интенсивность {f_intens}\n"
        f"\nСнег: {snow:.0f} см | Паводковый индекс: {fl_label}\n"
        f"\nСледить за уровнем: https://em-from-pu.github.io/oka-flood-monitor"
    )


# ══════════════════════════════════════════════════════════════════════════════
# HTML: ВСПОМОГАТЕЛЬНЫЕ УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _h(s) -> str:
    """HTML-экранирование строки."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_level(v) -> str:
    """Форматирует уровень в см."""
    if v is None:
        return "нет данных"
    try:
        return f"{float(v):.0f} см"
    except (ValueError, TypeError):
        return "нет данных"


def _fmt_change(v) -> str:
    """Форматирует изменение со знаком."""
    if v is None:
        return "—"
    try:
        fv = float(v)
        return f"{fv:+.0f} см"
    except (ValueError, TypeError):
        return "—"


def _badge_class(status: str) -> str:
    """Возвращает CSS-класс бейджа."""
    if status in ("ok",):
        return "ok"
    if status in ("cached", "partial"):
        return "cached"
    return "unavailable"


def _weather_code_to_desc(code) -> str:
    """Преобразует WMO weather code в краткое описание."""
    if code is None:
        return ""
    try:
        code = int(code)
    except (ValueError, TypeError):
        return ""
    if code == 0:
        return "ясно"
    if code in (1, 2, 3):
        return "облачно"
    if code in (45, 48):
        return "туман"
    if code in (51, 53, 55):
        return "морось"
    if code in (61, 63, 65):
        return "дождь"
    if code in (71, 73, 75, 77):
        return "снег"
    if code in (80, 81, 82):
        return "ливень"
    if code in (85, 86):
        return "снегопад"
    if code in (95, 96, 99):
        return "гроза"
    return "смешанные"


# ══════════════════════════════════════════════════════════════════════════════
# HTML: CSS v7 — GLASSMORPHISM DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

def _generate_css_v7() -> str:
    """Возвращает полный CSS v7.6.1 (Light Theme + Inter + 5-level colors)."""
    _water_b64 = NEW_IMAGES_B64.get("water_bubbles_pattern", "")
    _WATER_PATTERN_PLACEHOLDER = "__WATER_BUBBLES_B64__"
    css = """
/* ═══════════════════════════════════════════════════════════════
   OkaFloodMonitor v7.7.2 Design System — Light Theme
   ═══════════════════════════════════════════════════════════════ */
:root {
  --safe:      #22c55e;
  --watch:     #f59e0b;
  --warning:   #f97316;
  --danger:    #ef4444;
  --emergency: #a855f7;
  --accent:    #2563eb;

  --bg-primary: #f0f7ff;
  --bg-card: #ffffff;
  --bg-card-hover: #f8fafc;
  --bg-glass: rgba(0, 0, 0, 0.03);
  --card-bg: #ffffff;

  --border: rgba(0, 0, 0, 0.08);
  --border-hover: rgba(0, 0, 0, 0.16);

  --text-primary: #1a2332;
  --text-secondary: #5a6a7a;
  --text-dim: #8a9ab0;

  --shadow-card: 0 2px 12px rgba(0, 0, 0, 0.08);
  --shadow-glow-safe:      0 0 20px rgba(34, 197, 94, 0.15);
  --shadow-glow-watch:     0 0 20px rgba(245, 158, 11, 0.15);
  --shadow-glow-warning:   0 0 20px rgba(249, 115, 22, 0.15);
  --shadow-glow-danger:    0 0 20px rgba(239, 68, 68, 0.15);
  --shadow-glow-emergency: 0 0 20px rgba(168, 85, 247, 0.15);
}

* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.6;
  font-size: 15px;
  position: relative;
}

body::before {
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: url('data:image/jpeg;base64,__WATER_BUBBLES_B64__') repeat center/200px;
  opacity: 0.15;
  pointer-events: none;
  z-index: -1;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── CARD ────────────────────────────────────────────────────── */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  transition: all 0.3s ease;
}
.card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  box-shadow: 0 4px 20px rgba(0,0,0,0.12);
}

/* ── SCROLL ANIMATIONS ─────────────────────────────────────────── */
.fade-in-section {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}
.fade-in-section.visible {
  opacity: 1;
  transform: translateY(0);
}

/* ── STICKY HEADER ─────────────────────────────────────────────── */
.site-header {
  position: sticky;
  top: 0;
  z-index: 200;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid #e5e7eb;
  padding: 0 24px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.header-logo {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  letter-spacing: -0.02em;
}
.header-logo span { color: var(--accent); }

/* ── NAV DROPDOWN ────────────────────────────────────────── */
.header-nav {
  display: flex;
  gap: 2px;
  list-style: none;
}
.header-nav > li {
  position: relative;
}
.header-nav a {
  display: block;
  padding: 6px 12px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.88rem;
  font-weight: 500;
  transition: all 0.2s ease;
  white-space: nowrap;
}
.header-nav a:hover, .header-nav a.active {
  background: rgba(37,99,235,0.08);
  color: var(--accent);
  text-decoration: none;
}
/* Dropdown */
.header-nav .dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  min-width: 200px;
  z-index: 1000;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: all 0.15s ease;
  pointer-events: none;
  padding: 6px 0;
}
.header-nav > li:hover .dropdown {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
}
.header-nav .dropdown a {
  display: block;
  padding: 7px 16px;
  font-size: 0.83rem;
  color: var(--text-secondary);
  border-radius: 0;
  white-space: nowrap;
}
.header-nav .dropdown a:hover {
  background: rgba(37,99,235,0.06);
  color: var(--accent);
}

/* ── BURGER MENU ──────────────────────────────────────────── */
.burger-btn {
  display: none;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.4rem;
  color: var(--text-primary);
  padding: 4px 8px;
  border-radius: 6px;
  transition: background 0.2s;
}
.burger-btn:hover { background: rgba(0,0,0,0.06); }
.mobile-nav {
  display: none;
  position: fixed;
  top: 56px;
  left: 0;
  right: 0;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12);
  z-index: 199;
  padding: 8px 0 16px;
}
.mobile-nav.open { display: block; }
.mobile-nav a {
  display: block;
  padding: 10px 24px;
  font-size: 0.95rem;
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}
.mobile-nav a:hover, .mobile-nav a.active {
  background: rgba(37,99,235,0.05);
  color: var(--accent);
  border-left-color: var(--accent);
}
.mobile-nav .mobile-nav-group { border-top: 1px solid #f0f0f0; margin-top: 4px; padding-top: 4px; }
.mobile-nav .mobile-nav-sub {
  padding-left: 40px;
  font-size: 0.83rem;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.8rem;
}
.clock-display {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  font-weight: 500;
}
.source-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 0.72rem;
  font-weight: 600;
  border: 1px solid;
}
.source-badge.ok        { color: var(--safe);    border-color: rgba(16,185,129,0.3); background: rgba(16,185,129,0.1); }
.source-badge.cached    { color: var(--watch);   border-color: rgba(245,158,11,0.3); background: rgba(245,158,11,0.1); }
.source-badge.unavailable { color: var(--danger); border-color: rgba(239,68,68,0.3); background: rgba(239,68,68,0.1); }

/* ── HERO SECTION ──────────────────────────────────────────────── */
.hero-section {
  position: relative;
  padding: 40px 24px 32px;
  overflow: hidden;
  background:
    linear-gradient(180deg, rgba(224,242,254,0.55) 0%, rgba(247,249,252,0.55) 100%),
    url('data:image/jpeg;base64,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') center/cover no-repeat;
  background-color: #e0f2fe;
}

.composite-status {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.hero-section .composite-status {
  background: rgba(255,255,255,0.92);
  border-radius: 16px;
  padding: 20px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.level-display { text-align: center; }
.level-display .level-number {
  font-size: clamp(4rem, 9.5vw, 7rem);
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 1;
  opacity: 1;
}

/* ── Hero main row: thermometer + center ────────────────────────── */
.hero-main-row {
  display: flex;
  align-items: stretch;
  gap: 1.5rem;
  justify-content: center;
  margin-bottom: 1.5rem;
}
.thermometer-col {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 70px;
  max-width: 90px;
}
.hero-center-col {
  flex: 1;
  min-width: 0;
}

/* ── Термометр ──────────────────────────────────────────────────── */
.thermometer-wrap {
  position: relative;
  height: 280px;
  display: flex;
  align-items: flex-end;
  gap: 6px;
}
.therm-bar {
  width: 28px;
  height: 100%;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  position: relative;
  overflow: hidden;
}
.therm-fill {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  border-radius: 0 0 14px 14px;
  transition: height 1s ease;
}
.therm-mark {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  z-index: 2;
}
.therm-mark-nya { background: var(--warning); }
.therm-mark-oya { background: var(--danger); }
.therm-mark-cur { background: var(--text-secondary); height: 3px; }
.therm-labels {
  position: relative;
  height: 100%;
  width: 50px;
}
.therm-label {
  position: absolute;
  right: 0;
  transform: translateY(50%);
  white-space: nowrap;
}
.therm-tag {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 2px 5px;
  border-radius: 4px;
  letter-spacing: 0.02em;
}
.therm-tag.danger  { background: rgba(239,68,68,0.15); color: var(--danger); }
.therm-tag.warning { background: rgba(249,115,22,0.15); color: var(--warning); }
.therm-tag.current { background: rgba(99,102,241,0.15); color: #818cf8; }
.therm-zero {
  position: absolute;
  bottom: -20px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.6rem;
  color: var(--text-dim);
  white-space: nowrap;
}

/* ── Пояснения к числам ─────────────────────────────────────────── */
.level-explain {
  font-size: 0.75rem;
  color: var(--text-dim);
  margin-top: 0.2rem;
  letter-spacing: 0.02em;
}
.level-abs {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-top: 0.15rem;
  cursor: pointer;
}
.pi-q {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: var(--border);
  color: var(--text-dim);
  font-size: 0.6rem;
  font-weight: 700;
  cursor: pointer;
  vertical-align: middle;
  margin-left: 4px;
}
.pi-q:hover { background: var(--text-dim); color: var(--bg-primary); }

/* ── Инфо-карточки ──────────────────────────────────────────────── */
.info-cards-row {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.info-card {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.85rem 0.65rem;
  text-align: center;
  transition: border-color 0.2s, transform 0.2s;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.info-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
}
.ic-icon { font-size: 1.4rem; margin-bottom: 0.3rem; }
.ic-value {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.1;
}
.ic-unit {
  font-size: 0.7rem;
  font-weight: 500;
  color: var(--text-dim);
}
.ic-title {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-top: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.ic-hint {
  font-size: 0.62rem;
  color: var(--text-dim);
  margin-top: 0.2rem;
  line-height: 1.3;
}
.ic-hint2 {
  font-size: 0.58rem;
  color: var(--text-dim);
  margin-top: 2px;
  line-height: 1.3;
  opacity: 0.8;
}

/* ── v7.2: Новые стили карточек ──────────────────────────── */
.info-card {
  cursor: pointer;
}
a.info-card { text-decoration: none; display: block; }
a.info-card:hover { text-decoration: none; }
.ic-title-colored { font-size: 0.72rem; font-weight: 600; margin-top: 0.25rem; text-transform: uppercase; letter-spacing: 0.04em; }
.info-card-scenarios { min-height: 130px; }
.ic-scenarios { margin: 4px 0; font-size: 0.75em; line-height: 1.7; text-align: left; }
.sc-row { padding: 1px 0; }
.sc-row.sc-dim { opacity: 0.45; font-style: italic; }
.sc-note { color: var(--text-dim); font-size: 0.78em; }
.info-card-conflict { border-color: #f59e0b !important; }
.ic-conflict { color: #f59e0b; font-size: 0.68em; margin-top: 4px; text-align: left; }
.ic-basin { font-size: 0.62em; color: var(--text-dim); margin-top: 4px; text-align: left; }
.pi-hist { font-size: 0.7em; color: var(--text-dim); margin-top: 2px; }
/* Кирпичная кладка прихода волны */
.wave-brick { display: flex; flex-wrap: wrap; gap: 8px 12px; padding: 8px 0; }
.wave-brick-item { display: flex; flex-direction: column; align-items: center; min-width: 90px; }
.wave-brick-item:nth-child(odd)  { margin-top: 0; }
.wave-brick-item:nth-child(even) { margin-top: -24px; }
.wave-brick-name { font-size: 0.75rem; font-weight: 600; color: var(--text-primary); }
.wave-brick-time { font-size: 0.65rem; color: var(--text-dim); }
.wave-brick-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); margin-bottom: 4px; }
/* Скроллябельная таблица истории */
.history-scroll-wrap { max-height: 500px; overflow-y: auto; }
.history-scroll-wrap::-webkit-scrollbar { width: 4px; }
.history-scroll-wrap::-webkit-scrollbar-track { background: transparent; }
.history-scroll-wrap::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
/* Инфографика исторических пиков */
.hist-peaks-bar { display: flex; gap: 16px; align-items: flex-end; padding: 12px 0; justify-content: center; flex-wrap: wrap; }
.hist-peak-col { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.hist-peak-bar { width: 36px; border-radius: 4px 4px 0 0; background: var(--accent); }
.hist-peak-year { font-size: 0.72rem; color: var(--text-dim); font-weight: 600; }
.hist-peak-val  { font-size: 0.7rem;  color: var(--text-secondary); }
/* Глобальные карточки крупнее */
.glofas-station-card { padding: 16px; }
.glofas-abs-q { font-size: 0.9rem; font-weight: 700; color: var(--text-primary); margin: 4px 0; }
.glofas-trend-label { font-size: 0.78rem; color: var(--text-secondary); }
.glofas-pool-equiv { font-size: 0.7rem; color: var(--text-dim); }

/* ── Адаптив: мобильные ─────────────────────────────────────────── */
@media (max-width: 600px) {
  .hero-main-row {
    flex-direction: column;
    align-items: center;
  }
  .thermometer-col {
    order: 2;
    height: auto;
    min-width: unset;
    max-width: unset;
    width: 100%;
  }
  .thermometer-wrap {
    height: 160px;
    flex-direction: row;
    width: 100%;
    justify-content: center;
  }
  .hero-center-col { order: 1; }
  .info-cards-row {
    grid-template-columns: repeat(2, 1fr);
  }
}

.level-number.zone-safe      { color: var(--safe);      text-shadow: 0 0 40px rgba(16,185,129,0.5); }
.level-number.zone-watch     { color: var(--watch);     text-shadow: 0 0 40px rgba(245,158,11,0.5); }
.level-number.zone-warning   { color: var(--warning);   text-shadow: 0 0 40px rgba(249,115,22,0.5); }
.level-number.zone-danger    { color: var(--danger);    text-shadow: 0 0 40px rgba(239,68,68,0.5); }
.level-number.zone-emergency { color: var(--emergency); text-shadow: 0 0 40px rgba(168,85,247,0.5);
                                animation: pulse-emergency 1.5s infinite; }
.level-number.zone-unknown   { color: var(--text-dim); }

@keyframes pulse-emergency {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.level-label {
  font-size: 0.85rem;
  color: var(--text-dim);
  font-weight: 500;
  margin-top: 4px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.sub-indicators {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  width: 100%;
  max-width: 800px;
}
.sub-indicator {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  gap: 4px;
  transition: all 0.3s ease;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.sub-indicator .si-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-dim);
  font-weight: 600;
}
.sub-indicator .si-status {
  font-size: 0.88rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 5px;
}
.sub-indicator .si-value {
  font-size: 0.78rem;
  color: var(--text-secondary);
}

.verdict-banner {
  width: 100%;
  max-width: 800px;
  padding: 14px 20px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  border: 1px solid;
  margin-top: 24px;
}

.progress-bars {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  max-width: 800px;
}
.progress-item {
  display: flex;
  align-items: center;
  gap: 12px;
}
.progress-item .pi-label {
  width: 90px;
  font-size: 0.78rem;
  color: var(--text-secondary);
  font-weight: 500;
  text-align: right;
  white-space: nowrap;
}
.progress-bar-track {
  flex: 1;
  height: 8px;
  background: rgba(0,0,0,0.08);
  border-radius: 4px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.8s ease;
}
.progress-bar-fill.nya { background: linear-gradient(90deg, var(--safe), var(--watch)); }
.progress-bar-fill.oya { background: linear-gradient(90deg, var(--safe), var(--watch), var(--danger)); }
.progress-item .pi-value {
  width: 80px;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

/* ── FORECAST HYDROGRAPH ───────────────────────────────────────── */
.hydrograph-section {
  padding: 0 24px 32px;
}
.hydrograph-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  padding: 20px;
}
.hydrograph-card h3 {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.chart-container {
  position: relative;
  width: 100%;
  min-height: 250px;
  max-height: 400px;
}
.chart-container canvas {
  width: 100% !important;
  height: 100% !important;
}

/* ── STATION CARDS ─────────────────────────────────────────────── */
.stations-section {
  padding: 0 24px 32px;
}
.stations-section h2 {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 14px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.station-cards-scroll {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 8px;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.station-cards-scroll::-webkit-scrollbar { height: 4px; }
.station-cards-scroll::-webkit-scrollbar-track { background: transparent; }
.station-cards-scroll::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.station-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 14px;
  min-width: 140px;
  max-width: 160px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: all 0.3s ease;
  flex-shrink: 0;
  box-shadow: 0 1px 6px rgba(0,0,0,0.07);
}
.station-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,0.12);
}
.station-card.fr-normal  { border-color: rgba(16,185,129,0.4); }
.station-card.fr-watch   { border-color: rgba(245,158,11,0.4); }
.station-card.fr-warning { border-color: rgba(249,115,22,0.4); }
.station-card.fr-danger  { border-color: rgba(239,68,68,0.4); }
.station-card.fr-unknown { border-color: var(--border); }

.station-card.main-station {
  border-color: rgba(59,130,246,0.5);
  box-shadow: 0 0 20px rgba(59,130,246,0.15);
  min-width: 160px;
}

.sc-name {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--text-primary);
}
.sc-river {
  font-size: 0.7rem;
  color: var(--text-dim);
}
.sc-value {
  font-size: 1.2rem;
  font-weight: 700;
  line-height: 1.2;
}
.sc-sparkline { line-height: 0; }
.sc-trend {
  font-size: 0.82rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}
.sc-badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 20px;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.sc-badge.fr-normal  { background: rgba(16,185,129,0.15);  color: var(--safe); }
.sc-badge.fr-watch   { background: rgba(245,158,11,0.15);  color: var(--watch); }
.sc-badge.fr-warning { background: rgba(249,115,22,0.15);  color: var(--warning); }
.sc-badge.fr-danger  { background: rgba(239,68,68,0.15);   color: var(--danger); }
.sc-badge.fr-unknown { background: rgba(100,116,139,0.15); color: var(--text-dim); }

.sc-peak { font-size: 0.7rem; color: var(--text-dim); }
.sc-travel {
  font-size: 0.68rem;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
  padding-top: 5px;
  margin-top: 2px;
}

.station-arrow {
  display: flex;
  align-items: center;
  color: var(--text-dim);
  font-size: 1.2rem;
  flex-shrink: 0;
  align-self: center;
}

/* ── WAVE ARRIVAL TIMELINE ─────────────────────────────────────── */
.timeline-section { padding: 0 24px 32px; }
.timeline-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  padding: 20px;
}
.timeline-card h3 {
  font-size: 1rem;
  font-weight: 600;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.timeline-bar-container {
  position: relative;
  padding: 10px 0 40px;
}
.timeline-track {
  height: 4px;
  background: rgba(0,0,0,0.10);
  border-radius: 2px;
  position: relative;
  margin: 20px 0;
}
.timeline-marker {
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
}
.timeline-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid;
  background: #ffffff;
  position: relative;
  z-index: 1;
}
.timeline-dot.current { width: 16px; height: 16px; background: var(--accent); border-color: var(--accent); }
.timeline-marker-label {
  position: absolute;
  top: 14px;
  font-size: 0.65rem;
  white-space: nowrap;
  color: var(--text-secondary);
  text-align: center;
  transform: translateX(-50%);
  left: 50%;
}
.timeline-marker-name {
  position: absolute;
  bottom: 14px;
  font-size: 0.65rem;
  white-space: nowrap;
  color: var(--text-dim);
  text-align: center;
  transform: translateX(-50%);
  left: 50%;
}

/* ── ACTION BLOCK ──────────────────────────────────────────────── */
.action-section { padding: 0 24px 32px; }
.action-card {
  background: var(--bg-card);
  border-radius: 16px;
  padding: 24px;
  border-left: 4px solid;
  border-top: 1px solid var(--border);
  border-right: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-card);
}
.action-icon { font-size: 2rem; }
.action-title { font-size: 1.2rem; font-weight: 700; margin-bottom: 8px; }
.action-text { color: var(--text-secondary); line-height: 1.7; font-size: 0.92rem; }

/* ── WEATHER SECTION ───────────────────────────────────────────── */
.weather-section { padding: 0 24px 32px; }
.weather-flood-index {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  border-left: 3px solid;
  box-shadow: var(--shadow-card);
}
.wfi-label { font-size: 0.82rem; color: var(--text-dim); font-weight: 500; }
.wfi-value { font-size: 1.1rem; font-weight: 700; }
.wfi-summary { color: var(--text-secondary); font-size: 0.85rem; flex: 1; min-width: 200px; }

/* ── ACCORDION SECTIONS ────────────────────────────────────────── */
.accordion-section { padding: 0 24px 8px; }
.accordion-header {
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.95rem;
  transition: all 0.2s ease;
  user-select: none;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.accordion-header:hover { background: var(--bg-card-hover); }
.accordion-body {
  display: none;
  background: #ffffff;
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 12px 12px;
  padding: 20px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.accordion-body.open { display: block; }

/* ── WEATHER TABLE ─────────────────────────────────────────────── */
.weather-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.83rem;
}
.weather-table th, .weather-table td {
  padding: 8px 10px;
  text-align: center;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.weather-table th { color: var(--text-dim); font-weight: 600; font-size: 0.75rem; }
.weather-table .forecast-col { background: rgba(37,99,235,0.04); }
.weather-table td:first-child { text-align: left; color: var(--text-secondary); }
td.frost { background: rgba(192,57,43,0.25); color: #ff6b6b; font-weight: bold; }
td.zero  { background: rgba(243,156,18,0.20); color: #f39c12; }
td.warm-night { background: rgba(39,174,96,0.20); color: #27ae60; }
td.hot { color: #e74c3c; font-weight: bold; }

/* ── HISTORY TABLE ─────────────────────────────────────────────── */
#histTable { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
#histTable th, #histTable td {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
#histTable th { color: var(--text-secondary); font-size: 0.72rem; font-weight: 600; background: #f8fafc; }
.status-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 20px;
  font-size: 0.68rem;
  font-weight: 700;
}
.status-badge.норма     { background: rgba(16,185,129,0.15);  color: var(--safe); }
.status-badge.внимание  { background: rgba(245,158,11,0.15);  color: var(--watch); }
.status-badge.опасность { background: rgba(249,115,22,0.15);  color: var(--warning); }
.status-badge.критично  { background: rgba(239,68,68,0.15);   color: var(--danger); }
.status-badge.чс        { background: rgba(168,85,247,0.15);  color: var(--emergency); }
.status-badge.нет-данных { background: rgba(100,116,139,0.15); color: var(--text-dim); }

/* ── THRESHOLD SCALE ───────────────────────────────────────────── */
.threshold-scale-container { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }
.thresh-table { width: 100%; border-collapse: collapse; font-size: 0.88em; flex: 1; }
.thresh-table th { color: var(--text-dim); padding: 6px 8px; text-align: left; font-size: 0.75rem; font-weight: 600; }
.thresh-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.thresh-table tr.row-nya td { background: rgba(245,158,11,0.1); }
.thresh-table tr.row-oya td { background: rgba(239,68,68,0.1); }
.thresh-table tr.row-current td { background: rgba(59,130,246,0.1); font-weight: 700; }

/* ── CUGMS / PEAK SECTION ──────────────────────────────────────── */
.cugms-meta { font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 12px; }
.cugms-data { display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0; }
.cugms-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; background: #f8fafc;
  border: 1px solid var(--border); border-radius: 6px; min-width: 180px;
}
.cugms-station { font-size: 0.88rem; color: var(--text-secondary); min-width: 80px; }
.cugms-value { font-size: 1.05rem; font-weight: 700; color: var(--text-primary); }
.cugms-forecast {
  background: rgba(59,130,246,0.05); border-left: 3px solid var(--accent);
  padding: 10px 14px; border-radius: 0 6px 6px 0; font-size: 0.85rem;
  color: var(--text-secondary); margin-top: 10px; width: 100%;
}
.peak-trend {
  font-size: 1.05rem; font-weight: 600; margin: 8px 0;
  padding: 10px 14px; border-radius: 6px;
  background: var(--bg-glass); border-left: 3px solid;
}
.regression-block {
  background: rgba(59,130,246,0.05); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; margin-top: 10px; font-size: 0.88rem;
}
.regression-block p { color: var(--text-secondary); margin: 4px 0; }

/* ── EXPLAINER ─────────────────────────────────────────────────── */
.explainer {
  background: rgba(37,99,235,0.04); border-left: 3px solid var(--accent);
  padding: 10px 14px; margin: 8px 0 0; font-size: 0.85rem;
  color: var(--text-secondary); border-radius: 0 6px 6px 0;
}
.explainer b { color: var(--text-primary); }
.disclaimer-small { font-size: 0.8rem; color: var(--text-dim); margin-top: 8px; }
.no-data { color: var(--text-dim); font-size: 0.9rem; font-style: italic; padding: 10px 0; }

/* ── HISTORY CONTROLS ──────────────────────────────────────────── */
.history-controls { margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.hist-btn {
  padding: 5px 12px; border-radius: 6px; font-size: 0.82rem;
  background: var(--bg-glass); border: 1px solid var(--border);
  color: var(--text-secondary); cursor: pointer; text-decoration: none; display: inline-block;
  transition: all 0.2s ease;
}
.hist-btn:hover { background: rgba(59,130,246,0.2); color: var(--text-primary); border-color: var(--accent); }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 0 -16px; padding: 0 16px; }

/* ── REPORTS ────────────────────────────────────────────────────── */
.report-cards { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
.report-card {
  background: #f8fafc; border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; min-width: 200px; flex: 1;
}
.report-meta { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; }

/* ── FOOTER ────────────────────────────────────────────────────── */
.site-footer {
  background: rgba(247,249,252,0.95);
  border-top: 1px solid #e5e7eb;
  padding: 20px 24px;
  text-align: center;
  color: var(--text-dim);
  font-size: 0.78rem;
  margin-top: 8px;
}

/* ── ZONE TABLE (instructions) ─────────────────────────────────── */
.zone-table { margin: 10px 0; }
.zone-row { padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 0.88rem; }
.zone-row.green  { background: rgba(16,185,129,0.1);  border-left: 3px solid var(--safe); }
.zone-row.yellow { background: rgba(245,158,11,0.1);  border-left: 3px solid var(--watch); }
.zone-row.orange { background: rgba(249,115,22,0.1);  border-left: 3px solid var(--warning); }
.zone-row.red    { background: rgba(239,68,68,0.1);   border-left: 3px solid var(--danger); }
.zone-row.purple { background: rgba(168,85,247,0.1);  border-left: 3px solid var(--emergency); }

/* ── LINKS / INSTRUCTIONS ──────────────────────────────────────── */
.links-section, .instr-section {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  margin: 12px 0;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.links-section ul, .instr-section ul, .instr-section ol { padding-left: 20px; }
.links-section li, .instr-section li { margin: 8px 0; color: var(--text-secondary); }
.dead-sources {
  background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px; padding: 12px 16px; margin-top: 10px;
}
.action-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin: 10px 0; }
.action-table th { color: var(--text-dim); padding: 6px 8px; text-align: left; font-size: 0.75rem; font-weight: 600; border-bottom: 1px solid var(--border); }
.action-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }

/* ── CONTAINER ─────────────────────────────────────────────────── */
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px 32px; }

/* ── SECTION HEADERS ────────────────────────────────────────────── */
h1, h2, h3, h4 { color: var(--text-primary); }
h1 { font-size: 1.6rem; padding: 20px 0; }
h2 { font-size: 1.15rem; margin: 16px 0 8px; }
h3 { font-size: 1rem; margin: 12px 0 6px; }

/* ── RESPONSIVE ─────────────────────────────────────────────────── */
@media (max-width: 768px) {
  .sub-indicators { grid-template-columns: repeat(2, 1fr); }
  .hero-section { padding: 24px 16px 20px; }
  .level-display .level-number { font-size: 3.5rem; }
  .station-cards-scroll { gap: 8px; }
  .station-card { min-width: 130px; padding: 12px; }
  .station-arrow { display: none; }
  .hydrograph-section, .stations-section, .timeline-section,
  .action-section, .weather-section { padding-left: 16px; padding-right: 16px; }
  .accordion-section { padding-left: 16px; padding-right: 16px; }
}

@media (max-width: 768px) {
  .header-nav { display: none; }
  .burger-btn { display: block; }
}

@media (max-width: 480px) {
  .sub-indicators { grid-template-columns: 1fr 1fr; }
  .header-right { gap: 6px; }
}

/* ═══════════════════════════════════════════════════════════════
   v7.3: Tooltip system (CSS-only via data-tooltip)
   ═══════════════════════════════════════════════════════════════ */
[data-tooltip] { position: relative; cursor: pointer; }
[data-tooltip]::after {
  content: attr(data-tooltip);
  position: absolute; bottom: calc(100% + 8px); left: 50%;
  transform: translateX(-50%);
  background: rgba(26,35,50,0.95); color: #f8fafc;
  padding: 8px 14px; border-radius: 8px;
  font-size: 0.72rem; white-space: normal; max-width: 260px;
  opacity: 0; pointer-events: none;
  transition: opacity 0.2s; z-index: 100;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  line-height: 1.4;
}
[data-tooltip]:hover::after { opacity: 1; }
[data-tooltip=""]::after { display: none; }
[data-tooltip=""] { cursor: default; }

/* v7.3: Updated badge */
.updated-badge { font-size: 0.62rem; color: var(--text-dim); opacity: 0.6; margin-left: 6px; }

/* v7.3: Freshness dot */
.freshness-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: 8px; vertical-align: middle; }
.fresh-green { background: #10b981; }
.fresh-yellow { background: #f59e0b; }
.fresh-red { background: #ef4444; animation: pulse-fresh 1.5s infinite; }
@keyframes pulse-fresh { 0%,100% { opacity:1; } 50% { opacity:0.4; } }

/* v7.3: Stale data banner */
.stale-banner { background: rgba(245,158,11,0.10); border: 1px solid rgba(245,158,11,0.3); border-radius: 12px; padding: 12px 20px; margin: 0 24px 16px; color: #b45309; font-size: 0.85rem; text-align: center; }

/* v7.3: Report placeholder */
.report-placeholder { padding: 20px; color: var(--text-secondary); font-size: 0.88rem; text-align: center; }

/* v7.3: Clickable station cards */
a.station-card-link { text-decoration: none; color: inherit; display: block; }
a.station-card-link:hover .station-card { border-color: var(--border-hover); transform: translateY(-2px); }

/* v7.3: Wave timeline table */
.wave-table { width: 100%; border-collapse: collapse; font-size: 0.84rem; margin-top: 16px; }
.wave-table th { color: var(--text-dim); font-weight: 600; padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; }
.wave-table td { padding: 9px 12px; border-bottom: 1px solid rgba(255,255,255,0.04); color: var(--text-secondary); }
.wave-table tr:nth-child(even) td { background: #f8fafc; }
.wave-table tr:hover td { background: rgba(37,99,235,0.04); }
.wave-table .col-station { color: var(--text-primary); font-weight: 500; }
.wave-table .col-arrival { color: #10b981; font-weight: 600; }
"""
    return css.replace("__WATER_BUBBLES_B64__", _water_b64)


# ══════════════════════════════════════════════════════════════════════════════
# HTML: HEADER v7
# ══════════════════════════════════════════════════════════════════════════════

def _generate_header_v7(serp: dict, kim: dict, cugms: dict, glofas: dict,
                         now_msk: str) -> str:
    """Генерирует sticky header v7.6.1 с навигацией, часами, бейджами."""
    src_stat    = serp.get("source_status", "unavailable")
    kim_stat    = (kim.get("_api_status") or "unavailable")
    glofas_stat = (glofas or {}).get("_status", "unavailable")

    def _badge(label, status):
        cls = "ok" if status == "ok" else ("cached" if status in ("cached", "partial") else "unavailable")
        return f'<span class="source-badge {cls}">{_h(label)}</span>'

    base_nav = _build_nav("main", is_subpage=False)

    # Insert status row before </header>
    status_row = f"""<div class="header-right">
    <span class="clock-display" id="clock">--:--:-- МСК</span>
    <span class="freshness-dot" id="freshness" title="Проверка свежести данных..."></span>
    <span style="color:var(--text-dim); font-size:0.72rem;">обн. {_h(now_msk)}</span>
    {_badge("serp", src_stat)}
    {_badge("kim", kim_stat)}
    {_badge("GloFAS", glofas_stat)}
  </div>"""

    # Inject header-right before </header>
    return base_nav.replace("</header>", status_row + "\n</header>", 1)


# ══════════════════════════════════════════════════════════════════════════════
# HTML: HERO v7 — COMPOSITE STATUS
# ══════════════════════════════════════════════════════════════════════════════

def _generate_hero_v7(serp: dict, analytics: dict, composite: dict,
                       nya_fill_pct: float, oya_fill_pct: float,
                       nya_rem, oya_rem, wext=None) -> str:
    """Генерирует hero-секцию с Composite Status."""
    level_cm  = serp.get("level_cm")
    # v7.1: цвет числа по Composite Status (verdict), а не по уровню
    verdict_zone_name = composite.get("verdict", {}).get("zone", "unknown")
    zone_css = f"zone-{verdict_zone_name}"

    level_str = f"{level_cm:.0f} см" if level_cm is not None else "? см"
    abs_bs    = serp.get("abs_level_m_bs")
    abs_str   = f"{abs_bs:.3f} м БС" if abs_bs is not None else ""

    comp = composite
    level_comp   = comp.get("level", {})
    trend_comp   = comp.get("trend", {})
    glofas_comp  = comp.get("glofas", {})
    weather_comp = comp.get("weather", {})
    verdict      = comp.get("verdict", {})

    ZONE_ICONS = {
        "safe":      "🟢", "watch":     "🟡",
        "warning":   "🟠", "danger":    "🔴",
        "emergency": "🟣", "unknown":   "⚪",
    }

    def _si_html(label, icon, status_label, value, color, href="#"):
        return f"""
  <a href="{href}" style="text-decoration:none; color:inherit; cursor:pointer; display:block;" class="sub-indicator si-link">
    <div class="si-label">{_h(label)}</div>
    <div class="si-status" style="color:{color};">{icon} {_h(status_label)}</div>
    <div class="si-value">{_h(value)}</div>
  </a>"""

    si_html  = _si_html("\u0423\u0440\u043e\u0432\u0435\u043d\u044c",       ZONE_ICONS.get(level_comp.get("zone", "unknown"), "\u26aa"),
                          level_comp.get("label", "\u2014"), level_comp.get("value", "\u2014"),
                          level_comp.get("color", "#64748b"), "#threshAcc")
    si_html += _si_html("\u0422\u0440\u0435\u043d\u0434",         ZONE_ICONS.get(trend_comp.get("zone", "unknown"), "\u26aa"),
                          trend_comp.get("label", "\u2014"), trend_comp.get("value", "\u2014"),
                          trend_comp.get("color", "#64748b"), "#histAcc")
    si_html += _si_html("\u041f\u0440\u043e\u0433\u043d\u043e\u0437 GloFAS", ZONE_ICONS.get(glofas_comp.get("zone", "unknown"), "\u26aa"),
                          glofas_comp.get("label", "\u2014"), glofas_comp.get("value", "\u2014"),
                          glofas_comp.get("color", "#64748b"), "#glofas-section")
    si_html += _si_html("\u041f\u043e\u0433\u043e\u0434\u0430",        ZONE_ICONS.get(weather_comp.get("zone", "unknown"), "\u26aa"),
                          weather_comp.get("label", "\u2014"), weather_comp.get("value", "\u2014"),
                          weather_comp.get("color", "#64748b"), "#weatherAcc")

    verdict_color = verdict.get("color", "#64748b")
    verdict_label = verdict.get("label", "⚪ НЕТ ДАННЫХ")
    verdict_banner = f"""
<a href="#vigilance-section" style="text-decoration:none;display:block;">
  <div class="verdict-banner" style="background: {verdict_color}18; border-color: {verdict_color}40; color: {verdict_color}; cursor:pointer;" data-tooltip="\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u0434\u043b\u044f \u043f\u0435\u0440\u0435\u0445\u043e\u0434\u0430 \u043a \u0440\u0435\u043a\u043e\u043c\u0435\u043d\u0434\u0430\u0446\u0438\u044f\u043c">
    {_h(verdict_label)}
  </div>
</a>"""

    # Пороги в см от нуля поста
    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)

    nya_rem_str = f"{nya_rem:.2f} м до НЯ" if nya_rem is not None else "нет данных"
    oya_rem_str = f"{oya_rem:.2f} м до ОЯ" if oya_rem is not None else "нет данных"

    days_to_nya = analytics.get("days_to_nya")
    days_to_oya = analytics.get("days_to_oya")
    nya_days_str = f" ({days_to_nya:.0f} дн)" if days_to_nya and days_to_nya < 60 else ""
    oya_days_str = f" ({days_to_oya:.0f} дн)" if days_to_oya and days_to_oya < 90 else ""

    water_st = serp.get("water_status", "—") or "—"
    water_str = "" if water_st in ("—", "-", "") else f" | {water_st}"

    # ── Данные для мини-карточек (v7.2) ───────────────────────────
    snow_cm   = (wext or {}).get("snow_depth_cm", 0) or 0
    change_cm = serp.get("daily_change_cm")
    change_str = f"{change_cm:+.0f}" if change_cm is not None else "—"
    change_lbl = "рост" if change_cm and change_cm > 0 else ("спад" if change_cm and change_cm < 0 else "стабильно")

    fl_idx = (wext or {}).get("flood_index", 0) or 0
    fl_label_short = {0: "минимальный", 1: "низкий", 2: "умеренный", 3: "высокий", 4: "экстремальный"}.get(fl_idx, "?")
    if (wext or {}).get("_cached"):
        fl_label_short += " (кеш)"

    # v7.6: динамическое описание паводкового индекса
    flood_summary_short = (wext or {}).get("flood_summary", "") or f"{fl_label_short} — осадки и таяние"

    # v7.2: данные для карточек
    change_3d   = analytics.get("change_3d_cm")
    change_3d_str = f"{change_3d:+.0f}" if change_3d is not None else change_str
    accel       = analytics.get("change_acceleration")
    cugms_ch    = analytics.get("cugms_change_cm")
    conflict    = analytics.get("source_conflict", False)
    accel_labels = {
        "accelerating": "↑ ускоряется",
        "decelerating": "↓ замедляется",
        "stable":       "→ стабильно",
    }
    accel_str = accel_labels.get(accel, "")
    if conflict and cugms_ch is not None:
        try:
            conflict_html = f'<div class="ic-conflict">⚠️ ЦУГМС: {float(cugms_ch):+.0f} см/сут — источники противоречат</div>'
        except (ValueError, TypeError):
            conflict_html = f'<div class="ic-conflict">⚠️ ЦУГМС: {_h(str(cugms_ch))} — данные противоречат</div>'
    else:
        conflict_html = ""

    # v7.2: Сценарии до НЯ
    scenarios = analytics.get("nya_scenarios", [])
    sc_rows = ""
    for sc in scenarios:
        dim_class = " sc-dim" if not sc.get("realistic") else ""
        sc_rows += (
            f'<div class="sc-row{dim_class}">'
            f'{sc["emoji"]} <b>{_h(sc["label"])}:</b> '
            f'~{sc["days"]} дн → <b>{_h(sc["arrival"])}</b>'
            f'<span class="sc-note"> ({_h(sc["note"])})</span>'
            f'</div>'
        )
    if not sc_rows:
        sc_rows = '<div class="sc-row">Нет данных для расчёта</div>'

    # v7.2: Фаза паводка
    phase_code  = analytics.get("flood_phase", "unknown")
    phase_lbl   = analytics.get("flood_phase_label", "—")
    phase_icon  = analytics.get("flood_phase_icon", "⚪")
    PHASE_HINTS = {
        "before":       "Паводок ещё не начался. Следите за температурой и снегом.",
        "early_start":  "Ранний старт. Следите за динамикой.",
        "early_rise":   "Уровень растёт медленно. Ожидается ускорение через 5–10 дней.",
        "active_rise":  "Активный рост! Принимайте защитные меры.",
        "rapid_rise":   "Экстремальный рост! Немедленные действия.",
        "peak_zone":    "Зона НЯ. Уровень на пике и продолжает расти.",
        "peak":         "Уровень на пике. Спад ожидается в течение 1–3 дней.",
        "recession":    "Уровень снижается. Паводок проходит.",
        "return_to_channel": "Возврат в русло. Паводок завершён.",
        "unknown":      "Недостаточно данных для определения фазы.",
    }
    phase_hint = PHASE_HINTS.get(phase_code, "")

    # v7.2: цвет заголовка карточки по зоне параметра
    ZONE_COLOR_MAP = {
        "safe":      "#10b981",
        "watch":     "#f59e0b",
        "warning":   "#f97316",
        "danger":    "#ef4444",
        "emergency": "#a855f7",
        "unknown":   "#64748b",
    }
    snow_zone_card = "safe" if snow_cm < 20 else ("watch" if snow_cm < 50 else "warning")
    trend_zone_card = "safe"
    if change_3d is not None:
        if change_3d >= 50:   trend_zone_card = "danger"
        elif change_3d >= 20: trend_zone_card = "warning"
        elif change_3d >= 5:  trend_zone_card = "watch"
        elif change_3d < -10: trend_zone_card = "safe"
    weather_zone_card = "safe" if fl_idx < 2 else ("watch" if fl_idx < 3 else ("warning" if fl_idx < 4 else "danger"))
    phase_zone_card = {
        "before": "safe", "early_start": "watch", "early_rise": "watch",
        "active_rise": "warning", "rapid_rise": "danger", "peak_zone": "danger",
        "peak": "danger", "recession": "safe", "return_to_channel": "safe", "unknown": "unknown",
    }.get(phase_code, "unknown")
    snow_title_color    = ZONE_COLOR_MAP.get(snow_zone_card, "#94a3b8")
    trend_title_color   = ZONE_COLOR_MAP.get(trend_zone_card, "#94a3b8")
    weather_title_color = ZONE_COLOR_MAP.get(weather_zone_card, "#94a3b8")
    phase_title_color   = ZONE_COLOR_MAP.get(phase_zone_card, "#94a3b8")

    # v7.2: типичный сценарий для прогресс-бара
    typical_sc = next((s for s in scenarios if s.get("key") == "typical"), None)
    typical_str = f" | Типичный сценарий: ~{typical_sc['arrival']}" if typical_sc else ""

    # ── Термометр: расчёт позиций ────────────────────────────────
    # Шкала от 0 до ОЯ+10%
    oya_cm_scale = oya_cm * 1.1
    level_val = float(level_cm) if level_cm is not None else 0
    therm_cur_pct = min(100, max(0, level_val / oya_cm_scale * 100))
    therm_nya_pct = min(100, max(0, nya_cm / oya_cm_scale * 100))
    therm_oya_pct = min(100, max(0, oya_cm / oya_cm_scale * 100))

    # Gradient color for thermometer fill
    if therm_cur_pct < therm_nya_pct * 0.6:
        therm_grad = "linear-gradient(to top, #10b981, #10b981)"
    elif therm_cur_pct < therm_nya_pct:
        therm_grad = "linear-gradient(to top, #10b981, #f59e0b)"
    elif therm_cur_pct < therm_oya_pct:
        therm_grad = "linear-gradient(to top, #10b981, #f59e0b, #f97316)"
    else:
        therm_grad = "linear-gradient(to top, #10b981, #f59e0b, #f97316, #ef4444)"

    # НЯ tooltip
    nya_explained = f"Неблагоприятное явление: уровень {nya_cm:.0f} см ({LUKYANNOVO_NYA_M_BS:.2f} м БС)"
    oya_explained = f"Опасное явление: уровень {oya_cm:.0f} см ({LUKYANNOVO_OYA_M_BS:.2f} м БС)"

    # v7.6: обогащение карточек — ic-hint2
    snow_hint2 = "мало" if snow_cm < 5 else ("умеренно" if snow_cm < 20 else ("много — опасно!" if snow_cm >= 50 else "значительно"))
    trend_ctx = ""
    if change_3d is not None:
        if abs(change_3d) < 10:
            trend_ctx = "Умеренный. В 2013: +46, Калуга 2024: +132"
        elif change_3d > 40:
            trend_ctx = "Критически быстрый! В 2013: +46, Калуга 2024: +132"
        else:
            trend_ctx = f"Быстрый. В 2013: +46, Калуга 2024: +132"
    flood_components = []
    if (wext or {}).get("warm_nights_count"):
        flood_components.append(f"тёплые ночи: {(wext or {}).get('warm_nights_count')}/8")
    if snow_cm > 0:
        flood_components.append(f"снег: {snow_cm:.0f} см")
    if (wext or {}).get("precip_4d_mm"):
        flood_components.append(f"осадки: {(wext or {}).get('precip_4d_mm'):.0f} мм/4д")
    if (wext or {}).get("thaw_days"):
        flood_components.append(f"оттепель: {(wext or {}).get('thaw_days')} дн")
    flood_comp_hint = "; ".join(flood_components) if flood_components else ""
    phase_rec = ""
    if phase_lbl:
        pl = phase_lbl.lower()
        if "подготов" in pl or "нач" in pl:
            phase_rec = "Проверьте насос, батареи, маршрут эвакуации"
        elif "рост" in pl or "подъём" in pl:
            phase_rec = "Следите за уровнем ежедневно!"
        elif "пик" in pl:
            phase_rec = "Максимальная готовность. Не подходите к воде."
        elif "спад" in pl:
            phase_rec = "Вода уходит. Осторожно — берега размыты."
        else:
            phase_rec = "Мониторинг в штатном режиме"

    return f"""
<section class="hero-section">
  <div class="composite-status">

    <div class="hero-main-row">

      <!-- Термометр (левая часть) -->
      <div class="thermometer-col">
        <div class="thermometer-wrap" title="Уровень воды от нуля поста д. Лукьяново. НЯ = 645 см (выход на пойму), ОЯ = 800 см (подтопление населённых пунктов)" data-tooltip="Визуальная шкала: от нуля поста до ОЯ">
          <div class="therm-labels">
            <div class="therm-label therm-oya" style="bottom:{therm_oya_pct:.1f}%;" data-tooltip="\u041e\u042f = \u043e\u043f\u0430\u0441\u043d\u043e\u0435 \u044f\u0432\u043b\u0435\u043d\u0438\u0435. \u041f\u043e\u0434\u0442\u043e\u043f\u043b\u0435\u043d\u0438\u0435 \u043d\u0430\u0441\u0435\u043b\u0451\u043d\u043d\u044b\u0445 \u043f\u0443\u043d\u043a\u0442\u043e\u0432. \u041f\u043e\u0440\u043e\u0433: 800 \u0441\u043c">
              <span class="therm-tag danger">ОЯ {oya_cm:.0f}</span>
            </div>
            <div class="therm-label therm-nya" style="bottom:{therm_nya_pct:.1f}%;" data-tooltip="\u041d\u042f = \u043d\u0435\u0431\u043b\u0430\u0433\u043e\u043f\u0440\u0438\u044f\u0442\u043d\u043e\u0435 \u044f\u0432\u043b\u0435\u043d\u0438\u0435. \u0412\u044b\u0445\u043e\u0434 \u0432\u043e\u0434\u044b \u043d\u0430 \u043f\u043e\u0439\u043c\u0443. \u041f\u043e\u0440\u043e\u0433: 645 \u0441\u043c">
              <span class="therm-tag warning">НЯ {nya_cm:.0f}</span>
            </div>
            <div class="therm-label therm-cur" style="bottom:{therm_cur_pct:.1f}%;">
              <span class="therm-tag current">{level_val:.0f}</span>
            </div>
          </div>
          <div class="therm-bar">
            <div class="therm-fill" style="height:{therm_cur_pct:.1f}%; background:{therm_grad};"></div>
            <div class="therm-mark therm-mark-nya" style="bottom:{therm_nya_pct:.1f}%;" title="НЯ 645 см — неблагоприятное явление"></div>
            <div class="therm-mark therm-mark-oya" style="bottom:{therm_oya_pct:.1f}%;" title="ОЯ 800 см — опасное явление"></div>
            <div class="therm-mark therm-mark-cur" style="bottom:{therm_cur_pct:.1f}%;"></div>
            <div style="position:absolute; right:-38px; bottom:{therm_nya_pct:.1f}%; font-size:0.5rem; color:var(--warning); transform:translateY(50%); white-space:nowrap;">НЯ</div>
            <div style="position:absolute; right:-38px; bottom:{therm_oya_pct:.1f}%; font-size:0.5rem; color:var(--danger); transform:translateY(50%); white-space:nowrap;">ОЯ</div>
          </div>
          <div class="therm-zero">0 см</div>
        </div>
      </div>

      <!-- Центральный блок с уровнем -->
      <div class="hero-center-col">
        <div class="level-display">
          <div class="level-number {zone_css}" title="\u0423\u0440\u043e\u0432\u0435\u043d\u044c \u0432\u043e\u0434\u044b \u043e\u0442 \u043d\u0443\u043b\u044f \u0433\u0438\u0434\u0440\u043e\u043f\u043e\u0441\u0442\u0430 \u0434. \u041b\u0443\u043a\u044c\u044f\u043d\u043e\u0432\u043e (\u043d\u0443\u043b\u044c \u043f\u043e\u0441\u0442\u0430 = {LUKYANNOVO_ZERO_M_BS:.2f} \u043c \u0411\u0421)">{_h(level_str)}{f'<span class="updated-badge">\u043e\u0431\u043d. {_h(serp.get("fetch_time", "")[:16].replace("T", " ") if serp.get("fetch_time") else "")}</span>' if serp.get('fetch_time') else ''}</div>
          <div class="level-explain">\u0443\u0440\u043e\u0432\u0435\u043d\u044c \u043e\u0442 \u043d\u0443\u043b\u044f \u043f\u043e\u0441\u0442\u0430 \u0434. \u041b\u0443\u043a\u044c\u044f\u043d\u043e\u0432\u043e</div>
          <div class="level-label">р. Ока{_h(water_str)}</div>
          <div style="font-size:0.68rem; color:var(--text-dim); margin-top:4px; line-height:1.4;">от д. Лукьяново до Пущино ≈ 17 км по реке (~4–5 ч волны), до Жерновки ≈ 28 км (~7 ч волны)</div>
          {f'<div class="level-abs" title="Абсолютная отметка уровня в Балтийской системе высот">{_h(abs_str)}</div>' if abs_str else ''}
        </div>

        <div class="sub-indicators">
          {si_html}
        </div>

        {verdict_banner}
      </div>

    </div>

    <!-- Мини-карточки инфографики v7.2 -->
    <div class="info-cards-row">
      <a class="info-card" href="#weatherAcc" title="Перейти к разделу: Погода и паводковый индекс">
        <div class="ic-icon">❄️</div>
        <div class="ic-value">{snow_cm:.0f} <span class="ic-unit">см</span></div>
        <div class="ic-title-colored" style="color:{snow_title_color};">Снег у Серпухова</div>
        <div class="ic-hint">глубина снега по Open-Meteo (локально)</div>
        <div class="ic-hint2">Оценка: {snow_hint2}</div>
      </a>
      <a class="info-card{'  info-card-conflict' if conflict else ''}" href="#cugmsAcc" title="Перейти к разделу: ЦУГМС и станции">
        <div class="ic-icon">📈</div>
        <div class="ic-value">{change_3d_str} <span class="ic-unit">см/сут</span></div>
        <div class="ic-title-colored" style="color:{trend_title_color};">Тренд (3 дня) {accel_str}</div>
        <div class="ic-hint">Сейчас: {change_str} см/сут (serpuhov.ru)</div>
        <div class="ic-hint2">{_h(trend_ctx)}</div>
        {conflict_html}
      </a>
      <a class="info-card info-card-scenarios" href="#threshAcc" title="Перейти к разделу: Пороги и сценарии">
        <div class="ic-icon">⏳</div>
        <div class="ic-title-colored" style="color:#f59e0b;">Сценарии до НЯ</div>
        <div class="ic-scenarios">{sc_rows}</div>
        <div class="ic-hint">История: пик обычно 1–20 апр. Линейная оценка неприменима.</div>
      </a>
      <a class="info-card" href="#weatherAcc" title="Перейти к разделу: Погода и паводковый индекс">
        <div class="ic-icon">🌧️</div>
        <div class="ic-value">{fl_idx}/4</div>
        <div class="ic-title-colored" style="color:{weather_title_color};">Паводковый индекс</div>
        <div class="ic-hint">{_h(flood_summary_short)}</div>
        <div class="ic-hint2">{_h(flood_comp_hint)}</div>
      </a>
      <a class="info-card" href="#peakAcc" title="Перейти к разделу: Прогноз пика">
        <div class="ic-icon">{phase_icon}</div>
        <div class="ic-value" style="font-size:0.95rem;">{_h(phase_lbl)}</div>
        <div class="ic-title-colored" style="color:{phase_title_color};">Фаза паводка</div>
        <div class="ic-hint">{_h(phase_hint)}</div>
        <div class="ic-hint2">{_h(phase_rec)}</div>
      </a>
    </div>

    <!-- Прогресс-бары v7.2 -->
    <div class="progress-bars">
      <div class="progress-item">
        <div class="pi-label" title="{_h(nya_explained)}">До НЯ {nya_cm:.0f} см <span class="pi-q" title="Неблагоприятное гидрологическое явление — подтопление пойменных территорий">?</span></div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill nya" style="width:{nya_fill_pct:.1f}%;"></div>
        </div>
        <div class="pi-value">{_h(nya_rem_str)}{_h(typical_str)}</div>
        <div class="pi-hist">Исторически: пик 1–20 апр | рекорд 23 апр 2013</div>
      </div>
      <div class="progress-item">
        <div class="pi-label" title="{_h(oya_explained)}">До ОЯ {oya_cm:.0f} см <span class="pi-q" title="Опасное гидрологическое явление — затопление дорог и построек">?</span></div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill oya" style="width:{oya_fill_pct:.1f}%;"></div>
        </div>
        <div class="pi-value">{_h(oya_rem_str)}</div>
      </div>
    </div>

  </div>
  <div style="position:absolute;bottom:0;left:0;right:0;line-height:0;pointer-events:none;">
    <svg viewBox="0 0 1440 40" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M0,20 C360,40 720,0 1440,20 L1440,40 L0,40 Z" fill="#f7f9fc"/></svg>
  </div>
</section>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: FORECAST HYDROGRAPH
# ══════════════════════════════════════════════════════════════════════════════

def _generate_forecast_hydrograph(history: list, glofas: dict, ref_2024) -> str:
    """
    v7.7: Генерирует ДВА отдельных графика:
    Блок 1 — уровень воды (см) Серпухова с НЯ/ОЯ и рефом 2024.
    Блок 2 — расход воды GloFAS (м³/с) отдельно.
    Между блоками — пояснение что величины разные.
    """
    # История Серпухова — последние 30 точек
    hist_pts = []
    for row in history[-30:]:
        val = row.get("serp_level_cm")
        dt  = row.get("datetime", "")
        if val is not None and dt:
            try:
                hist_pts.append((dt[:19], float(val)))
            except (ValueError, TypeError):
                pass

    today_iso = datetime.now(timezone.utc).isoformat()[:19]

    # GloFAS прогноз — берём Таруса или Алексин
    glofas_pts = []
    glofas_station_name = "GloFAS"
    for slug in ["tarusa", "aleksin", "kaluga"]:
        st = (glofas or {}).get(slug, {})
        if st.get("source_status") != "ok":
            continue
        times    = st.get("time", [])
        discharge = st.get("discharge", [])
        if not times or not discharge:
            continue
        today_date = today_iso[:10]
        for t, q in zip(times, discharge):
            if t > today_date and q is not None:
                glofas_pts.append((t, float(q)))
        if glofas_pts:
            glofas_station_name = st.get("name", slug.capitalize())
            break

    # 2024 ref
    ref_pts = []
    if ref_2024 and isinstance(ref_2024, list):
        for row in ref_2024[-30:]:
            v = row.get("serp_level_cm") or row.get("serpukhov")
            d = row.get("datetime", "")
            if v is not None and d:
                try:
                    ref_pts.append((d[:10], float(v)))
                except (ValueError, TypeError):
                    pass

    # Пороги в см от нуля поста
    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)

    # --- Блок 1: Level chart data ---
    hist_labels   = json.dumps([p[0] for p in hist_pts])
    hist_values   = json.dumps([p[1] for p in hist_pts])
    ref_labels    = json.dumps([p[0] for p in ref_pts])
    ref_values    = json.dumps([p[1] for p in ref_pts])
    nya_val       = json.dumps(round(nya_cm, 1))
    oya_val       = json.dumps(round(oya_cm, 1))

    # --- Блок 2: GloFAS discharge chart data ---
    glofas_labels = json.dumps([p[0] for p in glofas_pts])
    glofas_values = json.dumps([p[1] for p in glofas_pts])

    # Helper: X-axis tick formatter (reused in both charts)
    tick_callback_js = """function(value, index) {{
              var lbl = this.getLabelForValue(value);
              if (!lbl) return '';
              if (lbl.length > 10) {{
                var dt = new Date(lbl + 'Z');
                var now = new Date();
                var diffDays = (now - dt) / 86400000;
                if (diffDays < 2) {{
                  return String(dt.getUTCHours()).padStart(2,'0') + ':' + String(dt.getUTCMinutes()).padStart(2,'0');
                }} else {{
                  return dt.getUTCDate() + '.' + String(dt.getUTCMonth()+1).padStart(2,'0');
                }}
              }}
              var parts = lbl.split('-');
              return parts.length === 3 ? parts[2] + '.' + parts[1] : lbl;
            }}"""

    # ═════ Блок 2 (GloFAS) HTML — only if we have data ═════
    glofas_block = ""
    if glofas_pts:
        glofas_block = f"""
<p style="text-align:center; color:var(--text-dim); font-size:0.82rem; margin:12px 0;">
  \u26a0\ufe0f Графики показывают <b>разные величины</b>: верхний \u2014 уровень воды (см),
  нижний \u2014 прогноз расхода (м\xb3/с). Расход не равен уровню.
</p>

<section class="hydrograph-section fade-in-section">
  <div class="hydrograph-card">
    <h3>\U0001f30a Прогноз расхода воды (GloFAS)</h3>
    <div class="chart-container">
      <canvas id="hydrograph-glofas"></canvas>
    </div>
    <p style="font-size:0.75rem; color:var(--text-dim); margin-top:8px;">
      Расход воды по модели GloFAS (Copernicus). Не является прямым прогнозом уровня.
    </p>
  </div>
</section>

<script>
(function() {{
  var ctx2 = document.getElementById('hydrograph-glofas');
  if (!ctx2) return;

  var gLabels = {glofas_labels};
  var gValues = {glofas_values};

  new Chart(ctx2, {{
    type: 'line',
    data: {{
      labels: gLabels,
      datasets: [{{
        label: 'Расход GloFAS (м\xb3/с)',
        data: gValues,
        borderColor: '#a855f7',
        backgroundColor: 'rgba(168,85,247,0.08)',
        borderWidth: 2,
        borderDash: [6, 4],
        tension: 0.3,
        fill: true,
        pointRadius: 2,
        spanGaps: false,
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11, family: 'Inter' }} }} }},
        tooltip: {{
          backgroundColor: 'rgba(17,25,40,0.95)',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
        }},
      }},
      scales: {{
        x: {{
          ticks: {{
            color: '#64748b',
            maxTicksLimit: 10,
            maxRotation: 45,
            callback: {tick_callback_js}
          }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
        }},
        y: {{
          position: 'left',
          ticks: {{ color: '#a855f7' }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
          title: {{ display: true, text: 'Расход, м\xb3/с', color: '#a855f7', font: {{ size: 11 }} }},
        }},
      }},
    }},
  }});
}})();
</script>"""

    return f"""
<section class="hydrograph-section fade-in-section">
  <div class="hydrograph-card">
    <h3>\U0001f4c8 Уровень воды: история наблюдений</h3>
    <div class="chart-container">
      <canvas id="hydrograph-level"></canvas>
    </div>
  </div>
</section>

<script>
(function() {{
  var ctx = document.getElementById('hydrograph-level');
  if (!ctx) return;

  var histLabels = {hist_labels};
  var histValues = {hist_values};
  var refLabels  = {ref_labels};
  var refValues  = {ref_values};
  var NYA        = {nya_val};
  var OYA        = {oya_val};

  var datasets = [
    {{
      label: 'Уровень (см) \u2014 serpuhov.ru',
      data: histValues,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      borderWidth: 2.5,
      tension: 0.3,
      fill: true,
      pointRadius: 2,
      spanGaps: false,
    }}
  ];

  // 2024 ref — align to histLabels
  if (refLabels.length) {{
    var refMap = {{}};
    refLabels.forEach(function(l, i) {{ refMap[l] = refValues[i]; }});
    var refAligned = histLabels.map(function(l) {{
      var short = l.substring(0, 10);
      return refMap[short] !== undefined ? refMap[short] : null;
    }});
    if (refAligned.some(function(v) {{ return v !== null; }})) {{
      datasets.push({{
        label: '2024 (справочно)',
        data: refAligned,
        borderColor: 'rgba(100,116,139,0.5)',
        backgroundColor: 'transparent',
        borderDash: [3, 3],
        borderWidth: 1.5,
        tension: 0.3,
        fill: false,
        pointRadius: 0,
        spanGaps: false,
      }});
    }}
  }}

  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: histLabels, datasets: datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11, family: 'Inter' }} }} }},
        tooltip: {{
          backgroundColor: 'rgba(17,25,40,0.95)',
          borderColor: 'rgba(255,255,255,0.08)',
          borderWidth: 1,
          titleColor: '#f1f5f9',
          bodyColor: '#94a3b8',
        }},
        annotation: {{
          annotations: {{
            nyaLine: {{
              type: 'line', yMin: NYA, yMax: NYA,
              borderColor: '#f59e0b', borderWidth: 1.5, borderDash: [8, 4],
              label: {{ content: 'НЯ ' + NYA + ' см', display: true,
                        backgroundColor: 'rgba(245,158,11,0.15)', color: '#f59e0b',
                        font: {{ size: 10 }} }}
            }},
            oyaLine: {{
              type: 'line', yMin: OYA, yMax: OYA,
              borderColor: '#ef4444', borderWidth: 1.5, borderDash: [8, 4],
              label: {{ content: 'ОЯ ' + OYA + ' см', display: true,
                        backgroundColor: 'rgba(239,68,68,0.15)', color: '#ef4444',
                        font: {{ size: 10 }} }}
            }},
          }}
        }}
      }},
      scales: {{
        x: {{
          ticks: {{
            color: '#64748b',
            maxTicksLimit: 10,
            maxRotation: 45,
            callback: {tick_callback_js}
          }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
        }},
        y: {{
          position: 'left',
          ticks: {{ color: '#64748b' }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
          title: {{ display: true, text: 'Уровень, см', color: '#64748b', font: {{ size: 11 }} }},
        }},
      }},
    }},
  }});
}})();
</script>

{glofas_block}"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: STATION CARDS v7
# ══════════════════════════════════════════════════════════════════════════════

def _generate_station_cards_v7(data: dict, glofas: dict, history: list) -> str:
    """
    Генерирует горизонтально-скроллируемые карточки станций с GloFAS-данными.
    Порядок: Орёл → Мценск → Белёв → Калуга → Алексин → Таруса → СЕРПУХОВ → Кашира
    """
    serp = data.get("serpuhov", {})
    kim  = data.get("kim", {})

    CARD_ORDER = [
        ("orel",       False),
        ("mtsensk",    False),
        ("belev",      False),
        ("kaluga",     False),
        ("aleksin",    False),
        ("tarusa",     False),
        ("serpuhov",   True),
        ("kashira",    False),
    ]

    WAVE_LABELS = {
        "orel":       "7 дн до Серпухова",
        "mtsensk":    "5–6 дн до Серпухова",
        "belev":      "4–5 дн до Серпухова",
        "kaluga":     "2–3 дн до Серпухова",
        "aleksin":    "1–2 дн до Серпухова",
        "tarusa":     "0.5–1 дн до Серпухова",
        "serpuhov":   "",
        "kashira":    "↓ ниже по течению",
    }

    def _flood_ratio_class(fr):
        if fr is None: return "fr-unknown"
        if fr >= 3:    return "fr-danger"
        if fr >= 2:    return "fr-warning"
        if fr >= 1.5:  return "fr-watch"
        return               "fr-normal"

    def _flood_ratio_label(fr):
        if fr is None: return "—"
        return f"×{fr:.1f}"

    def _sparkline_color(fr):
        if fr is None: return "#3b82f6"
        if fr >= 3:    return "#ef4444"
        if fr >= 2:    return "#f97316"
        if fr >= 1.5:  return "#f59e0b"
        return                "#10b981"

    glofas_fetch_date = ""
    for _slug in ["belev", "kaluga", "tarusa"]:
        _st = (glofas or {}).get(_slug, {})
        if _st.get("source_status") == "ok":
            _times = _st.get("time", [])
            if _times:
                try:
                    _last_t = sorted(t for t in _times if t)[-1]
                    glofas_fetch_date = _last_t[:10]
                except Exception:
                    pass
            if glofas_fetch_date:
                break
    glofas_badge = f' <span class="updated-badge">GloFAS {_h(glofas_fetch_date)}</span>' if glofas_fetch_date else ''

    html = '<section class="stations-section fade-in-section" id="glofas-section">\n'
    html += f'<h2>↑ Бассейн Оки по течению{glofas_badge}</h2>\n'
    html += '<p style="font-size:0.82rem; color:var(--text-secondary); margin:4px 0 12px;">'
    html += 'Карточки показывают <b>расход воды</b> (м³/с) по данным GloFAS — это объём воды, '
    html += 'проходящий через сечение реки за секунду. Чем больше расход, тем выше уровень воды. '
    html += 'Серпухов показывает <b>уровень</b> (см) по serpuhov.ru, т.к. GloFAS не имеет прямой станции.'
    html += '</p>\n'

    # v7.7: мини-линия убрана (дублировала нижние карточки)

    html += '<div class="station-cards-scroll">\n'

    for idx, (slug, is_main) in enumerate(CARD_ORDER):
        card_classes = "station-card"
        if is_main:
            card_classes += " main-station"

        if slug == "serpuhov":
            level_cm  = serp.get("level_cm")
            change_cm = serp.get("daily_change_cm")
            val_str   = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
            unit_str  = "см от нуля поста"
            trend_arr = _trend(change_cm)
            fr        = None
            fr_cls    = "fr-unknown"
            fr_label  = "serpuhov.ru"
            peak_str  = ""
            src_note  = "serpuhov.ru / Лукьяново"
            name      = "СЕРПУХОВ"
            river     = "р. Ока"

            # Sparkline из истории
            from_history = []
            for row in history[-7:]:
                v = row.get("serp_level_cm")
                if v is not None:
                    try:
                        from_history.append(float(v))
                    except (ValueError, TypeError):
                        pass
            sparkline = _svg_sparkline(from_history, color="#3b82f6") if len(from_history) >= 2 else ""

        elif slug == "kashira":
            kash      = (kim.get("kashira") or {})
            level_cm  = kash.get("level_cm")
            val_str   = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
            unit_str  = "см (КИМ)"
            trend_arr = "→"
            fr        = None
            fr_cls    = "fr-unknown"
            fr_label  = "КИМ API"
            peak_str  = ""
            sparkline = ""
            src_note  = "КИМ API"
            name      = "Кашира"
            river     = "р. Ока"

        else:
            # GloFAS-станция
            glofas_cfg = (GLOFAS_STATIONS or {}).get(slug, {})
            glofas_st  = (glofas or {}).get(slug, {})
            name  = glofas_st.get("name") or glofas_cfg.get("name", slug.capitalize())
            river = glofas_st.get("river") or glofas_cfg.get("river", "р. Ока")

            if glofas_st.get("source_status") == "ok":
                q_cur     = glofas_st.get("current_discharge")
                val_str   = f"{q_cur:.0f} м³/с" if q_cur is not None else "нет данных"
                unit_str  = "GloFAS / расход"
                trend_arr = glofas_st.get("trend_arrow", "→")
                fr        = glofas_st.get("flood_ratio")
                fr_cls    = _flood_ratio_class(fr)
                fr_label  = _flood_ratio_label(fr)

                peak_date = glofas_st.get("peak_date")
                peak_q    = glofas_st.get("peak_discharge")
                if peak_date and peak_q:
                    try:
                        pd_obj = datetime.strptime(peak_date, "%Y-%m-%d")
                        peak_str = f"пик {pd_obj.day}.{pd_obj.month:02d}: {peak_q:.0f} м³/с"
                    except Exception:
                        peak_str = f"пик {peak_date}: {peak_q:.0f} м³/с"
                else:
                    peak_str = ""

                # Sparkline 7 дней
                discharge  = glofas_st.get("discharge", [])
                time_arr   = glofas_st.get("time", [])
                today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                hist_vals  = [q for t, q in zip(time_arr, discharge)
                               if t <= today_date and q is not None][-7:]
                sc_color   = _sparkline_color(fr)
                sparkline  = _svg_sparkline(hist_vals, color=sc_color) if len(hist_vals) >= 2 else ""

                src_note  = "GloFAS Flood API"
                card_classes += f" {fr_cls}"
            else:
                # v7.7.2: сохраняем карточку с пометкой "временно недоступно"
                val_str   = "временно недоступно"
                unit_str  = "GloFAS"
                trend_arr = "?"
                fr        = None
                fr_cls    = "fr-unknown"
                fr_label  = "недоступно"
                peak_str  = ""
                sparkline = ""
                src_note  = "Данные временно недоступны (GloFAS rate limit). Обычно обновляются в течение суток."

        wave_label = WAVE_LABELS.get(slug, "")

        # v7.3: city page links
        city_href = f"cities/{slug}.html"
        city_tooltip = "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0430\u044f \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u0433\u043e\u0440\u043e\u0434\u0430 (\u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435)"

        # v7.7: словесные подписи для трендов
        trend_word = ""
        if trend_arr == "\u2191":
            trend_word = " \u0440\u0430\u0441\u0442\u0451\u0442"
        elif trend_arr == "\u2191\u2191":
            trend_word = " \u0443\u0441\u043a\u043e\u0440\u044f\u0435\u0442\u0441\u044f"
        elif trend_arr == "\u2193":
            trend_word = " \u0441\u043d\u0438\u0436\u0430\u0435\u0442\u0441\u044f"
        elif "0.9" in str(trend_arr) or "\u00d70" in str(trend_arr):
            trend_word = " \u0437\u0430\u043c\u0435\u0434\u043b\u0435\u043d\u0438\u0435"

        # v7.7: пояс\u043d\u0435\u043d\u0438\u0435 е\u0434\u0438\u043d\u0438\u0446 и\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u044f
        unit_explain = ""
        if slug == "serpuhov":
            unit_explain = '<div style="font-size:0.65rem; color:var(--text-dim); margin-top:2px; line-height:1.3;">\u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432: \u0434\u0430\u043d\u043d\u044b\u0435 serpuhov.ru \u0432 \u0441\u0430\u043d\u0442\u0438\u043c\u0435\u0442\u0440\u0430\u0445 \u0443\u0440\u043e\u0432\u043d\u044f (\u043d\u0435 \u0440\u0430\u0441\u0445\u043e\u0434). GloFAS \u043d\u0435 \u0438\u043c\u0435\u0435\u0442 \u043f\u0440\u044f\u043c\u043e\u0439 \u0441\u0442\u0430\u043d\u0446\u0438\u0438 \u0434\u043b\u044f \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432\u0430.</div>'
        elif slug != "kashira" and unit_str == "GloFAS / \u0440\u0430\u0441\u0445\u043e\u0434":
            unit_explain = '<div style="font-size:0.65rem; color:var(--text-dim); margin-top:2px;">\u0440\u0430\u0441\u0445\u043e\u0434 \u0432\u043e\u0434\u044b (\u043e\u0431\u044a\u0451\u043c, \u043f\u0440\u043e\u0442\u0435\u043a\u0430\u044e\u0449\u0438\u0439 \u0447\u0435\u0440\u0435\u0437 \u0441\u0435\u0447\u0435\u043d\u0438\u0435 \u0440\u0435\u043a\u0438 \u0437\u0430 1 \u0441\u0435\u043a)</div>'

        # v7.7: \u043f\u0438\u043a \u0441 \u043f\u043e\u043b\u043d\u043e\u0439 \u043f\u043e\u0434\u043f\u0438\u0441\u044c\u044e
        peak_display = ""
        if peak_str:
            peak_display = f'<div class="sc-peak">\u0440\u0430\u0441\u0447\u0451\u0442\u043d\u044b\u0439 {_h(peak_str)}</div>'

        spark_label = '<div style="font-size:0.58rem; color:var(--text-dim); text-align:center;">\u0434\u0438\u043d\u0430\u043c\u0438\u043a\u0430 \u0437\u0430 14 \u0434\u043d\u0435\u0439</div>' if sparkline else ''

        # v7.7.2: подпись источника под карточкой
        src_note_html = f'<div style="font-size:0.6rem; color:var(--text-dim); margin-top:4px; line-height:1.3;">{_h(src_note)}</div>' if src_note else ''

        card_inner = f"""
<div class="{card_classes}">
  <div class="sc-name">{_h(name)}</div>
  <div class="sc-river">{_h(river)}</div>
  <div class="sc-value" style="color: {'var(--accent)' if is_main else 'var(--text-primary)'};">\n    {_h(val_str)}\n  </div>
  {unit_explain}
  <div class="sc-sparkline">{sparkline}</div>
  {spark_label}
  <div class="sc-trend">
    {_h(trend_arr)}{_h(trend_word)}
    <span class="sc-badge {fr_cls}">{_h(fr_label)}</span>
  </div>
  {peak_display}
  {f'<div class="sc-travel">{_h(wave_label)}</div>' if wave_label else ''}
  {src_note_html}
</div>
"""
        if not is_main:
            html += f'<a href="{city_href}" style="text-decoration:none; color:inherit;" data-tooltip="{city_tooltip}">'
            html += card_inner
            html += '</a>\n'
        else:
            html += card_inner

        if slug != "kashira":
            html += '<div class="station-arrow">›</div>\n'

    html += '</div>\n'

    # v7.7: Аналитический вывод под блоком карточек
    analytics_parts = []
    # Собираем данные станций
    station_discharges = []
    upstream_growth = []
    midstream_stable = []
    peak_date_str = ""
    for _s, _ in CARD_ORDER:
        _gst = (glofas or {}).get(_s, {})
        if _gst.get("source_status") == "ok":
            _qcur = _gst.get("current_discharge")
            _nm = _gst.get("name", _s.capitalize())
            if _qcur is not None:
                station_discharges.append((_nm, _qcur))
            _pk = _gst.get("peak_date", "")
            if _pk and not peak_date_str:
                try:
                    _pd = datetime.strptime(_pk, "%Y-%m-%d")
                    peak_date_str = f"{_pd.day:02d}.{_pd.month:02d}"
                except Exception:
                    pass
    if station_discharges:
        vals = ", ".join(f"{n}: {q:.0f}" for n, q in station_discharges[:3])
        analytics_parts.append(f"\u0412\u0435\u0440\u0445\u043e\u0432\u044c\u044f: {vals} \u043c\u00b3/\u0441")
    if peak_date_str:
        analytics_parts.append(f"\u0420\u0430\u0441\u0447\u0451\u0442\u043d\u044b\u0439 \u043f\u0438\u043a \u2014 {peak_date_str}")
    analytics_parts.append("\u0412\u043e\u043b\u043d\u0430 \u043e\u0442 \u0432\u0435\u0440\u0445\u043e\u0432\u0438\u0439 \u0434\u0432\u0438\u0436\u0435\u0442\u0441\u044f \u0432\u043d\u0438\u0437 \u043f\u043e \u0442\u0435\u0447\u0435\u043d\u0438\u044e. \u041e\u0436\u0438\u0434\u0430\u0435\u043c\u044b\u0439 \u0440\u043e\u0441\u0442 \u0443 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432\u0430 \u2014 \u0432 \u0431\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0435 3\u20135 \u0434\u043d\u0435\u0439.")
    analytics_text = ". ".join(analytics_parts)
    html += f'<div style="background:rgba(59,130,246,0.06); border:1px solid rgba(59,130,246,0.15); border-radius:10px; padding:12px 16px; margin:16px 0 8px; font-size:0.85rem; color:var(--text-secondary); line-height:1.6;">\n'
    html += f'  \U0001f4ca <b>\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430:</b> {_h(analytics_text)}\n'
    html += '</div>\n'

    # v7.7.2: Примечание об источниках данных
    html += '<p style="font-size:0.75rem; color:var(--text-dim); margin:12px 0 4px; line-height:1.5; font-style:italic;">'
    html += 'Примечание: для Серпухова GloFAS не имеет прямой станции. Данные уровня — с гидропоста Лукьяново (serpuhov.ru). Для Каширы — КИМ API (нестабильно).'
    html += '</p>\n'

    # v7.6.1: Satellite monitoring image
    _sat_b64 = NEW_IMAGES_B64.get('satellite_monitoring', '')
    if _sat_b64:
        html += '<div style="margin:20px 0 8px; text-align:center;">\n'
        html += f'<img src="data:image/jpeg;base64,{_sat_b64}" alt="Спутниковый мониторинг" style="width:100%; max-width:700px; border-radius:12px; margin:8px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">\n'
        html += '<div style="font-size:0.78rem; color:var(--text-dim); margin-top:4px; font-style:italic;">Спутниковый мониторинг: GloFAS отслеживает расходы воды через систему Copernicus</div>\n'
        html += '</div>\n'

    html += '</section>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# HTML: WAVE ARRIVAL TIMELINE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_wave_timeline(glofas: dict) -> str:
    """
    v7.7: Горизонтальная река-лента (как линия метро) + детальная таблица.
    Ось X = километры от истока. Каждый город — кружок на линии.
    """
    if not glofas or glofas.get("_status") not in ("ok", "partial", "cached"):
        return ""

    today = datetime.now(timezone.utc).date()

    # Города с км от истока
    RIVER_CITIES = [
        ("orel",      "Орёл",      0,   False),
        ("mtsensk",   "Мценск",    115, False),
        ("belev",     "Белёв",     213, False),
        ("kozelsk",   "Козельск",  272, False),
        ("kaluga",    "Калуга",    348, False),
        ("aleksin",   "Алексин",   419, False),
        ("tarusa",    "Таруса",    465, False),
        ("serpukhov", "Серпухов",  517, True),
        ("zhernivka", "Жерновка",  545, True),
        ("kashira",   "Кашира",    570, False),
        ("kolomna",   "Коломна",   645, False),
    ]
    max_km = 645

    STATION_ORDER = ["orel", "mtsensk", "belev", "kozelsk", "kaluga", "aleksin", "tarusa", "serpukhov"]
    latest_arrival_dt = None
    rows = []

    for slug in STATION_ORDER:
        is_serpukhov = (slug == "serpukhov")
        if is_serpukhov:
            name = "СЕРПУХОВ"
            peak_str = ""
            arr_str = ""
            to_zhern = ""
            if latest_arrival_dt:
                arr_str = f"{latest_arrival_dt.day:02d}.{latest_arrival_dt.month:02d}"
                to_zhern = f"~{(latest_arrival_dt + timedelta(days=1)).day:02d}\u2013{(latest_arrival_dt + timedelta(days=2)).day:02d}.{(latest_arrival_dt + timedelta(days=1)).month:02d}"
        else:
            st = glofas.get(slug, {})
            if not st:
                continue
            name = st.get("name", slug.capitalize())
            peak_date = st.get("peak_date")
            wave = st.get("wave_arrival_serpukhov")
            peak_str = ""
            arr_str = ""
            to_zhern = ""
            if peak_date:
                try:
                    pd_obj = datetime.strptime(peak_date, "%Y-%m-%d").date()
                    peak_str = f"{pd_obj.day:02d}.{pd_obj.month:02d}"
                except Exception:
                    peak_str = peak_date[:10]
            if wave:
                try:
                    arr_dt = datetime.strptime(wave["earliest"], "%Y-%m-%d").date()
                    arr_late = datetime.strptime(wave["latest"], "%Y-%m-%d").date()
                    arr_str = f"{arr_dt.day:02d}.{arr_dt.month:02d}\u2013{arr_late.day:02d}.{arr_late.month:02d}"
                    zhern_dt = arr_late + timedelta(days=1)
                    to_zhern = f"~{arr_late.day:02d}\u2013{zhern_dt.day:02d}.{zhern_dt.month:02d}"
                    if latest_arrival_dt is None or arr_dt > latest_arrival_dt:
                        latest_arrival_dt = arr_dt
                except Exception:
                    arr_str = wave.get("earliest", "?")[:10]

        rows.append({"name": name, "peak_str": peak_str, "arr_str": arr_str,
                     "to_zhern": to_zhern, "is_dest": is_serpukhov})

    if not rows:
        return ""

    # ── Горизонтальная река-лента (SVG-стиль линия метро) ────────────────
    dots_html = ""
    for idx, (slug, city_name, km, is_highlight) in enumerate(RIVER_CITIES):
        pct = km / max_km * 100
        dot_color = "#ef4444" if is_highlight else "#3b82f6"
        dot_size = "14px" if is_highlight else "10px"
        fw = "700" if is_highlight else "500"
        # Получим пик/дату для подписи снизу
        sub_info = ""
        st = glofas.get(slug, {})
        if st and slug not in ("serpukhov", "zhernivka", "kashira", "kolomna"):
            pk = st.get("peak_date", "")
            if pk:
                try:
                    pd_obj = datetime.strptime(pk, "%Y-%m-%d").date()
                    sub_info = f"пик {pd_obj.day:02d}.{pd_obj.month:02d}"
                except Exception:
                    sub_info = pk[:10]
        elif slug == "serpukhov":
            # v7.7.2: peak date under Серпухов label
            if latest_arrival_dt:
                sub_info = f"пик ~{latest_arrival_dt.day:02d}.{latest_arrival_dt.month:02d}"
            else:
                sub_info = "гидропост"
        elif slug == "zhernivka":
            # v7.7.2: peak date under Жерновка label
            if latest_arrival_dt:
                _zhern_dt1 = latest_arrival_dt + timedelta(days=1)
                _zhern_dt2 = latest_arrival_dt + timedelta(days=2)
                sub_info = f"пик ~{_zhern_dt1.day:02d}\u2013{_zhern_dt2.day:02d}.{_zhern_dt1.month:02d}"
            else:
                sub_info = "~7ч от Лукьяново"

        # v7.7.1: Улучшенное разнесение подписей — Серпухов/Жерновка разнесены вертикально
        if slug == "serpukhov":
            # Серпухов — подпись сверху, доп-инфо снизу
            name_top = f'<div style="position:absolute; bottom:26px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.68rem; font-weight:{fw}; color:{dot_color};">{_h(city_name)}</div>'
            info_top = f'<div style="position:absolute; bottom:40px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.58rem; color:var(--text-dim);">{_h(sub_info)}</div>' if sub_info else ""
        elif slug == "zhernivka":
            # Жерновка — подпись снизу, доп-инфо ещё ниже
            name_top = f'<div style="position:absolute; top:22px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.68rem; font-weight:{fw}; color:{dot_color};">{_h(city_name)}</div>'
            info_top = f'<div style="position:absolute; top:36px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.58rem; color:var(--text-dim);">{_h(sub_info)}</div>' if sub_info else ""
        elif idx % 2 == 0:
            name_top = f'<div style="position:absolute; bottom:22px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.68rem; font-weight:{fw}; color:{dot_color};">{_h(city_name)}</div>'
            info_top = f'<div style="position:absolute; top:22px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.58rem; color:var(--text-dim);">{_h(sub_info)}</div>' if sub_info else ""
        else:
            name_top = f'<div style="position:absolute; top:22px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.68rem; font-weight:{fw}; color:{dot_color};">{_h(city_name)}</div>'
            info_top = f'<div style="position:absolute; bottom:22px; left:50%; transform:translateX(-50%); white-space:nowrap; font-size:0.58rem; color:var(--text-dim);">{_h(sub_info)}</div>' if sub_info else ""

        dots_html += f"""<div style="position:absolute; left:{pct:.1f}%; top:50%; transform:translate(-50%,-50%);">
  <div style="width:{dot_size}; height:{dot_size}; border-radius:50%; background:{dot_color}; border:2px solid #fff; box-shadow:0 1px 4px rgba(0,0,0,0.15);"></div>
  {name_top}
  {info_top}
</div>"""

    # Таблица
    table_rows_html = ""
    for row in rows:
        peak_disp = _h(row["peak_str"]) if row["peak_str"] else '<span style="color:var(--text-dim)">\u2014</span>'
        arr_disp = _h(row["arr_str"]) if row["arr_str"] else '<span style="color:var(--text-dim)">\u2014</span>'
        zhern_disp = _h(row["to_zhern"]) if row["to_zhern"] else '<span style="color:var(--text-dim)">\u2014</span>'
        is_dest_row = row.get("is_dest", False)
        name_cell = f'<b style="color:#ef4444;">{_h(row["name"])}</b>' if is_dest_row else _h(row["name"])
        tr_style = ' style="background:rgba(239,68,68,0.06);"' if is_dest_row else ""
        table_rows_html += f"""<tr{tr_style}><td class="col-station">{name_cell}</td><td>{peak_disp}</td><td class="col-arrival">{arr_disp}</td><td style="color:var(--text-dim);">{zhern_disp}</td></tr>"""

    return f"""
<section class="timeline-section fade-in-section">
  <div class="timeline-card">
    <h3>\u23f1 Прогноз прихода волны в Серпухов</h3>

    <!-- v7.7: Горизонтальная река-лента -->
    <div style="overflow-x:auto; margin:16px 0 40px; padding:0 8px;">
      <div style="position:relative; min-width:700px; height:160px;">
        <div style="position:absolute; left:0; right:0; top:50%; height:4px; background:linear-gradient(90deg, #3b82f6 0%, #3b82f6 79%, #ef4444 79%, #ef4444 85%, #3b82f6 85%, #3b82f6 100%); border-radius:2px; transform:translateY(-50%);"></div>
        {dots_html}
      </div>
    </div>

    <p style="font-size:0.78rem; color:var(--text-dim); margin:4px 0 16px; line-height:1.6;">
      Расстояния: от гидропоста Лукьяново до Серпухова ~2 км, от Серпухова до Пущино ~30 км, от Пущино до Жерновки ~8 км.
      Скорость волны 3\u20135 км/ч, задержка ~7 ч от Лукьяново до Жерновки.
    </p>

    <p style="font-size:0.88rem; color:var(--text-secondary); margin-bottom:12px;">
      <b>GloFAS</b> (Global Flood Awareness System) \u2014 европейская система раннего
      предупреждения о наводнениях, часть программы Copernicus.
    </p>

    <div class="table-wrap">
    <table class="wave-table">
      <thead>
        <tr>
          <th>Станция</th>
          <th>Пик на станции</th>
          <th>Прибытие в Серпухов</th>
          <th>Прибытие в Жерновку*</th>
        </tr>
      </thead>
      <tbody>
        {table_rows_html}
      </tbody>
    </table>
    </div>
    <p style="font-size:0.72rem; color:var(--text-dim); margin-top:8px;">
      * Жерновка расположена на ~40 км ниже гидропоста Лукьяново (ниже Серпухова). Волна доходит до Жерновки примерно через 1 сутки после прибытия в Серпухов.<br>
      Данные GloFAS Flood API. Погрешность \u00b11\u20132 дня.
    </p>
  </div>
</section>"""



# ══════════════════════════════════════════════════════════════════════════════
# HTML: ACTION SECTION
# ══════════════════════════════════════════════════════════════════════════════

def _generate_action_section(icon: str, title: str, text: str, color: str) -> str:
    """Генерирует action block в glassmorphism стиле. v7.2: поддерживает HTML в тексте."""
    return f"""
<section class="action-section" id="vigilance-section">
  <div class="action-card" style="border-left-color: {color};">
    <div class="action-icon">{icon}</div>
    <div class="action-title" style="color: {color};">{_h(title)}</div>
    <div class="action-text">{text}</div>
  </div>
</section>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: WEATHER SECTION
# ══════════════════════════════════════════════════════════════════════════════

def _generate_weather_section(wext, weather_multi_data=None) -> str:
    """Генерирует секцию погоды с glassmorphism стилем."""
    if not wext:
        return ""

    fl_idx     = wext.get("flood_index", 0)
    fl_label   = _h(wext.get("flood_label", "?"))
    fl_summary = _h(wext.get("flood_summary", ""))
    fl_colors  = {0: "#10b981", 1: "#10b981", 2: "#f59e0b", 3: "#f97316", 4: "#ef4444"}
    fl_color   = fl_colors.get(fl_idx, "#64748b")
    snow_d     = wext.get("snow_depth_cm", 0) or 0

    # v7.7: таблица критериев индекса
    criteria_table = """
<div class="table-wrap">
<table style="width:100%; border-collapse:collapse; font-size:0.78rem; margin:10px 0 6px;">
  <tr style="background:#f0fdf4;"><td style="padding:4px 8px; border:1px solid var(--border); font-weight:600; color:#10b981;">0 \u2014 \u041d\u043e\u0440\u043c\u0430</td><td style="padding:4px 8px; border:1px solid var(--border); color:var(--text-secondary);">\u0421\u043d\u0435\u0433 &lt; 5 \u0441\u043c, \u043e\u0441\u0430\u0434\u043a\u0438 \u043c\u0438\u043d\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0435, \u043d\u043e\u0447\u0438 \u0445\u043e\u043b\u043e\u0434\u043d\u044b\u0435</td></tr>
  <tr style="background:#fefce8;"><td style="padding:4px 8px; border:1px solid var(--border); font-weight:600; color:#10b981;">1 \u2014 \u0412\u043d\u0438\u043c\u0430\u043d\u0438\u0435</td><td style="padding:4px 8px; border:1px solid var(--border); color:var(--text-secondary);">\u041d\u0430\u0447\u0430\u043b\u043e \u0442\u0430\u044f\u043d\u0438\u044f, \u0434\u043d\u0435\u0432\u043d\u044b\u0435 \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b &gt; 5\u00b0C</td></tr>
  <tr style="background:#fff7ed;"><td style="padding:4px 8px; border:1px solid var(--border); font-weight:600; color:#f59e0b;">2 \u2014 \u041f\u043e\u0432\u044b\u0448\u0435\u043d\u043d\u044b\u0439</td><td style="padding:4px 8px; border:1px solid var(--border); color:var(--text-secondary);">\u0410\u043a\u0442\u0438\u0432\u043d\u043e\u0435 \u0442\u0430\u044f\u043d\u0438\u0435, \u0441\u043d\u0435\u0433 5\u201315 \u0441\u043c, \u043e\u0441\u0430\u0434\u043a\u0438</td></tr>
  <tr style="background:#fff1f2;"><td style="padding:4px 8px; border:1px solid var(--border); font-weight:600; color:#f97316;">3 \u2014 \u0412\u044b\u0441\u043e\u043a\u0438\u0439</td><td style="padding:4px 8px; border:1px solid var(--border); color:var(--text-secondary);">\u0411\u044b\u0441\u0442\u0440\u043e\u0435 \u0442\u0430\u044f\u043d\u0438\u0435, \u043e\u0441\u0430\u0434\u043a\u0438 &gt; 5 \u043c\u043c/\u0441\u0443\u0442, \u0442\u0451\u043f\u043b\u044b\u0435 \u043d\u043e\u0447\u0438</td></tr>
  <tr style="background:#fef2f2;"><td style="padding:4px 8px; border:1px solid var(--border); font-weight:600; color:#ef4444;">4 \u2014 \u041a\u0420\u0418\u0422\u0418\u0427\u0415\u0421\u041a\u0418\u0419</td><td style="padding:4px 8px; border:1px solid var(--border); color:var(--text-secondary);">\u0421\u043d\u0435\u0433 \u0442\u0430\u0435\u0442 \u043a\u0440\u0443\u0433\u043b\u043e\u0441\u0443\u0442\u043e\u0447\u043d\u043e, \u0432\u0441\u0435 \u043d\u043e\u0447\u0438 &gt; 0\u00b0C, \u0434\u043e\u0436\u0434\u044c \u043d\u0430 \u0441\u043d\u0435\u0433</td></tr>
</table>
</div>"""

    flood_index_block = f"""
<div class="weather-flood-index" style="border-left-color:{fl_color};">
  <div>
    <span class="wfi-label">Паводковый индекс погоды (0–4)</span>
    <span class="wfi-value" style="color:{fl_color};">{fl_label} ({fl_idx}/4)</span>
  </div>
  <div class="wfi-summary">{fl_summary}</div>
  {criteria_table}
  <div style="font-size:0.82rem; color:var(--text-dim);">Глубина снега (локально): {snow_d:.0f} см — глубина снежного покрова по Open-Meteo (не SWE)</div>
</div>"""

    weather_table_html = _generate_weather_table(wext)

    commentary = wext.get("commentary", [])
    # v7.7.1: убираем дубли про ночные температуры и круглосуточное таяние — объединяем в одну строку
    if commentary:
        night_thaw_phrases = [
            "тает круглосуточно", "ночи тёплые", "ночные температуры устойчиво",
            "ночи теплеют", "ускорение таяния", "все ночи тёплые",
            "снег тает круглосуточно", "таяние ускоряется",
        ]
        seen_keys = set()
        deduped = []
        night_thaw_found = False
        for c in commentary:
            norm = c.lower().strip()
            is_night_thaw = any(phrase in norm for phrase in night_thaw_phrases)
            if is_night_thaw:
                if not night_thaw_found:
                    night_thaw_found = True
                    deduped.append("🌡 Ночные температуры устойчиво выше нуля (теплеют). Снег тает круглосуточно, таяние ускоряется.")
                # skip duplicates
            else:
                key = norm
                if key not in seen_keys:
                    deduped.append(c)
                    seen_keys.add(key)
        commentary = deduped
    # v7.7.2: добавляем "в районе Серпухова" к упоминаниям осадков
    _precip_keywords = ["дождь", "осадк", "rain-on-snow", "мм)"]
    if commentary:
        _updated_commentary = []
        for c in commentary:
            c_lower = c.lower()
            if any(kw in c_lower for kw in _precip_keywords) and "серпухов" not in c_lower:
                # Добавляем географию перед закрывающим знаком
                if c.endswith("!"):
                    c = c[:-1] + " в районе Серпухова!"
                elif c.endswith("."):
                    c = c[:-1] + " в районе Серпухова."
                else:
                    c = c + " в районе Серпухова"
            _updated_commentary.append(c)
        commentary = _updated_commentary
    # v7.7.2: Матрица осадков по бассейну
    precip_matrix_html = ""
    if generate_precip_matrix_html and weather_multi_data:
        precip_matrix_html = generate_precip_matrix_html(weather_multi_data)
    
    commentary_html = ""
    if commentary:
        items = "\n".join(f"<li style='padding:4px 0; color:var(--text-secondary); font-size:0.88rem;'>{_h(c)}</li>" for c in commentary)
        commentary_html = f"""
<div style="margin-top:12px;">
  <div style="font-size:0.85rem; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">📝 Аналитика погодных факторов</div>
  <ul style="list-style:none; padding:0;">{items}</ul>
</div>"""

    # v7.6: Синхронизация снега в commentary с актуальным значением
    import re as _re_snow
    if commentary_html and snow_d > 0:
        commentary_html = _re_snow.sub(
            r'Снежный покров: \d+ см',
            f'Снежный покров: {snow_d:.0f} см',
            commentary_html
        )

    # v7.3: date badge for weather
    wx_date_badge = ""
    wx_days = wext.get("days", []) if wext else []
    if wx_days:
        try:
            first_forecast = next((d for d in wx_days if d.get("is_forecast")), wx_days[0])
            wx_date = first_forecast.get("date", "")
            if wx_date:
                wx_date_badge = f' <span class="updated-badge">{_h(wx_date[:10])}</span>'
        except Exception:
            pass

    return f"""
<section class="weather-section fade-in-section">
  <div class="accordion-header" onclick="toggleAccordion('weatherAcc')">
    ☁️ Погода и паводковый индекс{wx_date_badge}
    <span class="toggle-icon" id="weatherAcc-icon">▼</span>
  </div>
  <div class="accordion-body" id="weatherAcc" style="border-radius: 0 0 12px 12px;">
    {flood_index_block}
    <div class="table-wrap">{weather_table_html}</div>
    {commentary_html}
    {precip_matrix_html}
    <p style="font-size:0.75rem; color:var(--text-dim); margin:12px 0 4px; line-height:1.5; font-style:italic;">Источник: Open-Meteo API (координаты Серпухова). Прогноз осадков для верховий (Орёл, Калуга) может отличаться.</p>
    <div style="margin:20px 0 8px; text-align:center;">
      <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('snowmelt_spring', '')}" alt="Весеннее снеготаяние" style="width:100%; max-width:700px; border-radius:12px; margin:8px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      <div style="font-size:0.78rem; color:var(--text-dim); margin-top:4px; font-style:italic;">Весеннее снеготаяние — начало половодья</div>
    </div>
  </div>
</section>"""


def _generate_weather_table(wext) -> str:
    """Генерирует таблицу прогноза погоды."""
    if not wext:
        return ""

    days = wext.get("days", [])
    if not days:
        return ""

    header_cells = ""
    tmax_cells = tmin_cells = precip_cells = snow_cells = wind_cells = desc_cells = ""

    for d in days:
        is_fc   = d.get("is_forecast", False)
        fc_cls  = " forecast-col" if is_fc else ""
        date_str = d.get("date", "")
        try:
            dt_obj   = datetime.strptime(date_str, "%Y-%m-%d")
            date_fmt = dt_obj.strftime("%d.%m")
            dow      = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][dt_obj.weekday()]
            label    = f"{dow} {date_fmt}"
        except ValueError:
            label = date_str

        header_cells += f'<th class="{fc_cls}">{_h(label)}</th>'

        tmax   = d.get("tmax")
        tmin   = d.get("tmin")
        precip = d.get("precip") or 0
        snow   = d.get("snowfall_cm") or 0
        wind   = d.get("wind_ms") or 0
        code   = d.get("weather_code")

        def tmax_cls_fn(v):
            if v is None: return ""
            if v >= 25: return ' class="hot"'
            return ""

        def tmin_cls_fn(v):
            if v is None: return ""
            if v < -5: return ' class="frost"'
            if -5 <= v < 0: return ' class="zero"'
            if v >= 2: return ' class="warm-night"'
            return ""

        tmax_str  = f"{tmax:.0f}°" if tmax is not None else "?"
        tmin_str  = f"{tmin:.0f}°" if tmin is not None else "?"
        pre_str   = f"{precip:.1f}"
        snow_str  = f"{snow:.0f}"
        wind_str  = f"{wind:.0f}"
        desc_str  = _weather_code_to_desc(code)

        tmax_cells   += f'<td class="{fc_cls}"{tmax_cls_fn(tmax)}>{tmax_str}</td>'
        tmin_cells   += f'<td class="{fc_cls}"{tmin_cls_fn(tmin)}>{tmin_str}</td>'
        precip_cells += f'<td class="{fc_cls}">{pre_str}</td>'
        snow_cells   += f'<td class="{fc_cls}">{snow_str}</td>'
        wind_cells   += f'<td class="{fc_cls}">{wind_str}</td>'
        desc_cells   += f'<td class="{fc_cls}">{_h(desc_str)}</td>'

    return f"""
<table class="weather-table">
  <thead>
    <tr><th>Показатель</th>{header_cells}</tr>
  </thead>
  <tbody>
    <tr><td>Тmax °C</td>{tmax_cells}</tr>
    <tr><td>Tmin °C</td>{tmin_cells}</tr>
    <tr><td>Осадки, мм</td>{precip_cells}</tr>
    <tr><td>Снег, см</td>{snow_cells}</tr>
    <tr><td>Ветер, м/с</td>{wind_cells}</tr>
    <tr><td>Погода</td>{desc_cells}</tr>
  </tbody>
</table>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: DETAIL SECTIONS (аккордеоны)
# ══════════════════════════════════════════════════════════════════════════════

def _generate_threshold_section(serp: dict, analytics: dict) -> str:
    """Генерирует секцию пороговых значений с вертикальной шкалой."""
    level_cm = serp.get("level_cm")
    abs_bs   = serp.get("abs_level_m_bs")

    if abs_bs is None and level_cm is not None:
        abs_bs = LUKYANNOVO_ZERO_M_BS + level_cm / 100.0

    total_range = LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS
    nya_pct = min(100, max(0, (LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) / total_range * 100))

    current_pct = 0.0
    if abs_bs is not None:
        current_pct = min(100, max(0, (abs_bs - LUKYANNOVO_ZERO_M_BS) / total_range * 100))

    def thresh_status(threshold_m_bs, current):
        if current is None:
            return "нет данных"
        if current >= threshold_m_bs:
            return "⚠️ ДОСТИГНУТ"
        delta = threshold_m_bs - current
        return f"не достигнут (до порога {delta:.2f} м)"

    bya_m_bs = LUKYANNOVO_ZERO_M_BS + AUTHOR_BYA_CM / 100.0  # 967 см → м БС
    nya_status = thresh_status(LUKYANNOVO_NYA_M_BS, abs_bs)
    oya_status = thresh_status(LUKYANNOVO_OYA_M_BS, abs_bs)
    bya_status = thresh_status(bya_m_bs, abs_bs)
    serp_abs_str = f"{abs_bs:.3f}" if abs_bs is not None else "?"
    cur_status   = f"{abs_bs:.3f} м БС" if abs_bs is not None else "нет данных"

    return f"""
<div class="threshold-scale-container">
  <div style="position:relative; width:200px; height:260px;
    background:linear-gradient(to top, #10b981 0%, #f59e0b 50%, #f97316 75%, #ef4444 90%, #a855f7 100%);
    border-radius:8px; overflow:visible; flex-shrink:0;">
    <div style="position:absolute; left:0; top:0; bottom:0; right:0;
      background:linear-gradient(to top, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.2) 100%); border-radius:8px;"></div>
    <!-- НЯ marker -->
    <div style="position:absolute; bottom:{nya_pct:.1f}%; left:0; right:0; display:flex; align-items:center; gap:4px; padding:0 8px;">
      <div style="height:2px; background:rgba(245,220,100,0.9); flex:1;"></div>
      <span style="font-size:0.65em; color:#fff; background:rgba(0,0,0,0.6); padding:1px 5px; border-radius:3px; white-space:nowrap;">НЯ {LUKYANNOVO_NYA_M_BS} м</span>
    </div>
    <!-- ОЯ marker -->
    <div style="position:absolute; bottom:96%; left:0; right:0; display:flex; align-items:center; gap:4px; padding:0 8px;">
      <div style="height:2px; background:rgba(255,100,100,0.9); flex:1;"></div>
      <span style="font-size:0.65em; color:#fff; background:rgba(0,0,0,0.6); padding:1px 5px; border-radius:3px; white-space:nowrap;">ОЯ {LUKYANNOVO_OYA_M_BS} м</span>
    </div>
    <!-- Текущий уровень -->
    <div style="position:absolute; bottom:{current_pct:.1f}%; left:-6px; right:-6px; height:4px; background:#3b82f6; box-shadow:0 0 8px #3b82f6; border-radius:2px;"></div>
    <div style="position:absolute; bottom:{current_pct:.1f}%; left:8px; transform:translateY(50%);">
      <span style="font-size:0.7em; color:#3b82f6; font-weight:700; background:rgba(0,0,0,0.7); padding:2px 6px; border-radius:3px; white-space:nowrap;">▶ {serp_abs_str} м БС</span>
    </div>
    <div style="position:absolute; bottom:2px; left:8px;">
      <span style="font-size:0.6em; color:rgba(255,255,255,0.6); white-space:nowrap;">Нуль ~{LUKYANNOVO_ZERO_M_BS} м</span>
    </div>
  </div>
  <div class="table-wrap">
  <table class="thresh-table">
    <thead><tr><th>Отметка</th><th>м БС</th><th>Значение</th><th>Статус</th></tr></thead>
    <tbody>
      <tr><td>Нуль поста</td><td>~{LUKYANNOVO_ZERO_M_BS}</td><td>База измерения</td><td>—</td></tr>
      <tr class="row-nya">
        <td>НЯ</td><td>{LUKYANNOVO_NYA_M_BS}</td>
        <td>Выход на пойму</td><td>{_h(nya_status)}</td>
      </tr>
      <tr class="row-oya">
        <td>ОЯ</td><td>{LUKYANNOVO_OYA_M_BS}</td>
        <td>Подтопление НП</td><td>{_h(oya_status)}</td>
      </tr>
      <tr style="background:rgba(168,85,247,0.06);">
        <td>БЯ</td><td>{bya_m_bs:.2f}</td>
        <td>967 см — предел защитной дамбы у дома автора проекта</td><td>{_h(bya_status)}</td>
      </tr>
      <tr class="row-current">
        <td><b>Текущий</b></td><td><b>{serp_abs_str}</b></td>
        <td>Прямо сейчас</td><td><b>{_h(cur_status)}</b></td>
      </tr>
    </tbody>
  </table>
  </div>
</div>
<p class="explainer">
  <b>НЯ</b> — неблагоприятное явление (выход воды на пойму).
  <b>ОЯ</b> — опасное явление (подтопление населённых пунктов).
  Пост д. Лукьяново — официальный наблюдательный пункт на р. Ока у г. Серпухова.
</p>"""


def _generate_cugms_section(cugms: dict) -> str:
    """Генерирует секцию обзора ЦУГМС."""
    status = cugms.get("source_status", "unavailable")

    if status == "unavailable" or not cugms.get("review_number"):
        return """
<div class="no-data">Данные ЦУГМС временно недоступны. Проверьте вручную:
  <a href="https://cugms.ru/gidrologiya/vesennee-polovode-i-dozhdevye-pavodki-2026/" target="_blank">
  cugms.ru</a>
</div>"""

    n          = cugms.get("review_number", "?")
    c_date     = _h(cugms.get("review_date", "?"))
    src_url    = cugms.get("source_url", "#")
    s_chg      = cugms.get("serpuhov_change_cm")
    k_chg      = cugms.get("kashira_change_cm")
    ko_chg     = cugms.get("kolomna_change_cm")
    ice_dict   = cugms.get("ice_status", {})
    forecast   = _h((cugms.get("forecast_text") or "")[:400])
    f_intens   = _h(cugms.get("forecast_intensity_mps") or "")
    dangerous  = cugms.get("dangerous_expected", False)

    s_chg_str  = f"{s_chg:+.0f} см/сут" if s_chg is not None else "нет данных"
    k_chg_str  = f"{k_chg:+.0f} см/сут" if k_chg is not None else "нет данных"
    kol_ice    = ice_dict.get("Коломна", "")
    kol_str    = kol_ice if kol_ice else (f"{ko_chg:+.0f} см/сут" if ko_chg is not None else "нет данных")

    danger_block = ""
    if dangerous:
        danger_block = '<div style="background:rgba(239,68,68,0.1); border-left:3px solid var(--danger); padding:8px 12px; border-radius:0 6px 6px 0; font-size:0.88rem; color:var(--danger); margin:8px 0;">⚠️ ЦУГМС: ожидаются опасные явления!</div>'

    status_badge = "cached" if status == "cached" else "ok"
    status_label = "(из кеша)" if status == "cached" else ""

    return f"""
<div class="cugms-meta">
  Обзор №{n} от {c_date}
  <span class="source-badge {status_badge}" style="margin-left:8px;">{status_label}</span>
  <a href="{_h(src_url)}" target="_blank" rel="noopener" style="margin-left:8px;">→ Полный текст</a>
</div>
{danger_block}
<div class="cugms-data">
  <div class="cugms-row">
    <span class="cugms-station">Серпухов:</span>
    <span class="cugms-value">{_h(s_chg_str)}</span>
  </div>
  <div class="cugms-row">
    <span class="cugms-station">Кашира:</span>
    <span class="cugms-value">{_h(k_chg_str)}</span>
  </div>
  <div class="cugms-row">
    <span class="cugms-station">Коломна:</span>
    <span class="cugms-value">{_h(kol_str)}</span>
  </div>
</div>
{f'<div class="cugms-forecast"><b>Прогноз ({_h(f_intens)}):</b> {forecast}</div>' if forecast else ""}
<p class="explainer">
  ЦУГМС публикует суточные приросты и качественные данные.
  Абсолютные уровни в см — платная услуга Росгидромета.
</p>"""


def _generate_peak_section(analytics: dict, regression) -> str:
    """Генерирует секцию прогноза пика."""
    peak = analytics.get("peak_prediction", {})
    if not peak:
        return ""

    trend      = peak.get("trend", "unknown")
    trend_text = _h(peak.get("trend_text", "Недостаточно данных"))
    disclaimer = _h(peak.get("disclaimer", ""))

    trend_colors = {
        "accelerating": "#ef4444",
        "decelerating": "#f59e0b",
        "stable":       "#94a3b8",
        "falling":      "#10b981",
        "unknown":      "#94a3b8",
    }
    trend_color = trend_colors.get(trend, "#94a3b8")

    reg = regression or (peak.get("regression") if peak else None)
    reg_block = ""
    if reg and reg.get("r_squared", 0) >= 0.5:
        r2        = reg.get("r_squared", 0)
        ml_text   = _h(reg.get("trend_text_ml", ""))
        pred3     = reg.get("pred_3d")
        pred7     = reg.get("pred_7d")
        peak_date = reg.get("peak_date")
        nya_cm    = reg.get("nya_cm", 645)
        pred3_str = f"{pred3:.0f}" if pred3 is not None else "?"
        pred7_str = f"{pred7:.0f}" if pred7 is not None else "?"
        peak_dt_str = (
            f"<p style='color:var(--text-secondary); margin:4px 0;'>При текущем темпе НЯ ({nya_cm:.0f} см) может быть достигнута ~{_h(peak_date)}</p>"
            if peak_date else ""
        )
        reg_block = f"""
<div class="regression-block">
  <div style="font-size:0.85rem; font-weight:600; color:var(--accent); margin-bottom:6px;">
    🤖 Линейная регрессия (R²={r2:.2f}, {reg.get('n_points', 0)} точек)
  </div>
  <p>{ml_text}</p>
  <p>Прогноз: через 3 дня ≈ <b>{pred3_str} см</b> | через 7 дней ≈ <b>{pred7_str} см</b></p>
  {peak_dt_str}
</div>"""

    # v7.7: методология, сценарии, сравнение с официальными
    methodology_block = """
<div style="background:var(--bg-primary); border:1px solid var(--border); border-radius:10px; padding:12px 16px; margin:12px 0; font-size:0.82rem; line-height:1.6;">
  <b style="color:var(--text-primary);">\u041c\u0435\u0442\u043e\u0434\u043e\u043b\u043e\u0433\u0438\u044f:</b>
  <span style="color:var(--text-secondary);">\u041b\u0438\u043d\u0435\u0439\u043d\u0430\u044f \u0440\u0435\u0433\u0440\u0435\u0441\u0441\u0438\u044f \u043f\u043e 11 \u0442\u043e\u0447\u043a\u0430\u043c \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u0439 (R\u00b2\u22480.96). \u041c\u043e\u0434\u0435\u043b\u044c \u044d\u043a\u0441\u0442\u0440\u0430\u043f\u043e\u043b\u0438\u0440\u0443\u0435\u0442 \u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u0442\u0440\u0435\u043d\u0434 \u043f\u043e\u0434\u044a\u0451\u043c\u0430.
  \u041e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f: \u043d\u0435 \u0443\u0447\u0438\u0442\u044b\u0432\u0430\u0435\u0442 \u0437\u0430\u043c\u0435\u0434\u043b\u0435\u043d\u0438\u0435 \u043f\u0440\u0438 \u043f\u0440\u0438\u0431\u043b\u0438\u0436\u0435\u043d\u0438\u0438 \u043a \u043f\u0438\u043a\u0443, \u043f\u043e\u0433\u043e\u0434\u043d\u044b\u0435 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u0438 \u043f\u0440\u0438\u0442\u043e\u043a \u0441 \u043f\u0440\u0438\u0442\u043e\u043a\u043e\u0432.</span>
</div>"""

    scenarios_block = """
<div style="background:var(--bg-primary); border:1px solid var(--border); border-radius:10px; padding:12px 16px; margin:8px 0; font-size:0.82rem; line-height:1.6;">
  <b style="color:var(--text-primary);">\u0412\u0438\u043b\u043a\u0430 \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u0435\u0432:</b>
  <div style="color:var(--text-secondary); margin-top:6px;">
    \U0001f7e2 <b>\u041e\u043f\u0442\u0438\u043c\u0438\u0441\u0442\u0438\u0447\u043d\u044b\u0439:</b> \u043f\u0438\u043a ~600\u2013650 \u0441\u043c (\u043d\u0430\u0447\u0430\u043b\u043e \u0430\u043f\u0440\u0435\u043b\u044f), \u0431\u044b\u0441\u0442\u0440\u044b\u0439 \u0441\u043f\u0430\u0434 \u0437\u0430 5\u20137 \u0434\u043d\u0435\u0439<br>
    \U0001f7e1 <b>\u0411\u0430\u0437\u043e\u0432\u044b\u0439:</b> \u043f\u0438\u043a ~700\u2013800 \u0441\u043c (5\u201310 \u0430\u043f\u0440\u0435\u043b\u044f), \u0441\u0442\u043e\u044f\u043d\u0438\u0435 7\u201310 \u0434\u043d\u0435\u0439<br>
    \U0001f534 <b>\u041f\u0435\u0441\u0441\u0438\u043c\u0438\u0441\u0442\u0438\u0447\u043d\u044b\u0439:</b> \u043f\u0438\u043a ~800\u2013900 \u0441\u043c (10\u201315 \u0430\u043f\u0440\u0435\u043b\u044f), \u0441\u0442\u043e\u044f\u043d\u0438\u0435 10\u201314 \u0434\u043d\u0435\u0439
  </div>
</div>"""

    official_block = """
<div style="background:var(--bg-primary); border:1px solid var(--border); border-radius:10px; padding:12px 16px; margin:8px 0; font-size:0.82rem; line-height:1.6;">
  <b style="color:var(--text-primary);">\u0421\u0440\u0430\u0432\u043d\u0435\u043d\u0438\u0435 \u0441 \u043e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u043c\u0438 \u043f\u0440\u043e\u0433\u043d\u043e\u0437\u0430\u043c\u0438:</b>
  <span style="color:var(--text-secondary);">\u041e\u0444\u0438\u0446\u0438\u0430\u043b\u044c\u043d\u044b\u0435 \u043f\u0440\u043e\u0433\u043d\u043e\u0437\u044b (\u0426\u0423\u0413\u041c\u0421, \u0420\u043e\u0441\u0433\u0438\u0434\u0440\u043e\u043c\u0435\u0442) \u0434\u0430\u044e\u0442 \u043e\u0431\u0449\u0438\u0435 \u043e\u0446\u0435\u043d\u043a\u0438 \u0434\u043b\u044f \u041c\u043e\u0441\u043a\u043e\u0432\u0441\u043a\u043e\u0439 \u043e\u0431\u043b\u0430\u0441\u0442\u0438.
  \u041d\u0430\u0448\u0430 \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u0440\u0430\u0441\u0441\u0447\u0438\u0442\u044b\u0432\u0430\u0435\u0442 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u043a\u043e\u043d\u043a\u0440\u0435\u0442\u043d\u043e \u0434\u043b\u044f \u0443\u0447\u0430\u0441\u0442\u043a\u0430 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432\u2014\u0416\u0435\u0440\u043d\u043e\u0432\u043a\u0430, \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044f \u0434\u0430\u043d\u043d\u044b\u0435 GloFAS \u0438 \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0435 \u043d\u0430\u0431\u043b\u044e\u0434\u0435\u043d\u0438\u044f.</span>
</div>"""

    return f"""
<div class="peak-trend" style="color: {trend_color}; border-left-color: {trend_color};">
  {trend_text}
</div>
{methodology_block}
{reg_block}
{scenarios_block}
{official_block}
<p class="disclaimer-small" style="background:rgba(239,68,68,0.05); border-radius:8px; padding:10px 14px; margin-top:10px;">
  \u26a0\ufe0f \u041f\u0440\u043e\u0433\u043d\u043e\u0437 \u044f\u0432\u043b\u044f\u0435\u0442\u0441\u044f \u0440\u0430\u0441\u0447\u0451\u0442\u043d\u044b\u043c \u0438 \u043f\u0440\u0438\u0431\u043b\u0438\u0437\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u043c. \u0420\u0435\u0430\u043b\u044c\u043d\u044b\u0439 \u043f\u0438\u043a \u0437\u0430\u0432\u0438\u0441\u0438\u0442 \u043e\u0442 \u043f\u043e\u0433\u043e\u0434\u044b, \u043e\u0441\u0430\u0434\u043a\u043e\u0432 \u0438 \u0440\u0430\u0431\u043e\u0442\u044b \u0433\u0438\u0434\u0440\u043e\u0443\u0437\u043b\u043e\u0432.
</p>"""


def _generate_history_section(history: list) -> str:
    """
    Генерирует секцию таблицы истории.
    ИСПРАВЛЕНИЕ v7: alert_level отображается на РУССКОМ языке.
    + GloFAS колонки.
    """
    rows = list(reversed(history[-100:]))

    rows_html = ""
    for row in rows:
        dt_str  = _h((row.get("datetime") or "")[:19].replace("T", " "))
        lv_cm   = row.get("serp_level_cm")
        lv_str  = f"{lv_cm:.0f}" if lv_cm is not None else "—"
        chg     = row.get("serp_daily_change_cm")
        chg_str = _fmt_change(chg)
        abs_bs  = row.get("serp_abs_m_bs")
        abs_str = f"{abs_bs:.3f}" if abs_bs is not None else "—"
        kashira = row.get("kim_kashira_cm")
        snow    = row.get("snow_depth_cm")

        # ИСПРАВЛЕНИЕ v7: перевод alert_level в русский
        al_raw  = row.get("alert_level", "")
        al_rus  = _alert_level_to_russian(al_raw)
        al_lower = al_rus.lower()

        delta_style = ""
        if chg is not None:
            try:
                fchg = float(chg)
                if fchg > 5:
                    delta_style = 'style="color:var(--danger);"'
                elif fchg < -5:
                    delta_style = 'style="color:var(--safe);"'
            except (ValueError, TypeError):
                pass

        # GloFAS колонки
        glofas_belev  = row.get("glofas_belev_discharge")
        glofas_peak_d = row.get("glofas_peak_date", "")
        belev_str     = f"{glofas_belev:.0f}" if glofas_belev is not None else "—"
        peak_d_str    = (glofas_peak_d[8:10] + "." + glofas_peak_d[5:7]
                         if glofas_peak_d and len(glofas_peak_d) >= 10 else "—")

        rows_html += f"""
<tr>
  <td>{dt_str}</td>
  <td>{_h(lv_str)}</td>
  <td {delta_style}>{_h(chg_str)}</td>
  <td>{_h(abs_str)}</td>
  <td>{_h(str(kashira) if kashira is not None else "—")}</td>
  <td>{_h(belev_str)}</td>
  <td>{_h(peak_d_str)}</td>
  <td>{_h(str(int(snow)) if snow is not None else "—")}</td>
  <td><span class="status-badge {al_lower}">{_h(al_rus)}</span></td>
</tr>"""

    empty_note = ""
    if len(rows) < 5:
        empty_note = """<div style="padding:12px; background:rgba(59,130,246,0.05); border-left:3px solid var(--accent); border-radius:0 6px 6px 0; margin-bottom:12px; font-size:0.85rem; color:var(--text-secondary);">
  📊 Мониторинг запущен 29.03.2026. Полная ретроспектива будет доступна через неделю — Ока, как и положено великой реке, не торопится заполнять таблицы.
</div>"""

    return f"""
<div class="history-controls">
  <button onclick="filterHistory(7)"  class="hist-btn">7 дней</button>
  <button onclick="filterHistory(30)" class="hist-btn">30 дней</button>
  <button onclick="filterHistory(0)"  class="hist-btn">Всё</button>
  <a href="history.csv" download class="hist-btn">⬇ CSV</a>
</div>
{empty_note}
<div class="history-scroll-wrap">
<div class="table-wrap">
  <table id="histTable">
    <thead>
      <tr>
        <th>Дата/время</th>
        <th>Уровень (см)</th>
        <th>Δ см/сут</th>
        <th>м БС</th>
        <th>Кашира</th>
        <th>Белёв (м³/с)</th>
        <th>Пик GloFAS</th>
        <th>Снег (см)</th>
        <th>Статус</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</div>
</div>"""


def _generate_reports_section() -> str:
    """v7.6: Автосканирует reports/ папку для PDF файлов. Сортирует по дате в имени."""
    import glob as _glob
    import re as _re

    reports_dir = os.path.join(DOCS_DIR, "reports")
    reports = []

    # Auto-scan for PDF files
    if os.path.isdir(reports_dir):
        for fpath in _glob.glob(os.path.join(reports_dir, "*.pdf")):
            fname = os.path.basename(fpath)
            # Extract date from filename (report_YYYY-MM-DD.pdf or any YYYY-MM-DD pattern)
            date_match = _re.search(r'(\d{4}-\d{2}-\d{2})', fname)
            date_str = date_match.group(1) if date_match else ""
            size_bytes = os.path.getsize(fpath)
            size_str = f"{size_bytes // 1024} КБ" if size_bytes < 1024*1024 else f"{size_bytes / 1024 / 1024:.1f} МБ"
            # Title from filename
            title = fname.replace('.pdf', '').replace('_', ' ').replace('-', ' ').strip()
            if date_str:
                d = date_str.split('-')
                title = f"Отчёт {d[2]}.{d[1]}.{d[0]}"
            reports.append({
                "filename": fname,
                "title": title,
                "date": date_str,
                "size": size_str,
                "sort_key": date_str or fname,
            })

    # Sort by date (newest first)
    reports.sort(key=lambda r: r["sort_key"], reverse=True)
    reports = reports[:10]

    if not reports:
        return """
<div class="report-placeholder">
  <p>📁 Раздел PDF-отчётов в разработке. Здесь будут публиковаться обзоры паводковой обстановки.</p>
</div>"""

    cards_html = ""
    for rep in reports:
        filename = rep["filename"]
        title    = _h(rep["title"])
        date_str = _h(rep["date"])
        size_str = _h(rep["size"])
        link     = f"reports/{filename}"
        cards_html += f"""
<div class="report-card">
  <a href="{_h(link)}" target="_blank">📄 {title}</a>
  <div class="report-meta">{date_str} · {size_str}</div>
</div>"""

    return f"""
<div class="report-cards">
  {cards_html}
</div>"""


def _generate_detail_accordions(data: dict, analytics: dict, history: list,
                                  regression, wext) -> str:
    """Генерирует блок детальных секций в виде аккордеонов."""
    serp  = data.get("serpuhov", {})
    cugms = data.get("cugms", {})

    thresh_html  = _generate_threshold_section(serp, analytics)
    cugms_html   = _generate_cugms_section(cugms)
    peak_html    = _generate_peak_section(analytics, regression)
    hist_html    = _generate_history_section(history)
    reports_html = _generate_reports_section()

    # v7.3: reports accordion always shown
    reports_acc = f"""
<div class="accordion-section">
  <div class="accordion-header" onclick="toggleAccordion('reportsAcc')">
    \U0001f4c1 PDF-\u0430\u0440\u0445\u0438\u0432 \u043e\u0431\u0437\u043e\u0440\u043e\u0432
    <span class="toggle-icon" id="reportsAcc-icon">\u25bc</span>
  </div>
  <div class="accordion-body" id="reportsAcc">
    {reports_html}
  </div>
</div>"""

    return f"""
<section style="padding: 0 24px 24px;">
  <div style="display:flex; flex-direction:column; gap:8px;">

    <div class="accordion-section">
      <div class="accordion-header" onclick="toggleAccordion('threshAcc')">
        📏 Пороговые отметки
        <span class="toggle-icon" id="threshAcc-icon">▼</span>
      </div>
      <div class="accordion-body" id="threshAcc">
        {thresh_html}
      </div>
    </div>

    <div class="accordion-section">
      <div class="accordion-header" onclick="toggleAccordion('cugmsAcc')">
        📋 Последний обзор ЦУГМС
        <span class="toggle-icon" id="cugmsAcc-icon">▼</span>
      </div>
      <div class="accordion-body" id="cugmsAcc">
        <p style="font-size:0.82rem; color:var(--text-dim); margin-bottom:10px; line-height:1.5;">ЦУГМС (Центральное управление по гидрометеорологии и мониторингу окружающей среды) — федеральная служба, публикующая официальные гидрологические обзоры.</p>
        {cugms_html}
      </div>
    </div>

    <div class="accordion-section">
      <div class="accordion-header" onclick="toggleAccordion('peakAcc')">
        📈 Прогноз пика
        <span class="toggle-icon" id="peakAcc-icon">▼</span>
      </div>
      <div class="accordion-body" id="peakAcc">
        {peak_html}
      </div>
    </div>

    <div class="accordion-section fade-in-section">
      <div class="accordion-header" onclick="toggleAccordion('histAcc')">
        📊 История наблюдений
        <span class="toggle-icon" id="histAcc-icon">▼</span>
      </div>
      <div class="accordion-body" id="histAcc">
        {hist_html}
      </div>
    </div>

    {reports_acc}

  </div>
</section>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: JAVASCRIPT
# ══════════════════════════════════════════════════════════════════════════════

def _generate_all_js() -> str:
    """Генерирует весь JavaScript для index.html."""
    return """
// ── CLOCK ──────────────────────────────────────────────────────────────
function updateClock() {
  var now = new Date();
  // МСК = UTC+3: берём UTC-часы и добавляем 3
  var utcH = now.getUTCHours();
  var mskH = (utcH + 3) % 24;
  var h = String(mskH).padStart(2,'0');
  var m = String(now.getUTCMinutes()).padStart(2,'0');
  var s = String(now.getUTCSeconds()).padStart(2,'0');
  var el = document.getElementById('clock');
  if (el) el.textContent = h + ':' + m + ':' + s + ' МСК';
}
setInterval(updateClock, 1000);
updateClock();

// ── ACCORDION v7.2: по умолчанию открыты ──────────────────────────
function toggleAccordion(id) {
  var body = document.getElementById(id);
  var icon = document.getElementById(id + '-icon');
  if (!body) return;
  var isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  if (icon) icon.textContent = isOpen ? '▼' : '▲';
}
// Открыть все аккордеоны при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
  var allBodies = document.querySelectorAll('.accordion-body');
  allBodies.forEach(function(body) {
    body.classList.add('open');
    var icon = document.getElementById(body.id + '-icon');
    if (icon) icon.textContent = '▲';
  });
});

// ── HISTORY FILTER ───────────────────────────────────────────────────
function filterHistory(days) {
  var rows = document.querySelectorAll('#histTable tbody tr');
  var cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;
  rows.forEach(function(row) {
    if (!cutoff) { row.style.display = ''; return; }
    var dateStr = row.cells[0] ? row.cells[0].textContent.trim() : '';
    var d = new Date(dateStr.replace(' ', 'T') + 'Z');
    row.style.display = (!isNaN(d) && d >= cutoff) ? '' : 'none';
  });
}

// ── SCROLL ANIMATIONS (IntersectionObserver) ─────────────────────────
var observer = new IntersectionObserver(function(entries) {
  entries.forEach(function(e) {
    if (e.isIntersecting) {
      e.target.classList.add('visible');
    }
  });
}, { threshold: 0.08 });

document.querySelectorAll('.fade-in-section').forEach(function(s) {
  observer.observe(s);
});

// ── PROGRESS BAR ANIMATION ───────────────────────────────────────────
window.addEventListener('load', function() {
  document.querySelectorAll('.progress-bar-fill').forEach(function(bar) {
    var targetWidth = bar.style.width;
    bar.style.width = '0%';
    setTimeout(function() {
      bar.style.width = targetWidth;
    }, 300);
  });
});

// ── FRESHNESS CHECK v7.3 ─────────────────────────────────────────────
fetch('data.json').then(function(r){return r.json();}).then(function(d){
  var genAt = new Date(d.generated_at);
  var ageMin = (Date.now() - genAt.getTime()) / 60000;
  var dot = document.getElementById('freshness');
  if (!dot) return;
  if (ageMin < 240) {
    dot.className = 'freshness-dot fresh-green';
    dot.title = '\u0414\u0430\u043d\u043d\u044b\u0435 \u0430\u043a\u0442\u0443\u0430\u043b\u044c\u043d\u044b (\u043e\u0431\u043d. ' + Math.round(ageMin) + ' \u043c\u0438\u043d. \u043d\u0430\u0437\u0430\u0434)';
  } else if (ageMin < 480) {
    dot.className = 'freshness-dot fresh-yellow';
    dot.title = '\u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435\u043c\u043d\u043e\u0433\u043e \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0438 (' + Math.round(ageMin/60) + ' \u0447. \u043d\u0430\u0437\u0430\u0434)';
  } else {
    dot.className = 'freshness-dot fresh-red';
    dot.title = '\u0414\u0430\u043d\u043d\u044b\u0435 \u0443\u0441\u0442\u0430\u0440\u0435\u043b\u0438! \u0410\u0432\u0442\u043e\u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043d\u0430\u0440\u0443\u0448\u0435\u043d\u043e.';
    var banner = document.getElementById('stale-banner');
    if (banner) {
      banner.style.display = 'block';
      var staleTime = document.getElementById('stale-time');
      if (staleTime) staleTime.textContent = genAt.toLocaleString('ru-RU');
    }
  }
}).catch(function(){});

// ── BURGER MENU ────────────────────────────────────────────────────────
function toggleMobileNav() {
  var nav = document.getElementById('mobile-nav');
  var btn = document.querySelector('.burger-btn');
  if (!nav) return;
  nav.classList.toggle('open');
  btn.textContent = nav.classList.contains('open') ? '✕' : '☰';
}
document.addEventListener('click', function(e) {
  var nav = document.getElementById('mobile-nav');
  var btn = document.querySelector('.burger-btn');
  if (!nav || !btn) return;
  if (!nav.contains(e.target) && !btn.contains(e.target)) {
    nav.classList.remove('open');
    btn.textContent = '☰';
  }
});
"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: FOOTER
# ══════════════════════════════════════════════════════════════════════════════

def _generate_footer(now_msk: str) -> str:
    """Генерирует footer v7.6.1."""
    return f"""
<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | 54.833413, 37.741813 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS Flood API<br>
  Обновлено: {_h(now_msk)} МСК |
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
  <div style="margin-top:8px;font-size:0.65rem;color:var(--text-dim);opacity:0.5;">
    <img src="https://hits.seeyoufarm.com/api/count/incr/badge.svg?url=https%3A%2F%2Fem-from-pu.github.io%2Foka-flood-monitor&count_bg=%23555555&title_bg=%23555555&icon=&icon_color=%23E7E7E7&title=%D0%BF%D0%BE%D1%81%D0%B5%D1%89%D0%B5%D0%BD%D0%B8%D1%8F&edge_flat=true"
      alt="visits" style="height:18px;vertical-align:middle;opacity:0.6;" loading="lazy">
  </div>
</footer>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: ГЛАВНЫЙ ГЕНЕРАТОР
# ══════════════════════════════════════════════════════════════════════════════

def _generate_hist_peaks_infographic() -> str:
    """Генерирует инфографику исторических пиков на главной странице. v7.2."""
    peaks = [
        {"year": "2013", "val": 843, "color": "#f97316"},
        {"year": "2023", "val": 780, "color": "#f59e0b"},
        {"year": "2024", "val": 850, "color": "#ef4444"},
    ]
    max_val = max(p["val"] for p in peaks)
    bars_html = ""
    for p in peaks:
        bar_h = int(p["val"] / max_val * 80)
        bars_html += f"""
<div class="hist-peak-col">
  <div class="hist-peak-val">{p["val"]} см</div>
  <div class="hist-peak-bar" style="height:{bar_h}px; background:{p["color"]};"></div>
  <div class="hist-peak-year">{p["year"]}</div>
</div>"""

    return f"""
<section style="padding: 0 24px 8px;">
  <a href="history.html" style="text-decoration:none; color:inherit; display:block;">
  <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:16px 20px; cursor:pointer; transition:border-color 0.2s;" onmouseover="this.style.borderColor='rgba(255,255,255,0.15)'" onmouseout="this.style.borderColor='rgba(255,255,255,0.08)'">
    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:8px;">
      <div>
        <h3 style="font-size:0.95rem; font-weight:700; margin-bottom:4px;">📊 Исторические пики у Серпухова</h3>
        <div style="font-size:0.8rem; color:var(--text-dim);">НЯ = 645 см | ОЯ = 800 см | Рекорд 1908 г.: 1256 см</div>
      </div>
      <span style="font-size:0.82rem; color:var(--accent); white-space:nowrap;" title="Открыть страницу истории паводков">Полная история паводков →</span>
    </div>
    <div class="hist-peaks-bar">{bars_html}</div>
    <div style="font-size:0.75rem; color:var(--text-dim); text-align:center; margin-top:4px;">
      Ока, как и положено великой реке, не любит спешить — но когда решается, удивляет даже бывалых.
    </div>
  </div>
  </a>
</section>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: PERSONAL FORECAST (дом автора проекта) v7.7
# ══════════════════════════════════════════════════════════════════════════════

def _generate_author_forecast(level_cm, change_cm_day, history, glofas, analytics):
    """Персональный блок: вероятности НЯ/ОЯ/БЯ для дома автора проекта."""

    # Текущий уровень и скорость
    current = level_cm or 0
    speed = change_cm_day or 0

    # Расстояния до порогов
    to_nya = 645 - current
    to_oya_author = AUTHOR_OYA_CM - current
    to_bya = AUTHOR_BYA_CM - current

    # v7.7: Исправленный расчёт дней до порога с decay 0.85 и cap 30 дней
    def days_to_threshold(dist, spd):
        if dist <= 0:
            return -1  # порог уже превышен
        if spd <= 0:
            return None
        days = 0
        remaining = dist
        s = spd
        while remaining > 0 and days < 30:
            remaining -= s
            s *= 0.85  # v7.7: более реалистичное замедление
            days += 1
        if remaining > 0:
            return None  # не ожидается при текущем прогнозе
        return days

    days_nya = days_to_threshold(to_nya, speed)
    days_oya = days_to_threshold(to_oya_author, speed)
    days_bya = days_to_threshold(to_bya, speed)

    # v7.7: Реалистичные вероятности с учётом скорости и запаса снега
    snow_cm = ((analytics or {}).get("snow_depth_cm") or 0)
    is_fast_rise = speed > 40
    is_high_snow = snow_cm > 20  # значительный запас
    if is_fast_rise and is_high_snow:
        prob_nya = min(99, max(50, 92 - max(0, to_nya) // 10))
        prob_oya = min(70, max(10, 55 - max(0, to_oya_author) // 15))
        prob_bya = min(20, max(2, 10 - max(0, to_bya) // 40))
    elif is_fast_rise:
        prob_nya = min(99, max(30, 85 - max(0, to_nya) // 8))
        prob_oya = min(60, max(8, 45 - max(0, to_oya_author) // 12))
        prob_bya = min(15, max(2, 8 - max(0, to_bya) // 30))
    else:
        prob_nya = min(95, max(5, int(80 - max(0, to_nya) / 6)))
        prob_oya = min(55, max(3, int(35 - max(0, to_oya_author) / 10)))
        prob_bya = min(20, max(1, int(8 - max(0, to_bya) / 25)))

    # Форматирование
    def fmt_dist(d):
        if d <= 0:
            return '<span style="color:#ef4444; font-weight:700;">Достигнут!</span>'
        return f"осталось {d:.0f} см"

    def fmt_days(d):
        if d is None:
            return '<span style="color:var(--text-dim); font-size:0.78rem;">не ожидается при текущем прогнозе</span>'
        if d < 0:
            return '<span style="color:#ef4444; font-weight:700;">ПОРОГ ПРЕВЫШЕН</span>'
        if d == 0:
            return '<span style="color:#ef4444; font-weight:700;">сейчас</span>'
        return f"~{d} дн."

    def card_color(prob):
        if prob >= 70:
            return "#ef4444"
        if prob >= 40:
            return "#f97316"
        if prob >= 20:
            return "#f59e0b"
        return "#10b981"

    # Рекомендация
    recommendation = ""
    if speed > 0:
        recommendation = f"При текущей скорости подъёма {speed:+.0f} см/сут "
        if days_oya is not None and days_oya < 3:
            recommendation += '\n<div style="margin-top:6px; padding:8px 12px; background:rgba(239,68,68,0.12); border-radius:8px; color:#ef4444; font-weight:600;">\U0001f6a8 СРОЧНО: осталось менее 3 дней до критического уровня</div>'
        elif days_oya is not None and days_oya < 7:
            recommendation += f'\n<div style="margin-top:6px; padding:8px 12px; background:rgba(249,115,22,0.12); border-radius:8px; color:#f97316; font-weight:600;">\u26a0\ufe0f Подготовку дома завершить в ближайшие {days_oya} дней</div>'
        elif days_oya is not None:
            recommendation += f"\u2014 до уровня 867 см ориентировочно {days_oya} дн."
        else:
            recommendation += "\u2014 вода не поднимается до критических отметок при текущем темпе."
    else:
        recommendation = "Уровень стабилен или снижается \u2014 непосредственной угрозы нет."

    nya_color = card_color(prob_nya)
    oya_color = card_color(prob_oya)
    bya_color = card_color(prob_bya)

    return f"""
<section class="author-forecast-section fade-in-section" style="padding: 0 24px 12px;">
  <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:16px; padding:20px 24px;">
    <h3 style="font-size:1.05rem; font-weight:700; margin-bottom:4px;">\U0001f3e0 Прогноз для дома автора проекта</h3>
    <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:16px;">
      Расч\u0451т для точки \u2248 28 км ниже гидропоста Лукьяново (время прихода волны: ~7 \u0447)
    </p>

    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:12px; margin-bottom:16px;">
      <!-- НЯ -->
      <div style="background:var(--bg-primary); border:1px solid {nya_color}30; border-radius:12px; padding:14px; text-align:center;">
        <div style="font-size:1.3rem; margin-bottom:4px;">\U0001f7e1</div>
        <div style="font-size:0.78rem; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">До НЯ (645 см)</div>
        <div style="font-size:1.4rem; font-weight:800; color:{nya_color};">{fmt_dist(to_nya)}</div>
        <div style="font-size:0.82rem; color:var(--text-dim); margin-top:4px;">{fmt_days(days_nya)}</div>
        <div style="font-size:0.75rem; color:{nya_color}; margin-top:4px; font-weight:600;">{prob_nya}%</div>
      </div>
      <!-- ОЯ автора -->
      <div style="background:var(--bg-primary); border:1px solid {oya_color}30; border-radius:12px; padding:14px; text-align:center;">
        <div style="font-size:1.3rem; margin-bottom:4px;">\U0001f534</div>
        <div style="font-size:0.78rem; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">До 867 см \u2014 вода у порога</div>
        <div style="font-size:1.4rem; font-weight:800; color:{oya_color};">{fmt_dist(to_oya_author)}</div>
        <div style="font-size:0.82rem; color:var(--text-dim); margin-top:4px;">{fmt_days(days_oya)}</div>
        <div style="font-size:0.75rem; color:{oya_color}; margin-top:4px; font-weight:600;">{prob_oya}%</div>
      </div>
      <!-- БЯ -->
      <div style="background:var(--bg-primary); border:1px solid {bya_color}30; border-radius:12px; padding:14px; text-align:center;">
        <div style="font-size:1.3rem; margin-bottom:4px;">\u26ab</div>
        <div style="font-size:0.78rem; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">До 967 см \u2014 предел дамбы</div>
        <div style="font-size:1.4rem; font-weight:800; color:{bya_color};">{fmt_dist(to_bya)}</div>
        <div style="font-size:0.82rem; color:var(--text-dim); margin-top:4px;">{fmt_days(days_bya)}</div>
        <div style="font-size:0.75rem; color:{bya_color}; margin-top:4px; font-weight:600;">{prob_bya}%</div>
      </div>
    </div>

    <div style="font-size:0.85rem; color:var(--text-secondary); line-height:1.6;">
      {recommendation}
    </div>
    <p style="font-size:0.68rem; color:var(--text-dim); margin-top:10px; opacity:0.6;">
      Эвристическая оценка на основе текущей динамики. Не является официальным прогнозом.
    </p>
  </div>
</section>"""


def generate_html(data: dict, analytics: dict, history: list, wext,
                  regression, ref_2024, weather_multi_data=None) -> str:
    """
    Генерирует полную HTML-страницу index.html.
    v7: glassmorphism UI, Composite Status, GloFAS station cards, forecast hydrograph.
    """
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})
    cugms  = data.get("cugms", {})
    glofas = data.get("glofas", {})

    # Composite status
    composite = compute_composite_status(serp, wext, glofas, analytics)

    level_cm  = serp.get("level_cm")
    change_cm = serp.get("daily_change_cm")
    abs_bs    = serp.get("abs_level_m_bs")
    src_stat  = serp.get("source_status", "unavailable")

    _, zone_color, _, _, zone_css = get_level_zone(level_cm)

    level_str = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
    abs_str   = f"{abs_bs:.3f} м БС" if abs_bs is not None else ""

    action_icon, action_title, action_text, action_color = generate_action_block(
        level_cm, (wext or {}).get("flood_index", 0), composite
    )

    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    nya_fill_pct = analytics.get("nya_fill_pct", 0)
    oya_fill_pct = analytics.get("oya_fill_pct", 0)
    nya_rem      = analytics.get("nya_remaining_m")
    oya_rem      = analytics.get("oya_remaining_m")

    css               = _generate_css_v7()
    header_html       = _generate_header_v7(serp, kim, cugms, glofas, now_msk)
    hero_html         = _generate_hero_v7(serp, analytics, composite, nya_fill_pct, oya_fill_pct, nya_rem, oya_rem, wext)
    hydrograph_html   = _generate_forecast_hydrograph(history, glofas, ref_2024)
    station_cards_html = _generate_station_cards_v7(data, glofas, history)
    timeline_html     = _generate_wave_timeline(glofas)
    author_html       = _generate_author_forecast(level_cm, change_cm, history, glofas, analytics)
    action_html       = _generate_action_section(action_icon, action_title, action_text, action_color)
    weather_html      = _generate_weather_section(wext, weather_multi_data)
    details_html      = _generate_detail_accordions(data, analytics, history, regression, wext)
    footer_html       = _generate_footer(now_msk)
    js_html           = _generate_all_js()
    hist_peaks_html   = _generate_hist_peaks_infographic()

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="OkaFloodMonitor — мониторинг паводка на реке Ока у Серпухова. Данные обновляются 4 раза в день.">
  <title>OkaFloodMonitor — Серпухов / Жерновка</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
  <style>{css}</style>
</head>
<body>

{header_html}

<div style="background:var(--bg-card); border-bottom:1px solid var(--border); padding:10px 24px; font-size:0.82rem; color:var(--text-secondary); line-height:1.5; text-align:center;">
  Независимый мониторинг паводка на Оке от Орла до Коломны. Оперативные данные, прогноз волны и расчёт сроков подъёма воды.<br>
  <b>НЯ</b> (645 см) — неблагоприятное явление: выход воды на пойму &nbsp;|&nbsp;
  <b>ОЯ</b> (800 см) — опасное явление: подтопление населённых пунктов
</div>

<div id="stale-banner" class="stale-banner" style="display:none;">
  ⚠️ Данные устарели. Автоматическое обновление может быть нарушено.
  Последнее обновление: <span id="stale-time"></span>
</div>

<main>
  {hero_html}

  <div class="fade-in-section">
    {hydrograph_html}
  </div>

  {timeline_html}

  {author_html}

  {station_cards_html}

  <div class="fade-in-section">
    {action_html}
  </div>

  {weather_html}

  <section style="padding: 0 24px 12px;">
    <div class="news-signals" style="background:var(--bg-card); border:1px solid var(--border); border-radius:12px; padding:16px 20px;">
      <h3 style="font-size:0.95rem; font-weight:700; margin-bottom:8px;">📡 Сигналы паводка</h3>
      <ul style="list-style:none; padding:0; margin:0; font-size:0.85rem; color:var(--text-secondary); line-height:1.8;">
        <li>🔔 <b>Луховицы</b> (Ока, ~100 км НИЖЕ Серпухова по течению): уровень поднялся на 75 см за 2 суток (28–29 марта 2026). Луховицы находятся ниже по течению, поэтому этот рост НЕ влияет на уровень у Серпухова напрямую, но показывает масштаб текущего половодья.</li>
        <li>🔔 <b>Ледоход Ступино</b>: начался 24 марта 2026 — в пределах нормы</li>
      </ul>
    </div>
  </section>

  {hist_peaks_html}

  {details_html}

  <section style="padding:0 24px 32px;">
    <div style="background:linear-gradient(135deg, rgba(29,155,240,0.1), rgba(29,155,240,0.05));
      border:1px solid rgba(29,155,240,0.3); border-radius:16px; padding:24px; text-align:center;">
      <div style="font-size:1.5rem;">📱</div>
      <h3 style="color:#1d9bf0; margin:8px 0;">Telegram-оповещения</h3>
      <p style="color:var(--text-secondary);font-size:0.88rem;">
        Получайте уведомления о паводке прямо в Telegram — алерты, дайджесты, прогнозы.
      </p>
      <a href="instructions.html#telegram" style="display:inline-block;margin-top:12px;
        background:#1d9bf0;color:#fff;padding:10px 24px;border-radius:10px;
        text-decoration:none;font-weight:600;font-size:0.88rem;">
        Подробнее →
      </a>
    </div>
  </section>
</main>

{footer_html}

<script>
{js_html}
</script>


<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# LINKS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_links_css() -> str:
    """CSS для страниц links и instructions — использует базовый дизайн v7.6.1 light."""
    return """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --safe:      #22c55e;
  --watch:     #f59e0b;
  --warning:   #f97316;
  --danger:    #ef4444;
  --emergency: #a855f7;
  --accent:    #2563eb;
  --bg-primary: #f7f9fc;
  --bg-card: #ffffff;
  --bg-card-hover: #f8fafc;
  --bg-glass: rgba(0, 0, 0, 0.03);
  --border: rgba(0, 0, 0, 0.08);
  --border-hover: rgba(0, 0, 0, 0.16);
  --text-primary: #1a2332;
  --text-secondary: #5a6a7a;
  --text-dim: #8a9ab0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.6;
  font-size: 15px;
  position: relative;
}
body::before {
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(circle at 20% 50%, rgba(186,230,253,0.12) 0%, transparent 50%),
              radial-gradient(circle at 80% 20%, rgba(186,230,253,0.10) 0%, transparent 40%);
  pointer-events: none;
  z-index: -1;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.8rem; font-weight: 800; padding: 20px 24px; }
h2 { font-size: 1.2rem; font-weight: 600; color: var(--text-secondary); margin: 24px 0 12px; }
h3 { font-size: 1rem; font-weight: 600; margin: 16px 0 8px; }
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px 40px; }
.site-header {
  position: sticky; top: 0; z-index: 200;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid #e5e7eb;
  padding: 0 24px; height: 56px;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.header-logo { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); white-space: nowrap; letter-spacing: -0.02em; }
.header-logo span { color: var(--accent); }
.header-nav { display: flex; gap: 2px; list-style: none; }
.header-nav > li { position: relative; }
.header-nav a {
  display: block; padding: 6px 12px; border-radius: 8px;
  color: var(--text-secondary); text-decoration: none; font-size: 0.88rem; font-weight: 500; transition: all 0.2s ease; white-space: nowrap;
}
.header-nav a:hover, .header-nav a.active { background: rgba(37,99,235,0.08); color: var(--accent); }
.header-nav .dropdown {
  position: absolute; top: calc(100% + 4px); left: 0;
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 200px; z-index: 1000;
  opacity: 0; visibility: hidden; transform: translateY(-4px);
  transition: all 0.15s ease; pointer-events: none; padding: 6px 0;
}
.header-nav > li:hover .dropdown { opacity: 1; visibility: visible; transform: translateY(0); pointer-events: auto; }
.header-nav .dropdown a { padding: 7px 16px; font-size: 0.83rem; border-radius: 0; }
.burger-btn { display: none; background: none; border: none; cursor: pointer; font-size: 1.4rem; color: var(--text-primary); padding: 4px 8px; border-radius: 6px; }
.mobile-nav { display: none; position: fixed; top: 56px; left: 0; right: 0; background: #ffffff; border-bottom: 1px solid #e5e7eb; box-shadow: 0 8px 24px rgba(0,0,0,0.12); z-index: 199; padding: 8px 0 16px; }
.mobile-nav.open { display: block; }
.mobile-nav a { display: block; padding: 10px 24px; font-size: 0.95rem; font-weight: 500; color: var(--text-secondary); text-decoration: none; border-left: 3px solid transparent; transition: all 0.15s; }
.mobile-nav a:hover, .mobile-nav a.active { background: rgba(37,99,235,0.05); color: var(--accent); border-left-color: var(--accent); }
.mobile-nav .mobile-nav-sub { padding-left: 40px; font-size: 0.83rem; }
@media (max-width: 768px) { .header-nav { display: none; } .burger-btn { display: block; } }
.card {
  background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 16px; margin-bottom: 16px; padding: 20px;
  box-shadow: var(--shadow-card, 0 2px 12px rgba(0,0,0,0.08));
}
.section-card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.explainer { background: rgba(37,99,235,0.04); border-left: 3px solid var(--accent); padding: 10px 14px; margin: 8px 0 16px; font-size: 0.88em; color: var(--text-secondary); border-radius: 0 6px 6px 0; }
.zone-row { padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 0.88em; }
.zone-row.green  { background: rgba(34,197,94,0.08); border-left: 3px solid var(--safe); }
.zone-row.yellow { background: rgba(245,158,11,0.08); border-left: 3px solid var(--watch); }
.zone-row.orange { background: rgba(249,115,22,0.08); border-left: 3px solid var(--warning); }
.zone-row.red    { background: rgba(239,68,68,0.08);  border-left: 3px solid var(--danger); }
.action-table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin: 10px 0; }
.action-table th { background: #f8fafc; padding: 6px 8px; text-align: left; color: var(--text-dim); }
.action-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }
.dead-sources { background: rgba(239,68,68,0.04); border: 1px solid rgba(239,68,68,0.2); border-radius: 8px; padding: 12px 16px; margin-top: 10px; }
.dead-sources ul { padding-left: 20px; }
.dead-sources li { margin: 5px 0; color: var(--text-secondary); font-size: 0.9em; }
.site-footer {
  background: rgba(247,249,252,0.95); border-top: 1px solid #e5e7eb;
  padding: 20px 24px; text-align: center; color: var(--text-dim); font-size: 0.78rem;
}
"""



# ══════════════════════════════════════════════════════════════════════════════
# ИСТОРИЯ ПАВОДКОВ: history.html
# ══════════════════════════════════════════════════════════════════════════════

def generate_history_page() -> None:
    """
    Генерирует docs/history.html — страница истории паводков Оки.
    v7.3: расширенный контент x2, фотографии из репутабельных источников,
    секция «Мифы о дамбах».
    """
    css = _generate_links_css()
    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="История паводков реки Оки от Орла до Коломны — 1908, 1970, 2013, 2023, 2024. Фото, цифры, мифы о плотинах. OkaFloodMonitor.">
  <title>История паводков Оки — OkaFloodMonitor</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    {css}
    .hist-section {{ margin-bottom: 32px; }}
    .hist-section h2 {{ font-size: 1.3rem; font-weight: 700; color: var(--text-primary); margin-bottom: 12px; border-left: 3px solid var(--accent); padding-left: 12px; }}
    .hist-section h3 {{ font-size: 1.05rem; font-weight: 600; color: var(--text-primary); margin: 16px 0 8px; }}
    .hist-section p {{ color: var(--text-secondary); line-height: 1.75; margin-bottom: 10px; font-size: 0.9rem; }}
    .hist-table {{ width: 100%; border-collapse: collapse; font-size: 0.83rem; margin: 12px 0; }}
    .hist-table th {{ background: #f8fafc; padding: 8px 10px; text-align: left; color: var(--text-secondary); font-size: 0.76rem; font-weight: 600; }}
    .hist-table td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }}
    .hist-table tr:hover td {{ background: rgba(37,99,235,0.03); }}
    .fact-card {{ background: rgba(59,130,246,0.05); border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; padding: 10px 16px; margin: 8px 0; font-size: 0.88rem; color: var(--text-secondary); line-height:1.65; }}
    .year-badge {{ display: inline-block; background: var(--accent); color: #fff; font-size: 0.75rem; font-weight: 700; padding: 2px 10px; border-radius: 20px; margin-right: 8px; }}
    .toc-nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }}
    .toc-nav a {{ padding: 6px 14px; border: 1px solid var(--border); border-radius: 20px; font-size: 0.83rem; color: var(--text-secondary); text-decoration: none; transition: all 0.2s; background: #ffffff; }}
    .toc-nav a:hover {{ border-color: var(--accent); color: var(--accent); }}
    .photo-caption {{ font-size:0.78rem; color:var(--text-dim); margin:-4px 0 12px; font-style:italic; }}
    .myth-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:16px; margin-top:16px; }}
    .myth-card {{ border-radius:12px; padding:16px; background:var(--bg-card); border:1px solid var(--border); box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
    .myth-card.myth-false {{ border-left:4px solid #ef5350; }}
    .myth-card.myth-mixed {{ border-left:4px solid #ffb74d; }}
    .myth-label {{ font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:6px; }}
    .myth-card.myth-false .myth-label {{ color:#ef5350; }}
    .myth-card.myth-mixed .myth-label {{ color:#ffb74d; }}
    .myth-card h4 {{ font-size:0.92rem; font-weight:600; color:var(--text-primary); margin:0 0 10px; line-height:1.4; }}
    .myth-reality {{ font-size:0.84rem; color:var(--text-secondary); line-height:1.65; }}
    .myth-reality strong {{ color:#81c784; }}
  </style>
</head>
<body>

{_build_nav('history')}

<div class="container">
<h1>📜 История паводков реки Оки</h1>
<p style="color:var(--text-secondary); margin-bottom:8px; line-height:1.75;">
  Ока — крупнейший правый приток Волги. Длина 1498&nbsp;км, бассейн 245 тысяч км² —
  примерно площадь Румынии. Она берёт начало в деревне Александровка Орловской области,
  на высоте 226&nbsp;м, и несёт воды через семь регионов до впадения в Волгу у Нижнего Новгорода.
</p>
<p style="color:var(--text-secondary); margin-bottom:16px; line-height:1.75;">
  Половодье здесь — явление весеннее и снеговое. На бассейне Оки каждую зиму накапливается
  от 60 до 200&nbsp;мм воды в снежном покрове. Когда многоснежная зима сменяется дружной
  весной без ночных заморозков — река демонстрирует всё, на что способна. Пик половодья в
  верховьях традиционно приходится на начало апреля, в районе Серпухова — на середину
  и конец апреля, хотя в 2023&nbsp;году он пришёлся на 1&nbsp;апреля — почти на месяц раньше нормы.
</p>

<div class="fact-card" style="margin-bottom:16px;">
  <b>Сокращения:</b>
  <b>НЯ</b> — неблагоприятное гидрологическое явление (выход воды на пойму) |
  <b>ОЯ</b> — опасное явление (подтопление населённых пунктов) |
  <b>БС</b> — Балтийская система высот |
  <b>ЦУГМС</b> — Центральное управление по гидрометеорологии и мониторингу окружающей среды
</div>


<div style="margin:16px 0 24px; text-align:center;">
  <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('oka_river_spring', '')}" alt="Река Ока весной" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
  <div class="photo-caption">Река Ока в весеннее половодье</div>
</div>

<nav class="toc-nav">
  <a href="#flood-1908">1908 — Великий</a>
  <a href="#flood-1970">1970 — Советский</a>
  <a href="#flood-1979">1979 — Девятиэтажки</a>
  <a href="#flood-1994">1994 — Рекорд Белёва</a>
  <a href="#flood-2013">2013 — Рекорд XXI в.</a>
  <a href="#flood-2023">2023 — Ранний</a>
  <a href="#flood-2024">2024 — Новый рекорд</a>
  <a href="#dams">Плотины</a>
  <a href="#curious">Интересные факты</a>
  <a href="#records-table">Таблица рекордов</a>
  <a href="#myths">Мифы о плотинах</a>
</nav>

<!-- ═══════════════════ 1908 ═══════════════════ -->
<div class="section-card hist-section" id="flood-1908">
  <h2><span class="year-badge">1908</span>Великий паводок — Абсолютный рекорд</h2>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,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" alt="Историческое наводнение 1908 года" style="width:100%; max-width:600px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.15);">
    <div class="photo-caption">Историческое наводнение на Оке</div>
  </div>
  <p>В апреле 1908&nbsp;года Ока решила напомнить жителям, кто здесь настоящий хозяин.
  Зима задалась необычно многоснежной и морозной — к марту снег лежал плотным покрывалом
  на всём огромном бассейне. А потом вдруг — в один день — обернулась тёплой,
  почти летней весной. Ни ночных заморозков, ни медленного постепенного таяния.
  Всё сразу. Снег таял не по дням, а по часам. Плюс весенние дожди.
  «Идеальный шторм» по всем гидрологическим параметрам.</p>

  <p>Газета «Раннее утро» от 13 (26) апреля 1908 года писала о Серпухове:
  <em>«Не меньшее бедствие постигло и побережье реки Оки. Город Серпухов тоже почти весь в воде,
  все фабричные здания Коншинской мануфактуры, расположенные сравнительно на возвышенной
  местности, затоплены по второй этаж».</em></p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Город</th><th>Уровень</th><th>Дата пика</th><th>Последствия</th></tr></thead>
    <tbody>
      <tr><td>Орёл</td><td>908–1005&nbsp;см*</td><td>Апрель</td><td>Дома на «Стрелке» по первый этаж; нижняя часть города под водой</td></tr>
      <tr><td>Белёв</td><td>Очень высокий</td><td>8–9 апреля</td><td>Ледоход + наводнение ночью; купец Сабинин — убыток 10&nbsp;тыс. руб.</td></tr>
      <tr><td>Калуга</td><td>16&nbsp;м 77&nbsp;см над летним горизонтом</td><td>25 апреля</td><td>Абсолютный рекорд за всё время наблюдений с 1877&nbsp;года</td></tr>
      <tr><td>Таруса</td><td>Очень высокий</td><td>Апрель</td><td>Вода залила полы Петропавловского собора, казначейство, торговые ряды</td></tr>
      <tr><td><b>Серпухов</b></td><td><b>1256&nbsp;см</b></td><td>Апрель</td><td>Абсолютный исторический рекорд; 6 фабрик, 70 домов под водой</td></tr>
    </tbody>
  </table>
  </div>

  <div class="fact-card">
    *Данные по Орлу расходятся: orelvkartinkax.ru даёт 908&nbsp;см, другие источники — 1005&nbsp;см.
    Расхождение, по-видимому, объясняется разными привязками к нулю поста. Без архивных первоисточников
    разрешить его невозможно.
  </div>

  <p>В Калуге на стене завода КЭМЗ долгие годы висела металлическая табличка с отметкой
  уровня 1908&nbsp;года. Для рабочих это был живой аргумент в споре «да что за паводок
  какой-то» — достаточно было показать на эту дощечку в двух метрах над головой.</p>

  <p>В Москве тот же паводок поднял воду на 8,9&nbsp;м, затопил около 16&nbsp;км² столицы
  и повредил около 25&nbsp;000 сооружений. Причина повсюду одна — аномально
  многоснежная зима, дружная весна без заморозков, дожди в период таяния. Три кита
  катастрофического паводка, и все три совпали в один сезон.</p>

  <div class="fact-card">
    📰 Источники: <a href="https://www.orelvkartinkax.ru/bigwater.htm" target="_blank" rel="noopener">orelvkartinkax.ru</a> — история орловских наводнений;
    <a href="https://snegochistka.ru/articles/iz_letopisi_katastrof_kaluzhskoi_oblasti" target="_blank" rel="noopener">snegochistka.ru</a> — летопись Калужской области;
    <a href="https://dzen.ru/b/ZHT6XvNuLircyfDX" target="_blank" rel="noopener">Дзен — фото Серпухова 1908 года</a>
  </div>
</div>

<!-- ═══════════════════ 1970 ═══════════════════ -->
<div class="section-card hist-section" id="flood-1970">
  <h2><span class="year-badge">1970</span>Советский паводок — Второй по величине</h2>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('flood_1970s_soviet', '')}" alt="Паводок 1970 года — советский рекорд" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div class="photo-caption">Паводок 1970 года на Оке</div>
  </div>
  <p>Весной 1970&nbsp;года советский Орёл готовился к 100-летию со дня рождения Ленина.
  Первомайские транспаранты уже печатали, речи репетировали, концертные программы
  утверждали. Ока, однако, о юбилее не слышала — у неё было своё расписание.</p>

  <p><b>5&nbsp;апреля 1970&nbsp;года</b> вода в Орле перевалила за <b>10&nbsp;метров</b> (1010&nbsp;см),
  установив абсолютный рекорд для города. По улицам пошёл лёд с Оки. В городе ввели
  чрезвычайное положение. Орловский обком КПСС написал в ЦК письмо — просил отменить
  праздничные мероприятия. ЦК ответил уже после того, как торжества прошли. Водная стихия
  оказалась более оперативной, чем советская бюрократия.</p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Показатель</th><th>Данные</th></tr></thead>
    <tbody>
      <tr><td>Орёл — уровень</td><td>1010&nbsp;см (абсолютный рекорд для Орла; 5 апреля)</td></tr>
      <tr><td>Орёл — подтоплено улиц</td><td>29</td></tr>
      <tr><td>Орёл — подтоплено домов</td><td>913 жилых домов</td></tr>
      <tr><td>Орёл — предприятия</td><td>21 предприятие, 3 школы, 3 детских сада, медучилище</td></tr>
      <tr><td>Орёл — инфраструктура</td><td>16 мостов, 5 водозаборных узлов, КНС</td></tr>
      <tr><td>Орёл — эвакуировано</td><td>1195 человек</td></tr>
      <tr><td>Орёл — погибло</td><td>Мать с сыном утонули на улице Свободы, спасая вещи</td></tr>
      <tr><td>Калуга</td><td>15&nbsp;м 25&nbsp;см (13 апреля) — второй по высоте рекорд</td></tr>
      <tr><td><b>Серпухов</b></td><td><b>1208&nbsp;см</b> — второй исторический рекорд</td></tr>
    </tbody>
  </table>
  </div>

  <p>По улице Московской в Орле ходили на лодках — мимо универмага и кинотеатра «Родина».
  По Оке плыли дачные домики, вырванные с корнем деревья. В Калуге, у остановки КЭМЗ,
  вода достигала крыши троллейбуса — это не метафора, а задокументированный факт на видеозаписи
  из семейного архива читателя «КП-40» Юрия Уральского, снятой его отцом.</p>

  <div class="fact-card">
    🐀 <b>Крысы как сигнализация:</b> в ночь перед наводнением один загулявший орловец
    наткнулся на сотни крыс, покрывших его путь живым серым ковром. Они мчали из нижних
    хибар наверх, в Егорьевскую горку. Через час хибары были залиты. Крысы оказались
    точнее любого гидрологического прогноза — и, по правде говоря, их нервная система
    работала без перебоев в отличие от телефонных линий.
  </div>
  <div class="fact-card">
    🐄 <b>Спасение коровы:</b> дородную бурёнку, растопырившую копыта по льдине,
    народ кинулся спасать. Льдину прибило к берегу у завода гладильных прессов.
    Корове накинули на рога верёвку и под общие аплодисменты вывели на сухое.
    Она, спасённая, подогнула колени и полчаса лежала без сил. Орловские газеты
    описывали этот эпизод с нескрываемой нежностью.
  </div>

  <p><b>Причина паводка</b>: запасы воды в снеге вдвое выше нормы + позднее и дружное
  снеготаяние + большие осадки в период половодья (в 1,5–2,0 раза выше нормы).
  Всё те же три кита, что и в 1908-м. После 1970&nbsp;года обветшавшие домишки по берегам
  Оки и Орлика были снесены, набережные забетонированы — и последующие, тоже мощные
  паводки уже не причиняли столь сильных разрушений. Иными словами, урок был усвоен —
  хотя и дорогой ценой.</p>

  <div class="fact-card">
    📰 Источники: <a href="https://www.orelvkartinkax.ru/bigwater.htm" target="_blank" rel="noopener">orelvkartinkax.ru</a>;
    <a href="https://www.kp40.ru/news/society/89696/" target="_blank" rel="noopener">KP40.ru — уникальное видео разлива 1970 года</a>;
    <a href="https://newsorel.ru/fn_1644685.html" target="_blank" rel="noopener">newsorel.ru — 55 лет наводнению 1970</a>
  </div>
</div>

<!-- ═══════════════════ 1979 ═══════════════════ -->
<div class="section-card hist-section" id="flood-1979">
  <h2><span class="year-badge">1979</span>Год отрезанных девятиэтажек</h2>
  <p>Через девять лет после «великого» советского наводнения Ока нанесла ещё один,
  хотя и менее катастрофический визит. Уровень в Орле составил <b>985&nbsp;см</b> —
  третий по величине исторический результат для города.</p>

  <p>Примечательная деталь: к тому времени на улице Революции уже стояли новые
  девятиэтажные панельные дома, возведённые взамен снесённых после 1970&nbsp;года лачуг.
  В 1979&nbsp;году жители этих девятиэтажек оказались отрезаны от мира — вода окружила
  дома со всех сторон. Продукты и почту доставляли на лодках прямо к подъездам,
  на первый этаж. Советская плановая экономика не предусмотрела в бюджете статью
  «доставка хлеба на вёслах», но жизнь оказалась изобретательнее планировщиков.</p>

  <div class="fact-card">
    📰 Источник: <a href="https://istoki.tv/news/istoricheskiy-orel/istoriya-orlovskikh-navodneniy/" target="_blank" rel="noopener">Истоки.ТВ — история орловских наводнений</a>
  </div>
</div>

<!-- ═══════════════════ 1994 ═══════════════════ -->
<div class="section-card hist-section" id="flood-1994">
  <h2><span class="year-badge">1994</span>Рекорд верховьев — последний крупный паводок XX&nbsp;века</h2>
  <p>1994&nbsp;год стал последним по-настоящему крупным паводком XX&nbsp;века для верхней
  части бассейна. По ряду показателей он превзошёл все предыдущие — по крайней мере
  в официально измеренных данных.</p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Гидропост</th><th>Уровень</th><th>Порог НЯ</th><th>Примечания</th></tr></thead>
    <tbody>
      <tr><td>Белёв</td><td>~1250&nbsp;см*</td><td>1155&nbsp;см</td><td>Предполагаемый абсолютный рекорд у Белёва</td></tr>
      <tr><td>Алексин (Щукина)</td><td>~1155&nbsp;см</td><td>1120&nbsp;см</td><td>НЯ превышен</td></tr>
      <tr><td>Орёл</td><td>935&nbsp;см</td><td>880&nbsp;см</td><td>29 улиц, 654 дома, 2 школы</td></tr>
      <tr><td>Орёл — зона затопления</td><td>—</td><td>—</td><td>3120 человек в зоне затопления, эвакуировано 65</td></tr>
    </tbody>
  </table>
  </div>

  <p>Вода дошла до дорожного полотна улицы Городской в Орле. Это уже не поэзия —
  это конкретная городская артерия, по которой в обычное время ездят машины.
  После 1994&nbsp;года следующие 18–20 лет Ока у Серпухова практически не выходила
  на пойму — малоснежные зимы сделали своё дело. Именно в эти тихие годы многие
  дачники и купили участки в пойме, не подозревая, что «обычное» половодье —
  это исторически ненормальное затишье.</p>

  <div class="fact-card">
    📰 Источники: <a href="https://www.tula.kp.ru/daily/27248/4377180/" target="_blank" rel="noopener">КП-Тула</a>;
    <a href="https://www.orelvkartinkax.ru/bigwater.htm" target="_blank" rel="noopener">orelvkartinkax.ru</a>
  </div>
</div>

<!-- ═══════════════════ 2013 ═══════════════════ -->
<div class="section-card hist-section" id="flood-2013">
  <h2><span class="year-badge">2013</span>Рекорд XXI века — Апрельское возвращение Оки</h2>
  <p>В апреле 2013&nbsp;года Ока поставила новый инструментальный рекорд — первый в XXI&nbsp;веке,
  заставивший вспомнить о «стариках» 1908 и 1970. Паводковая волна шла сверху вниз
  с задержкой в 1–2 дня между гидропостами — наглядная демонстрация того, что паводок
  это не цунами, а медленная, неотвратимая волна.</p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Гидропост</th><th>Максимум</th><th>Дата пика</th><th>Примечания</th></tr></thead>
    <tbody>
      <tr><td>Калуга</td><td>919&nbsp;см</td><td>21 апреля</td><td>Набережная затоплена; нижний ярус под водой</td></tr>
      <tr><td>Алексин (Щукина)</td><td>1069&nbsp;см</td><td>21 апреля</td><td>Рекорд для поста</td></tr>
      <tr><td>Серпухов</td><td><b>843&nbsp;см</b></td><td>23 апреля</td><td>Рекорд XXI века для Серпухова (до 2024 года)</td></tr>
      <tr><td>Кашира</td><td>792&nbsp;см</td><td>23 апреля</td><td>Рекорд для поста</td></tr>
      <tr><td>Коломна</td><td>633&nbsp;см</td><td>24 апреля</td><td>Рекорд для поста; выше порога НЯ (615 см)</td></tr>
      <tr><td>Белоомут (нижний бьеф)</td><td>905&nbsp;см</td><td>29 апреля</td><td>Серьёзное испытание для старой плотины</td></tr>
    </tbody>
  </table>
  </div>

  <p>Наглядный маршрут паводковой волны 2013: Калуга → Серпухов → Кашира → Коломна,
  каждый раз с задержкой в 1–2 суток и небольшим затуханием высоты. В Коломне уровень
  633&nbsp;см превысил порог НЯ (615&nbsp;см) и оказался абсолютным рекордом за весь период
  цифровых наблюдений.</p>

  <p>В Калуге уровень 692&nbsp;см (18 апреля) рос со скоростью +91&nbsp;см/сутки —
  за двое суток набережная ушла под воду. На гидроузле «Белоомут» вода поднялась
  более чем на 4&nbsp;метра от нормы — серьёзное испытание для старой плотины,
  которой на тот момент было почти 100&nbsp;лет.</p>

  <div class="fact-card">
    📰 Источники:
    <a href="https://allrivers.info/gauge/oka-serpuhov/waterlevel/" target="_blank" rel="noopener">allrivers.info — Серпухов</a>;
    <a href="https://kaluga24.tv/news/001330" target="_blank" rel="noopener">Калуга24 — апрель 2013</a>;
    <a href="https://ya-kraeved.ru/pavodok-na-oke-dostig-svoego-pika/" target="_blank" rel="noopener">ya-kraeved.ru — паводок на Оке 2013</a>
  </div>
</div>

<!-- ═══════════════════ 2023 ═══════════════════ -->
<div class="section-card hist-section" id="flood-2023">
  <h2><span class="year-badge">2023</span>Аномально ранний паводок — март вместо апреля</h2>
  <p>Половодье-2023 отличилось тем, чем удивить непросто — оно пришло в
  <b>середине марта</b>, почти на месяц раньше привычных апрельских сроков.
  В Серпухове за одну неделю (с 14&nbsp;марта) вода поднялась на 1,6&nbsp;метра.
  Даже у Рязани — на 250&nbsp;км ниже по течению — пик зафиксирован 31&nbsp;марта:
  уровень 5&nbsp;м 22&nbsp;см, что выше пика 2022&nbsp;года (5&nbsp;м 10&nbsp;см).</p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Показатель</th><th>Данные</th></tr></thead>
    <tbody>
      <tr><td>Серпухов — пик</td><td><b>780&nbsp;см</b> (1 апреля; ранний рекорд)</td></tr>
      <tr><td>Калуга</td><td>775&nbsp;см (максимум 2021–2024&nbsp;гг.)</td></tr>
      <tr><td>Алексин</td><td>705–775&nbsp;см</td></tr>
      <tr><td>Белёв</td><td>685&nbsp;см (максимум 2021–2024&nbsp;гг.)</td></tr>
      <tr><td>Кашира</td><td>524&nbsp;см</td></tr>
      <tr><td>Коломна</td><td>577&nbsp;см (рекорд 2021–2024; 25–26 марта — 426–490 см, рекорд на эту дату за 20 лет)</td></tr>
      <tr><td>Запасы снега (бассейн)</td><td>120% нормы</td></tr>
      <tr><td>Температура</td><td>+3°C выше нормы (март 2023)</td></tr>
    </tbody>
  </table>
  </div>

  <p>Январь 2023&nbsp;года тоже удивил: необычный зимний паводок — уровень воды выше
  летнего. Очевидцы называли это явление небывалым: снег залёг на пресыщенную влагой
  почву после тёплого ноября–декабря, а потом затяжная оттепель согнала воду прямо
  в реку ещё до настоящей весны.</p>

  <div class="fact-card">
    📅 Пик паводка прошёл почти на месяц раньше исторических сроков. Изменение климата
    сдвигает сроки весенних паводков: если раньше Ока выходила на пойму в конце апреля,
    то 2023 и 2024&nbsp;годы показали пик уже в начале апреля и даже конце марта.
  </div>

  <div class="fact-card">
    📰 Источники:
    <a href="https://www.oka.fm/new/read/social/Oka-v-Serpuhove-pokazyvaet-bystryj-podem-vody/" target="_blank" rel="noopener">oka.fm — Серпухов 2023</a>;
    <a href="https://www.kp40.ru/news/society/99119/" target="_blank" rel="noopener">KP40.ru — нейросеть раскрасила фото разлива 2023</a>
  </div>
</div>

<!-- ═══════════════════ 2024 ═══════════════════ -->
<div class="section-card hist-section" id="flood-2024">
  <h2><span class="year-badge">2024</span>Новый рекорд XXI века — Серпухов, 850 сантиметров</h2>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('flood_2024_modern', '')}" alt="Паводок 2024 года — новый рекорд" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div class="photo-caption">Рекордный паводок 2024 года</div>
  </div>
  <p>2024&nbsp;год переписал рекордную книгу XXI&nbsp;века для Серпухова. Уровень достиг
  <b>~850&nbsp;см</b> — побив рекорд 2013&nbsp;года (843&nbsp;см). Официально подтверждено
  главой Серпуховского округа Алексеем Шимко: «В 2024 году паводок достиг максимальной
  отметки в 850&nbsp;см, но благодаря заблаговременной подготовке последствия удалось
  минимизировать без происшествий».</p>

  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Показатель</th><th>Данные</th></tr></thead>
    <tbody>
      <tr><td><b>Серпухов — пик</b></td><td><b>~850&nbsp;см</b> (новый рекорд XXI в.; апрель 2024)</td></tr>
      <tr><td>Серпухов — глубина затопления поймы</td><td>от 135&nbsp;см (мкр. Слобода, Заборье)</td></tr>
      <tr><td>Калуга</td><td>&gt;781&nbsp;см (3 апреля); +75&nbsp;см/сутки в пиковые дни</td></tr>
      <tr><td>Кашира</td><td>634&nbsp;см (3 апреля)</td></tr>
      <tr><td>Коломна</td><td>~536&nbsp;см (критический уровень 420&nbsp;см превышен)</td></tr>
      <tr><td>Рекорд суточного прироста (Калуга)</td><td>+132&nbsp;см/сутки (27 марта) — рекорд сезона</td></tr>
      <tr><td>Жиздра / Угра</td><td>+35&nbsp;см/сутки; Жиздра — рекордные 866&nbsp;см</td></tr>
      <tr><td>Ранова у с. Троица (Рязанская обл.)</td><td>+108&nbsp;см/сутки — рекордный прирост</td></tr>
    </tbody>
  </table>
  </div>

  <p>При уровне 8,5&nbsp;м в Серпухове начинается подтопление частного сектора в мкр. Слобода
  и Заборье, предприятий на улицах Тульской и 2-й Московской. В Калуге затопило набережную —
  нижний ярус, дорога к пляжу, зоны отдыха у Гагаринского моста. Паводок 2024&nbsp;года в
  Рязанской области отрезал деревни от «большой земли»: в Тарусском районе на дороге
  Залужье стояло 200&nbsp;метров воды, организована круглосуточная переправа.</p>

  <img src="https://msk1.ru/wp-content/uploads/2024/04/05/serpuhov_park_flood_2024.jpg"
       alt="Затопленный Принарский парк в Серпухове, апрель 2024"
       loading="lazy"
       style="max-width:100%;border-radius:12px;margin:12px 0;"
       onerror="this.style.display='none'">
  <p class="photo-caption">Принарский парк в Серпухове под водой, апрель 2024.
    Источник: <a href="https://msk1.ru/text/incidents/2024/04/05/73430921/" target="_blank" rel="noopener">MSK1.ru</a></p>

  <div class="fact-card">
    🏖️ <b>«Серпуховские Мальдивы»:</b> городской пляж, открытый летом 2023&nbsp;года —
    белый песок, шезлонги, детские площадки — полностью ушёл под воду. Местные жители
    окрестили затопленную пойму «Серпуховскими Мальдивами» — за живописные виды разлива.
    Название подхватили СМИ. Рабочие потом долго убирали мусор и восстанавливали
    инфраструктуру. МЧС юмора не оценило.
  </div>

  <div class="fact-card">
    📰 Источники:
    <a href="https://regions.ru/serpuhov/proisshestvie/rekordnyy-pavodok-2024-oka-zatopila-serpuhovskie-maldivy" target="_blank" rel="noopener">REGIONS.ru — рекордный паводок 2024</a>;
    <a href="https://msk1.ru/text/incidents/2024/04/05/73430921/" target="_blank" rel="noopener">MSK1.ru — Серпухов апрель 2024</a>;
    <a href="https://kalugafoto.net/kaluga/krasivaya-kaluga/3776-razliv-oki-naberezhnaya-oki-v-kaluge-2-aprelya-2024" target="_blank" rel="noopener">kalugafoto.net — набережная Калуги 2 апреля 2024</a>
  </div>
</div>

<!-- ═══════════════════ ПЛОТИНЫ ═══════════════════ -->
<div class="section-card hist-section" id="dams">
  <h2>🏗️ Плотины и человеческий фактор</h2>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('dam_hydroelectric', '')}" alt="Гидроузлы на Оке" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div class="photo-caption">Гидроузел на реке Оке</div>
  </div>

  <h3>Кузьминский гидроузел: история и судьба</h3>
  <p>Первый Кузьминский гидроузел был построен в <b>1911–1915&nbsp;годах</b> по проекту
  выдающегося гидротехника Нестора Пузыревского — вместе с Белоомутским. Единственная
  цель: поддерживать необходимые для судоходства глубины на участке Оки до Коломны.
  Никаких противопаводковых функций изначально не предусматривалось.</p>

  <p>К 2000-м годам старый гидроузел пришёл в аварийное состояние: с 1981 по 2015&nbsp;год
  он не удерживал нормальный подпорный уровень, что создавало мелководье для судов.
  В <b>2013–2015&nbsp;годах</b> рядом с деревней Аксёново построен <b>Новый Кузьминский
  гидроузел</b>, введённый в эксплуатацию 16&nbsp;октября 2015&nbsp;года. После его ввода
  старая плотина оказалась частично затоплена. За год паводка вода промыла яму глубиной
  <b>11&nbsp;метров</b> — вовремя заметили и успели принять меры. Своеобразное «плотинозамещение».</p>

  <h3>Белоомутский гидроузел: долгострой с приключениями</h3>
  <p>Построен в 1911–1915&nbsp;годах одновременно с Кузьминским. В 2015&nbsp;году началась
  комплексная реконструкция стоимостью 5,54&nbsp;млрд рублей. И тут начались приключения.</p>

  <p><b>Инцидент апреля 2018&nbsp;года:</b> 9&nbsp;апреля 2018&nbsp;года на строительной площадке
  под давлением паводковых вод разошлась шпунтовая стенка — специальное ограждение
  монтажного котлована. Котлован был затоплен. Видео разошлось по интернету, породив
  настоящую панику у жителей ниже по течению. Однако, как позже объяснили представители
  «Канала имени Москвы», затопление строительного котлована было <em>предусмотрено
  проектом</em> — гидроузел является затапливаемым, паводковые воды проходят через
  все его сооружения. Реальной угрозы прорыва не было.</p>

  <p>Тем не менее старая плотина к тому моменту находилась в аварийном состоянии:
  бетон устоев трескался, более 10% ферм требовали срочной замены, плотина второй год
  находилась в поднятом положении — опустить её было невозможно из-за риска, что
  не поднимут обратно. А генподрядчик реконструкции тем временем объявил о банкротстве,
  не завершив работ. Стройка была заброшена. Ввод в эксплуатацию переносился несколько раз.</p>

  <p>В 2018&nbsp;году произошёл также прорыв дамбы между старой и новой камерой шлюзов.
  В зону подтопления попали сёла Окское, Ловцы, Любичи и Слемские Борки — небольшие,
  но от этого не менее потопленные.</p>

  <div class="fact-card">
    📰 Источники:
    <a href="https://www.mk.ru/social/2019/07/04/stroyka-na-oke-grozit-paralichom-sudokhodstva-i-proryvom-plotiny.html" target="_blank" rel="noopener">МК — стройка на Оке, 2019</a>;
    <a href="https://cruiseinform.ru/info/news/11/" target="_blank" rel="noopener">cruiseinform.ru — Белоомут 2018</a>;
    <a href="https://ru.wikipedia.org/wiki/%D0%9A%D1%83%D0%B7%D1%8C%D0%BC%D0%B8%D0%BD%D1%81%D0%BA%D0%B8%D0%B9_%D0%B3%D0%B8%D0%B4%D1%80%D0%BE%D1%83%D0%B7%D0%B5%D0%BB" target="_blank" rel="noopener">Кузьминский гидроузел — Википедия</a>
  </div>
</div>

<!-- ═══════════════════ ЛЮБОПЫТНЫЕ ФАКТЫ ═══════════════════ -->
<div class="section-card hist-section" id="curious">
  <h2>🎲 Интересные факты и рекорды</h2>

  <h3>Рекорды суточного подъёма</h3>
  <div class="table-wrap">
  <table class="hist-table">
    <thead><tr><th>Место</th><th>Прирост</th><th>Дата</th></tr></thead>
    <tbody>
      <tr><td>Ранова у с. Троица</td><td>+108&nbsp;см/сутки</td><td>30 марта 2024</td></tr>
      <tr><td>Калуга</td><td>+132&nbsp;см/сутки</td><td>27 марта 2024</td></tr>
      <tr><td>Серпухов</td><td>+39&nbsp;см/сутки</td><td>март 2023</td></tr>
      <tr><td>Луховицкий р-н (2026)</td><td>+75&nbsp;см за 2 суток</td><td>март 2026</td></tr>
    </tbody>
  </table>
  </div>

  <h3>Рекорды ранних паводков в Орле</h3>
  <div class="fact-card">
    📅 Исторически самый ранний ледоход в Орле — <b>12 февраля</b>. Самый поздний — <b>24 апреля</b>.
    Паводок 2023&nbsp;года начался в середине марта — на месяц раньше средних сроков.
    Паводок 2016&nbsp;года в Орле тоже был ранним: мост на Гати затопило уже 5&nbsp;марта.
  </div>

  <h3>Летопись катастроф: цитата XVII века</h3>
  <div class="fact-card">
    🏰 В XVII&nbsp;веке из Орла писали воеводе:
    <em>«Старый город Орел поставлен в низком месте... в полую воду казенный погреб заливает
    и зелейную казну во все годы от воды выносят вон на городскую стену».</em>
    Прошло 400&nbsp;лет — проблема паводков никуда не делась.
  </div>

  <h3>Обмеление Оки — парадокс</h3>
  <p style="color:var(--text-secondary); font-size:0.9rem; line-height:1.75;">
    За последние десятилетия Ока значительно обмелела в межень — причина: добыча
    песка и гравия земснарядами начиная с 1960-х годов. На участке Коломна—Половское
    изъято более <b>40&nbsp;млн м³</b> русловых отложений. Меженный уровень упал на
    0,5–2,1&nbsp;м. Парадокс: река стала глубже (3–13&nbsp;м в ямах), но воды в ней
    стало меньше. Судоходство деградировало. Паводки, однако, никуда не делись —
    потому что определяются объёмом снеготаяния в бассейне, а не глубиной русла.
  </p>

  <h3>Белёвская «Робинзонада», 1903</h3>
  <div class="fact-card">
    🚣 В 1903&nbsp;году трое приятелей в Белёве, «хорошенько повеселившись», отправились
    на лодке по разлившейся Оке. Гребец уронил вёсла. Лодку унесло на пойменный остров.
    Пришлось ждать спасателей — несколько часов, которые, по воспоминаниям участников,
    показались значительно дольше.
  </div>

  <h3>Ледоход как 14-летний фотопроект</h3>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('ice_breakup_oka', '')}" alt="Ледоход на Оке" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div class="photo-caption">Ледоход на реке Оке</div>
  </div>
  <p style="color:var(--text-secondary); font-size:0.9rem; line-height:1.75;">
    Местный житель Ступина вёл фотоархив ледохода на Оке на протяжении <b>14 лет подряд</b> —
    с 2012 по 2026&nbsp;год, фиксируя дату начала каждый год.
    В 2026&nbsp;году ледоход в Ступине начался 24&nbsp;марта — в пределах нормы.
    (<a href="https://regions.ru/stupino/socialnaya_sfera/fotoohota-dlinoj-v-14-let-zhitel-stupina-dokazal-chto-ledohod-2026-na-oke-ne-pobil-rekord" target="_blank" rel="noopener">regions.ru</a>)
  </p>
</div>

<!-- ═══════════════════ ТАБЛИЦА РЕКОРДОВ ═══════════════════ -->
<div class="section-card hist-section" id="records-table">
  <h2>📊 Сводная таблица рекордов</h2>
  <div class="table-wrap">
  <table class="hist-table">
    <thead>
      <tr>
        <th>Гидропост</th>
        <th>Абс. максимум</th>
        <th>Год</th>
        <th>Порог НЯ</th>
        <th>Нуль поста (БС)</th>
      </tr>
    </thead>
    <tbody>
      <tr><td>Орёл</td><td>~1005–1010&nbsp;см*</td><td>1970 (1908)</td><td>880&nbsp;см</td><td>146.31&nbsp;м</td></tr>
      <tr><td>Мценск (р.Зуша)</td><td>1275&nbsp;см*</td><td>н/д</td><td>900&nbsp;см</td><td>н/д</td></tr>
      <tr><td>Белёв</td><td>~1250&nbsp;см (1994)* / 1100&nbsp;см (2003)</td><td>1994/2003</td><td>1155&nbsp;см</td><td>127.15&nbsp;м</td></tr>
      <tr><td>Калуга</td><td>919&nbsp;см (совр.) / 1677&nbsp;см (1908, от межени)</td><td>2013/1908</td><td>1100&nbsp;см</td><td>116.72&nbsp;м</td></tr>
      <tr><td>Алексин (Щукина)</td><td>1069&nbsp;см</td><td>2013</td><td>1120&nbsp;см</td><td>111.19&nbsp;м</td></tr>
      <tr><td><b>Серпухов (Лукьяново)</b></td><td><b>850&nbsp;см (XXI&nbsp;в.) / 1256&nbsp;см (1908, ист.)</b></td><td>2024/1908</td><td>645&nbsp;см (НЯ), 800&nbsp;см (ОЯ)</td><td>107.54&nbsp;м</td></tr>
      <tr><td>Кашира</td><td>792&nbsp;см</td><td>2013</td><td>918&nbsp;см</td><td>103.82&nbsp;м</td></tr>
      <tr><td>Коломна</td><td>633&nbsp;см</td><td>2013</td><td>615&nbsp;см</td><td>100.26&nbsp;м</td></tr>
    </tbody>
  </table>
  </div>
  <p style="font-size:0.78rem; color:var(--text-dim);">
    *Данные из исторических и краеведческих источников, не из современного гидрологического архива.
    Современный цифровой архив: <a href="https://allrivers.info/river/oka" target="_blank" rel="noopener">allrivers.info</a>
  </p>

  <h3>Ключевые закономерности</h3>
  <div class="fact-card">
    🌊 <b>Паводковая волна движется сверху вниз</b> со скоростью около 1–2 суток на 100&nbsp;км.
    Пик в Калуге — примерно 21&nbsp;апреля, в Серпухове — 23&nbsp;апреля, в Кашире — 23–24&nbsp;апреля,
    в Коломне — 24–25&nbsp;апреля (данные 2013&nbsp;года).
  </div>
  <div class="fact-card">
    🌡️ <b>Главные условия катастрофического паводка:</b> снежный запас в 1,5–2 раза выше нормы
    + резкое потепление без ночных заморозков + осадки в период таяния. Именно это сочеталось
    в 1908, 1970 и 2013&nbsp;годах.
  </div>
  <div class="fact-card">
    📅 <b>Тренд к более ранним паводкам:</b> исторически пик приходился на конец апреля;
    в 2023&nbsp;году — 1&nbsp;апреля в Серпухове. Изменение климата сдвигает сроки.
  </div>
  <div class="fact-card">
    ⚠️ <b>XXI&nbsp;век обновляет рекорды:</b> паводок 2013&nbsp;года поставил современные
    инструментальные рекорды на большинстве постов. Паводок 2024&nbsp;года в Серпухове
    превысил рекорд 2013&nbsp;года.
  </div>
  <div class="fact-card">
    📉 <b>Обмеление vs паводки:</b> несмотря на общее обмеление Оки в межень (добыча песка),
    паводковые уровни остаются высокими — потому что определяются объёмом снеготаяния
    в бассейне, а не глубиной русла в спокойное время.
  </div>
</div>

<!-- ═══════════════════ МИФЫ ═══════════════════ -->
<div class="section-card hist-section" id="myths">
  <h2>🔍 Мифы о дамбах и паводках: разбор по пунктам</h2>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('sandbag_protection', '')}" alt="Защита от паводка" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div class="photo-caption">Подготовка к паводку — мешки с песком</div>
  </div>
  <p style="color:var(--text-secondary); font-size:0.9rem; margin-bottom:4px;">
    Каждую весну в чатах и на форумах расцветает целая мифология о плотинах, водохранилищах
    и «злых умыслах». Разбираем семь главных заблуждений — с фактами и ссылками.
  </p>

  <div class="myth-grid">

    <div class="myth-card myth-false">
      <div class="myth-label">❌ МИФ</div>
      <h4>«Кузьминскую плотину открыли/закрыли — вот из-за этого и затопило»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Кузьминский гидроузел находится в 250+ км <em>ниже</em>
        Серпухова по течению — у сёл Константиново и Аксёново в Рязанской области.
        Он физически не способен влиять на уровень воды <em>выше</em> себя. В половодье
        все затворы полностью открываются — гидроузел просто пропускает паводковый расход
        насквозь. Подъём воды у Серпухова в 2024 году до 850 см определялся количеством снега,
        темпом таяния и водоотдачей бассейна, но не Кузьминской плотиной.
        (<a href="https://ru.wikipedia.org/wiki/%D0%9A%D1%83%D0%B7%D1%8C%D0%BC%D0%B8%D0%BD%D1%81%D0%BA%D0%B8%D0%B9_%D0%B3%D0%B8%D0%B4%D1%80%D0%BE%D1%83%D0%B7%D0%B5%D0%BB" target="_blank" rel="noopener">Кузьминский гидроузел — Википедия</a>)
      </div>
    </div>

    <div class="myth-card myth-mixed">
      <div class="myth-label">⚠️ ПОЛУПРАВДА</div>
      <h4>«Водохранилища специально сбросили воду на дачи»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Водохранилища действительно производят сбросы в паводок —
        но это <em>вынужденная мера безопасности</em>, а не злой умысел. Когда водохранилище
        грозит переполниться, не открыть затворы значит допустить неконтролируемый перелив.
        Водохранилища системы «Канала имени Москвы» в целом <em>снижают</em> паводок,
        поглощая часть весеннего стока. На участке Серпухов–Таруса крупных водохранилищ
        прямо на Оке вообще нет.
        (<a href="https://aif.ru/society/nature/1025160" target="_blank" rel="noopener">АиФ — история волжских наводнений</a>)
      </div>
    </div>

    <div class="myth-card myth-false">
      <div class="myth-label">❌ МИФ</div>
      <h4>«Раньше таких паводков не было — это из-за плотин»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Рекордные паводки фиксировались задолго до любых плотин.
        1908 год — 1256 см у Серпухова, весь город почти под водой. В 1970 году вода
        доходила до крыши троллейбуса в Калуге. Паводок 1908 года в 1,5 раза превысил
        рекорд 2024 года. Именно строительство водохранилищ на Москве-реке <em>предотвратило</em>
        катастрофические паводки столицы после 1931 года.
        (<a href="https://www.orelvkartinkax.ru/bigwater.htm" target="_blank" rel="noopener">orelvkartinkax.ru</a>)
      </div>
    </div>

    <div class="myth-card myth-false">
      <div class="myth-label">❌ МИФ</div>
      <h4>«Если бы плотину отремонтировали, паводка бы не было»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> В районе Серпухова, Тарусы, Пущино плотин нет вообще.
        Кузьминский гидроузел (который действительно реконструировали в 2013–2015 годах)
        расположен ниже по течению и не влияет на уровень воды в этих местах.
        Реконструкция решала задачи судоходства, а не защиты от паводков.
        (<a href="https://7dogs.livejournal.com/855011.html" target="_blank" rel="noopener">7dogs.livejournal.com — история Кузьминского гидроузла</a>)
      </div>
    </div>

    <div class="myth-card myth-mixed">
      <div class="myth-label">⚠️ НЕТОЧНО</div>
      <h4>«Каждый год всё сильнее топит — климат меняется, скоро совсем зальёт»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Статистика не подтверждает нарастающего тренда.
        2015–2022 годы — серия слабых паводков: Ока у Серпухова не выходила на пойму.
        2023 год — сильный паводок (780 см) после многих слабых лет. 2024 год — рекорд XXI века
        (850 см), но в 1,5 раза слабее 1908 и 1970 годов. Истинная причина варьирования —
        погодные условия конкретной зимы.
        (<a href="https://ya-kraeved.ru/pavodok-na-oke-dostig-svoego-pika/" target="_blank" rel="noopener">ya-kraeved.ru</a>)
      </div>
    </div>

    <div class="myth-card myth-false">
      <div class="myth-label">❌ ЗАБЛУЖДЕНИЕ</div>
      <h4>«Дача в пойме — нормально, нас должны защитить»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Пойма реки — это зона, <em>предназначенная природой
        для затопления</em>. В период 1994–2012 годов Ока у Серпухова почти не разливалась
        на пойму из-за аномально малоснежных зим — это создало ложное ощущение безопасности.
        Заместитель серпуховского комитета по благоустройству о ежегодном затоплении парка:
        «Это не стихийное бедствие, а обычный природный фактор. На этапе проектирования
        это уже было предусмотрено».
        (<a href="https://msk1.ru/text/incidents/2024/04/05/73430921/" target="_blank" rel="noopener">MSK1.ru</a>)
      </div>
    </div>

    <div class="myth-card myth-false">
      <div class="myth-label">❌ МИФ</div>
      <h4>«На реке есть ГЭС — она сдерживает воду, а потом разом сбрасывает»</h4>
      <div class="myth-reality">
        <strong>Реальность:</strong> Кузьминская ГЭС (построена в 1945 году) закрыта в
        1970-е годы. Сам гидроузел предназначен для судоходства, а не для выработки
        электроэнергии. На участке Серпухов–Таруса–Пущино никаких действующих ГЭС нет.
        Если дача расположена в пойме Нары или притока Оки — затопление там является штатным
        природным явлением каждого года, независимо от любых плотин.
        (<a href="https://cruiseinform.ru/catalog/06/oka/kuzminskiy-shlyuz/" target="_blank" rel="noopener">cruiseinform.ru</a>)
      </div>
    </div>

  </div>
</div>

<!-- ═══════════════════ ПОДВАЛ ═══════════════════ -->
<div class="section-card" style="text-align:center; margin-top:16px;">
  <p style="color:var(--text-dim); font-size:0.82rem;">
    Документ составлен: март 2026 года. Данные актуальны на дату составления.<br>
    Основные источники:
    <a href="https://allrivers.info/river/oka" target="_blank" rel="noopener">allrivers.info</a> |
    <a href="https://www.orelvkartinkax.ru/bigwater.htm" target="_blank" rel="noopener">orelvkartinkax.ru</a> |
    <a href="https://regions.ru/serpuhov/" target="_blank" rel="noopener">regions.ru</a> |
    <a href="https://serpuhov.ru/" target="_blank" rel="noopener">serpuhov.ru</a> |
    <a href="https://snegochistka.ru/articles/iz_letopisi_katastrof_kaluzhskoi_oblasti" target="_blank" rel="noopener">snegochistka.ru</a> |
    <a href="https://www.kp40.ru/news/society/89696/" target="_blank" rel="noopener">KP40.ru</a>
  </p>
  <p style="margin-top:12px;">
    <a href="flood-guide.html" style="color:var(--accent); font-size:0.88rem;">📚 Физика половодья &rarr;</a>
  </p>
</div>

</div>

<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | 54.833413, 37.741813 | Жерновка, р. Ока<br>
  Обновлено: {now_msk} МСК | <a href="index.html">Мониторинг</a> | <a href="links.html">Ссылки</a>
</footer>


<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(HISTORY_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] history.html сохранён ({len(html)} символов)")


# ══════════════════════════════════════════════════════════════════════════════
# СТРАНИЦЫ ГОРОДОВ ПО ОКЕ (БЛОК 6)
# ══════════════════════════════════════════════════════════════════════════════


def _build_nav(current_page: str = "main", is_subpage: bool = False) -> str:
    """
    Unified navigation builder for ALL pages.
    current_page: 'main'|'cities'|'history'|'guide'|'links'|'instructions'
    is_subpage: True for cities/*.html (paths start with ../)
    """
    p = "../" if is_subpage else ""

    nav_items = {
        "main":         (f"{p}index.html",        "Главная",           "Открыть главную страницу мониторинга"),
        "cities":       (f"{p}cities/index.html", "Города",            "Открыть карту городов на Оке"),
        "history":      (f"{p}history.html",       "История паводков",  "Открыть историю паводков Оки"),
        "guide":        (f"{p}flood-guide.html",   "Физика половодья",   "Открыть раздел о физике половодья"),
        "links":        (f"{p}links.html",         "Ссылки",             "Открыть список полезных ссылок"),
        "instructions": (f"{p}instructions.html",  "Инструкции",         "Открыть инструкцию по использованию"),
    }

    # Dropdowns content
    history_dd = f"""
          <ul class="dropdown">
            <li><a href="{p}history.html#flood-1908">1908 — Великий паводок</a></li>
            <li><a href="{p}history.html#flood-1970">1970 — Советский рекорд</a></li>
            <li><a href="{p}history.html#flood-1979">1979 — Год стройки</a></li>
            <li><a href="{p}history.html#flood-1994">1994 — Рекорд Белёва</a></li>
            <li><a href="{p}history.html#flood-2013">2013 — Рекорд XXI века</a></li>
            <li><a href="{p}history.html#flood-2023">2023 — Ранний</a></li>
            <li><a href="{p}history.html#flood-2024">2024 — Новый рекорд</a></li>
            <li><a href="{p}history.html#dams">Плотины и мифы</a></li>
            <li><a href="{p}history.html#records-table">Таблица рекордов</a></li>
          </ul>"""

    guide_dd = f"""
          <ul class="dropdown">
            <li><a href="{p}flood-guide.html#s1">Что такое половодье</a></li>
            <li><a href="{p}flood-guide.html#s2">Скорость волны</a></li>
            <li><a href="{p}flood-guide.html#s3">Ока от Орла до Коломны</a></li>
            <li><a href="{p}flood-guide.html#s4">Несколько волн за весну</a></li>
            <li><a href="{p}flood-guide.html#s5">Пять факторов</a></li>
            <li><a href="{p}flood-guide.html#s6">Гидропост</a></li>
            <li><a href="{p}flood-guide.html#s7">НЯ и ОЯ</a></li>
            <li><a href="{p}flood-guide.html#s8">Плотины</a></li>
            <li><a href="{p}flood-guide.html#s9">Что делать</a></li>
          </ul>"""

    cities_dd = f"""
          <ul class="dropdown">
            <li><a href="{p}cities/index.html">Все города</a></li>
            <li><a href="{p}cities/orel.html">Орёл</a></li>
            <li><a href="{p}cities/belev.html">Белёв</a></li>
            <li><a href="{p}cities/kaluga.html">Калуга</a></li>
            <li><a href="{p}cities/aleksin.html">Алексин</a></li>
            <li><a href="{p}cities/tarusa.html">Таруса</a></li>
            <li><a href="{p}cities/serpuhov.html">Серпухов</a></li>
            <li><a href="{p}cities/pushchino.html">Пущино</a></li>
            <li><a href="{p}cities/kashira.html">Кашира</a></li>
            <li><a href="{p}cities/kolomna.html">Коломна</a></li>
          </ul>"""

    dd_map = {
        "history": history_dd,
        "guide":   guide_dd,
        "cities":  cities_dd,
    }

    nav_html = ""
    for key, (href, label, tip) in nav_items.items():
        cls = ' class="active"' if key == current_page else ""
        dd = dd_map.get(key, "")
        if dd:
            nav_html += f"""
      <li>{dd}
        <a href="{href}"{cls} title="{tip}">{label} <span style="font-size:0.7rem;opacity:0.6;">▾</span></a>
      </li>"""
        else:
            nav_html += f"""
      <li><a href="{href}"{cls} title="{tip}">{label}</a></li>"""

    # Mobile nav items (flat)
    mobile_html = ""
    for key, (href, label, tip) in nav_items.items():
        cls = ' class="active"' if key == current_page else ""
        mobile_html += f'<a href="{href}"{cls} title="{tip}">{label}</a>'

        # Add sub-items for dropdowns
        if key == "history":
            mobile_html += f'<a href="{p}history.html#flood-1908" class="mobile-nav-sub">— 1908 Великий</a>'

            mobile_html += f'<a href="{p}history.html#flood-2013" class="mobile-nav-sub">— 2013 Рекорд</a>'

            mobile_html += f'<a href="{p}history.html#flood-2024" class="mobile-nav-sub">— 2024</a>'

        elif key == "cities":
            mobile_html += f'<a href="{p}cities/serpuhov.html" class="mobile-nav-sub">— Серпухов</a>'

            mobile_html += f'<a href="{p}cities/pushchino.html" class="mobile-nav-sub">— Пущино</a>'

            mobile_html += f'<a href="{p}cities/kaluga.html" class="mobile-nav-sub">— Калуга</a>'


    logo_href = f"{p}index.html"

    return f"""<header class="site-header">
  <a class="header-logo" href="{logo_href}" style="text-decoration:none; color:inherit;">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" style="vertical-align:middle;margin-right:4px;"><path d="M2 12c1.5-3 4-5 6-5s4 3 6 3 4-5 6-5" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/><path d="M2 18c1.5-3 4-5 6-5s4 3 6 3 4-5 6-5" stroke="#93c5fd" stroke-width="1.5" stroke-linecap="round"/></svg>
    <span>Oka</span>FloodMonitor
  </a>
  <nav>
    <ul class="header-nav">{nav_html}
    </ul>
  </nav>
  <button class="burger-btn" onclick="toggleMobileNav()" aria-label="Меню">☰</button>
</header>
<div class="mobile-nav" id="mobile-nav">
{mobile_html}</div>"""




def _city_nav_html(active_slug: str = "") -> str:
    """Обёртка для _build_nav, обратная совместимость."""
    # ВСЕ страницы в cities/ — это subpages, включая index
    return _build_nav("cities", is_subpage=True)


def _city_page_css() -> str:
    """CSS для страниц городов (переиспользует переменные основного дизайна)."""
    return """
:root {
  --safe:      #22c55e;
  --watch:     #f59e0b;
  --warning:   #f97316;
  --danger:    #ef4444;
  --emergency: #a855f7;
  --accent:    #2563eb;
  --bg-primary: #f7f9fc;
  --bg-card: #ffffff;
  --bg-card-hover: #f8fafc;
  --bg-glass: rgba(0, 0, 0, 0.03);
  --border: rgba(0, 0, 0, 0.08);
  --border-hover: rgba(0, 0, 0, 0.16);
  --text-primary: #1a2332;
  --text-secondary: #5a6a7a;
  --text-dim: #8a9ab0;
  --shadow-card: 0 2px 12px rgba(0, 0, 0, 0.08);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  min-height: 100vh;
  line-height: 1.6;
  font-size: 15px;
  position: relative;
}
body::before {
  content: '';
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: radial-gradient(circle at 20% 50%, rgba(186,230,253,0.12) 0%, transparent 50%),
              radial-gradient(circle at 80% 20%, rgba(186,230,253,0.10) 0%, transparent 40%);
  pointer-events: none;
  z-index: -1;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 900px; margin: 0 auto; padding: 24px; }
.city-content { max-width: 900px; margin: 0 auto; padding: 0 24px; }
.card, .section-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  padding: 20px 24px;
  margin-bottom: 20px;
  transition: all 0.3s ease;
}
.card:hover, .section-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  box-shadow: 0 4px 20px rgba(0,0,0,0.12);
}
.site-header {
  position: sticky; top: 0; z-index: 200;
  background: rgba(255,255,255,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid #e5e7eb;
  padding: 0 24px; height: 56px;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.header-logo {
  font-size: 1.1rem; font-weight: 700; color: var(--text-primary);
  white-space: nowrap; letter-spacing: -0.02em;
}
.header-logo span { color: var(--accent); }
.header-nav { display: flex; gap: 2px; list-style: none; }
.header-nav > li { position: relative; }
.header-nav a {
  display: block; padding: 6px 12px; border-radius: 8px;
  color: var(--text-secondary); text-decoration: none;
  font-size: 0.88rem; font-weight: 500; transition: all 0.2s ease; white-space: nowrap;
}
.header-nav a:hover, .header-nav a.active {
  background: rgba(37,99,235,0.08); color: var(--accent);
}
.header-nav .dropdown {
  position: absolute; top: calc(100% + 4px); left: 0;
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 200px; z-index: 1000;
  opacity: 0; visibility: hidden; transform: translateY(-4px);
  transition: all 0.15s ease; pointer-events: none; padding: 6px 0;
}
.header-nav > li:hover .dropdown { opacity: 1; visibility: visible; transform: translateY(0); pointer-events: auto; }
.header-nav .dropdown a { padding: 7px 16px; font-size: 0.83rem; border-radius: 0; }
.burger-btn { display: none; background: none; border: none; cursor: pointer; font-size: 1.4rem; color: var(--text-primary); padding: 4px 8px; border-radius: 6px; }
.mobile-nav { display: none; position: fixed; top: 56px; left: 0; right: 0; background: #ffffff; border-bottom: 1px solid #e5e7eb; box-shadow: 0 8px 24px rgba(0,0,0,0.12); z-index: 199; padding: 8px 0 16px; }
.mobile-nav.open { display: block; }
.mobile-nav a { display: block; padding: 10px 24px; font-size: 0.95rem; font-weight: 500; color: var(--text-secondary); text-decoration: none; border-left: 3px solid transparent; transition: all 0.15s; }
.mobile-nav a:hover, .mobile-nav a.active { background: rgba(37,99,235,0.05); color: var(--accent); border-left-color: var(--accent); }
.mobile-nav .mobile-nav-sub { padding-left: 40px; font-size: 0.83rem; }
@media (max-width: 768px) { .header-nav { display: none; } .burger-btn { display: block; } }
.site-footer {
  text-align: center; padding: 32px 24px 24px;
  color: var(--text-dim); font-size: 0.8rem; line-height: 1.8;
}
h1 { font-size: 1.8rem; font-weight: 800; margin-bottom: 8px; letter-spacing: -0.03em; }
h2 {
  font-size: 1.1rem; font-weight: 700; color: var(--text-primary);
  margin-bottom: 12px; border-left: 3px solid var(--accent); padding-left: 12px;
}
h3 { font-size: 0.95rem; font-weight: 600; color: var(--text-secondary); margin: 12px 0 6px; }
p { color: var(--text-secondary); line-height: 1.75; margin-bottom: 10px; font-size: 0.9rem; }
.badge {
  display: inline-block; font-size: 0.72rem; font-weight: 700;
  padding: 2px 10px; border-radius: 20px; margin-right: 6px;
}
.badge-blue   { background: rgba(37,99,235,0.10); color: #2563eb; }
.badge-green  { background: rgba(16,185,129,0.15); color: #34d399; }
.badge-orange { background: rgba(249,115,22,0.15); color: #fb923c; }
.badge-red    { background: rgba(239,68,68,0.15);  color: #f87171; }
.badge-purple { background: rgba(168,85,247,0.15); color: #c084fc; }
.info-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 12px; margin: 12px 0;
}
@media (max-width: 480px) { .info-grid { grid-template-columns: 1fr; } }
.info-item { }
.info-label { font-size: 0.72rem; color: var(--text-dim); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 2px; }
.info-value { font-size: 0.9rem; color: var(--text-primary); font-weight: 500; }
.flood-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; margin: 10px 0; }
.flood-table th {
  background: #f8fafc; padding: 8px 10px;
  text-align: left; color: var(--text-secondary); font-size: 0.76rem; font-weight: 600;
}
.flood-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }
.flood-table tr:hover td { background: rgba(37,99,235,0.03); }
.fact-card {
  background: rgba(59,130,246,0.05); border-left: 3px solid var(--accent);
  border-radius: 0 8px 8px 0; padding: 10px 16px; margin: 8px 0;
  font-size: 0.88rem; color: var(--text-secondary);
}
.warn-card {
  background: rgba(249,115,22,0.05); border-left: 3px solid var(--warning);
  border-radius: 0 8px 8px 0; padding: 10px 16px; margin: 8px 0;
  font-size: 0.88rem; color: var(--text-secondary);
}
.city-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 20px;
}
@media (max-width: 768px) { .city-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 480px) { .city-grid { grid-template-columns: 1fr; } }
@media (max-width: 768px) { .city-index-grid { grid-template-columns: 1fr !important; } }
.city-card {
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
  padding: 16px 18px; text-decoration: none; color: inherit; display: block;
  transition: all 0.25s ease;
}
.city-card:hover {
  background: var(--bg-card-hover); border-color: var(--border-hover);
  transform: translateY(-2px); text-decoration: none;
}
.city-card-name { font-size: 1.05rem; font-weight: 700; margin-bottom: 4px; }
.city-card-river { font-size: 0.8rem; color: var(--text-dim); margin-bottom: 8px; }
.city-card-stats { display: flex; gap: 10px; flex-wrap: wrap; }
.city-card-stat { font-size: 0.76rem; color: var(--text-secondary); }
.city-card-stat span { color: var(--text-primary); font-weight: 600; }
.river-timeline {
  position: relative; padding: 12px 0;
  margin: 20px 0;
}
.river-line {
  position: absolute; left: 24px; top: 0; bottom: 0;
  width: 3px; background: linear-gradient(to bottom, #1e40af, #3b82f6, #60a5fa);
  border-radius: 2px;
}
.river-city {
  position: relative; padding: 6px 0 6px 56px; min-height: 36px;
  display: flex; align-items: center;
}
.river-dot {
  position: absolute; left: 17px;
  width: 17px; height: 17px; border-radius: 50%;
  background: var(--bg-primary); border: 2px solid var(--accent);
  z-index: 2;
}
.river-dot.main-dot {
  border-color: var(--danger); background: rgba(239,68,68,0.2);
  width: 21px; height: 21px; left: 15px;
}
.river-city-name { font-size: 0.88rem; font-weight: 600; color: var(--text-primary); }
.river-city-meta { font-size: 0.75rem; color: var(--text-dim); margin-left: 8px; }
.critical-level { color: var(--danger); font-weight: 700; }
.warning-level  { color: var(--warning); font-weight: 700; }
"""



def _generate_oka_svg_map() -> str:
    """Генерирует SVG-карту реки Ока с городами v7.6.1."""
    import math as _math
    cities_map = [
        ("Орёл",    111,  True,  False, "orel",     289503),
        ("Мценск",  150,  False, False, "mtsensk",  36070),
        ("Белёв",   258,  True,  False, "belev",    12382),
        ("Чекалин", 300,  False, False, "chekalin", 935),
        ("Козельск",340,  True,  False, "kozelsk",  16603),
        ("Калуга",  391,  True,  False, "kaluga",   329673),
        ("Алексин", 452,  True,  False, "aleksin",  60842),
        ("Таруса",  490,  False, False, "tarusa",   8785),
        ("Серпухов",522,  True,  True,  "serpuhov", 133756),
        ("Пущино",  535,  False, False, "pushchino",19342),
        ("Кашира",  573,  True,  False, "kashira",  35000),
        ("Коломна", 645,  False, False, "kolomna",  141000),
    ]
    W, H = 760, 320
    km_min, km_max = 111, 645
    margin_l, margin_r = 60, 60

    def km_to_x(km):
        t = (km - km_min) / (km_max - km_min)
        return margin_l + t * (W - margin_l - margin_r)

    def km_to_y(km):
        t = (km - km_min) / (km_max - km_min)
        return H/2 + _math.sin(t * _math.pi * 2.5) * 45

    pts = [(km_to_x(km), km_to_y(km)) for km in range(km_min, km_max+1, 4)]
    path_d = f"M {pts[0][0]:.1f},{pts[0][1]:.1f}" + "".join(f" L {x:.1f},{y:.1f}" for x, y in pts[1:])

    dots_html = ""
    for i, (name, km, has_post, is_main, slug, pop) in enumerate(cities_map):
        cx = km_to_x(km)
        cy = km_to_y(km)
        r = max(6, min(18, 5 + _math.log10(max(pop, 1000)) * 2.5))
        fill, stroke = ("#ef4444","#b91c1c") if is_main else (("#22c55e","#15803d") if has_post else ("#94a3b8","#64748b"))
        label_dy = -r - 8 if i % 2 == 0 else r + 14
        dots_html += f'''
  <a href="{slug}.html" title="{name}">
    <circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>
    <text x="{cx:.1f}" y="{cy+label_dy:.1f}" text-anchor="middle"
      font-family="Inter,sans-serif" font-size="11" fill="#374151" font-weight="500">{name}</text>
  </a>'''

    reg_html = ""
    for rx, rtext in [(135,"Орловская"), (270,"Тульская"), (420,"Калужская"), (590,"Московская")]:
        reg_html += f'<text x="{rx}" y="22" font-family="Inter,sans-serif" font-size="10" fill="#9ca3af" text-anchor="middle">{rtext} обл.</text>\n  '

    div_lines = ""
    for km in [185, 310, 500]:
        x = km_to_x(km)
        div_lines += f'<line x1="{x:.1f}" y1="28" x2="{x:.1f}" y2="{H-10}" stroke="#e5e7eb" stroke-width="1" stroke-dasharray="4,3"/>\n      '

    return f"""<div class="section-card" style="margin-bottom:24px; padding:20px; overflow:hidden;">
  <h2 style="margin-bottom:4px;">Схематичная карта Оки</h2>
  <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:12px;">
    Нажмите на город для подробной информации. Размер точки пропорционален населению.
  </p>
  <div style="overflow-x:auto;">
    <svg viewBox="0 0 {W} {H}" width="100%" style="max-height:{H}px; min-width:480px; display:block;">
      <defs>
        <linearGradient id="rg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#bae6fd"/><stop offset="100%" stop-color="#38bdf8"/>
        </linearGradient>
      </defs>
      <rect width="{W}" height="{H}" fill="#f8fafc" rx="8"/>
      {div_lines}
      {reg_html}
      <text x="44" y="{H//2+4}" font-family="Inter,sans-serif" font-size="10" fill="#9ca3af">← исток</text>
      <text x="{W-36}" y="{H//2+4}" font-family="Inter,sans-serif" font-size="10" fill="#9ca3af">→ устье</text>
      <path d="{path_d}" fill="none" stroke="url(#rg)" stroke-width="7" stroke-linecap="round" opacity="0.6"/>
      <path d="{path_d}" fill="none" stroke="#93c5fd" stroke-width="2" stroke-linecap="round" opacity="0.5"/>
      {dots_html}
      <g transform="translate(8,{H-54})">
        <circle cx="7" cy="7" r="5" fill="#ef4444" stroke="#b91c1c" stroke-width="1.5"/><text x="16" y="11" font-family="Inter,sans-serif" font-size="10" fill="#374151">Главная точка</text>
        <circle cx="7" cy="22" r="5" fill="#22c55e" stroke="#15803d" stroke-width="1.5"/><text x="16" y="26" font-family="Inter,sans-serif" font-size="10" fill="#374151">Есть гидропост</text>
        <circle cx="7" cy="37" r="5" fill="#94a3b8" stroke="#64748b" stroke-width="1.5"/><text x="16" y="41" font-family="Inter,sans-serif" font-size="10" fill="#374151">Нет поста</text>
      </g>
    </svg>
  </div>
</div>"""




def generate_city_index_page() -> None:
    """
    Генерирует docs/cities/index.html — индекс всех городов на Оке.
    """
    cities_dir = os.path.join(DOCS_DIR, "cities")
    os.makedirs(cities_dir, exist_ok=True)

    css = _city_page_css()
    nav = _city_nav_html(active_slug="index")
    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    # Карточки городов
    cards_html = ""
    for city in OKA_CITIES:
        slug      = city["slug"]
        name      = city["name"]
        river     = city.get("river", "р. Ока")
        pop       = city.get("population", 0)
        founded   = city.get("founded", 0)
        km_src    = city.get("km_from_source")
        has_post  = city.get("hydro_post") is not None
        is_main   = city.get("is_main", False)

        pop_str   = f"{pop // 1000} тыс." if pop >= 1000 else str(pop)
        km_str    = f"{km_src} км" if km_src else "—"
        post_str  = "✅ есть" if has_post else "нет"
        main_mark = " 🔴" if is_main else ""

        cards_html += f"""
<a class="city-card" href="{_h(slug)}.html">
  <div class="city-card-name">{_h(name)}{main_mark}</div>
  <div class="city-card-river">{_h(river)}</div>
  <div class="city-card-stats">
    <div class="city-card-stat">Осн. <span>{founded}</span></div>
    <div class="city-card-stat">Нас. <span>{pop_str}</span></div>
    <div class="city-card-stat">От истока <span>{km_str}</span></div>
    <div class="city-card-stat">Пост <span>{post_str}</span></div>
  </div>
</a>"""

    # Схема реки (вертикальная временна́я шкала)
    timeline_html = "<div class=\"river-timeline\">\n<div class=\"river-line\"></div>\n"
    for city in OKA_CITIES:
        slug    = city["slug"]
        name    = city["name"]
        km_src  = city.get("km_from_source")
        is_main = city.get("is_main", False)
        km_label = f"{km_src} км от истока" if km_src else ""
        dot_cls  = "river-dot main-dot" if is_main else "river-dot"
        timeline_html += f"""
<div class="river-city">
  <div class="{dot_cls}"></div>
  <a href="{_h(slug)}.html" style="text-decoration:none; color:inherit; display:flex; align-items:baseline;">
    <span class="river-city-name">{_h(name)}</span>
    <span class="river-city-meta">{_h(km_label)}</span>
  </a>
</div>"""
    timeline_html += "\n</div>\n"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="Города на реке Ока — от Орла до Коломны. Гидрологические посты, паводки, зоны риска. OkaFloodMonitor.">
  <title>Города на Оке — OkaFloodMonitor</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    {css}
  </style>
</head>
<body>
{nav}

<div class="container">
  <h1>🏙️ Города на реке Ока</h1>
  <p style="color:var(--text-dim); margin-bottom:4px;">От Орла (111 км от истока) до Коломны (645 км). {len(OKA_CITIES)} городов и населённых пунктов.</p>
  <p style="color:var(--text-dim); font-size:0.82rem; margin-bottom:20px;">🔴 — основная мониторинговая точка (Жерновка / Серпухов)</p>

  {_generate_oka_svg_map()}

  <div class="city-index-grid" style="display:grid; grid-template-columns:2fr 1fr; gap:24px; margin-top:16px;">
    <div>
      <div class="city-grid">
        {cards_html}
      </div>
    </div>
    <div>
      <div class="section-card" style="padding:16px 20px;">
        <h2 style="border-color:var(--accent);">Ока: от истока к устью</h2>
        <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:12px;">Схематичное расположение городов вдоль реки (сверху — ближе к истоку)</p>
        {timeline_html}
      </div>
    </div>
  </div>

  <div class="section-card" style="margin-top:8px;">
    <h2>О системе мониторинга</h2>
    <p>Гидрологические посты на Оке образуют единую цепь наблюдений: данные верхних постов
    (Орёл, Белёв) служат ранним предупреждением для городов ниже по течению.
    Паводковая волна проходит путь от Орла до Серпухова за 5–7 дней,
    от Серпухова до Коломны — ещё за 2–4 дня.</p>
    <p>Не все города имеют официальные гидрологические посты на реке: для части из них
    мониторинг ведётся через ближайшие посты и региональными службами МЧС.</p>
    <div style="font-size:0.8rem; color:var(--text-dim); margin-top:8px;">Обновлено: {_h(now_msk)} МСК</div>
  </div>
</div>

<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | Города на Оке | <a href="../index.html">← На главную</a><br>
  Источники: Росгидромет / Центр регистра и кадастра / Канал имени Москвы / МЧС
</footer>


<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    out_path = os.path.join(cities_dir, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] cities/index.html сохранён ({len(html)} символов)")


def generate_city_page(city_data: dict, glofas_data: dict) -> None:
    """
    Генерирует docs/cities/{slug}.html для одного города.
    """
    cities_dir = os.path.join(DOCS_DIR, "cities")
    os.makedirs(cities_dir, exist_ok=True)

    slug     = city_data["slug"]
    name     = city_data["name"]
    river    = city_data.get("river", "р. Ока")
    bank     = city_data.get("bank", "")
    pop      = city_data.get("population", 0)
    founded  = city_data.get("founded", 0)
    km_src   = city_data.get("km_from_source")
    glofas_slug = city_data.get("glofas_slug")
    hydro_post  = city_data.get("hydro_post")
    near_post   = city_data.get("nearest_hydro_post", "")
    flood_risk  = city_data.get("flood_risk", "")
    floods      = city_data.get("notable_floods", [])
    desc_paras  = city_data.get("description", ())
    serp_km     = city_data.get("serpuhov_km_river")
    serp_days   = city_data.get("serpuhov_wave_days")
    is_main     = city_data.get("is_main", False)

    # v7.7.1: Эмодзи городов для h1
    CITY_COAT_OF_ARMS = {
        "orel": "data:image/svg+xml;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB3aWR0aD0iMjE0LjQybW0iIGhlaWdodD0iMjY0LjU4bW0iIHZlcnNpb249IjEuMSIgdmlld0JveD0iMCAwIDIxNC40MiAyNjQuNTgiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgeG1sbnM6Y2M9Imh0dHA6Ly9jcmVhdGl2ZWNvbW1vbnMub3JnL25zIyIgeG1sbnM6ZGM9Imh0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvIiB4bWxuczpyZGY9Imh0dHA6Ly93d3cudzMub3JnLzE5OTkvMDIvMjItcmRmLXN5bnRheC1ucyMiPgoJPG1ldGFkYXRhPgoJCTxyZGY6UkRGPgoJCQk8Y2M6V29yayByZGY6YWJvdXQ9IiI+CgkJCQk8ZGM6Zm9ybWF0PmltYWdlL3N2Zyt4bWw8L2RjOmZvcm1hdD4KCQkJCTxkYzp0eXBlIHJkZjpyZXNvdXJjZT0iaHR0cDovL3B1cmwub3JnL2RjL2RjbWl0eXBlL1N0aWxsSW1hZ2UiLz4KCQkJPC9jYzpXb3JrPgoJCTwvcmRmOlJERj4KCTwvbWV0YWRhdGE+Cgk8ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSguMDY2MTQ2IC0zMi42OTMpIj4KCQk8cGF0aCBkPSJtMC44NTY0OCAzMy42MTV2MjE4LjdjMCAxMS41MTIgMS44ODg2IDMxLjIwMyAyOC4yOTkgMzEuMjAzaDYwLjgzNWMxMi40ODMgMCAxNy4xNTUgMTIuODMgMTcuMTU1IDEyLjgzczQuNjY1MS0xMi44MyAxNy4xNDgtMTIuODNoNjAuODQzYzI2LjQxIDAgMjguMjkxLTE5LjY5MSAyOC4yOTEtMzEuMjAzdi0yMTguN3oiIGZpbGw9IiMwMWEwZTIiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIxLjg0NTIiLz4KCQk8cGF0aCBkPSJtMC44NTY0OCAyNDAuMDR2MTIuMjc1YzAgMTEuNTEyIDEuODg4NiAzMS4yMDMgMjguMjk5IDMxLjIwM2g2MC44MzVjMTIuNDgzIDAgMTcuMTU1IDEyLjgzIDE3LjE1NSAxMi44M3M0LjY2NTEtMTIuODMgMTcuMTQ4LTEyLjgzaDYwLjg0M2MyNi40MSAwIDI4LjI5MS0xOS42OTEgMjguMjkxLTMxLjIwM3YtMTIuMjc1eiIgZmlsbD0iIzIxOWIzYyIgc3Ryb2tlPSIjMDAwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjEuODQ1MiIvPgoJCTxyZWN0IHg9IjkwLjEwMSIgeT0iMTg4LjExIiB3aWR0aD0iMzUuNjgxIiBoZWlnaHQ9IjUxLjkzIiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iMS4xMDcxIi8+CgkJPHBhdGggZD0ibTEyMy44OCAxMjMuNTZjNi4yMDgtNC43NzUzIDAuNTQyOTctMTkuMzQ5IDguODk1OC0yMi42OSAxMy4xNy01LjI2NzkgMjMuNTM2IDAuODQ5NDUgMTcuOTQ5IDEzLjUyNC0zLjIwNTIgNy4yNzE3LTExLjUyMyAxNS40MzItMTcuMDQ4IDE5Ljk3Ni0xLjIyODMgMC4zMDY4Ni0xLjU0MzggMS43NDMxLTIuMzgwNSAyLjQ2MzctMC44NjA3IDIuNDM4Ny05LjAzNjMgMTguNDI5LTkuOTMxOCAxOC40MjktMTUuMzYyIDAtMTQuODU4LTEwLjk2My00NC42NDMgNS44NDEzIDMuODI4OC02LjgwNjggMTguNDg3LTIwLjEzMyAxNi40MzktMjguMzIyLTAuNzYyMTEtMy4wNDg1LTYuNzQ2MiAyLjE5MTgtNy43ODEgMi41MzY4LTAuMDE3MDIgMC4yMDc4My0wLjQyNzU4LTQuNjY2OC0zLjAxNzgtNC44MjI4LTIuNjUwOS0wLjE1OTAxLTQuMTIyOSAyLjMxODEtNy42NDU5IDUuNDM4OSAwLjMzMTY2LTIuMzg1NyAwLjA0OTM4LTQuNzcyOC0xLjI2MTItNC44ODcxLTIuNTU2Mi0wLjIyMzE3LTExLjAxNyA2LjAzNC0xMy4zMiA3LjQxNTkgMC43ODg2Ni0xLjk1MjIgMi42MTYtOC4wMTQzLTAuNzg5ODUtNi4zMTIzLTQuNTg5NCAyLjI5MzItMTAuNTkzIDYuMzQ1Ni0xNS43ODkgNy40MDYxIDcuMDY2OC0xMC4wOTUgMjcuMzU2LTQzLjE3NyA0MS4zMjgtMzkuODgyIDguNDYzNiAxLjk5NiAxNS4wNTYgMjAuNzEyIDIzLjY0NyA3LjkxNjEgMy42MTc4LTUuMzg4NS0xLjUzMDQtMTMuNDY1LTYuMzg0Ny01Ljg3OC0xLjQ3NzQtNC44NzUyIDIuNTE0My01LjI2MzQgNC4zMzUzLTcuOTk1IDQuMjE3OS05Ljg4MzIgMTIuNzExLTcuNTQxNiAxNi42MDkgNC4zMzU0IDMuMjM5NCA5Ljg2ODgtMC45MjE3MyAxNy43OTIgMC43ODgyNCAyNS41MDUiIGZpbGw9IiM0MjQyNDIiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIxLjEwNzEiLz4KCQk8cGF0aCBkPSJtOTEuNTA0IDE0Ni40OHYyOC4wOWgzMi42MDJ2LTI4LjA5aC01LjI5Nzl2NS4wMDk1aC0zLjcxMjF2LTUuMDA5NWgtNS4yOTA3djUuMDA5NWgtMy41NTM1di01LjAwOTVoLTUuMjkwN3Y1LjAwOTVoLTQuMTY2MnYtNS4wMDk1eiIgZmlsbD0iI2ZmZiIgc3Ryb2tlPSIjMDAwIiBzdHJva2Utd2lkdGg9IjEuMTA3MSIvPgoJCTxwYXRoIGQ9Im05MS41MDQgMTUyLjI3aDMyLjYwMiIgZmlsbC1vcGFjaXR5PSIwIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iMS4xMDcxIi8+CgkJPHBhdGggZD0ibTEwNy44OCAxNTIuMjItNS45NjgyIDQuODAwNnYxNC4xNzhoMTEuOTM2di0xNC4xNzh6IiBmaWxsPSJub25lIiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iMS4xMDcxIi8+CgkJPHBhdGggZD0ibTEwNy44OCAxNTUuMTEtNC4wNjk2IDMuMzI1N3YxMi43NjJoOC4xMzkzdi0xMi43NjJ6Ii8+CgkJPGNpcmNsZSBjeD0iOTYuMjI2IiBjeT0iMTU2LjM3IiByPSIyLjcyOSIvPgoJCTxjaXJjbGUgY3g9IjEyMC40MyIgY3k9IjE1Ni4zNyIgcj0iMi43MjkiLz4KCQk8cmVjdCB4PSI5Ny43NTIiIHk9IjIyMC42MyIgd2lkdGg9IjIwLjM4MiIgaGVpZ2h0PSI1LjUxNzciIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIuNzM4MSIvPgoJCTxyZWN0IHg9IjkwLjEwMSIgeT0iMTg4LjExIiB3aWR0aD0iMzUuNjg0IiBoZWlnaHQ9IjUxLjkzMiIgZmlsbD0ibm9uZSIgc3Ryb2tlPSIjOGZiYzhmIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjEuMTA3MSIvPgoJCTxwYXRoIGQ9Im0xMDMuOTkgMjAzLjAxdjMuNzYyNmgyLjA3NTl2NS40MzVoMy43NjI2di01LjQzNWgyLjA3NTl2LTMuNzYyNnoiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIuNzM4MSIvPgoJCTxwYXRoIGQ9Im0xMDcuOTUgMjA4Ljk0Yy00LjQwODIgMC02LjE2MjggMS44MzA4LTYuMTYyOCAxLjgzMDh2MjkuMjc5aDEyLjMxOHYtMjkuMjc5cy0xLjc0NzQtMS44MzA4LTYuMTU1Ni0xLjgzMDh6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iLjczODEiLz4KCQk8cGF0aCBkPSJtMTA3Ljk1IDIxMS4wNmMtMi41NjYgMC0zLjU4OTYgMS42MTQ1LTMuNTg5NiAxLjYxNDV2MjcuMzY5aDcuMTcxOXYtMjcuMzY5cy0xLjAxNjQtMS42MTQ1LTMuNTgyNC0xLjYxNDV6Ii8+CgkJPHJlY3QgeD0iOTAuMTAxIiB5PSIxODguMTEiIHdpZHRoPSIzNS42ODQiIGhlaWdodD0iNTEuOTMyIiBmaWxsPSJub25lIiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iMS4xMDcxIi8+CgkJPGcgdHJhbnNmb3JtPSJtYXRyaXgoMy42OTA1IDAgMCAzLjY5MDUgLjg1NjQ4IDMzLjYxNSkiPgoJCQk8Zz4KCQkJCTxwYXRoIGQ9Im0xNi4zMTYgNDAuNjE3djUuNjAyOGwtMi4wODI1IDAuMDEwMjEgMC4wMjc5MS01LjYxM3oiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMiIvPgoJCQkJPHBhdGggZD0ibTEzLjMwNiAzOS4xMDMtMS4xMDQ5IDEuNTEzOHY1LjYxM2gyLjA2MTJ2LTUuNjEzeiIgZmlsbD0iI2ZmZiIgc3Ryb2tlPSIjMDAwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9Ii4yIi8+CgkJCQk8cGF0aCBkPSJtMTMuMzA2IDM5LjEwM2gxLjg1NzJsMS4xNTM3IDEuNTEzOGgtMi4wNTQ2eiIgZmlsbD0iI2ZmZiIgc3Ryb2tlPSIjMDAwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9Ii4yIi8+CgkJCQk8cmVjdCB4PSIxMi43NTMiIHk9IjQwLjcwNSIgd2lkdGg9Ii4zNDE3NyIgaGVpZ2h0PSIxLjIyMzIiIHJ4PSIuMDExMzYiIHJ5PSIuMDExMzYiLz4KCQkJCTxyZWN0IHg9IjEzLjQ0MiIgeT0iNDAuNzA1IiB3aWR0aD0iLjM0MTc3IiBoZWlnaHQ9IjEuMjIzMiIgcng9Ii4wMTEzNiIgcnk9Ii4wMTEzNiIvPgoJCQk8L2c+CgkJCTxyZWN0IHg9IjEuNzk0MSIgeT0iNDUuMzc5IiB3aWR0aD0iNS44MDEiIGhlaWdodD0iMTAuNTU1IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQkJPHJlY3QgeD0iMS40MDU3IiB5PSI0My45NjMiIHdpZHRoPSI2LjM2NCIgaGVpZ2h0PSIxLjc2NTQiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMyIvPgoJCQk8cGF0aCB0cmFuc2Zvcm09Im1hdHJpeCguNzg5NDggMCAwIC0xLjM5NTIgLjk3NTcxIC0xMi4yMjEpIiBkPSJtNC42MzQ4LTMxLjA5My00LjQ4MjctNy43NjQzIDQuNDgyNy0xZS02aDQuNDgyN2wtMi4yNDEzIDMuODgyMXoiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMyIvPgoJCQk8cGF0aCBkPSJtMjMuNDA4IDM2LjIyNy0xLjI1OTggMC45NTg5OHYxLjY0NDVsLTEuNzkzIDEuMzYzM3YtMS42NDQ1bC0xLjc5NDkgMS4zNjUydjEuNjQ0NWwtMi4yNDIyIDEuNzA1MXYtMS42NDQ1bC0xLjMwMjcgMC45OTAyM3YxLjY0NDVsLTIuMjQ0MSAxLjcwN3YtMS42NDQ1bC0xLjU4MDEgMS4yMDEydjEuNjQ0NWwtMi4yNDIyIDEuNzA1MXYtMS42NDQ1bC0xLjM1MzUgMS4wMjkzLTUuNzY5ZS00IDcuNjgyNmgxNi41ODd2LTE0LjA3MnoiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMyIvPgoJCQk8Y2lyY2xlIGN4PSIxMC44MzIiIGN5PSI0OS4zOTIiIHI9Ii44Njk2Ii8+CgkJCTxjaXJjbGUgY3g9IjE2LjI3NCIgY3k9IjQ1LjIwNiIgcj0iLjg2OTYiLz4KCQkJPGNpcmNsZSBjeD0iMjEuMTQ4IiBjeT0iNDEuMzQ5IiByPSIuODY5NiIvPgoJCQk8Y2lyY2xlIGN4PSIzLjA4NzIiIGN5PSI0Ny4yMTEiIHI9Ii43OTMzMiIvPgoJCQk8Y2lyY2xlIGN4PSI2LjIzIiBjeT0iNDcuMjExIiByPSIuNzkzMzIiLz4KCQkJPHBhdGggZD0ibTE4LjU2MSAzOS45MTQgMC45MTI4NS01LjM5ODcgMC44ODIwNyA0LjAzMzUiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMiIvPgoJCQk8cGF0aCBkPSJtMS4wMTM3IDQwLjExN3YzLjcyNjZoNy4xNjAydi0zLjcyNjZoLTEuMzk2NXYxLjMyODFoLTEuNDg2M3YtMS4zMjgxaC0xLjM5NDV2MS4zMjgxaC0xLjQ4ODN2LTEuMzI4MXoiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMyIvPgoJCQk8cGF0aCBkPSJtMjQuMTgyIDQxLjg2My0xNi41ODYgMTMuMTMxdjAuOTQxNDFoMS43NTk4bDE0LjgyNi0xMi4zNjF6IiBmaWxsPSIjNzE3Mjc1IiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQk8L2c+CgkJPHBhdGggZD0ibTg3LjI0NCAxNjUuOTd2MTcuODExaDQxLjc3N3YtMTcuODExaC01LjI3NjJ2NC40MTEzaC02Ljk0MTN2LTQuNDExM2gtNS4yNzYydjQuNDExM2gtNy40MDk4di00LjQxMTNoLTUuMjgzNXY0LjQxMTNoLTYuMzA3di00LjQxMTN6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS13aWR0aD0iMS4xMDcxIi8+CgkJPHJlY3QgeD0iODguOTcxIiB5PSIxODMuNyIgd2lkdGg9IjM3Ljk0NSIgaGVpZ2h0PSI0LjQwNTkiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLXdpZHRoPSIxLjEwNzEiLz4KCQk8cGF0aCBkPSJtMzUuOTk1IDI0MS4wN2MtMC4xOTg2MiAwLjU0Njc3LTAuNjY2NTMgMS42MTA2LTEuNDg0OCAzLjE5My0xLjI5NzEgMi41MDgzLTEuNDA4NSAzLjY0MzQtMC40MTA4NiA0LjI2IDAuNzQ3NSAwLjQ2MTY5IDEuMDcwNSAwLjM1NzA4IDAuNzEzNi0wLjIzMDE1LTAuNzIyMjgtMS4xODg0IDIuMDQ2NS00LjIyNDUgMi45OTEzLTMuMjc5NyAwLjMyOTA0IDAuMzI5MTggMC41MjI3LTAuMzY5NjMgMC40MjUyNy0xLjU0OTctMC42NDczNC0wLjM1NzA3IDAuNDQ2ODgtMC42NTI3OCAyLjAyNTQtMC45MTUtMC4yOTM1OC0wLjM3MjQyLTAuNjgxNjQtMC45MzU5My0wLjc5Mjg4LTEuNDI3Mi0xLjU2MDctMC4wMTE5LTEuMzk4Ni0wLjA0MTktMy40NjctMC4wNTU4em0xMTkuODMgMi43NjA2Yy0xLjY0ODYgMC02LjE2MjggMy42NDQtNi4xNjI4IDQuOTczNCAyZS01IDAuNzEyNzYgMC45NjczMiAwLjQxMTQ3IDIuMTU1Mi0wLjY2MjU0IDEuMTg3OC0xLjA3NTQgMi43ODU2LTEuOTUzMyAzLjU0NjMtMS45NTMzIDAuNzYwNzQgMCAxLjM4NC0wLjUzMjgzIDEuMzg0LTEuMTgxNCAwLTAuNjQ5OTktMC40MTc2MS0xLjE3NDQtMC45MjI2OC0xLjE3NDR6bS02LjYxNjkgMC4wOTc2Yy0wLjYxMjE5LTAuMTI1NTMtMi4wMTExIDAuMzk4OTItNS4xMTA1IDEuNjkzOS0yLjUzNzEgMS4wNjAxLTQuNTgzNiAxLjM0Ni00Ljk4NzkgMC42OTE4NC0wLjY3MTMyLTEuMDg2Ni0xOC4wNTEgMy4yODItMTkuNzI4IDQuOTU5LTAuNDQ4NTkgMC40NDkxMy0yLjcyNTMgMC44NzE3Ny01LjA1MjggMC45MzczMi0zLjc3NTkgMC4wOTc2LTMuOTEwMiAwLjIxMjAyLTEuMjc1OCAwLjk5NDUyIDEuNjIzOCAwLjQ4MjYxIDMuNDUwNiAwLjYwMjU2IDQuMDU4MSAwLjI2NjQxIDAuNjA3NTItMC4zMzQ3NiA1LjI3MDgtMS43ODQ0IDEwLjM2NS0zLjIyMTkgNi41MjMtMS44NDA4IDguODc2Mi0yLjE0NjIgNy45NTA0LTEuMDMwOC0xLjA3NTUgMS4yOTU4LTAuNzA2MTcgMS4zOTUgMi4wMzI2IDAuNTMyODMgOS44ODcyLTMuMTEwMyAxMi4yMDMtNC4wNTEzIDEyLjIwMy00Ljk0NDcgMC0wLjUwNDkzLTAuMDg2NS0wLjgwNzYxLTAuNDU0MTUtMC44ODAxNHptLTIyLjI0NCAwLjgyMTU2Yy0wLjQ5NDc2LTAuMTI1NTQtMS42NTE3IDAuMjA5MjItMi45OTEzIDAuOTA4MDMtMS43ODYyIDAuOTMxNzUtNC45NjU4IDIuMDIyNC03LjA3MSAyLjQyMTgtMi4xMDUzIDAuMzk4OTMtMy41Njc4IDEuMTU0OS0zLjI0MzYgMS42Nzk1IDEuMTExOSAxLjc5OSAxMy41NjUtMi41NDE5IDEzLjU2NS00LjcyODUgMC0wLjE0NjQ2LTAuMDk0Ni0wLjIzOTkyLTAuMjU5NDgtMC4yODE3NnptMzcuNTEgMC44NTc4MmMtMi40ODQyIDAuMDI3OS04LjkwOSAyLjM2MzgtOC45MDkgMy40NjcgMCAwLjgzMTMyLTAuMjkyOTIgMC44ODAxMyA1LjgwOTYtMC45NDQzIDIuOTA1OC0wLjg2ODk4IDQuNjMyMS0xLjkyMTQgMy44OTIzLTIuMzc4Ni0wLjE2NDAzLTAuMDk3Ni0wLjQzNzk4LTAuMTQ3ODUtMC43OTI4Mi0wLjE0MzY2em0tMTAyLjY5IDMuNDE2NWMtMC40MDQ5OSAwLjEyNTU0LTAuNjkxOTYgMC44MTMxOS0wLjY5MTk2IDEuODE2NSAwIDIuODUxNCAwLjY1NjIgMy4xNDAzIDEuNTkzIDAuNjk4ODEgMC4zNjU4OC0wLjk1NDA2IDAuMTU5ODMtMi4wNTI1LTAuNDYxMzEtMi40MzY0LTAuMTU1My0wLjA5NzYtMC4zMDQ2OS0wLjEyNTUzLTAuNDM5NjktMC4wODM3em0xMjguMTMgMC43MjgxYy0xLjA2NDUtMC4wOTc2LTIuNjcyIDAuNTg0NDQtMy43MTIxIDEuODM4MS0xLjI4MDMgMS41NDI3LTEuMjYwOSAyLjA0NDUgMC4xNDQwOSAyLjkzMzYgMi4yMDM2IDEuMzk0OCAyLjU5MzkgMS4zNzY3IDEuNjkzOS0wLjA4MzctMC40MDQyMi0wLjY1NDE4IDAuMDk0OC0xLjUwNiAxLjExLTEuODk1NyAxLjAxNTQtMC4zODkxNiAxLjg0NTItMS4xODU2IDEuODQ1Mi0xLjc2NTkgMC0wLjY0NzItMC40NDI0NC0wLjk3NjM4LTEuMDgxMS0xLjAzMDh6bTE0LjkyMSAyLjg3NmMtMC4zNDMxMy0wLjA0MTgtMS4wMjkyIDAuMzMwNTgtMi4wMjU0IDEuMjMzLTEuMjk5IDEuMTc1OC0yLjM2NDIgMi41ODY3LTIuMzY0MiAzLjEzNTYgMCAxLjYyODUgMS4zOTk0IDEuMTQzOCAzLjA3NzgtMS4wNjcgMS40OTcyLTEuOTcyNCAxLjg4MzgtMy4yMjU3IDEuMzExOC0zLjMwMTN6bS01OS40NTEgMS4xMDMzYy0wLjE0MzM5LTVlLTMgLTAuMjk2MjYgMC4wNDE4LTAuNDYxMjcgMC4xNDM2Ni0wLjY2MDE3IDAuNDA3MjktMC44OTI2OSAxLjIzMy0wLjUxOTAyIDEuODM4MSAxLjAxMjQgMS42MzgxIDEuNzE1NSAxLjMzMjEgMS43MTU1LTAuNzQyMDUgMC0wLjc1ODc5LTAuMzA0NzctMS4yMjYxLTAuNzM1MjItMS4yNHptLTEyOS4xNyAwLjcyMTEyYy0xLjI5OSAwLTIuMzY0MiAwLjUzMjgzLTIuMzY0MiAxLjE4MTQgMCAwLjY0OTk5IDEuMDY1MiAxLjE4MTQgMi4zNjQyIDEuMTgxNCAxLjI5OSAwIDIuMzY0Mi0wLjUzMjgyIDIuMzY0Mi0xLjE4MTQgMWUtNiAtMC42NDk5OS0xLjA2NTItMS4xODE0LTIuMzY0Mi0xLjE4MTR6bTEwMi40NSAyLjg1NDRjLTAuNTk5NzUtMC4wNjk3LTAuNDYyMDEgMC40NjcyNyAwLjMwMjc0IDEuODk1NyAxLjQ2NTEgMi43Mzc1IDIuMzQ5OCAyLjk5ODcgMi4zNDk4IDAuNjkxODMgMC0wLjkwNTI0LTAuODEyNjctMS45NTU3LTEuODAyLTIuMzM1NC0wLjM2Njg2LTAuMTQwODgtMC42NTA2My0wLjIzMTU0LTAuODUwNTMtMC4yNTI0N3ptMTEuMjMgMC4xNjU5OWMtMC4xNTM1NS0wLjA2OTctMC4zMDMwNy0wLjA2OTctMC40NDY4OSAwLjAxNC0xLjU0MjYgMC45NTQwNi0xLjI2ODcgMy43NjA5IDAuNDMyNDggNC40NDc0IDAuODExOTEgMC4zMjc3OSAxLjUzNTEgMC42NDAyMyAxLjYwNzQgMC42OTE4NCAwLjA3MjIgMC4wNTU4LTAuMTIzNTgtMS4yMzE2LTAuNDMyNDgtMi44NDczLTAuMjMxNzItMS4yMTIxLTAuNjk5ODQtMi4wOTA2LTEuMTYwNS0yLjMwNjV6bTQ4LjUxNyAwLjkwODAzYy0xLjQxMTQtMC4wNTU4LTQuMzkyMiAwLjkyMTk4LTUuNjA3OCAyLjA1NDMtMC41ODY2NyAwLjU0Njc3LTIuMDk2NSAwLjQ0MDc2LTMuMzUxNy0wLjIzMDE1LTMuMTkyLTEuNzA4Mi0zLjg2ODYtMC40OTA5OC0xLjI5MDIgMi4zMTM3IDEuMTkwOCAxLjI5NTggMi40Mjg3IDIuMjUzOCAyLjc1MzQgMi4xMzM1IDIuMzA2My0wLjg1MzY0IDguMjU0NC01LjA2ODMgOC4yNjA0LTUuODUyOCAyZS0zIC0wLjI3MzM5LTAuMjkzNDctMC40MDE3MS0wLjc2NDA5LTAuNDE4NDV6bS0yMC4zOTkgMC4wNDE5Yy0wLjkzNjkxIDAuMzE5NDEtMS41MjUyIDMuMTEzNy0wLjYxOTg2IDUuMTgyNiAwLjQ5NzM5IDEuMTM2OCAwLjgxMTA5IDIuNTA2MiAwLjY5MTk3IDMuMDQxNy0wLjExODU2IDAuNTM1NjIgMC4zMjczNyAwLjYzNjA1IDAuOTk0NjUgMC4yMjMxOCAwLjgzMDIxLTAuNTEzMyAwLjgyODM5LTEuNDY1IDAtMy4wMTMtMC45NzgzMy0xLjgyODEtMC44NjE1OC0yLjEzNTkgMC41OTA5OS0xLjU3ODUgMC45ODkzNiAwLjM3OTQgMS43OTQ4IDAuMDY5NyAxLjc5NDgtMC42ODQ4NiAwLTAuNzg2NjggMC42MzM2Ny0wLjk5NzMgMS40Nzc2LTAuNDg5NTggMC44ODkzNCAwLjUzNDIyIDAuNzg4OTEgMC4wNDE4LTAuMjUyMzMtMS4yNC0xLjE4NTktMS40Ni0xLjg3NTMtMS42NzU4LTIuMjA1Ni0wLjY4NDg2LTAuMzYzOTEgMS4wOTIyLTAuNzE5MzEgMS4wNjI5LTEuNDU2LTAuMTI1NTMtMC4zNDc0NS0wLjU2MjEyLTAuNzAzOTctMC43MzM2OC0xLjAxNjMtMC42Mjc2OHptMzkuNDEzIDAuMDI3OWMtMC4xMTg1Ni0wLjA0MTgtMC4yODE0Ny0wLjAxNC0wLjQ4Mjg5IDAuMTExNTktMC42NzU1MSAwLjQxNzA1LTEuMjI1NCAyLjE0ODItMS4yMjU0IDMuODQxOSAwIDMuNzAxNyAwLjU2MzY2IDMuMjcwNSAxLjY1MDYtMS4yNTQgMC4zOTU0My0xLjY0NjMgMC40MTM4NC0yLjU1MjUgMC4wNTcyLTIuNjk1OHptLTE3Mi45NSAwLjcyODFjLTAuNjQ5NTMgMC0xLjE4MjEgMC43OTkyNC0xLjE4MjEgMS43NzMyIDAgMC45NzM1OSAwLjUzMjU5IDEuNzczMSAxLjE4MjEgMS43NzMxIDAuNjQ5NTMgMCAxLjE4MjEtMC43OTkyNCAxLjE4MjEtMS43NzMxIDAtMC45NzQ5OC0wLjUzMjU5LTEuNzczMi0xLjE4MjEtMS43NzMyem0xMDguMzIgMGMtMC42NzA2NiAwLTAuMjU2NTkgMS4wNjg0IDAuOTIyNjIgMi4zNzE1IDEuMTc5MiAxLjMwMjggMi4zOTcxIDIuMTE1IDIuNzEwMiAxLjgwMiAwLjc5MzUyLTAuNzkzNjYtMi4xNDY5LTQuMTczNS0zLjYzMjgtNC4xNzM1em0tMTAyLjUgMC4wNjk3Yy0wLjQ1MjU4LTAuMTU2MjMtMS4zMzMgMC41MzU2MS0yLjIzNDUgMi4yMjAyLTAuNjcyMzggMS4yNTY3LTEuMjI1NCAyLjU4NzgtMS4yMjU0IDIuOTU1MiAwIDEuNzQgMS45MjE1IDAuMzQwMzQgMy4xNDI3LTIuMjkyMSAwLjc5NzgxLTEuNzIwMSAwLjc2OTc0LTIuNzI3NCAwLjMxNzE1LTIuODgzMnptMTUyLjUxIDEuMTE3MmMtMC40ODQ0MiAwLTEuNDcyOCAxLjMwNTYtMi4xOTg0IDIuODk3Ni0xLjA2NCAyLjMzNTItMS4wMDUzIDIuNzc0IDAuMjg4MzEgMi4yNzc4IDEuNzE2Ny0wLjY1ODM2IDMuMzgzLTUuMTc1NCAxLjkxMDEtNS4xNzU0em0tMTE0LjM3IDAuMjgxNzZjLTAuMTczMTUgMC4xMzk0OC0wLjIzNzcxIDAuNzEyNzYtMC4yNDUwOSAxLjc4NzYtMC4wMSAxLjQ2MTQgMC41MTgxNyAyLjY1OTggMS4xNjc3IDIuNjU5OCAxLjQ3OTYgMCAxLjQ3OTYtMS4yNTY4IDAtMy41NDY0LTAuNDYyODYtMC43MTY5NC0wLjc0OTQ3LTEuMDMyMi0wLjkyMjYyLTAuOTAxMDZ6bS00OS4xOTQgMS4yODMyYy0wLjExMTU5LTAuMDU1OC0wLjIwNzEzLTAuMDU1OC0wLjI4ODMzIDAuMDI3OS0wLjMyNDc2IDAuMzI1LTAuMjI3MTMgMS43Mzg1IDAuMjE2MjQgMy4xMzU0IDAuNDQzMzcgMS4zOTcxIDEuMDY2NCAyLjI3MDkgMS4zOTExIDEuOTQ2MiAwLjMyNDc2LTAuMzI1IDAuMjI3MTMtMS43MzEzLTAuMjE2MjQtMy4xMjgyLTAuMzMyNTMtMS4wNDc1LTAuNzY4MjctMS44MDctMS4xMDI4LTEuOTgyM3ptNTkuMTA1IDAuMDY5N2MtMC40MjM0OCAwLjAxMzktMC43MjA4MSAwLjQ4Njc5LTAuNzIwODEgMS4yNDcgMCAxLjAxMjYgMC41MjUzOCAxLjg0NTIgMS4xNzQ5IDEuODQ1MiAwLjY0OTUzIDAgMS4xODIxLTAuNTA2MzIgMS4xODIxLTEuMTE3MiAwLTAuNjEwOTQtMC41MzI1OS0xLjQzNjUtMS4xODIxLTEuODM4LTAuMTYyMzktMC4wOTc2LTAuMzEyOTYtMC4xNDM2Ny0wLjQ1NDEtMC4xMzk0OXptOC4yNjc2IDBjLTAuNDIzNDggMC4wMTM5LTAuNzI4IDAuNDg2NzktMC43MjggMS4yNDcgMCAxLjAxMjYgMC41MzI1OSAxLjg0NTIgMS4xODIxIDEuODQ1MiAwLjY0OTUzIDAgMS4xODIxLTAuNTA2MzIgMS4xODIxLTEuMTE3MiAwLTAuNjEwOTQtMC41MzI1OS0xLjQzNjUtMS4xODIxLTEuODM4LTAuMTYyMzktMC4wOTc2LTAuMzEyOTYtMC4xNDM2Ny0wLjQ1NDEtMC4xMzk0OXptMjkuMDI3IDAuNzQyMDVjLTEuNzIxIDAuMDEzOS0xLjc1NzMgMC4xODEzMi0wLjIzMDY2IDEuMTY3NSAyLjMxMjggMS40OTQ3IDMuODc5IDEuNDk0NyAyLjk1NTMgMC0wLjQwMTQzLTAuNjQ5OTktMS42MjYzLTEuMTc3Mi0yLjcyNDYtMS4xNjc1em02Ljg2MiAwLjA5NzZjLTAuNDMzMDIgMC0wLjg2ODg2IDAuMjc3NTctMS40MiAwLjgyODUzLTEuMTAyMiAxLjEwMTktMC43ODQ0OCAxLjQxOTkgMS40MiAxLjQxOTkgMi4yMDQ1IDAgMi41MTUtMC4zMTgwMiAxLjQxMjgtMS40MTk5LTAuNTUxMTItMC41NTA5Ni0wLjk3OTc1LTAuODI4NTMtMS40MTI4LTAuODI4NTN6bS0xNy4zODYgMC4zMzE5N2MtMC4xMjQxNCAwLjEyNTU0LTAuMjA5NTQgMC41MzcwMS0wLjIzNzg0IDEuMjI2MS0wLjA1MTMgMS4yNDQyIDAuMjI3NDggMS45NDIyIDAuNjE5ODkgMS41NDk4IDAuMzkyNDEtMC4zOTE5NCAwLjQzNDg1LTEuNDEwOSAwLjA5MzctMi4yNjM0LTAuMTg4NTEtMC40NzE0NS0wLjM1MTU1LTAuNjM2MDQtMC40NzU3Mi0wLjUxMTl6bTIxLjc2OCAyLjI0ODljLTAuMTg2ODEtMC4wNTU4LTAuNDY5NjggMC4wMjc5LTAuODQzMzMgMC4yNTk0NC0wLjY0OTUzIDAuNDAxNzEtMS4xNzAxIDEuNjI2NC0xLjE2MDUgMi43MjQ3IDAuMDE1NSAxLjcyMDkgMC4xNzM5NCAxLjc1MDEgMS4xNjA1IDAuMjIzMTcgMS4xMjEtMS43MzQ2IDEuNDAzOC0zLjA0OTEgMC44NDMzMy0zLjIwNzZ6bTQuNTE5NCAwLjYyNzY3Yy0wLjYwNTg2LTAuMDgzNy0xLjE3ODMgMC4zMTM4NC0yLjExOTIgMS4xMzgyLTEuMTQwNyAxLjAwMDEtMS43MzY3IDIuMTMyNy0xLjMxOTEgMi41MTU2IDAuNDE3NjcgMC4zODIxOCAxLjAwMDMgMC4wMjc5IDEuMjkwMi0wLjc3ODMyIDAuMjg5OTYtMC44MTE3OSAwLjk5NjMzLTEuNDc3NSAxLjU3MTMtMS40Nzc1IDAuNTc1MDIgMCAwLjc0MTQ2IDAuNzk5MjQgMC4zNjc2MSAxLjc3MzEtMC4zNzM4NyAwLjk3MzU5LTAuMDkxOSAxLjc3MzIgMC42MjcwOSAxLjc3MzIgMC43MTkwMiAwIDEuMzA0Ni0wLjU2NjMgMS4zMDQ2LTEuMjU0czAuNjY1NzItMC44NjYxOSAxLjQ3NzYtMC40MDMxYzAuODExOTEgMC40NjMwOCAwLjQxMjQ3LTAuMjQ0MS0wLjg4NjU4LTEuNTY0Mi0xLjA3MTUtMS4wODk0LTEuNzA3OS0xLjY0MzItMi4zMTM4LTEuNzIyOHptLTE3LjYwMiAwLjE2NTk5Yy0wLjgwOTAyLTAuMTc3MTUtMi41OTcyIDAuODAyMDItMy45Mjg0IDIuMzU3MS0xLjA4MzggMS4yNjY1LTIuNDAwMiAyLjAzMzQtMi45MjY0IDEuNzA4Mi0wLjUyNjIzLTAuMzI1LTAuNjM5MDkgMC4yMzE1NC0wLjI1MjI4IDEuMjRzMC45ODMwOSAxLjgzOCAxLjMyNjMgMS44MzhjMC43MzM3MSAwIDYuMjEzMy01Ljc4NDUgNi4yMTMzLTYuNTU5MiAwLTAuMzM3NTUtMC4xNjI4Mi0wLjUyNDQ2LTAuNDMyNDgtMC41ODQ0M3ptMzAuNjcgMS4yMzNjLTAuMjU1MjUgMC0wLjc3MjE4IDAuNzk5MjMtMS4xNDYxIDEuNzczMi0wLjM3MzgyIDAuOTczNTktMC4xNjA1NSAxLjc3MzEgMC40Njg1MiAxLjc3MzEgMC42MjkyMSAwIDEuMTM4OS0wLjc5OTI0IDEuMTM4OS0xLjc3MzEgMC0wLjk3MzU5LTAuMjA2MDItMS43NzMyLTAuNDYxMjctMS43NzMyem01Ni45NjUgMC4zMDk2NWMtMC4zNTk4NiAwLjAyNzktMS4yMDI1IDAuNTgxNjQtMi4xNzY4IDEuNDYzMy0xLjI5OSAxLjE3NTgtMi4zNjQyIDIuNjg3Ni0yLjM2NDIgMy4zNTg5IDAgMC42NzA5MiAxLjA2NTIgMC4wODM3IDIuMzY0Mi0xLjMxMTEgMS4yOTktMS4zOTQ4IDIuMzY0Mi0yLjkwNjQgMi4zNjQyLTMuMzU4OSAwLTAuMTExNTgtMC4wNjY5LTAuMTYxOC0wLjE4NzQ2LTAuMTUyMDN6bS0xNDkuNDYgMS4wMzc4Yy0xLjEyMzktMC4xMzk0OC0yLjY4MDUgMi4zNzMyLTIuNTg3NyA0LjU2MjggMC4wNjY4MSAxLjU3NDUgMC4xNTAyNCAxLjU3NDUgMC43NDk2MiAwIDAuMzcwODctMC45NzQ5OSAxLjI0MzItMi4xNDMyIDEuOTM4OS0yLjU5NDkgMC42OTU3LTAuNDUxOTMgMC44NDk2My0xLjIzMyAwLjM0NTk5LTEuNzM3MS0wLjEzNjgzLTAuMTM5NDktMC4yODYzNC0wLjIxMDYyLTAuNDQ2ODktMC4yMzAxNXptMTUuNDkgMC4yMzg1MmMtMC4xNzIxMiAwLjA1NTgtMC4zODUyMSAwLjIxMjAxLTAuNjM0MyAwLjQ2MTY5LTAuNzM1NzkgMC43MzY0Ny0xLjAxNzcgMi4xNzUyLTAuNjI3MDkgMy4xOTMyIDEuMDgxMSAyLjgxNzMgMS45Njc4IDIuMjEyNSAxLjk2NzgtMS4zNDA0IDAtMS43ODEyLTAuMTkwMDItMi40ODk5LTAuNzA2MzgtMi4zMTM4em0xMjYuNiAwLjIxNjJjLTAuMzYwMTUtMC4wODM3LTAuODEwMjYgMC4xNTM0My0xLjQ0MTYgMC42Nzc4OC0wLjg5ODQxIDAuNzQ2MjQtMS42MzYyIDEuODIzLTEuNjM2MiAyLjM5MzEgMCAwLjU3MDQ5IDAuNTMyNTQgMS4wMzc4IDEuMTgyMSAxLjAzNzggMC42NDk1NyAwIDEuMTgyMS0wLjU2NjMgMS4xODIxLTEuMjU0IDAtMC42ODc2NSAwLjUyNTU4LTAuOTIzMzcgMS4xNjc4LTAuNTI1ODUgMC42NzM0MiAwLjQxNTY2IDAuODY2NDYtMC4wNjk3IDAuNDU0MTUtMS4xNDY2LTAuMjc2MzEtMC43MTk3My0wLjU0ODAzLTEuMTA0Ny0wLjkwODE3LTEuMTgxNHptLTQwLjkyNyAwLjU2MjExYy0wLjY0NzkgMC0wLjMwNzE0IDEuMzMyMSAwLjc1Njg0IDIuOTU1NCAxLjA2NCAxLjYyMzcgMS41NzY3IDIuOTQ4IDEuMTM4OSAyLjk0OC0wLjQzNzgzIDAtMC40NTg0OCAwLjU0Mzk4LTAuMDUwMiAxLjIwMzcgMC40MDc5OSAwLjY1OTc1IDEuMjM1OCAwLjg5MTMgMS44MzggMC41MTg4OCAxLjMxNDItMC44MTE4LTEuOTc3NC03LjYyNi0zLjY4MzMtNy42MjZ6bTMyLjAxOCAxLjE1MzVjLTAuMjQ3NzItMC4wMjc5LTAuNTE0MjcgMC4wODM3LTAuNzc4NDUgMC4zNDU5MS0wLjM4OTg2IDAuMzg5MTYtMC4yOTI1IDEuMzgyMyAwLjIxNjIgMi4yMDU2IDAuNzQ0IDEuMjAzNyAxLjAxOTkgMS4xOTk2IDEuNDIgMCAwLjQyODA3LTEuMjg0Ni0wLjExNDM4LTIuNDgtMC44NTc4Mi0yLjU1MTZ6bS0xNDEuNzkgMS4yMTA3Yy0wLjY0OTUzIDAtMS4xODIxIDEuMDkyMi0xLjE4MjEgMi40MjkxIDAgMS4zMzc2IDAuNTMyNTkgMi4xMDI2IDEuMTgyMSAxLjcwMTEgMC42NDk1My0wLjQwMTcxIDEuMTgyMS0xLjQ5MzIgMS4xODIxLTIuNDI5MXMtMC41MzI1OS0xLjcwMTEtMS4xODIxLTEuNzAxMXoiIGZpbGw9IiMwNzUzMTMiIHN0cm9rZS13aWR0aD0iMy42OTA1Ii8+CgkJPGcgdHJhbnNmb3JtPSJtYXRyaXgoLTMuNjkwNSAwIDAgMy42OTA1IDIxNS4wMyAzMy42MTUpIj4KCQkJPGc+CgkJCQk8cGF0aCBkPSJtMTYuMzE2IDQwLjYxN3Y1LjYwMjhsLTIuMDgyNSAwLjAxMDIxIDAuMDI3OTEtNS42MTN6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjIiLz4KCQkJCTxwYXRoIGQ9Im0xMy4zMDYgMzkuMTAzLTEuMTA0OSAxLjUxMzh2NS42MTNoMi4wNjEydi01LjYxM3oiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMiIvPgoJCQkJPHBhdGggZD0ibTEzLjMwNiAzOS4xMDNoMS44NTcybDEuMTUzNyAxLjUxMzhoLTIuMDU0NnoiIGZpbGw9IiNmZmYiIHN0cm9rZT0iIzAwMCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgc3Ryb2tlLXdpZHRoPSIuMiIvPgoJCQkJPHJlY3QgeD0iMTIuNzUzIiB5PSI0MC43MDUiIHdpZHRoPSIuMzQxNzciIGhlaWdodD0iMS4yMjMyIiByeD0iLjAxMTM2IiByeT0iLjAxMTM2Ii8+CgkJCQk8cmVjdCB4PSIxMy40NDIiIHk9IjQwLjcwNSIgd2lkdGg9Ii4zNDE3NyIgaGVpZ2h0PSIxLjIyMzIiIHJ4PSIuMDExMzYiIHJ5PSIuMDExMzYiLz4KCQkJPC9nPgoJCQk8cmVjdCB4PSIxLjc5NDEiIHk9IjQ1LjM3OSIgd2lkdGg9IjUuODAxIiBoZWlnaHQ9IjEwLjU1NSIgZmlsbD0iI2ZmZiIgc3Ryb2tlPSIjMDAwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9Ii4zIi8+CgkJCTxyZWN0IHg9IjEuNDA1NyIgeT0iNDMuOTYzIiB3aWR0aD0iNi4zNjQiIGhlaWdodD0iMS43NjU0IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQkJPHBhdGggdHJhbnNmb3JtPSJtYXRyaXgoLjc4OTQ4IDAgMCAtMS4zOTUyIC45NzU3MSAtMTIuMjIxKSIgZD0ibTQuNjM0OC0zMS4wOTMtNC40ODI3LTcuNzY0MyA0LjQ4MjctMWUtNmg0LjQ4MjdsLTIuMjQxMyAzLjg4MjF6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQkJPHBhdGggZD0ibTIzLjQwOCAzNi4yMjctMS4yNTk4IDAuOTU4OTh2MS42NDQ1bC0xLjc5MyAxLjM2MzN2LTEuNjQ0NWwtMS43OTQ5IDEuMzY1MnYxLjY0NDVsLTIuMjQyMiAxLjcwNTF2LTEuNjQ0NWwtMS4zMDI3IDAuOTkwMjN2MS42NDQ1bC0yLjI0NDEgMS43MDd2LTEuNjQ0NWwtMS41ODAxIDEuMjAxMnYxLjY0NDVsLTIuMjQyMiAxLjcwNTF2LTEuNjQ0NWwtMS4zNTM1IDEuMDI5My01Ljc2OWUtNCA3LjY4MjZoMTYuNTg3di0xNC4wNzJ6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQkJPGNpcmNsZSBjeD0iMTAuODMyIiBjeT0iNDkuMzkyIiByPSIuODY5NiIvPgoJCQk8Y2lyY2xlIGN4PSIxNi4yNzQiIGN5PSI0NS4yMDYiIHI9Ii44Njk2Ii8+CgkJCTxjaXJjbGUgY3g9IjIxLjE0OCIgY3k9IjQxLjM0OSIgcj0iLjg2OTYiLz4KCQkJPGNpcmNsZSBjeD0iMy4wODcyIiBjeT0iNDcuMjExIiByPSIuNzkzMzIiLz4KCQkJPGNpcmNsZSBjeD0iNi4yMyIgY3k9IjQ3LjIxMSIgcj0iLjc5MzMyIi8+CgkJCTxwYXRoIGQ9Im0xOC41NjEgMzkuOTE0IDAuOTEyODUtNS4zOTg3IDAuODgyMDcgNC4wMzM1IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjIiLz4KCQkJPHBhdGggZD0ibTEuMDEzNyA0MC4xMTd2My43MjY2aDcuMTYwMnYtMy43MjY2aC0xLjM5NjV2MS4zMjgxaC0xLjQ4NjN2LTEuMzI4MWgtMS4zOTQ1djEuMzI4MWgtMS40ODgzdi0xLjMyODF6IiBmaWxsPSIjZmZmIiBzdHJva2U9IiMwMDAiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIHN0cm9rZS13aWR0aD0iLjMiLz4KCQkJPHBhdGggZD0ibTI0LjE4MiA0MS44NjMtMTYuNTg2IDEzLjEzMXYwLjk0MTQxaDEuNzU5OGwxNC44MjYtMTIuMzYxeiIgZmlsbD0iIzcxNzI3NSIgc3Ryb2tlPSIjMDAwIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9Ii4zIi8+CgkJPC9nPgoJPC9nPgo8L3N2Zz4K",
        "mtsensk": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACgAAAAwCAYAAABjezibAAAHTUlEQVR42s2YaVRU5xnHfzP3zgwwwwyETUTA6kBwl0QErUJ7mkVNazA1q0prcYlJtNWs2lPSmCLmmERD2w/ZXGIT1GJtbCRuQUlVMMSD4oZsggzgAsgywzCXYW4/zHEIAVHKnGSeb3PvM//zu+99nvt/3lehn71KlgJGcMeQu3BfKEGhuGOWutmEaAuKxhY6Bk8MWSmixMPD7YANiYmeC7imdhYqUSbt6kzPBPz44nTGzw8h66CP5wHqi/ewIDGWLXvzscui2wAHrSS21mPXh9I6fg5vA03vv4Ojq+vHX0FteR6PFL3Fy34VRG6e67p+ZP8eFq9MAyA3OQxted4PD6gtz2PePQ04Om189tEm9AYDAD5VBTy1cDmBwaEgO1g4ewoWY9IPC7ikaTeRp7YQ8ZMoKirKMcaM495xk4jcPJdZUhHmtlZElYo/eRUSNizc/TVoKNpFS+wTfSbHffl7DtTXOjs2Mx2bbyg2WweW5hsAOOyd2GxW0l9ZwojoMdSaatwPuGK8yJvfX2ZrC+FZqRT+LruXQB0QmPce8bFxeGt9OfDvLJSCQHnJWRoSl7u/SZYuXdgryeFtoLoPuFvx+MThJD08h6KCPJIefpQRUaNRCsKg6++2Nai7uP/uBawt/PHFFP6+fg0HD+0h78DnbNv8Lt5e3gOGSfjyhf4BvUynAQjI/+iuRcOzUpEkieMnDgFw/MQhLBYLDzww8NXbsXMrwz5deHvAFEU+AM89v3hAwmq1mjWr17p+19bW09zcOvCGEAU+2LT29oBpr7+GJElcKim7o9jQf/0BwFWb6zLSWLN6LUsWL2fIkBDWZaShkNpd+Zr68/3q+Z/cCsCxY/n912BBQSE6nfbO9TIyqNe1RYtTiE+IY+0b6/n66+MoJYvrnm/p4X71Xp4e7Kx/X13/gGVlFeh0WlRNVf0KTpg4ttc1u90OQFXVFc6dvYDCYXfde8yo7lcvJeVpAIwjRxDxHetU3rKoC084WVNTU7jZ3MwXj2h6CEwtSGdF4xYy/Z3eGhwUyOidvyU38YYrJzraSGpqCtm7t/Pc84tJDynGtMhA5Oa5PLss1enPiTcwLTJgWmRw/S9s17IeD3706D7u27usG1Bht6HX+7qSXn11FWdOF/cA/MsrS3h2WSrJc36Jpv488QlxWDus6LS9y6GysoqGhkZXqUyZMpng4CDWqXOIjjYCsG/fAVf+yYOfdfu8VssX/9lPRkZaN6BgM1NaWk7xmXOUlpYjSRLPzOtpd9HRRmbOeIwdWdmMKtiI2Wxh/vwne9UMwPDhEVRX1/DVYedqv/1Ouus1tra2ARAYGNDnq/7kkyw0XhrCw8MAUGheipNtEe6bgN0ZmivtuG30jdhQQkKMRF6rAatRh76wCdMLUT/+RH0rWqcEEKO/gvJKM6f+2463RsbkCSO/a6BQKdmWo8WgdZD1ZhN+OgfGWg/aNLXd70+QXxfTJkiE+Ds4VqzxrF2dLCqZPlFCJcocKtTw+od6z9sXZ+drUSqhpEqk+rUYzzz6eHByB0uSLZ55slCzMprsXG92Hu79Xb1n/1X3d3Hk+hLUosxD8R1crhM5Oj6S9lH915YoQFNb7+c2j3N6r8LuYHfnN+w47EPCWImUme2UVIukvhXIpRXRdw847G/dM2HRJTVeGpktwy7y1RENMxI6ePGvBhbMaEejggzbSMwT/Zwb91Mapk+0uf67tfEbSqpEDhdqiB8jsWCGlaxD3tjtUHRJZPY0BZEhXbRphD45BHFq2J+7DKo+2hKM5jaazUr89Q7iR0sYdDKCEkqqVSQnWpk+oRNfH5kj2+20TAsEoGlqEEUjhjj9dm8dsb5m5xg1zE6Qv4MKkwgK+MUkG2o11FwTeW+Xjp/FWMkPC+25ei2dt1/BjggffhNh4cPPtZiuC4gToKpeoKRaxaqnzMzYZ8R+TU2nvwrppe4NUvjGUrp8BOqWjqRh9lBMJ67xz7N6xNZOHk+y8vSD7fx6dQAF5+wE+3cREdJFaEAX2bneMLk3x22HBe+yNjS1Vu6ruc5VQcOFZ+7OVzeUf8vP77cxqeWnAzsdO9lIa3zA3Q8L1ihfrFG+5BI8MMuT4Y2P9TB3gF4e3/f4pRQsdrd+B+tuCEyKkZi18+ygtQSLHaVPmdltcEPfryD23k6uNQnkPDlu0Ho+ZWaUobUKtwEmj2qjslag5rpA4N66QesFVztQFl+45DbAQD/nyeq5SpFNiYM/2TpfWu60uqn/GLx36k82crVR4NgZDQat3KfdDeicZltztxcfP1lI1MbLgxK0DfHCT+fgcr1AUqwNb438f2tFbbxM/renew4LpZXVFMRlELGhBPGmNHDASC3bz/uTubKF+kaB8JCBHaSLNyXCN5ZSEJdBaWX1dxxtkHH0SK4cOTREJjNJJjNJ1s8bK5OZJEcMDZFzcnIGKy8rZFmW3dEgu3d9ytyrHwCwN3Ilv3o02S2N5zZAgItnT6AQ/YkZNcptX4b/AfbjH86HmQZYAAAAAElFTkSuQmCC",
        "belev": "data:image/png;base64,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",
        "chekalin": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAwCAYAAABwrHhvAAADmUlEQVR42u2XT2gjVRzHP690YXKbwRWcgAvxNrCX5iIkiLQDsnTBXZoFcddb97K0nhrw0HjbnMzAoi2y0F48LAi7ZRXak4kHTaqgDSzaVg/2ULY5iGTUrhlUeB5mJs3U/Bknnc7FHyTvzXu/N7/v/P693w/DMGSSNEHC1BdAoVAAwDRNarUamqahaRoAjuMghADojv7c5+nd78c7EkAmkwGg3W4DoOs6uq4DYFkWUsour2ma3bnPf1pgNpsdrIJhPjAzMyOr1WpgrdPpSEVRZKfTkYAEpJRSqqra5QH+te+Pp2kyjJ38r/G/3HEcUqkUUkoajQamabK7uxs4oyhKOCdIOgom98ghitG9ODfn2vdhvol+VlFwVnRFhawO9nkC2OuZ/56CB1VQJRR61NOKE4ABNOvuvN6CigkbAh55UltHBEwViwmm8vDhiju3XwDLM0OjDno6yDsZl/3vLLpZ4KGAt190zZDrkwzHBjC7XfBmTfd/BxYX4a2bcAcXxAc+s5dAHQeUlJdjMOYls2sDBWxagqtLcuC+rHi2FQIdV9VfpaH0B3xmw+M1uF4AtJMzahgfMN532Wa9Z339pVAaUYErR/CN7ar95UVQVaituXtq2DDc/evXk8vp/iVes1v/zTYSNtbBcAABc/OQ1yPmgfrxIfdw4GktlOz9b8G2YetdF8inH7sg6kfwiTIUgBN48tWue6rTvrZQP7o8EsD8DVA1WGvBrTS8/gasqi6Ia52hABSkdRIrm/ZBYPfP5zNs/vz9aI31HNOn4R0VFvx8LMKE4cGWm1BOLV/40VtfTdNcOAIg3/AuowFgKg+Ggw0AyNy/5PrPxtW+zG37AE3RWXVa3Dq1d6M+FSmPBAD8dHw48kDbaQ293ca6jsMG2mU9Fw+A9JCM10tPb9bjAfDchglSjv7FZYJf5qqUy+XhBeqbtTMF0P8yajXorGcDlW2pVKLs3B14GZ1pZ4Se4+KrwUq1n/DYWjOAZ6+ssLe/T7FYRNxunm9v6FOjXqdSqYA6lQyArS++S6Y79qn55EnsAIbWhE6IFxRLxfgA/HbBGPmC7dmai1Rh8BjVBM8uhnQ+ZcQYuTUz5sdqXBNvTv8HMHYUhKH3WEkWQC43XnU0MXn8Q7I+8Pfhl4kJF0IwsbwjBZZIRPjyjhRieSdajVcuWpKppW5FlL9dZHqhIs4tDJcrS4Ltsie8FEk4QGQN+PT5aklOL9yNbMN/AC2xbX15HxOqAAAAAElFTkSuQmCC",
        "kozelsk": "data:image/png;base64,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",
        "kaluga": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACMAAAAwCAYAAACbm8NsAAAFJklEQVR42u1Ya0xTZxh+vo9D6cXSUqCioICAQ2d2URDCEtjFZcNLnFl2UbZlyxLnnEPnklmNMxOzDbuRKaTCFn8scXO3LCZz6qbORVwyo8RlpiBqsQJqFYO0rLaH2p53P9Aj7QprsQyX8Cb9cXre7+lz3svzvj2MbT1LxDlG2xjnGH0WA2yMzP+CjBBrwGtv50IVT/J1D+OY+OHZyIr4TruJcQHSW1kQBxAIZ0fVSXhkQ9PIdNPO6jJ4TTnQNTaiWZXwr/7Fnh7oHS2xS1NC+wk465/BpqwSVKw7ApIkAEDOj2JE5x1bF0BV3Tb8Al54cCu8physa3gRfZkzoapuwwfLdshEdlaXRR3RYUXGZcqF3nweqjkrB/VZ5LwQFZmh/Icko6u2AZJ/TPSGZfPvXRyV/+t5T8RWZ5gyEdIbRiAOYGYbvKaciM8O1k1R6Qzz96HPlItLa/MA0Q1WYwMz2wAAGaVVEWFoN5y6c53xmnKQ+NIvSKi23fxGCrrfPbcCE8YZ4Ni7YlCMCfN3wK9WjOw4CLVfqwpQ7OmJeAwMTFNMByX3OFHs6cEufQYqTEdAIREc8anNFOPgW50GQQKETacHFKgUNdawyNya1P54QPvUt4iXa2kU9hnBagOrsd0dondjetZ/q8BMoYbW8jzec3yKLxMPY8mhSiiPfA4WBf/4q3YUNJTD3PsF6nzfo6ChHPFX7UMIUX4hafMLaW5pEQ20uaVFlLLATKzuIjFLJwmbT5Fh6pN05bJD9hG9XkpPTSZNQTklJaeQ+f2NQRhZqYmkqTxAzNJJzNJJmlWHKD01OcinrsZMer2ONAXlJEzydvTrweUHwesvgQIimEIN3clWXLywHGqNRia+d9oyZK7/DuL98wAA6o5L0AY4pjit8CYQNv/GsKahA+Tvn/QFxjS0fTIHt2UsA6WNaeC1NhDnYIIAw0ERKWoBKqcVGG/QUXpqMu3ftyeIcfb4JNKsPkzM0k6svp2YpZ30i7fTOyuXyz6BANGSRfNIr9dR7uSJ1Otyyffs59ooJWs2sS32/vP17cRqO0if/TCdaT0l+113uyl/8kQy6LTE9M/tICRwuGYVg24+gXpXFZq3b0BW9pR/pLVy6SvYlv0aAlpj/yrafR2q5kbcMObBM2M6yO8DU6gxq7YMx62nw5ZGyQPTcHT5YZDPDSYooLa2IL7rLISer1+A5JfAhduFuWh3O+7bch5/5YUUtSAg9U8Rv79KKCy6TbRPzEOCUhnka3gXcjqCMCQJeocEaakRgFFOX59YCkG55hi4EAdxUirI7wfjAjJbz6H350fDPtUPxqdRur0J4vHx/eDgUHU64EtOQmCcEiRJYJKEFQtLUFuZGxaj0loCXnsGxPtlTvD4oOjuASOioD88B37ai2e/csJVVNIPDA5wAST5ZPXVb3wc166cHrRD8ycbYVt9DAFBks8AAN1cYVmAY2rNbLR2dAWL6cBQMi5AuXs3PHsswBCT/CNnBeLMJyCp9WFnVVKvCP+qoYUxrcoH/lkXyOeWS0CQQkI575s/oNzUjL5kzaBzyXDQh0Prr6Hs0Znhf2gtB9/WIUciHIYRCKmbEdhnxl4WjZEZIzNGJpSMorv37mDidYPP3vPyXcElc/ND4I1NJ5m25fyoEtFZ22DvcjF2a2inT0inq2/uh1+viQjg1mu0waQ9Eotzi8j4uAj2LhcDABayQURlhTPuoaZl++TraVseQ4vNzoYNSER3/EFdG8UCJyatrW29EJPa+RsbKrLIc0E1VwAAAABJRU5ErkJggg==",
        "aleksin": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACcAAAAwCAYAAACScGMWAAADHklEQVR42u2YIW/bQBiGn0QFkUIc1pJJHguaWuaRSUVVqhKXZSryWFHlslKPrf8ggR5bSeXAKiNntrJEI440FNawViU3cHHtJWnsi50smnaSZce5sx+/3/e9d3ZFgmRLW5Utbv/h/km4nUUnewE0GjAYwHgMoxF0uuXffCigtgthCO2POZVrNsGywHHUb8OAS7dcKCQ0LTBNuLt7paMEObtFEVLKZIsipGUhO535vtqbRPo+MgjUseu+ft1Xcy4Mk+PxGI6P1bnLZgHFApUihgGtVnKPXlenIA5gdzf5aVnQbquL0lodrtlSD9pqwTCEblelkB9qwJmTpBBezplwfg6TCXxy9MFGUfKgANdddU2Amq6VWO9hfPpneOOLmSZ8PixWFIahohOGSzrlSeK4QDxP7R0Hadv5iyAIkEIkxRAXQau1fFwuEzbfqhDHeWjbcHAAp3Y+lRoNFc7RSG2Hh3BzA0EvY6CODQxEYi8DoRTMGuO5iR11Oko1YeS7H7o+lfZAz5uGOsPX4r6+r3cvVjFSkVLQcZCPGUp7Xj6VS4GbVdB1FzzAVRJOneIpBS6uwrgC58IrlcKrKFYKXDrEQiSAQijFMvNx3XDp3HrxLlkcrDS4dIhtG2kYSM/YIrh0iHUto9AMkaeFQq2cw1DNBnlnj7W/Q4RC7ff21IJhOFTTW1gUsKj0/nniZ7NWssj/NpZzfspoZ2cJYScVvHE4z1VQrot8qNUWw/vFACkSSttGts3sCo4fYu1wkZOYrGvnt5iByF5cFlduCib29cZ1OmosGmMqOp/Avvrw+Ai9Hny7Wc1yRiP44cKXcYlWIq5UeIQo/lKddwmVCy62hTIm83RqFIbzrWTFW9Yc/NDMZ9JL4cS+Xhi0FgnTaCyrYLLcv+gUlKVgFKkllp5yawabex/RUs7aDFhpPrfxb8JhEGwlWBgEVJ/r9co2wj3X65UqwPd+f6sAY55q+sSkVtsaMIBKv9+f6/Dh6Ejy9PTXoJbC6bR3FxfSuL9f+N/Ycfh5drZyyhSGi9ub21tpXl9TZg7vlBWWXycnFUBO96W032UeGYi+r2/JAAAAAElFTkSuQmCC",
        "tarusa": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAADAAAAAuCAYAAABu3ppsAAAEB0lEQVR42u1ZPWvbQBh+TmQqIUMxJnTQkJpSDHEheBRUUyZNoU2g/yAeNKfQsVAPHYSG+B8U0prg4SZPV7ixBOqAEcXNkCGYIkoppas6xKeeL3f6cPzRQl4QtvXxvs/zfvn0HmGMYRGytbWVyL8vLi7IIuxY81ASBEGyjGdmIvDo/qvk9MRNTF4OgiAJwxDD4bAwoOFwmIRhiCAIEjVSQk5P3OTR/VfJzARkBUeHjlFBGIbwfT8FVgQ8APi+jzAMjfcJm1kOBACiqwEdc84jVOtdkpXrlFL0+30jMN/3sbu7C8/zMmvj2/BZ4jiPbzz/5ftrkhmBomFTQQnxPC/Tq2EYToGXny0iumhMRcAE3uR9XRRkUIKM7lxeZzJFQY1ESiALPIDCBMpIHgEAyCNhidTR3dTucC34TddNxKF62Pd9+L4PSunUIc6rkVJ1CRE2BQZdk0kjoPN+u8NxdOjgrMFRk84/xmIlkr6PAOwMnBSLLgrkauBowTvbFYgQ/mzwaQJvs0FUekeIn7yZPvf5Jc7etTKfs217isDGwElTmJ/HWhKWLued7Qqq9S6514rBeQRq6kBfr4+rXWfukaATLPdaMar1LnG2KymZKQIix9odDs4j8PM4zb8agEYrhn1c0RoRUVqE2McVNFpxmr7Vepfw82uHypitvQNG5GLdO2AEAD5NiopmdKD93zHCh8CDPp87gWq9S0TkBZa9A0bk4t47YGRNXCij/HL/MvP6Tu94oYUu481dzHmSB9RWCQD2e3vqs+y/q0k+uW7i3WY12mR/WaqKek4PPad3A7z93kbP6c2FgGfAospalpLR5LOG1Yiwvz7r+0AEYJ0xsiL8WGeMRDn3ZEbAFLplFnEzx4FWkWJaVQSK2LbKFBNdAmhqsD2Xl/rmEuqhrA1jDWxqwre5hHRSbYjfYwMx61/L+7L1YJnyXjCmKwQtbI8ZI16ZGtAV0pgxMl5CDch2ijQQa1XFOq/itooUE11h+uQ1D+s27P+FdmrhP5c7AncE7giUFLbAjjSL7v8+AmtFF1JyX1778QIA8KCRMQ9SRosxb8O229pbrwZisve69FSCmHYpVQVjxsgv1012JsZ0uyWquB+eJgDAnn/MvVcMmM8aHOuMEXUlYPpjI1nbrKqSFxPwwsg8U0F2zrsGh+q8mVKISitCb6L48hCwATSVSFFcT65rk3GISvCX6ybiWjTRJ3s2AtDvcNidm6vQ5iwpZFpIjQxzInGeZrzLimt5OlDQ+4W60MbAwcbASVeHpiFXrcCLuFdQB5Xs3qqNisJqdziajBGq8ah4ARmVyPeR9JxOZ5P9nZjn7ZoaU0gGX3Z6PS85PXETsStj6nqZEeA8Whl44HqMrtuVkeUPKscZgd005NoAAAAASUVORK5CYII=",
        "serpuhov": "data:image/png;base64,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",
        "pushchino": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACYAAAAwCAYAAAB9sggoAAAEZElEQVR42s1Zb2gbZRj/5e7eXtp0NthEnGZS2g1k2CmtOrZ9GcMMP2lYp0TiWqHsjyDIcJBaUeuqYmBOhkVmBYkbxdKtEsiXYsE/FKV+iNYNtaAbk6aUNnVmay5/evf29UOWmCxN7i533fLAfXjv/cPvnuf3/J7n7iyMMYYaNIF8SKFkagsU6+fBoUaNqzVv5UMpiDAcyunDCnY6RQCA5X1qDjCjByj+OHi+uWAM8DxvGKBhjgkBO+YpBb11WQdkU7xW4jEhJWefvJ5oPsQVKBjo2AcAX7woo/cCKaETdzuo9ABBuo+ASIsbTvDpwwp8DxLIr/ElcxbhlMKUDJDwF0+kAdjTcVjP2jdE53JcBABKKeIA7IhDCNiLdawxANgH5DyowR8SEM5oB6X40+jZPq+DmwClUn7sCGT5mvcY3lPYejxTdHLl5TYfTj57Bs7TDl373Juv4NvrbUUOYP08OMItlz69TlDLrwKLmSUcHXuhhBJqNrnQtm5UOHnNYYgrX3UlcGTcnR93j7jzmW1ILqQxV9Wbk6KAt9r2lNz//fUYWnd2IMNXqd/9C8YE1vHTHBYzSyX3+y72gL8cuzvKL0ai6Dq3r+x817l9YJFo9cBEqt/dEmmCN7RXdd2xLz0GPGbVv+ne6d+wJqlnbnJNApn8pUpgaf2bcoqtxYjz/mo5lkYtGocqYilR7W0N/Sd957IytbtFe1U40HHngDVkFATcQdV1w75JbLrxr3FgjCqaNzY9sx+kOVU+hCsy6jtdRjhW0JxpKCGMKiBHP8DK3qcwdDKKhnUy9NCOg/gsGIMYiUKMRCHRe3QDsyiPuFiGV1TANMI6M4vnR9wlc2O+MP7wHMDbz2UL99jgHMIXjuP8pYtF627KMiZ7p5B8bLM6VWYW1IGl3ngX/TfHsUzKZ9cqLwNpoI6oi24DZ8OnLSeAV7wVgXFqyI+kRiqCAoA6ShDuncJ49zeaqsGhq++ARaLg6hz6Q3nc34FlObWud0LeUNG7ZCVboX/DFzwIQjaVdiekHh8FftYXyqtbdmDQk4RCtHWzOW9V6jgKzbm6itNDV8pGqmwats5dwudnBVinZ+Ed9WBNRe2ldidgtYLra6lY4Bt4HkHvBDIqUlKRYxZZQaZzK87vGYIgl2+XR6UewJpdP+qZKLtuV/N2nBqeVwWlWS7yTxH6DmSLC57g0wCAcO8UpHYnLLwAMfIXMp1b8y13/Y/X4A1me7bQSxO4/ug22ARt3wg1yYXmMjWzoEmjtJ5VddvDqAJGFSRFAZJiwWL3MYj0vvz93GXgo4oVgL4DmJSA7c8VAICtgPzxlsfRHP61aG3siYdhk29UU5IcrOrXrNs8aLscg9S+DRY+YUYozTWjoAx1sOVsafcu81rrr0+8adphjclrhs8QbyWMhTHGzEpzs6Qir/y5wd22T+r+L/QWo79sZjtb8RAt7kL8TQ/g4+8jxpLIrH9JOTqY5X3T5GL4yf2GPqJsmMc24E28Nu0//V/M79h9LhsAAAAASUVORK5CYII=",
        "kashira": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACYAAAAwCAYAAAB9sggoAAAE00lEQVR42s2ZL3DiTBjGf3Q6NxuXOCJzLjhwQYLLudYVeXWtuWnddT5x05lTnTPUHRJc6sDRqeIcuOIuMrjEZefMfoLytyQkkPvmew3Jbnb32fd93mffHUq0AwUCkMxt8byvja2+rG3Z1jqdv2xPcoiJteekTWS3EwozuQXquE2erCYRBQEUHBcFuR7KQwHMF1efzY2eUidI2azMNO/J+w9ljp2JnJ4QGceIhce2s4KUzBEZQYk9XBRbvNxsO8lP7k0u7AtzsndlFo9xQDhFjk1st+2TklTy7wopqM/GXsjbybBKCJF5c6fFEjwrHcQOQV4HKtI4VjSoPFopF8BkSjYWeWTJPQ5YPZ9mI7DYIZ7JnCp1wj3g5N5wn2bJkORqgYxalaaTuyNysk9PNgGIjDsXe3gqU8aIY6qLfceLzMEzkVT2ZBVKcWQG5htfmlewpJyLabxJUvSk0id7tXGyfydpoihTPCO3eCNycHkn+UWGECYVl9mkYPWdTPTsabayJK0y2CWQxxcBJaWU4n9oB8nF8/MtAE+9HpFM9s5TvQaQ+k1yiXKgeV5Vtdu2urm52dkfNKpKKaX6Z+5B8x8msLLEeOwymjaYTCY89XorL/V6zJo1xrrJU72Ge+j5n3UH/VFfeU5VhXGshkNLga0cx1EIfeVFp6pi11HKdVXsOip2HfXy8pK4RrXqJK6Xm/wP9QquofPsRnS7OpqmMRwOmTVrjGLwkbQ0gS4Ej2FESxOUh+ONOWq1OgDj8ShZ+Q/JykhKapUa5bLOaDTi4eGR1qBDN5a4hs4gjHANHQC7v1r8/PwcYZrMplOGw2HxWdmoNwCYzSIAWoMOoRBcGToWcGXo+MJgEEbLjGxdXs5/W+5eUBlq/t3eMk2DVqvFYPAEQHk4ZlSvYWigC0EkJRYhtbeQnp+fA+B53t/Tsavra3Td4vHxkTCMl+1nhkk3lgzCuYcMKSkPx1xeXmMYJpZl5asu8nKsdXkJMWiaIEbSDQIeQh/r7YhxDcEglHRNC8uy8H0fu1Zj5geEYZDZa7lDOfN9AHRdIAyTgZhzCmAQShohGIbJdDJFSkkQhMAY3w9oNOp8+vSJfr9ffCh1Xads20wmPqaucz3xaQmTyjSC61tM00QIQbmsI9+Ib1kWd7fX+L5PEIR8/Fgp3mOe5y3JPJlMODtz57WCYeA9PzOZTLEsk9ksolpd3Z7OLi4Y+z6WFeK/eb1wufA8D6dRX4LzfR8ZBmgILi7OiOOY379fiaKIsm0TSEGz2aTX6RJISRRFxZN/3X79mtBqtSiXder1FdB1nWo2m+/GZdGxg6uLdXMcR4GtwkBX3fbVRt/X+3tVrTrKdd3Us3HbjgK2ANFu2/ND3psf8kVYbmBhHKv+qK/cnw2lYpTnVZWKUd32lQoDXTXaZ6rdtpX1s6qsn1X1dXiv+qN+bsCJHJtOp9yN7vErPqAt2424TKjN3t5izFeNoAJ3rwG6JbnVLATx1s1AA+J31b75anFfv8O27ffkf3l5AeDLh28q+dqwWEhbPi/eF/1568G0/0l+/PleWsqF3bFS7izaEtTiWa55cd6X/46+PcbqVPjx53tpw2PH2JcP39S61xaT/+e3pG378eef0sJrRYAqDNgCnNWpFDVdMaH8G/YvdlmD+dJAnuIAAAAASUVORK5CYII=",
        "kolomna": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACcAAAAwCAYAAACScGMWAAADwElEQVR42u2YL3TiShSHv6QVgwvmHSLzXGRxxew71NHzDLiNpA5ccYtMHXWNa2TqqHu4crqGddQRiZycZxLHOJ4AWtiW7mMIPSt6Tf7OzZffzL0zd4w51px1E4ACbjO4sF6uVzbJADDCzWbv2bxpoGPmM5BY3lmBtC0SR7xcr7/zQWZu+2BiC8KaB8CfTnEBqT4abqWWgrNqlY7vg4DUPwdgMB7jntYXKr5ht47BrWPwTRiknZfuWz/XtePnLgPcExeAq2YTMasgTiDoBYhyg9Jd+Ga3Xkzn1OIFSL8Ptdjg5ARakZuDckvVElvgRSEAUggukz7TeIwoN1DT8eZ4/MkcB+q1xfnqqAhzUG4ZjaWpIup1QYEo2pxLG0c9odSYf4Luu04s6xuOWyXLMsbjMZmCe3maj3LXtQpXrSZpmmKPBvRETLfvU0tTXBsSR3DfD2k3G2868X2fYrFAvV4H4KbnU1PB3nCGdEpzgF5zoY5dspGJRKUSxy0jE4k9GnBiDSnfgTVRr/Jciy43PZ9ut4vv+3iex50d7Z3njDnW/LpWQYgxo0qRyiil23EAqN1AVvRwbejV2/yoljgdJq/g5r3lOFMKIURucMdez2ZoScAmLsfEPQsxUXSuwVOSyB1wGYwYTgTV7P1EJ6XEcZzc8txx0JkiH0CG0Boqqt2E+DzBqiwnhu4iUqcVBXfvTxErsCiKyNoBA9HaLyAsBO4QCkOLoCNoVBYAsRQ8qRFekJA4gkZ7O5jnea/u7Qv2koSvBKcoKIvnidRajDrAWia4D55YgePVKuN3NJPf2D7hPuE+4faF26W40XlfG073QzrtdoIrhLP91mc7Apq7OFY5TGG7AJqH7Mp9/ZkfDbaL33fhOvc3B00VT9LVgwviFtdp66Bw5cFkd7gn6dIe6aumlMqle435hI2njcFo55rzq3y9El4vcHR3osyfx1gexXBeAfKsXBC3tLtyVRpuOO7oQa4raO47xrbtJmkX0msKmokq/TJqtplAYaXbn7eyi70ADS7n2ll2pc593MdxbKZTiWVZFIsFwiDk5jLUTuICpQdXEgnSsxc1q/+VKHodmcPhkKp99hxoOjlTC26l2DawDVtuLNqRJFGlw67ndAf6SumDwemC6bY3PwpMx8/xvg7bFxdYpRJZkpDOZhQLhZccOJsRdd/293+i2Hh4eJifDaoHV0xnTWceHR0ZD7XhTtk/L9v243X7B49/fzeMx8fHvT/y5Y+/NiT4/u9jLn+VS1G9DpMXWK4Vf55QB9mOyBvwPyVOlHWARYQcAAAAAElFTkSuQmCC",
    }
    city_coat = CITY_COAT_OF_ARMS.get(slug, "")

    css = _city_page_css()
    nav = _city_nav_html(active_slug=slug)
    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    pop_str    = f"{pop:,}".replace(",", "\u2009")  # тонкий пробел
    km_str     = f"{km_src} км" if km_src else "нет данных"

    # ── A. HERO HEADER ────────────────────────────────────────────────────────
    is_main_badge = '<span class="badge badge-red">Главная точка мониторинга</span>' if is_main else ""
    river_badge   = f'<span class="badge badge-blue">{_h(river)}</span>'
    km_badge      = f'<span class="badge badge-blue">{_h(km_str)} от истока</span>' if km_src else ""

    hero_html = f"""
<div style="padding: 32px 0 20px;">
  <div style="font-size:0.8rem; color:var(--text-dim); margin-bottom:8px;">
    <a href="index.html">← Все города</a>
  </div>
  <h1 style="font-size:2.5rem; font-weight:800; letter-spacing:-0.04em; margin-bottom:10px;">{f'<img src="{city_coat}" style="height:36px; vertical-align:middle; margin-right:8px;" alt="Герб">' if city_coat else ''}{_h(name)}</h1>
  <div style="margin-bottom:14px; display:flex; flex-wrap:wrap; gap:6px;">
    {river_badge}
    {km_badge}
    {is_main_badge}
  </div>
  <div class="info-grid">
    <div class="info-item">
      <div class="info-label">Год основания</div>
      <div class="info-value">{founded} г.</div>
    </div>
    <div class="info-item">
      <div class="info-label">Население</div>
      <div class="info-value">{pop_str} чел.</div>
    </div>
    <div class="info-item">
      <div class="info-label">Берег</div>
      <div class="info-value">{_h(bank)}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Расстояние от истока</div>
      <div class="info-value">{_h(km_str)}</div>
    </div>
  </div>
</div>"""

    # ── B. О ГОРОДЕ ───────────────────────────────────────────────────────────
    desc_html = ""
    if isinstance(desc_paras, tuple):
        for para in desc_paras:
            desc_html += f"<p>{_h(para)}</p>\n"
    else:
        desc_html = f"<p>{_h(str(desc_paras))}</p>\n"

    about_html = f"""
<div class="section-card">
  <h2>О городе</h2>
  {desc_html}
</div>"""

    # ── C. ГИДРОЛОГИЧЕСКИЙ ПОСТ ───────────────────────────────────────────────
    if hydro_post:
        post_name   = hydro_post.get("name", "")
        zero_m_bs   = hydro_post.get("zero_m_bs")
        operator    = hydro_post.get("operator", "")
        crit_levels = hydro_post.get("critical_levels", [])

        crit_rows = ""
        for lvl_cm, lvl_desc in crit_levels:
            crit_rows += f"""
<tr>
  <td class="critical-level">{lvl_cm} см</td>
  <td>{_h(lvl_desc)}</td>
</tr>"""

        crit_table = ""
        if crit_rows:
            crit_table = f"""
<h3>Критические уровни</h3>
<div class="table-wrap">
<table class="flood-table">
  <thead><tr><th>Уровень</th><th>Значение</th></tr></thead>
  <tbody>{crit_rows}</tbody>
</table>
</div>"""

        zero_str = f"{zero_m_bs:.2f} м БС" if zero_m_bs is not None else "—"
        hydro_html = f"""
<div class="section-card">
  <h2>Гидрологический пост</h2>
  <div class="info-grid">
    <div class="info-item">
      <div class="info-label">Наименование</div>
      <div class="info-value">{_h(post_name)}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Отметка нуля поста</div>
      <div class="info-value">{zero_str}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Оператор</div>
      <div class="info-value" style="font-size:0.82rem;">{_h(operator)}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Данные на allrivers.info</div>
      <div class="info-value"><a href="https://allrivers.info" target="_blank" rel="noopener">allrivers.info</a></div>
    </div>
  </div>
  {crit_table}
</div>"""
    else:
        hydro_html = f"""
<div class="section-card">
  <h2>Гидрологический пост</h2>
  <div class="fact-card">
    Официального гидропоста непосредственно в {_h(name)} нет.<br>
    Ближайший пост: <strong>{_h(near_post)}</strong>
  </div>
  <p>Мониторинг ведётся региональными службами МЧС с опорой на соседние посты.</p>
</div>"""

    # ── D. GloFAS ПРОГНОЗ ─────────────────────────────────────────────────────
    if glofas_slug and glofas_data:
        # Ищем данные по slug в glofas_data
        g_station = None
        if isinstance(glofas_data, dict):
            for k, v in glofas_data.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, dict):
                    v_slug = (v.get("slug") or v.get("name") or k).lower()
                    if glofas_slug.lower() in v_slug or v_slug in glofas_slug.lower():
                        g_station = v
                        break

        if g_station:
            discharge = g_station.get("discharge")
            peak_date = g_station.get("peak_date") or g_station.get("peak")
            flood_ratio = g_station.get("flood_ratio") or g_station.get("ratio")
            stat_label = g_station.get("status_label") or g_station.get("label", "")

            dis_str   = f"{discharge:.0f} м³/с" if discharge is not None else "нет данных"
            ratio_str = f"{flood_ratio:.2f}" if flood_ratio is not None else "—"
            peak_str  = str(peak_date) if peak_date else "—"

            glofas_html = f"""
<div class="section-card">
  <h2>GloFAS прогноз</h2>
  <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:12px;">
    <b>GloFAS</b> (Global Flood Awareness System) — Европейская система прогнозирования наводнений Copernicus.
  </p>
  <div class="info-grid">
    <div class="info-item">
      <div class="info-label">Текущий расход воды</div>
      <div class="info-value">{dis_str}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Дата пика</div>
      <div class="info-value">{_h(peak_str)}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Паводковый коэф.</div>
      <div class="info-value">{ratio_str}</div>
    </div>
    <div class="info-item">
      <div class="info-label">Статус</div>
      <div class="info-value">{_h(stat_label)}</div>
    </div>
  </div>
  <div style="font-size:0.78rem; color:var(--text-dim); margin-top:8px;">
    Данные: <a href="https://global-flood.emergency.copernicus.eu/" target="_blank" rel="noopener">GloFAS Flood API (Copernicus)</a>
  </div>
</div>"""
        else:
            glofas_html = f"""
<div class="section-card">
  <h2>GloFAS прогноз</h2>
  <p style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:8px;">
    <b>GloFAS</b> (Global Flood Awareness System) — Европейская система прогнозирования наводнений Copernicus.
  </p>
  <div class="fact-card">
    Станция GloFAS «{_h(glofas_slug)}» — данные временно недоступны или обновляются.
  </div>
  <div style="font-size:0.78rem; color:var(--text-dim); margin-top:8px;">
    <a href="https://global-flood.emergency.copernicus.eu/" target="_blank" rel="noopener">GloFAS Flood API (Copernicus)</a>
  </div>
</div>"""
    else:
        # Нет GloFAS станции для этого города
        serp_link = '<a href="serpuhov.html">пост Серпухов / Лукьяново</a>'
        glofas_html = f"""
<div class="section-card">
  <h2>GloFAS прогноз</h2>
  <p>Для {_h(name)} отдельной станции GloFAS (Европейская система прогнозирования наводнений Copernicus) нет.
  Ближайшая точка наблюдения — {serp_link}.</p>
  <p style="font-size:0.82rem; color:var(--text-dim);">Данные по Оке в целом доступны на
  <a href="https://global-flood.emergency.copernicus.eu/" target="_blank" rel="noopener">GloFAS (Copernicus)</a>.</p>
</div>"""

    # ── E. ПАВОДКОВАЯ ИСТОРИЯ ─────────────────────────────────────────────────
    if floods:
        flood_rows = ""
        for flood_item in floods:
            if not isinstance(flood_item, (list, tuple)) or len(flood_item) < 3:
                continue
            year, level, note = flood_item[0], flood_item[1], flood_item[2]
            year_str = str(year) if year else "—"
            flood_rows += f"""
<tr>
  <td style="font-weight:600; color:var(--warning);">{_h(year_str)}</td>
  <td>{_h(str(level))}</td>
  <td>{_h(str(note))}</td>
</tr>"""
        floods_html = f"""
<div class="section-card">
  <h2>Паводковая история</h2>
  <div class="table-wrap">
  <table class="flood-table">
    <thead><tr><th>Год</th><th>Уровень</th><th>Последствия</th></tr></thead>
    <tbody>{flood_rows}</tbody>
  </table>
  </div>
</div>"""
    else:
        floods_html = ""

    # ── F. ЗОНЫ РИСКА ─────────────────────────────────────────────────────────
    if flood_risk:
        risk_html = f"""
<div class="section-card">
  <h2>Зоны риска</h2>
  <div class="warn-card">⚠️ {_h(flood_risk)}</div>
  <p style="font-size:0.85rem; color:var(--text-dim); margin-top:8px;">
    При значительном паводке указанные территории могут оказаться под водой.
    Следите за данными гидропоста и предупреждениями МЧС.
  </p>
</div>"""
    else:
        risk_html = ""

    # ── G. РАССТОЯНИЕ ДО СЕРПУХОВА ────────────────────────────────────────────
    if is_main:
        dist_html = ""
    elif serp_km is not None:
        if serp_km == 0:
            dist_html = ""
        else:
            wave_str = ""
            if serp_days:
                d_min, d_max = serp_days
                if d_min == d_max:
                    wave_str = f"~{d_min} сут."
                elif d_min < 1:
                    h_min = int(d_min * 24)
                    h_max = int(d_max * 24)
                    wave_str = f"{h_min}–{h_max} ч."
                else:
                    wave_str = f"{d_min}–{d_max} сут."
            dist_html = f"""
<div class="section-card">
  <h2>Расстояние до Серпухова</h2>
  <div class="info-grid">
    <div class="info-item">
      <div class="info-label">По реке</div>
      <div class="info-value">{serp_km} км</div>
    </div>
    <div class="info-item">
      <div class="info-label">Время прохода волны</div>
      <div class="info-value">{_h(wave_str) if wave_str else "нет данных"}</div>
    </div>
  </div>
  <p style="font-size:0.82rem; color:var(--text-dim); margin-top:6px;">
    Паводковая волна от {_h(name)} до поста Лукьяново (Серпухов) идёт {_h(wave_str) if wave_str else "несколько суток"}.
    <a href="serpuhov.html">Данные поста Серпухов →</a>
  </p>
</div>"""
    else:
        dist_html = ""

    # ── Навигация между городами ────────────────────────────────────────────────
    city_slugs = [c["slug"] for c in OKA_CITIES]
    city_names = {c["slug"]: c["name"] for c in OKA_CITIES}
    idx = city_slugs.index(slug) if slug in city_slugs else -1
    prev_link = ""
    next_link = ""
    if idx > 0:
        ps = city_slugs[idx - 1]
        prev_link = f'<a href="{_h(ps)}.html">← {_h(city_names[ps])}</a>'
    if idx >= 0 and idx < len(city_slugs) - 1:
        ns = city_slugs[idx + 1]
        next_link = f'<a href="{_h(ns)}.html">{_h(city_names[ns])} →</a>'

    city_nav_bottom = f"""
<div style="display:flex; justify-content:space-between; align-items:center;
            padding:16px 0; font-size:0.88rem; color:var(--text-secondary);">
  <div>{prev_link}</div>
  <div><a href="index.html">Все города</a></div>
  <div>{next_link}</div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{_h(name)} на реке Ока — гидрологический пост, паводки, зоны риска. OkaFloodMonitor.">
  <title>{_h(name)} — города на Оке — OkaFloodMonitor</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    {css}
  </style>
</head>
<body>
{nav}

<div class="container">
  {hero_html}
  {about_html}
  {hydro_html}
  {glofas_html}
  {floods_html}
  {risk_html}
  {dist_html}
  {city_nav_bottom}
</div>

<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | {_h(name)}, {_h(river)}<br>
  <a href="../index.html">На главную</a> |
  <a href="index.html">Все города</a> |
  Обновлено: {_h(now_msk)} МСК
</footer>


<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    out_path = os.path.join(cities_dir, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] cities/{slug}.html сохранён ({len(html)} символов)")


def generate_city_pages(data: dict) -> None:
    """
    Генерирует все страницы городов:
    - docs/cities/index.html
    - docs/cities/{slug}.html для каждого города из OKA_CITIES
    """
    glofas_data = (data or {}).get("glofas", {})
    cities_dir = os.path.join(DOCS_DIR, "cities")
    os.makedirs(cities_dir, exist_ok=True)

    generate_city_index_page()
    for city in OKA_CITIES:
        try:
            generate_city_page(city, glofas_data)
        except Exception as exc:
            print(f"[HTML] Ошибка генерации cities/{city.get('slug')}.html: {exc}")
    print(f"[HTML] Сгенерировано {len(OKA_CITIES)} страниц городов + index")


def generate_flood_guide_page() -> None:
    """Генерирует docs/flood-guide.html — образовательный ликбез по физике паводка."""
    from datetime import datetime, timezone, timedelta
    now_msk = datetime.now(timezone.utc) + timedelta(hours=3)
    ts = now_msk.strftime("%d.%m.%Y %H:%M МСК")

    css = _generate_links_css()

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Физика половодья на Оке — OkaFloodMonitor</title>
  <meta name="description" content="Физика весеннего половодья на Оке: волна, скорость, факторы, гидрологические посты, НЯ и ОЯ, плотины, практические советы."/>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <style>
    {css}

    .guide-section {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 28px 32px;
      margin-bottom: 28px;
      backdrop-filter: blur(10px);
    }}
    .guide-section h2 {{
      font-size: 1.45rem;
      font-weight: 700;
      color: var(--accent);
      margin-top: 0;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 10px;
    }}
    .guide-section h3 {{
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-top: 22px;
      margin-bottom: 10px;
    }}
    .guide-section p {{
      color: var(--text-secondary);
      line-height: 1.8;
      margin-bottom: 14px;
    }}
    .guide-section ul, .guide-section ol {{
      color: var(--text-secondary);
      line-height: 1.8;
      padding-left: 20px;
      margin-bottom: 14px;
    }}
    .guide-section li {{
      margin-bottom: 6px;
    }}
    .guide-blockquote {{
      border-left: 4px solid var(--accent);
      background: rgba(56,189,248,0.07);
      border-radius: 0 10px 10px 0;
      padding: 14px 20px;
      margin: 18px 0;
      color: var(--text-secondary);
      font-style: italic;
      line-height: 1.7;
    }}
    .guide-formula {{
      font-family: 'Courier New', Courier, monospace;
      background: #f1f5fb;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px 20px;
      margin: 16px 0;
      color: #1e40af;
      font-size: 1rem;
      display: block;
    }}
    .guide-summary-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0;
      font-size: 0.9rem;
    }}
    .guide-summary-table th {{
      background: rgba(56,189,248,0.15);
      color: var(--accent);
      padding: 10px 14px;
      text-align: left;
      border-bottom: 2px solid var(--card-border);
    }}
    .guide-summary-table td {{
      padding: 9px 14px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      color: var(--text-secondary);
      vertical-align: top;
    }}
    .guide-summary-table tr:hover td {{
      background: rgba(56,189,248,0.04);
    }}
    .guide-toc {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 22px 28px;
      margin-bottom: 32px;
    }}
    .guide-toc h2 {{
      font-size: 1.05rem;
      color: var(--accent);
      margin-top: 0;
      margin-bottom: 14px;
    }}
    .guide-toc ol {{
      padding-left: 20px;
      margin: 0;
    }}
    .guide-toc li {{
      margin-bottom: 7px;
    }}
    .guide-toc a {{
      color: var(--text-secondary);
      text-decoration: none;
      transition: color 0.2s;
    }}
    .guide-toc a:hover {{
      color: var(--accent);
    }}
    .guide-highlight {{
      display: inline-block;
      background: rgba(56,189,248,0.12);
      border-radius: 6px;
      padding: 2px 8px;
      color: var(--accent);
      font-weight: 600;
    }}
    .guide-warn {{
      background: rgba(239,68,68,0.08);
      border: 1px solid rgba(239,68,68,0.3);
      border-radius: 10px;
      padding: 14px 18px;
      color: #fca5a5;
      margin: 16px 0;
      line-height: 1.7;
    }}
    .guide-tip {{
      background: rgba(34,197,94,0.07);
      border: 1px solid rgba(34,197,94,0.25);
      border-radius: 10px;
      padding: 14px 18px;
      color: #86efac;
      margin: 16px 0;
      line-height: 1.7;
    }}
    .guide-checklist {{
      list-style: none;
      padding: 0;
    }}
    .guide-checklist li {{
      padding: 7px 0 7px 28px;
      position: relative;
      border-bottom: 1px solid rgba(255,255,255,0.04);
    }}
    .guide-checklist li::before {{
      content: "✓";
      position: absolute;
      left: 4px;
      color: #4ade80;
      font-weight: 700;
    }}
    .section-number {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      background: var(--accent);
      color: #0f172a;
      border-radius: 50%;
      font-weight: 700;
      font-size: 0.9rem;
      margin-right: 10px;
      flex-shrink: 0;
      vertical-align: middle;
    }}
    .back-link-block {{
      text-align: center;
      margin: 40px 0 20px;
    }}
    .back-link-block a {{
      display: inline-block;
      background: var(--accent);
      color: #0f172a;
      padding: 12px 28px;
      border-radius: 10px;
      text-decoration: none;
      font-weight: 700;
      font-size: 1rem;
      margin: 6px 8px;
      transition: opacity 0.2s;
    }}
    .back-link-block a:hover {{ opacity: 0.85; }}
    .back-link-block a.secondary {{
      background: transparent;
      border: 1px solid var(--accent);
      color: var(--accent);
    }}
  </style>
</head>
<body>
  {_build_nav('guide')}

  <main class="container" style="max-width:860px; margin:0 auto; padding:24px 16px;">

    <div style="margin-bottom:28px;">
      <h1 style="font-size:2rem; font-weight:800; color:var(--text-primary); margin-bottom:8px;">
        <svg width="28" height="20" viewBox="0 0 28 20" fill="none" style="vertical-align:middle;margin-right:6px;"><path d="M2 10c2-4 5-7 8-7s6 4 8 4 5-7 8-7" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round"/><path d="M2 17c2-4 5-7 8-7s6 4 8 4 5-7 8-7" stroke="#93c5fd" stroke-width="1.5" stroke-linecap="round"/></svg>
        Физика весеннего половодья на Оке
      </h1>
      <p style="color:var(--text-secondary); font-size:1.05rem; line-height:1.7; margin:0;">
        От Орла до Коломны — всё, что домовладелец и дачник должны знать о паводковой волне,
        прежде чем вода постучит в подвал.
      </p>
    </div>

    <!-- TOC -->
    <div class="guide-toc">
      <h2>📋 Содержание</h2>
      <ol>
        <li><a href="#s1">Что такое весеннее половодье и как рождается паводковая волна</a></li>
        <li><a href="#s2">Скорость волны: почему паводок — это не цунами</a></li>
        <li><a href="#s3">Ока от Орла до Коломны: сколько дней у вас есть</a></li>
        <li><a href="#s4">Почему за одну весну бывает несколько волн</a></li>
        <li><a href="#s5">Пять факторов, которые решают, насколько высоко поднимется вода</a></li>
        <li><a href="#s6">Гидрологический пост: маленькая будка, которая знает всё</a></li>
        <li><a href="#s7">НЯ и ОЯ: когда пора паковать вещи</a></li>
        <li><a href="#s8">Кузьминский и Белоомутский гидроузлы: плотины, которые не спасают</a></li>
        <li><a href="#s9">Что делать обычному человеку: подготовка, эвакуация, страхование</a></li>
      </ol>
    </div>

    <!-- SECTION 1 -->
    <div class="guide-section" id="s1">
      <h2><span class="section-number">1</span>Что такое весеннее половодье и как рождается паводковая волна</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('oka_floodplain_aerial', '')}" alt="Аэрофотоснимок поймы реки Оки" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Россия — страна снега. Каждую зиму на бассейн Оки (<span class="guide-highlight">245 000 км²</span> —
        это примерно площадь Румынии) ложится снежный покров. К марту в этом снеге хранится от 60 до 200 мм воды
        в пересчёте на слой, в зависимости от года. Когда температура воздуха переходит отметку
        <span class="guide-highlight">+4…+6 °С</span>, снег начинает таять, и вода устремляется в реку.
      </p>
      <p>
        <strong>Половодье</strong> — это ежегодный, закономерный, почти как расписание автобуса, подъём воды,
        вызванный таянием снега. В отличие от паводка, половодье повторяется каждый год в один и тот же сезон.
        Паводок — его озорной брат: нерегулярное, более быстрое поднятие воды от дождей или резкой оттепели.
      </p>
      <h3>Как рождается волна</h3>
      <p>
        Представьте, что снег начал таять в верховьях Оки — в Орловской области. Талая вода просачивается
        сквозь почву, заполняет лога и балки, а потом небольшими ручейками стекает в притоки: Орлик, Зушу, Упу.
        Те несут её в Оку.
      </p>
      <p>
        Но снег тает не равномерно — а фронтом, двигающимся с юга на север. Пока в Орле уже вовсю ледоход,
        в Серпухове ещё лежит снег. Это создаёт растянутую во времени «зарядку» реки водой — и формирует
        <strong>паводочную волну</strong>: гребень повышенного уровня воды, который движется вниз по течению,
        как рябь от брошенного в лужу камня, только очень медленно и очень мощно.
      </p>
      <div class="guide-blockquote">
        Питание Оки на 59% обеспечивается талыми водами, на 20% — дождями и лишь на 21% — подземными
        источниками. Весной подземные воды практически не играют роли: всё решает снег. В среднегодовом
        выражении Ока пропускает через себя 1200–1258 м³/с воды. В половодье этот показатель вырастает кратно.
      </div>
    </div>

    <!-- SECTION 2 -->
    <div class="guide-section" id="s2">
      <h2><span class="section-number">2</span>Скорость волны: почему паводок — это не цунами</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('wave_speed_flood', '')}" alt="Скорость паводковой волны" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('physics_wave_russian', '')}" alt="Физика паводковой волны (русская версия)" style="width:100%; max-width:700px; border-radius:12px; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
    <div style="font-size:0.78rem; color:var(--text-dim); margin-top:4px; font-style:italic;">Схема распространения паводковой волны</div>
  </div>
      <p>
        Первый вопрос, который задаёт любой здравомыслящий дачник: «Как быстро она придёт?»
      </p>
      <h3>Два вида скоростей</h3>
      <p>Нужно различать две принципиально разные вещи:</p>
      <ul>
        <li><strong>Скорость воды</strong> (velocity) — с какой скоростью течёт сама вода в реке.
          Для Оки в межень — около 1,3 м/с (~4,7 км/ч). В половодье — до 4 м/с (~14 км/ч).</li>
        <li><strong>Скорость волны</strong> (celerity) — с какой скоростью движется <em>гребень волны</em>
          — зона максимального подъёма уровня. Это совсем другое число.</li>
      </ul>
      <p>
        Паводочная волна на равнинной реке — это <strong>кинематическая волна</strong>. Она движется медленнее,
        чем вода, и не «прибывает» с одного конца до другого в виде резкого вала воды. Представьте не волну
        прибоя, а медленно надувающийся шарик — уровень воды постепенно поднимается на несколько сантиметров
        в час.
      </p>
      <h3>Формула Манинга и закон «5/3»</h3>
      <p>Скорость паводочной волны описывается через скорость воды. По формуле Манинга для кинематических волн:</p>
      <code class="guide-formula">c = (5/3) × V</code>
      <p>
        где <code>V</code> — средняя скорость потока, а <code>c</code> — скорость волны. Коэффициент
        5/3 ≈ 1,67 означает, что волна бежит <em>быстрее</em> воды примерно в 1,7 раза.
      </p>
      <h3>Факторы, влияющие на скорость волны</h3>
      <div class="table-wrap">
      <table class="guide-summary-table">
        <thead>
          <tr><th>Фактор</th><th>Влияние на скорость волны</th></tr>
        </thead>
        <tbody>
          <tr><td><strong>Уклон реки</strong></td><td>Больше уклон → быстрее волна</td></tr>
          <tr><td><strong>Ширина русла</strong></td><td>Более широкое русло → медленнее волна (больше объём заполнения)</td></tr>
          <tr><td><strong>Расход воды</strong></td><td>Больше воды → быстрее волна (глубже поток)</td></tr>
          <tr><td><strong>Тип поймы</strong></td><td>Широкая пойма «растягивает» волну, уменьшает её скорость и высоту</td></tr>
          <tr><td><strong>Притоки</strong></td><td>Добавляют воду → волна растёт вниз по течению</td></tr>
        </tbody>
      </table>
      </div>
      <p>
        На горных реках паводок может нестись со скоростью до 45 км/ч. На равнинных — значительно скромнее:
        <span class="guide-highlight">2–5 км/ч</span>, или <span class="guide-highlight">40–120 км/сутки</span>
        в типичном диапазоне.
      </p>
      <h3>Почему волна замедляется на пойме</h3>
      <p>
        Когда уровень воды перекрывает берега и вода выходит на пойму, она встречает огромное пространство для
        «растекания». Фактически вода заполняет не только русло шириной 200 метров, но и пойму шириной до
        6–15 км. Объём воды, нужный для подъёма уровня на 1 см, возрастает в десятки раз. Волна «расплющивается»
        во времени: гребень становится ниже, но шире — как блин вместо кекса.
      </p>
    </div>

    <!-- SECTION 3 -->
    <div class="guide-section" id="s3">
      <h2><span class="section-number">3</span>Ока от Орла до Коломны: сколько дней у вас есть</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('oka_river_spring', '')}" alt="Река Ока весной — от Орла до Коломны" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Расстояние от Орла до Серпухова по руслу Оки — около 550 км. До Коломны — примерно 700 км.
        Это не трасса М2, а извилистая равнинная река с широкой поймой.
      </p>
      <h3>Типичный временно́й диапазон</h3>
      <div class="table-wrap">
      <table class="guide-summary-table">
        <thead>
          <tr><th>Участок</th><th>Расстояние (по руслу)</th><th>Время добегания волны</th><th>Скорость волны</th></tr>
        </thead>
        <tbody>
          <tr><td>Орёл → Белёв</td><td>~180 км</td><td>2–4 суток</td><td>45–90 км/сут</td></tr>
          <tr><td>Белёв → Калуга</td><td>~130 км</td><td>2–3 суток</td><td>43–65 км/сут</td></tr>
          <tr><td>Калуга → Серпухов</td><td>~240 км</td><td>4–7 суток</td><td>34–60 км/сут</td></tr>
          <tr><td>Серпухов → Коломна</td><td>~110 км</td><td>2–4 суток</td><td>27–55 км/сут</td></tr>
          <tr>
            <td><strong>Орёл → Серпухов</strong></td>
            <td><strong>~550 км</strong></td>
            <td><strong>7–14 суток</strong></td>
            <td><strong>~40–80 км/сут</strong></td>
          </tr>
          <tr>
            <td><strong>Орёл → Коломна</strong></td>
            <td><strong>~700 км</strong></td>
            <td><strong>9–18 суток</strong></td>
            <td><strong>~40–80 км/сут</strong></td>
          </tr>
        </tbody>
      </table>
      </div>
      <div class="guide-blockquote">
        Если в Орле уровень воды резко пошёл вверх, у жителей Серпухова и Жерновки есть, грубо говоря,
        <em>от одной до двух недель</em> до прихода волны. Точнее скажут только гидрологи, которые знают
        актуальный профиль снежного покрова и температурный прогноз.
      </div>
      <h3>Пример реального сезона</h3>
      <p>
        Вскрытие верхней Оки (Орловская область) происходит примерно <strong>на неделю раньше</strong>, чем
        Средней и Нижней. Половодье в верховьях протекает более бурно и заканчивается быстрее. Пик в Калуге
        обычно наступает в конце марта — начале апреля, в Серпухове — в первой половине апреля, в Коломне —
        в апреле.
      </p>
      <p>
        В паводок 2023 года Ока у Рязани 31 марта показала подъём 22 см за сутки, достигнув отметки 5 м 22 см —
        это выше пика 2022 года (5 м 10 см, 23 апреля). В марте 2026 года в Луховицком районе уровень Оки
        поднялся на <strong>1,5 метра всего за двое суток</strong> — исключительно быстрый подъём, вызванный
        интенсивным таянием при антициклоне с дневными температурами выше +10 °С.
      </p>
      <div class="guide-warn">
        ⚠️ Волна не идёт с постоянной скоростью. На сужениях русла она ускоряется, на широкой пойме —
        замедляется. Поэтому любые расчёты — это диапазон, а не точное расписание.
      </div>
    </div>

    <!-- SECTION 4 -->
    <div class="guide-section" id="s4">
      <h2><span class="section-number">4</span>Почему за одну весну бывает несколько волн</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('multiple_waves_flood', '')}" alt="Несколько паводковых волн за одну весну" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Опытный дачник замечал: вода поднялась, потом чуть упала — и снова пошла вверх. Это не дежавю. Это физика.
      </p>
      <h3>Причина 1: Разновременное таяние в бассейне</h3>
      <p>
        Бассейн Оки огромен — 245 000 км². Снег в Орловской области тает на 1–2 недели раньше, чем в
        Московской. Пока первая волна от орловских снегов идёт вниз по реке, в верховьях притоков ещё
        лежит снег. Потом тает он — и формируется <strong>вторая волна</strong>.
      </p>
      <h3>Причина 2: Дожди на Москва-реке и других притоках</h3>
      <p>
        Москва-река — крупнейший приток Оки, впадающий у Коломны. У неё свой собственный паводочный цикл.
        Если вдобавок к снеготаянию в бассейне верхней Оки ещё и прольются дожди над бассейном
        Москвы-реки, у Коломны произойдёт «сложение» двух волн — и уровень скакнёт непредсказуемо.
      </p>
      <h3>Причина 3: Задержанное таяние в верховьях</h3>
      <p>
        В отдельные годы снег в верховьях лежит дольше из-за затяжных заморозков. Первая волна
        формируется за счёт нижних и средних участков бассейна. Потом ударяет тепло — и верховья «отдают»
        свои запасы разом. Получается вторая, порой более мощная волна.
      </p>
      <h3>Причина 4: Сбросы с плотин</h3>
      <p>
        Москворецко-Окская шлюзованная система включает несколько гидроузлов на нижней Москве-реке
        (Перервинский, Трудкоммуна, Андреевка, Фаустово). Регулируемые сбросы воды через их затворы
        могут искусственно приподнимать уровень Оки у Коломны — создавая дополнительный «горб» на гидрографе
        (графике уровня воды).
      </p>
      <h3>Причина 5: Ледовые заторы</h3>
      <p>
        Ледоход на реке — зрелище живописное, но опасное. Если льдины накапливаются на перекате или у
        моста, они образуют временную «плотину». Уровень воды выше затора резко вырастает. Потом затор
        прорывает — и вниз идёт <strong>«волна прорыва»</strong>, крутая и злая.
      </p>
    </div>

    <!-- SECTION 5 -->
    <div class="guide-section" id="s5">
      <h2><span class="section-number">5</span>Пять факторов, которые решают, насколько высоко поднимется вода</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('five_factors_flood', '')}" alt="Пять факторов, определяющих высоту паводка" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Метеорологи и гидрологи каждую осень оценивают «паводковый потенциал» следующей весны.
        Вот пять главных переменных.
      </p>

      <h3>1. Запасы воды в снеге (СЗВ)</h3>
      <p>
        Самый важный фактор. Измеряется в миллиметрах водного эквивалента. Снегомерные маршруты прокладываются
        ежемесячно, результаты агрегируются Росгидрометом. Если к 1 марта СЗВ на бассейне Оки составляет
        150 мм (против нормы 100 мм), паводок обещает быть выше среднего. Если 60 мм — весна будет тихой.
      </p>

      <h3>2. Глубина промерзания грунта</h3>
      <p>
        Это коварный фактор. Промёрзший грунт — как асфальт: талая вода не просачивается в него, а стекает
        вся по поверхности прямо в реку. Весенний сток возрастает, паводок — выше.
      </p>
      <div class="guide-blockquote">
        Самая опасная комбинация: <strong>много снега + промёрзший грунт</strong> (бывает, если снег лёг
        поздно, уже после промерзания). В 1970 году именно так и случилось.
      </div>

      <h3>3. Скорость таяния</h3>
      <p>
        Если снег тает постепенно в течение 3–4 недель, грунт успевает поглощать воду, а реки — пропускать
        расход без катастрофических пиков. Если же тепло приходит резко (+15–20 °С вместо обычных +5–8 °С)
        — снег стаивает за несколько дней, и весь запас воды одновременно обрушивается в реку.
      </p>
      <p>
        Рекордный паводок в Калуге 1908 года (уровень <span class="guide-highlight">+16 м 77 см</span>!) и
        паводок 1970 года (+15 м 60 см) были вызваны именно аномально быстрым потеплением после очень
        снежной зимы.
      </p>

      <h3>4. Дожди в период таяния</h3>
      <p>
        «Снег ещё не сошёл, а дождь уже льёт» — бич апрельских паводков. Дождевая вода не просачивается
        в ещё не оттаявший грунт и напрямую стекает в реку, усиливая волну. Дожди в конце марта — начале
        апреля могут добавить 0,5–2 м к уровню воды сверх снегового паводка.
      </p>

      <h3>5. Направление и сила ветра</h3>
      <p>
        Кажется мелочью — но нет. При сильном южном ветре (т.н. нагон) вода буквально «наваливается» на
        низменный берег. В районе Коломны и ниже зафиксированы нагонные явления, когда ветер поднимает
        уровень воды на дополнительные 30–60 см. Это редко, но жители в пойме помнят.
      </p>
    </div>

    <!-- SECTION 6 -->
    <div class="guide-section" id="s6">
      <h2><span class="section-number">6</span>Гидрологический пост: маленькая будка, которая знает всё</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('nya_oya_gauge', '')}" alt="Гидрологический пост на реке Оке" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
  <div style="margin:12px 0 16px; text-align:center;">
    <img src="data:image/jpeg;base64,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" alt="Гидрологический пост" style="width:100%; max-width:600px; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,0.15);">
    <div style="font-size:0.78rem; color:var(--text-dim); margin-top:4px; font-style:italic;">Типичный гидрологический пост на реке</div>
  </div>
      <p>
        На реке Оке расположено <span class="guide-highlight">15 гидрологических постов</span> — от Орла
        до нижнего течения. Ключевые из них: Орёл (111 км от истока), Белёв, Калуга, Алексин/Щукино,
        Серпухов, Кашира, Коломна (645 км от истока).
      </p>

      <h3>Что измеряет гидропост</h3>
      <p>
        Гидрологический пост — это не просто столбик с делениями. Современный автоматизированный
        гидрологический комплекс (АГК) включает:
      </p>
      <ul>
        <li><strong>Уровнемер</strong> — непрерывное измерение уровня воды (поплавковый, гидростатический,
          барботажный или радарный). Точность — 1 см.</li>
        <li><strong>Скоростемер / расходомер</strong> — акустический доплеровский профилограф, измеряет
          скорость потока и расход воды в м³/с.</li>
        <li><strong>Термометр воды</strong> — важно для прогноза ледообразования.</li>
        <li><strong>Контроллер и канал связи</strong> — данные уходят в Росгидромет каждые 1–4 часа.</li>
      </ul>

      <h3>Как часто берутся измерения</h3>
      <p>
        В обычное время — дважды в сутки (8:00 и 20:00). <strong>В период половодья — учащённо</strong>:
        каждый час или чаще, если уровень быстро меняется. В критические моменты дежурные гидрологи
        буквально не отходят от приборов. Расходы воды измеряются вручную или акустически: в межень
        — раз в 7–10 дней, в паводковый период — 5–6 измерений на подъёме и 5–8 на спаде.
      </p>

      <h3>Кто ведёт наблюдения</h3>
      <p>
        Основная сеть постов — <strong>ФГБУ «Центральное УГМС»</strong>, подведомственное Росгидромету.
        Данные публикуются на сайте ведомства и агрегируются на allrivers.info и сайтах региональных МЧС.
      </p>

      <h3>Где смотреть данные онлайн</h3>
      <ul>
        <li><strong><a href="https://allrivers.info/river/oka" style="color:var(--accent);">allrivers.info</a></strong>
          — уровни на всех постах, графики за прошлые годы (данные на май 2024, обновление приостановлено)</li>
        <li><strong>ЕСИМО</strong> — Единая государственная система информации, официальный источник</li>
        <li><strong>Сайты региональных ГУ МЧС</strong> — сводки раз в сутки в паводок</li>
        <li><a href="https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-kolomna-segodnya"
             style="color:var(--accent);">СНТ Бугорок</a> — уровни с привязкой к коломенским ориентирам</li>
      </ul>
      <div class="guide-blockquote">
        Нулевая отметка поста в Коломне находится на высоте 100,26 м в Балтийской системе высот. Уровень
        615 см — выход воды на пойму (НЯ). Критический уровень (режим повышенной готовности) — 420 см.
      </div>
    </div>

    <!-- SECTION 7 -->
    <div class="guide-section" id="s7">
      <h2><span class="section-number">7</span>НЯ и ОЯ: когда пора паковать вещи</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('flooded_village', '')}" alt="Затопленный населённый пункт — НЯ и ОЯ" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        В России паводковые уровни делятся на несколько категорий, и это не просто бюрократическая
        классификация — за ними стоят конкретные действия властей и конкретные последствия для жителей.
      </p>

      <h3>Система уровней</h3>
      <div class="table-wrap">
      <table class="guide-summary-table">
        <thead>
          <tr><th>Порог</th><th>Что происходит</th><th>Чьи действия</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Критический уровень (КУ)</strong></td>
            <td>Начинается подтопление жилых домов или хозяйственных объектов в конкретном населённом пункте</td>
            <td>Муниципалитет переходит в режим готовности</td>
          </tr>
          <tr>
            <td><strong>НЯ — Неблагоприятное явление</strong></td>
            <td>Вода вышла на пойму, возможно подтопление дорог, огородов, нижних этажей; трудности, но не катастрофа</td>
            <td>Росгидромет публикует бюллетень, МЧС уведомляет районы</td>
          </tr>
          <tr>
            <td><strong>ОЯ — Опасное явление</strong></td>
            <td>Значительное затопление населённых пунктов, угроза жизни, разрушение коммуникаций</td>
            <td>Режим ЧС, обязательная эвакуация, федеральный уровень реагирования</td>
          </tr>
        </tbody>
      </table>
      </div>
      <p>
        Конкретные пороговые отметки для каждого поста свои — они определены на основании многолетних
        наблюдений. Для Коломны: НЯ — <span class="guide-highlight">615 см</span>, критический —
        <span class="guide-highlight">420 см</span>. Для Серпухова уровень воды в экстремальный паводок
        достигал 12 метров.
      </p>

      <h3>Классификация наводнений по частоте</h3>
      <ul>
        <li><strong>Низкое</strong> (1–2 раза в 5–10 лет): заливает поймы, неудобства.</li>
        <li><strong>Высокое</strong> (1 раз в 20–25 лет): затопление жилья в пойме.</li>
        <li><strong>Выдающееся</strong> (1 раз в 50–100 лет): масштабные разрушения.</li>
        <li><strong>Катастрофическое</strong> (1 раз в 100–200 лет): несколько районов, национальная трагедия.</li>
      </ul>

      <h3>Исторический ориентир</h3>
      <div class="table-wrap">
      <table class="guide-summary-table">
        <thead>
          <tr><th>Год</th><th>Орёл</th><th>Калуга</th><th>Примечания</th></tr>
        </thead>
        <tbody>
          <tr><td><strong>1908</strong></td><td>908 см</td><td>1677 см</td><td>Исторический максимум в Калуге</td></tr>
          <tr><td><strong>1970</strong></td><td>1020 см</td><td>1560 см</td><td>Крупнейший в XX веке; 913 домов в Орле, 1195 эвакуированных</td></tr>
          <tr><td><strong>1979</strong></td><td>~985 см</td><td>—</td><td>«Год отрезанных девятиэтажек»</td></tr>
          <tr><td><strong>1994</strong></td><td>—</td><td>—</td><td>3120 чел. в зоне затопления в Орле</td></tr>
          <tr><td><strong>2003</strong></td><td>866 см</td><td>—</td><td>223 дома в Орле</td></tr>
          <tr><td><strong>2013</strong></td><td>—</td><td>—</td><td>Алексин (пост Щукино): подъём 10,2 м</td></tr>
          <tr><td><strong>2023</strong></td><td>—</td><td>—</td><td>Рязань: 5 м 22 см, выше пика 2022 г.</td></tr>
          <tr><td><strong>2026</strong></td><td>—</td><td>—</td><td>Луховицкий р-н: +1,5 м за двое суток (март)</td></tr>
        </tbody>
      </table>
      </div>
      <div class="guide-blockquote">
        Если кто-то говорит «в прошлый раз вода до нас не дошла» — уточните, какой именно год он имеет
        в виду. 1970-й по сей день стоит маяком, и не зря.
      </div>
    </div>

    <!-- SECTION 8 -->
    <div class="guide-section" id="s8">
      <h2><span class="section-number">8</span>Кузьминский и Белоомутский гидроузлы: плотины, которые не спасают от паводка</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('dam_hydroelectric', '')}" alt="Кузьминский и Белоомутский гидроузлы" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Один из самых распространённых мифов: «У нас на реке плотина — значит, паводок нам не страшен».
        Увы, это не так. Разбираемся почему.
      </p>

      <h3>Кузьминский и Белоомутский гидроузлы: кто они</h3>
      <p>Оба гидроузла расположены между Коломной и Рязанью:</p>
      <ul>
        <li><strong>Белоомутский</strong> — в Луховицком районе Московской области, поддерживает уровень
          воды на участке от устья Москвы-реки до плотины.</li>
        <li><strong>Кузьминский</strong> — в 60 км ниже по течению, в Рязанской области, поддерживает
          уровень между собой и Белоомутским гидроузлом.</li>
      </ul>
      <p>
        Оба построены в <strong>1911–1915 годах</strong> по проекту гидротехника Нестора Пузыревского —
        с единственной целью: обеспечить судоходные глубины на Оке в летнюю межень для прохода барж в
        Москву. В 2010-х оба прошли масштабную реконструкцию стоимостью более 10 млрд рублей суммарно.
      </p>

      <h3>Что они делают и чего не делают</h3>
      <p>
        Гидроузлы <strong>не являются водохранилищами</strong>. Это проточные плотины-подпоры. Их задача
        — поднять уровень воды выше плотины на 3–4 метра в условиях маловодья, чтобы суда не садились на мель.
      </p>
      <p>
        В половодье, когда расход воды в Оке вырастает с 300–400 м³/с (летняя межень) до
        <span class="guide-highlight">5000–8000 м³/с</span> (пик половодья), плотины просто
        <strong>открывают все затворы</strong> и пропускают воду свободно. Гидроузел при этом не сдерживает
        паводок, а лишь немного «подпирает» воду выше по течению — то есть может даже
        <strong>ухудшить</strong> ситуацию для населённых пунктов между Коломной и гидроузлами.
      </p>
      <div class="guide-warn">
        ⚠️ Плотины на Оке — инфраструктура для судоходства, а не противопаводковая защита. Если вы покупаете
        участок в пойме Оки между Коломной и Рязанью, рассчитывать на то, что «плотина защитит», не стоит.
        Она вас <em>не</em> защитит.
      </div>
      <p>
        На уровень воды у Коломны существенно влияют и <strong>пять гидроузлов Москворецкой шлюзовой системы</strong>
        (Трудкоммуна, Андреевка, Фаустово и другие), расположенных на нижней Москве-реке. Сбросы через них
        в половодье — это дополнительные кубометры воды, поступающие в Оку через устьё Москвы-реки.
      </p>
    </div>

    <!-- SECTION 9 -->
    <div class="guide-section" id="s9">
      <h2><span class="section-number">9</span>Что делать обычному человеку: подготовка, эвакуация, страхование</h2>
      <div style="margin:12px 0 16px; text-align:center;">
        <img src="data:image/jpeg;base64,{NEW_IMAGES_B64.get('emergency_prep_flood', '')}" alt="Подготовка к паводку — что делать обычному человеку" style="width:100%; max-width:700px; border-radius:12px; margin:16px 0; box-shadow:0 4px 16px rgba(0,0,0,0.12);">
      </div>
      <p>
        Физика паводка — это интересно. Но домовладельцу и дачнику важен практический вывод. Вот он — без
        паники, но по делу.
      </p>

      <h3>До паводка: подготовительный сезон (октябрь — март)</h3>
      <ul class="guide-checklist">
        <li><strong>Узнайте свою отметку.</strong> Зайдите на allrivers.info, найдите ближайший гидрологический
          пост и выясните, на какой высоте исторически была вода в рекордные годы.</li>
        <li><strong>Зарегистрируйтесь на информационных ресурсах.</strong> Сайты региональных МЧС, Telegram-каналы
          администраций, приложение «МЧС России». В период паводка там публикуются оперативные уровни ежедневно.</li>
        <li><strong>Перенесите ценности</strong> выше уровня возможного подтопления — второй этаж или надёжный
          гараж на возвышенности.</li>
        <li><strong>Подготовьте «тревожный чемоданчик»:</strong> документы в герметичном пакете, наличные деньги,
          запас лекарств на 3–7 дней, одежда, вода, еда на 3 дня, фонарик, внешний аккумулятор.</li>
        <li><strong>Заранее отключите газ и электричество</strong> в подвале и на первом этаже, если ожидается
          затопление. Вода и электричество — смертельная комбинация.</li>
        <li><strong>Если есть возможность — поднимите участок.</strong> Подсыпка грунта, дренажные канавы
          по периметру, ливневая канализация — это работает, но только если успели сделать до паводка.</li>
      </ul>

      <h3>Во время паводка</h3>
      <ul class="guide-checklist">
        <li><strong>Следите за уровнем непрерывно.</strong> Когда подъём составляет 20–80 см в сутки (именно
          такая динамика была в марте 2026 года на Оке), ситуация меняется за несколько часов.</li>
        <li><strong>Не ждите официального приказа об эвакуации.</strong> Если вода подступает к порогу, а
          объявления ещё нет — уходите сами. Лучше эвакуироваться лишний раз, чем ждать лодку на крыше.</li>
        <li><strong>Не пытайтесь проехать через затопленные участки дороги.</strong> 30 см воды достаточно,
          чтобы снести легковой автомобиль. 50 см — критично для любого транспорта.</li>
        <li><strong>Не выходите на лёд во время ледохода.</strong> Весенний лёд «игольчатый» и рыхлый — он
          внезапно проваливается без предупреждения.</li>
      </ul>

      <h3>После паводка</h3>
      <ul class="guide-checklist">
        <li><strong>Не спешите возвращаться.</strong> Вода ушла, но грунт ещё насыщен влагой, возможны подвижки
          почвы, оползни на склонах, повреждения фундаментов.</li>
        <li><strong>Проверьте коммуникации</strong> перед включением электричества и газа. Вызовите специалистов.</li>
        <li><strong>Зафиксируйте ущерб</strong> для страховой: фотографии, видео, акты оценки ущерба.</li>
      </ul>

      <h3>Страхование</h3>
      <p>В России существует страхование имущества от наводнений. Ключевые моменты:</p>
      <ul>
        <li>Страхование нужно оформить <strong>заблаговременно</strong> — за несколько месяцев до паводкового
          сезона. Страховые компании отказывают в полисах при «выраженной паводковой угрозе».</li>
        <li>Убедитесь, что в полисе прямо прописаны риски <strong>«наводнение», «паводок», «затопление»</strong>
          — без этих слов страховщик откажет в выплате.</li>
        <li>Стоимость полиса на дачный дом в пойме — 3 000–15 000 рублей/год в зависимости от зоны риска.</li>
        <li>Государственная компенсация при ЧС — это отдельная история, она не заменяет страховку.</li>
      </ul>
    </div>

    <!-- SUMMARY TABLE -->
    <div class="guide-section">
      <h2>📋 Краткая шпаргалка: что важно знать</h2>
      <div class="table-wrap">
      <table class="guide-summary-table">
        <thead>
          <tr><th>Вопрос</th><th>Ответ</th></tr>
        </thead>
        <tbody>
          <tr><td>Что такое паводочная волна?</td><td>Гребень повышенного уровня, движущийся вниз по реке медленно и плавно</td></tr>
          <tr><td>Скорость волны на Оке?</td><td>40–80 км/сутки (7–14 дней от Орла до Серпухова)</td></tr>
          <tr><td>Почему бывает несколько волн?</td><td>Разновременное таяние, дожди, сбросы с плотин, ледовые заторы</td></tr>
          <tr><td>Главный фактор высоты паводка?</td><td>Запасы воды в снеге + промёрзлость грунта</td></tr>
          <tr><td>Как следить за уровнем?</td><td>allrivers.info (данные до мая 2024), сайт регионального МЧС, serpuhov.ru</td></tr>
          <tr><td>НЯ — что делать?</td><td>Готовиться к эвакуации, следить за обстановкой каждые 2 часа</td></tr>
          <tr><td>ОЯ — что делать?</td><td>Эвакуироваться немедленно</td></tr>
          <tr><td>Помогут ли плотины Белоомут/Кузьминск?</td><td>Нет — они для судоходства, не для защиты от паводка</td></tr>
          <tr><td>Когда оформлять страховку?</td><td>Осенью или в начале зимы — до паводкового сезона</td></tr>
        </tbody>
      </table>
      </div>
      <div class="guide-tip">
        ✅ Ока разливается каждую весну — это не катастрофа, а часть её природного ритма. Знать физику
        этого процесса, следить за гидрологическими постами и держать чемодан наготове — задача куда более
        выполнимая, чем кажется. Удачи вам, сухих подвалов и спокойного апреля.
      </div>
    </div>

    <!-- SOURCES -->
    <div class="guide-section">
      <h2>🔗 Источники и полезные ссылки</h2>
      <ul>
        <li><a href="https://ru.wikipedia.org/wiki/%D0%9E%D0%BA%D0%B0" style="color:var(--accent);">Ока — Википедия</a> — базовые гидрологические характеристики</li>
        <li><a href="https://allrivers.info/river/oka" style="color:var(--accent);">Allrivers.info: река Ока</a> — гидропосты, уровни, история наблюдений (данные на май 2024, обновление приостановлено)</li>
        <li><a href="https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-kolomna-segodnya" style="color:var(--accent);">СНТ Бугорок: уровень воды у Коломны</a> — критические отметки</li>
        <li><a href="https://www.orelvkartinkax.ru/bigwater.htm" style="color:var(--accent);">Краткая история орловских наводнений</a> — архивные данные по Орлу</li>
        <li><a href="https://www.kp40.ru/news/perekrestok/71009/" style="color:var(--accent);">История паводков, Калуга</a> — паводки 1908 и 1970 годов</li>
        <li><a href="https://ru.wikipedia.org/wiki/%D0%91%D0%B5%D0%BB%D0%BE%D0%BE%D0%BC%D1%83%D1%82%D1%81%D0%BA%D0%B8%D0%B9_%D0%B3%D0%B8%D0%B4%D1%80%D0%BE%D1%83%D0%B7%D0%B5%D0%BB" style="color:var(--accent);">Белоомутский гидроузел — Википедия</a></li>
        <li><a href="https://ru.wikipedia.org/wiki/%D0%9A%D1%83%D0%B7%D1%8C%D0%BC%D0%B8%D0%BD%D1%81%D0%BA%D0%B8%D0%B9_%D0%B3%D0%B8%D0%B4%D1%80%D0%BE%D1%83%D0%B7%D0%B5%D0%BB" style="color:var(--accent);">Кузьминский гидроузел — Википедия</a></li>
        <li><a href="https://www.nkj.ru/archive/articles/9307/" style="color:var(--accent);">Наука и жизнь: весеннее половодье</a> — природа Оки в паводок</li>
        <li><a href="https://uon.sdsu.edu/kinematic_waves_demystified.html" style="color:var(--accent);">Kinematic waves demystified (SDSU)</a> — теория кинематических волн</li>
      </ul>
      <p style="margin-top:16px;">
        <a href="history.html" style="color:var(--accent);">→ История паводков на Оке в цифрах</a>
      </p>
    </div>

    <div class="back-link-block">
      <a href="index.html">← Вернуться на главную</a>
      <a href="history.html" class="secondary">📜 История паводков</a>
    </div>

  </main>

  <footer style="text-align:center; padding:24px 16px; color:var(--text-muted); font-size:0.82rem; border-top:1px solid var(--card-border); margin-top:16px;">
    OkaFloodMonitor — образовательный ресурс о паводках на Оке |
    Обновлено: {_h(ts)} | v7.3
  </footer>

<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(FLOOD_GUIDE_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] flood-guide.html сохранён ({len(html)} символов)")



def generate_links_page(data: dict = None) -> str:
    """Генерирует docs/links.html."""
    serp = (data or {}).get("serpuhov", {}) if data else {}
    src_stat = serp.get("source_status", "unavailable")
    src_cls = "ok" if src_stat == "ok" else ("cached" if src_stat == "cached" else "unavailable")

    css = _generate_links_css()
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ссылки — OkaFloodMonitor</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>

{_build_nav('links')}

<div class="container">
<h1>🔗 Полезные ссылки</h1>

<div class="section-card">
  <h2>🌊 Данные о паводке на Оке</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li>
      <a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">
        serpuhov.ru — Паводковая обстановка Серпухова</a>
      — ежедневные данные о уровне воды у д. Лукьяново
      <span class="source-badge {src_cls}" style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-size:0.72rem;font-weight:600;border:1px solid;margin-left:6px;">{src_stat}</span>
    </li>
    <li>
      <a href="https://cugms.ru/gidrologiya/vesennee-polovode-i-dozhdevye-pavodki-2026/" target="_blank" rel="noopener">
        ЦУГМС — Весеннее половодье 2026</a>
      — ежедневные обзоры развития паводка
    </li>
    <li>
      <a href="https://cugms.ru/utochnenie-dolgosrochnogo-prognoza-maksimalnogo-urovnya-vody-vesennego-polovodya-2026-g-dlya-rek-bassejnov-verhnej-oki/" target="_blank" rel="noopener">
        ЦУГМС — Уточнённый прогноз пика для бассейна верхней Оки</a>
    </li>
    <li>
      <a href="https://ris.kim-online.ru/" target="_blank" rel="noopener">
        КИМ — уровни воды по гидропостам</a>
      — API для Каширы, Калуги, Рязани
    </li>
    <li>
      <a href="https://flood-api.open-meteo.com/v1/flood" target="_blank" rel="noopener">
        GloFAS Flood API (Open-Meteo)</a>
      — расход воды на 7 станциях верховий Оки, прогноз 16 дней
    </li>
  </ul>
</div>

<div class="section-card">
  <h2>🌦 Погода</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li><a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>
      — погода и снежный покров (бесплатный API, используется в мониторинге)</li>
    <li><a href="https://meteoinfo.ru/" target="_blank" rel="noopener">Meteoinfo.ru</a>
      — прогноз погоды ФГБУ ЦПГиМ</li>
    <li><a href="https://rp5.ru/" target="_blank" rel="noopener">rp5.ru</a>
      — подробный прогноз для Серпухова</li>
  </ul>
</div>

<div class="section-card">
  <h2>🚨 Экстренные службы</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li><b style="color:var(--text-primary);">Единый номер экстренных служб:</b> 112</li>
    <li><b style="color:var(--text-primary);">МЧС России (бесплатно):</b> 8-800-775-17-17</li>
    <li><a href="https://mchs.gov.ru/" target="_blank" rel="noopener">mchs.gov.ru</a>
      — официальный сайт МЧС России</li>
    <li><a href="https://serpuhov.ru/bezopasnost/grazhdanskaya-oborona/" target="_blank" rel="noopener">
      Гражданская оборона Серпухова</a></li>
    <li><a href="https://serpuhov.ru" target="_blank" rel="noopener">serpuhov.ru</a>
      — Администрация г.о. Серпухов</li>
  </ul>
</div>

<div class="section-card">
  <h2>📱 Местные ресурсы</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li><a href="https://vk.com/selodedinovo" target="_blank" rel="noopener">ВКонтакте — село Дединово</a>
      — уровни воды у Луховиц (#Уровень_воды_Ока)</li>
    <li>
      <a href="https://em-from-pu.github.io/oka-flood-monitor" target="_blank" rel="noopener">
        OkaFloodMonitor — GitHub Pages</a>
      — основная страница мониторинга
    </li>
  </ul>
</div>

<div class="section-card">
  <h2>⚠️ Почему нет других источников?</h2>
  <div class="dead-sources">
    <p style="color:var(--text-secondary); margin-bottom:8px;">Следующие ресурсы <b style="color:var(--danger);">прекратили публикацию данных</b> и не используются:</p>
    <ul>
      <li>fishingsib.ru — последние данные по Оке: март 2024</li>
      <li>allrivers.info/gauge/oka-serpuhov — последние данные: май 2024</li>
      <li>ЕСИМО — прекратил открытую публикацию данных Росгидромета ~2020</li>
      <li>КИМ API (Серпухов) — последние данные: ноябрь 2022 (используется только для Каширы, Калуги, Рязани)</li>
    </ul>
  </div>
</div>

<div class="section-card">
  <h2>📂 Публичные данные мониторинга</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li><a href="history.csv" download>history.csv</a> — история уровней воды (CSV)</li>
    <li><a href="data.json" target="_blank">data.json</a> — текущие данные (JSON)</li>
  </ul>
</div>

</div>

<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | 54.833413, 37.741813 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

<script>
(function() {{
  function updateClock() {{
    var now = new Date();
    var utcH = now.getUTCHours();
    var mskH = (utcH + 3) % 24;
    var h = String(mskH).padStart(2,'0');
    var m = String(now.getUTCMinutes()).padStart(2,'0');
    var s = String(now.getUTCSeconds()).padStart(2,'0');
    var el = document.getElementById('clock');
    if (el) el.textContent = h + ':' + m + ':' + s + ' МСК';
  }}
  setInterval(updateClock, 1000);
  updateClock();
}})();
</script>

<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(LINKS_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] Сохранено: {LINKS_HTML}")
    return html


def generate_instructions_page() -> str:
    """Генерирует docs/instructions.html."""
    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    css = _generate_links_css()

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Инструкции — OkaFloodMonitor</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌊</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{css}</style>
</head>
<body>

{_build_nav('instructions')}

<div class="container">
<h1>📖 Инструкция по использованию мониторинга</h1>

<div class="section-card">
  <h2>🌊 Что такое OkaFloodMonitor?</h2>
  <p style="color:var(--text-secondary);">Автоматическая система мониторинга паводка на реке Оке в районе Серпухова.
  Работает 24/7, данные обновляются 4 раза в день (08:00, 12:00, 17:00, 20:00 МСК).</p>
  <p style="color:var(--text-secondary); margin-top:8px;">В версии v7.0 добавлен источник GloFAS Flood API —
  глобальная система прогнозирования стока рек, дающая данные по 7 станциям верховий Оки
  и 16-дневный прогноз.</p>
</div>

<div class="section-card">
  <h2>📊 Откуда берутся данные?</h2>
  <p style="color:var(--text-secondary);"><b style="color:var(--text-primary);">Уровень воды в Серпухове</b> — сайт администрации г. Серпухова
  (<a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">serpuhov.ru</a>),
  пост наблюдения д. Лукьяново на р. Ока. Публикуется ежедневно в ~09:00.</p>
  <p style="color:var(--text-secondary); margin-top:8px;"><b style="color:var(--text-primary);">Другие станции (Кашира, Калуга, Рязань)</b> — API навигационного
  сервиса <a href="https://ris.kim-online.ru/" target="_blank" rel="noopener">КИМ</a>.
  Абсолютные уровни в см от нуля соответствующего поста (не сравниваются напрямую с Серпуховом).</p>
  <p style="color:var(--text-secondary); margin-top:8px;"><b style="color:var(--text-primary);">Суточные приросты и прогнозы</b> —
  <a href="https://cugms.ru/" target="_blank" rel="noopener">Центральное УГМС (ЦУГМС)</a>,
  ежедневные обзоры развития весеннего половодья.</p>
  <p style="color:var(--text-secondary); margin-top:8px;"><b style="color:var(--text-primary);">Погода и снежный покров</b> —
  <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo API</a> (бесплатный).</p>
  <p style="color:var(--text-secondary); margin-top:8px;"><b style="color:var(--text-primary);">GloFAS (верховья Оки)</b> —
  <a href="https://flood-api.open-meteo.com/" target="_blank" rel="noopener">GloFAS Flood API</a>.
  Расход воды (м³/с) для 7 станций: Орёл, Мценск, Белёв, Козельск, Калуга, Алексин, Таруса.
  Прогноз 16 дней. Без API-ключа, бесплатно.</p>
</div>

<div class="section-card">
  <h2>🔢 Как читать данные?</h2>
  <h3 style="margin-top:0;">Уровень воды (см)</h3>
  <p style="color:var(--text-secondary);">Высота воды над нулём водомерного поста д. Лукьяново.
  Нуль поста ≈ {LUKYANNOVO_ZERO_M_BS} м БС. Формула: <b>абсолютный = {LUKYANNOVO_ZERO_M_BS} + уровень_м</b></p>
  <div class="zone-table" style="margin-top:12px;">
    <div class="zone-row green">&lt; {ZONE_GREEN_MAX} см — <b>НОРМА</b>. Паводковый сезон в начальной фазе.</div>
    <div class="zone-row yellow">{ZONE_GREEN_MAX}–{ZONE_YELLOW_MAX} см — <b>ВНИМАНИЕ</b>. Пойма начинает заполняться.</div>
    <div class="zone-row orange">{ZONE_YELLOW_MAX}–{ZONE_ORANGE_MAX} см — <b>ОПАСНОСТЬ</b>. Пойма затоплена, приближаемся к НЯ.</div>
    <div class="zone-row red">&gt; {ZONE_ORANGE_MAX} см — <b>КРИТИЧНО</b>. Немедленно следите за сводками.</div>
  </div>
  <h3>НЯ и ОЯ</h3>
  <p style="color:var(--text-secondary);"><b style="color:var(--text-primary);">НЯ ({LUKYANNOVO_NYA_M_BS} м БС, ≈{nya_cm:.0f} см)</b> —
  неблагоприятное явление — уровень выхода воды на пойму.</p>
  <p style="color:var(--text-secondary); margin-top:8px;"><b style="color:var(--text-primary);">ОЯ ({LUKYANNOVO_OYA_M_BS} м БС, ≈{oya_cm:.0f} см)</b> —
  опасное явление — уровень подтопления населённых пунктов.</p>
  <h3>Расход GloFAS (м³/с)</h3>
  <p style="color:var(--text-secondary);">Объём воды, протекающей через поперечное сечение русла в секунду.
  Flood ratio (×N) — отношение текущего расхода к среднему: &gt;3 = высокий паводок, &gt;5 = экстремальный.</p>
</div>

<div class="section-card">
  <h2>🌡 Паводковый индекс погоды</h2>
  <p style="color:var(--text-secondary);">Комплексный показатель риска подъёма воды (0–4), вычисляется по данным Open-Meteo:</p>
  <ul style="padding-left:20px; color:var(--text-secondary); margin-top:8px; line-height:2;">
    <li><b style="color:var(--safe);">0 — СТАБИЛЬНЫЙ</b>: морозы сдерживают таяние</li>
    <li><b style="color:var(--safe);">1 — УМЕРЕННЫЙ</b>: незначительное таяние</li>
    <li><b style="color:var(--watch);">2 — ПОВЫШЕННЫЙ</b>: снег тает, осадки умеренные</li>
    <li><b style="color:var(--warning);">3 — ВЫСОКИЙ</b>: значительный риск подъёма</li>
    <li><b style="color:var(--danger);">4 — КРИТИЧЕСКИЙ</b>: активное таяние + осадки + Rain-on-Snow</li>
  </ul>
</div>

<div class="section-card">
  <h2>🚨 Что делать при разных уровнях?</h2>
  <div class="table-wrap">
  <table class="action-table">
    <tr><th>Уровень (см)</th><th>Статус</th><th>Рекомендации</th></tr>
    <tr><td>&lt; {ZONE_GREEN_MAX}</td><td>🟢 НОРМА</td><td style="color:var(--text-secondary);">Следите за динамикой. Обновления 4 раза в день.</td></tr>
    <tr><td>{ZONE_GREEN_MAX}–{ZONE_YELLOW_MAX}</td><td>🟡 ВНИМАНИЕ</td><td style="color:var(--text-secondary);">Проверьте участок. Уберите ценности с низких мест.</td></tr>
    <tr><td>{ZONE_YELLOW_MAX}–{ZONE_ORANGE_MAX}</td><td>🟠 ОПАСНОСТЬ</td><td style="color:var(--text-secondary);">Подготовьтесь к эвакуации. Насосы наготове.</td></tr>
    <tr><td>&gt; {ZONE_ORANGE_MAX}</td><td>🔴 КРИТИЧНО</td><td style="color:var(--text-secondary);">Немедленно вывезите ценные вещи. Звоните 112.</td></tr>
  </table>
  </div>
</div>

<div class="section-card">
  <h2>📞 Контакты экстренных служб</h2>
  <ul style="padding-left:20px; color: var(--text-secondary); line-height:2;">
    <li>Единый номер экстренных служб: <b style="color:var(--text-primary);">112</b></li>
    <li>МЧС России (бесплатно): <b style="color:var(--text-primary);">8-800-775-17-17</b></li>
    <li>Администрация Серпухова: <a href="https://serpuhov.ru" target="_blank" rel="noopener">serpuhov.ru</a></li>
    <li>Паводковая обстановка:
      <a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">
      serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/</a></li>
  </ul>
</div>

<div class="section-card" id="telegram">
  <h2>📱 Система Telegram-оповещений</h2>

  <h3 style="color:var(--text-primary); margin:16px 0 8px;">Как работает система</h3>
  <p style="color:var(--text-secondary);">Мониторинг запускается автоматически <b>4 раза в сутки</b> (08:00, 12:00, 17:00, 20:00 МСК).
  При каждом запуске скрипт собирает данные из пяти источников, вычисляет аналитику и, если нужно,
  отправляет уведомление в Telegram. Никакого дежурного человека за пультом нет — только алгоритм и бдительность.</p>

  <h3 style="color:var(--text-primary); margin:16px 0 8px;">Виды уведомлений</h3>
  <div class="table-wrap">
  <table class="action-table" style="margin-top:0;">
    <tr><th>Тип</th><th>Когда</th><th>Что содержит</th></tr>
    <tr>
      <td style="color:#64b5f6;"><b>💓 Heartbeat</b></td>
      <td style="color:var(--text-secondary);">Каждый запуск (4×/сут)</td>
      <td style="color:var(--text-secondary);">Краткий статус: уровень, прирост, источники данных</td>
    </tr>
    <tr>
      <td style="color:#81c784;"><b>📋 Дайджест</b></td>
      <td style="color:var(--text-secondary);">08:00 и 20:00 МСК</td>
      <td style="color:var(--text-secondary);">Полный обзор: уровни по всем постам, прогноз, погодный индекс, сводка GloFAS</td>
    </tr>
    <tr>
      <td style="color:#ef5350;"><b>🚨 Алерт</b></td>
      <td style="color:var(--text-secondary);">При превышении порогов ({ALERT_ATTENTION}, {ALERT_DANGER} см и выше)</td>
      <td style="color:var(--text-secondary);">Пороговое предупреждение с уровнем, динамикой и рекомендациями</td>
    </tr>
    <tr>
      <td style="color:#ffb74d;"><b>🌧️ Погодный алерт</b></td>
      <td style="color:var(--text-secondary);">При паводковом индексе ≥ 3/4</td>
      <td style="color:var(--text-secondary);">Предупреждение о высоком паводковом риске за 2–3 дня до возможного подъёма</td>
    </tr>
  </table>
  </div>

  <h3 style="color:var(--text-primary); margin:16px 0 8px;">Как подключиться</h3>
  <p style="color:var(--text-secondary);">В настоящее время уведомления рассылаются по закрытому списку подписчиков.
  Чтобы попасть в список —
  <a href="https://t.me/Egor_Melnikov_Me" target="_blank" style="color:var(--accent);">Написать разработчику в Telegram</a>.
  Публичный канал находится в разработке.</p>

  <div style="background:rgba(29,155,240,0.07); border:1px solid rgba(29,155,240,0.25); border-radius:12px; padding:16px; margin-top:16px;">
    <p style="color:var(--text-secondary); margin:0; font-size:0.88rem;">
      <b style="color:#1d9bf0;">Пример heartbeat-сообщения:</b><br><br>
      <span style="font-family:monospace; font-size:0.82rem; display:block; white-space:pre-wrap; color:var(--text-secondary);"
      >💓 OkaFloodMonitor | 30.03.2026 08:00 МСК
Серпухов: 542 см  (+12 см/сут)  🟡 ВНИМАНИЕ
Калуга: 389 см | Кашира: 461 см
GloFAS Таруса: flood ratio 2.1×
Погода: индекс 2/4 (умеренный)
Источники: ✅ serpuhov.ru ✅ КИМ ✅ ЦУГМС ✅ GloFAS</span>
    </p>
  </div>

  <div style="background:rgba(239,83,80,0.07); border:1px solid rgba(239,83,80,0.25); border-radius:12px; padding:16px; margin-top:12px;">
    <p style="color:var(--text-secondary); margin:0; font-size:0.88rem;">
      <b style="color:#ef5350;">Пример алерта:</b><br><br>
      <span style="font-family:monospace; font-size:0.82rem; display:block; white-space:pre-wrap; color:var(--text-secondary);"
      >🚨 АЛЕРТ: Уровень 603 см (+47 см/сут)
До ОЯ (867 см — вода у порога дома автора): ~5–6 дней
Прогноз: вода продолжит подъём 3–5 дней, затем замедление.
Расчётный пик: ~750–850 см к 10–12 апреля.
Вероятность превышения ОЯ: 45–55%.
Рекомендация: завершить подготовку защиты в ближайшие 3 дня.</span>
    </p>
  </div>
</div>

<div class="section-card">
  <h2>❓ Часто задаваемые вопросы</h2>
  <p style="color:var(--text-secondary);"><b style="color:var(--text-primary);">Почему нет других источников данных?</b><br>
  fishingsib.ru и allrivers.info прекратили публикацию данных (последние данные — 2024 год).
  КИМ API в Серпухове мёртв с ноября 2022. Основной источник — serpuhov.ru.</p>
  <p style="color:var(--text-secondary); margin-top:12px;"><b style="color:var(--text-primary);">Что такое «Жерновка»?</b><br>
  Локальное название местности примерно в 8 км ниже Пущино по реке Ока.
  Паводковая волна от Серпухова доходит туда примерно за 6–12 часов.</p>
  <p style="color:var(--text-secondary); margin-top:12px;"><b style="color:var(--text-primary);">Как работает GloFAS Timeline?</b><br>
  Горизонтальная шкала показывает прогнозируемое время пика на каждой станции
  и расчётное время прибытия волны в Серпухов, исходя из типичной скорости волны добегания.</p>
</div>

</div>

<footer class="site-footer">
  OkaFloodMonitor v7.7.2 | 54.833413, 37.741813 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>


<script>
function toggleMobileNav(){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n)return;n.classList.toggle('open');if(b)b.textContent=n.classList.contains('open')?'\u2715':'\u2630';}}
document.addEventListener('click',function(e){{var n=document.getElementById('mobile-nav'),b=document.querySelector('.burger-btn');if(!n||!b)return;if(!n.contains(e.target)&&!b.contains(e.target)){{n.classList.remove('open');if(b)b.textContent='\u2630';}} }});
</script>
</body>
</html>"""

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(INSTRUCTIONS_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] Сохранено: {INSTRUCTIONS_HTML}")
    return html


# ══════════════════════════════════════════════════════════════════════════════
# DATA.JSON
# ══════════════════════════════════════════════════════════════════════════════

def generate_data_json(data: dict, analytics: dict, history: list,
                        composite: dict, wext) -> dict:
    """
    Генерирует структуру data.json для docs/.
    v7: добавлена секция glofas.
    """
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})
    cugms  = data.get("cugms", {})
    glofas = data.get("glofas", {})

    # GloFAS summary
    glofas_summary = {}
    for slug in (GLOFAS_STATIONS or {}):
        st = glofas.get(slug, {})
        if st:
            glofas_summary[slug] = {
                "name":              st.get("name"),
                "current_discharge": st.get("current_discharge"),
                "peak_discharge":    st.get("peak_discharge"),
                "peak_date":         st.get("peak_date"),
                "trend_arrow":       st.get("trend_arrow"),
                "flood_ratio":       st.get("flood_ratio"),
                "wave_arrival":      st.get("wave_arrival_serpukhov"),
                "source_status":     st.get("source_status"),
            }

    wave_arrivals = calculate_wave_arrival(glofas)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "serpuhov": {
            "level_cm":        serp.get("level_cm"),
            "level_m":         serp.get("level_m"),
            "daily_change_cm": serp.get("daily_change_cm"),
            "abs_level_m_bs":  serp.get("abs_level_m_bs"),
            "water_status":    serp.get("water_status"),
            "nya_m_bs":        LUKYANNOVO_NYA_M_BS,
            "oya_m_bs":        LUKYANNOVO_OYA_M_BS,
            "source_status":   serp.get("source_status"),
            "cache_age_h":     serp.get("cache_age_h", 0),
        },
        "analytics": {
            "alert_level":     analytics.get("alert_level"),
            "days_to_nya":     analytics.get("days_to_nya"),
            "days_to_oya":     analytics.get("days_to_oya"),
            "nya_remaining_m": analytics.get("nya_remaining_m"),
            "oya_remaining_m": analytics.get("oya_remaining_m"),
        },
        "composite_status": composite,
        "glofas": {
            "status":    (glofas or {}).get("_status"),
            "stations":  glofas_summary,
            "wave_arrival_serpukhov": wave_arrivals.get("serpukhov_arrival"),
        },
        "weather": {
            "flood_index":   (wext or {}).get("flood_index"),
            "flood_label":   (wext or {}).get("flood_label"),
            "flood_summary": (wext or {}).get("flood_summary"),
            "snow_depth_cm": (wext or {}).get("snow_depth_cm"),
        },
        "kim": {
            "kashira_cm": ((kim.get("kashira") or {}).get("level_cm")),
            "kaluga_cm":  ((kim.get("kaluga") or {}).get("level_cm")),
            "ryazan_cm":  ((kim.get("ryazan") or {}).get("level_cm")),
            "api_status": kim.get("_api_status"),
        },
        "cugms": {
            "review_number":     cugms.get("review_number"),
            "review_date":       cugms.get("review_date"),
            "serpuhov_change_cm": cugms.get("serpuhov_change_cm"),
            "forecast_text":     cugms.get("forecast_text"),
            "source_status":     cugms.get("source_status"),
        },
        "history_count": len(history),
        "sources": {
            "ok":     data.get("sources_ok", []),
            "failed": data.get("sources_failed", []),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# GIT
# ══════════════════════════════════════════════════════════════════════════════

def git_push() -> None:
    """Выполняет git add, commit, push."""
    try:
        now_str = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        subprocess.run(
            ["git", "config", "user.email", "bot@github.com"],
            cwd=BASE_DIR, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "OkaFloodBot"],
            cwd=BASE_DIR, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "add", "docs/", "data/", "-f"],
            cwd=BASE_DIR, check=True, capture_output=True
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=BASE_DIR, capture_output=True
        )
        if result.returncode == 0:
            print("[git] Нет изменений для коммита.")
            return
        subprocess.run(
            ["git", "commit", "-m", f"auto: monitor v7.0 update {now_str} МСК"],
            cwd=BASE_DIR, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "push"],
            cwd=BASE_DIR, check=True, capture_output=True
        )
        print("[git] Push выполнен успешно.")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
        print(f"[git] Ошибка: {e} | stderr: {stderr[:200]}")
    except Exception as e:
        print(f"[git] Неожиданная ошибка: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# КЕШИРОВАНИЕ ПОГОДЫ ПРИ TIMEOUT
# ══════════════════════════════════════════════════════════════════════════════


def _load_last_weather_from_json():
    """Загружает последние данные погоды из data/latest.json при timeout."""
    try:
        path = os.path.join(DATA_DIR, "latest.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            w = obj.get("weather", {})
            return {
                "flood_index": w.get("flood_index"),
                "flood_label": w.get("flood_label"),
                "flood_summary": w.get("flood_summary"),
                "snow_depth_cm": w.get("snow_depth_cm"),
                "_cached": True,
            }
    except Exception:
        pass
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    Точка входа monitor.py v7.2.

    Порядок:
    1.  Загружаем данные (5 источников параллельно)
    2.  Загружаем историю, 2024-ref
    3.  Вычисляем аналитику
    4.  Вычисляем Composite Status
    5.  Дополняем историю и сохраняем
    6.  Вычисляем регрессию
    7.  Генерируем HTML (3 страницы)
    8.  Генерируем data.json + history.csv
    9.  TG-сообщения (heartbeat, алерты, дайджесты)
    10. Git commit + push
    """
    print(
        f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] "
        f"OkaFloodMonitor v7.7 START"
    )

    # ─── 1. ДАННЫЕ ───────────────────────────────────────────────────────────
    data   = fetch_all_data()
    wext   = data.get("weather") or {}
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})

    # v7.6: при timeout погоды — подгружаем кеш из latest.json
    if not wext.get("flood_index") and not wext.get("days"):
        cached_w = _load_last_weather_from_json()
        if cached_w.get("flood_index"):
            wext.update(cached_w)
            print(f"[v7] Погода: используем кеш из latest.json (flood_index={cached_w.get('flood_index')})")
    cugms  = data.get("cugms", {})
    glofas = data.get("glofas", {})

    # ── Корректировка flood_summary: текст должен соответствовать реальным факторам ──
    # Не перезаписывать summary если данные из кеша (нет days)
    if wext and wext.get("flood_index", 0) >= 3 and not wext.get("_cached"):
        days = wext.get("days", [])
        total_precip = sum(d.get("precip", 0) or 0 for d in days)
        snow_cm = wext.get("snow_depth_cm", 0) or 0
        warm_nights = sum(1 for d in days if (d.get("tmin", -5) or -5) > 0)
        hot_days = sum(1 for d in days if (d.get("tmax", 0) or 0) > 10)
        has_rain = total_precip >= 5
        has_melt = hot_days >= 3 or warm_nights >= 3
        # Формируем точное описание
        factors = []
        if has_melt:
            factors.append("активное таяние")
        if has_rain:
            factors.append(f"осадки ({total_precip:.0f} мм)")
        if snow_cm >= 5:
            factors.append(f"снег {snow_cm:.0f} см")
        if warm_nights >= 3:
            factors.append(f"тёплые ночи (Tmin > 0°C, {warm_nights} из 8)")
        if not has_rain and not has_melt:
            factors.append("умеренные условия")
        factors_str = ", ".join(factors) if factors else "Условия паводкоопасные"
        # Заглавная только для первой буквы (не ломаем Tmin/°C)
        if factors_str and factors_str[0].islower():
            factors_str = factors_str[0].upper() + factors_str[1:]
        verdict = "Максимально быстрый рост уровня" if wext.get("flood_index", 0) >= 4 else "Значительный риск подъёма"
        summary_text = f"{factors_str}. {verdict}"
        wext["flood_summary"] = summary_text

    print(f"[v7] Источники OK: {data.get('sources_ok')}")
    print(f"[v7] Источники FAILED: {data.get('sources_failed')}")
    print(f"  Погода: {(wext or {}).get('flood_label', '?')} — {(wext or {}).get('flood_summary', '')}")
    print(f"  serpuhov.ru: {serp.get('level_cm')} см ({serp.get('source_status')})")
    kash_cm = (kim.get("kashira") or {}).get("level_cm")
    kal_cm  = (kim.get("kaluga") or {}).get("level_cm")
    print(f"  КИМ: Кашира={kash_cm} Калуга={kal_cm}")
    print(f"  ЦУГМС: обзор №{cugms.get('review_number')}, Серпухов {cugms.get('serpuhov_change_cm')} см/сут")
    print(f"  GloFAS статус: {(glofas or {}).get('_status')}")

    # ─── 2. ИСТОРИЯ + 2024-REF ──────────────────────────────────────────────
    history  = load_history()
    ref_2024 = load_2024_ref()

    # ─── 3. АНАЛИТИКА ───────────────────────────────────────────────────────
    analytics  = compute_analytics(serp, kim, cugms, history, wext)
    regression = compute_regression(history)

    # ─── 4. COMPOSITE STATUS ────────────────────────────────────────────────
    composite = compute_composite_status(serp, wext, glofas, analytics)
    verdict_label = (composite.get("verdict") or {}).get("label", "—")
    print(f"  Composite Status: {verdict_label}")

    # ─── 5. ИСТОРИЯ: запись + сохранение ────────────────────────────────────
    history = append_history_row(history, data, analytics, wext)
    save_history(history)
    export_history_csv(history)
    print(f"  История: {len(history)} записей сохранено.")


    # ─── 5.5 МУЛЬТИ-ТОЧЕЧНАЯ ПОГОДА ────────────────────────────────────────
    weather_multi_data = {}
    if fetch_multi_weather:
        try:
            weather_multi_data = fetch_multi_weather()
            print(f"  Осадки по бассейну: {weather_multi_data.get('status', 'error')} ({len(weather_multi_data.get('points', []))} точек)")
        except Exception as e:
            print(f"  [weather_multi] Ошибка: {e}")
    # ─── 6. HTML ГЕНЕРАЦИЯ ──────────────────────────────────────────────────
    html_content = generate_html(data, analytics, history, wext, regression, ref_2024, weather_multi_data)
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[HTML] index.html сохранён ({len(html_content)} символов)")

    generate_links_page(data)
    generate_instructions_page()
    generate_history_page()
    generate_flood_guide_page()
    generate_city_pages(data)

    # ─── 7. DATA.JSON ───────────────────────────────────────────────────────
    data_json_obj = generate_data_json(data, analytics, history, composite, wext)
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data_json_obj, f, ensure_ascii=False, indent=2)
    print(f"[data.json] Сохранено: {DATA_JSON}")

    # ─── 8. GROUP DRAFT ─────────────────────────────────────────────────────
    group_draft = format_group_draft(data, wext)
    with open(GROUP_DRAFT, "w", encoding="utf-8") as f:
        f.write(group_draft)

    # ─── 9. TELEGRAM ────────────────────────────────────────────────────────
    if TG_TOKEN:
        now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
        msk_hour = (datetime.now(timezone.utc) + timedelta(hours=3)).hour

        # Heartbeat (admin) — каждый запуск
        hb = build_heartbeat_message(data, analytics, composite, now_msk)
        tg_send(CHAT_ADMIN, hb)

        # Алерты — пороговые
        alerts = load_alerts()
        alerts_changed = False

        level_triggered = check_level_triggers(serp.get("level_cm"), alerts)
        for key, text in level_triggered:
            tg_send(CHAT_ADMIN, text)
            if (serp.get("level_cm") or 0) >= ALERT_DANGER:
                tg_send(CHAT_MY_GROUP, text)
                if CHAT_ZMSS:
                    tg_send(CHAT_ZMSS, text)
            alerts[key] = datetime.now(timezone.utc).isoformat()
            alerts_changed = True

        watchdog_triggered = check_watchdog(data, alerts)
        for key, text in watchdog_triggered:
            tg_send(CHAT_ADMIN, text)
            alerts[key] = datetime.now(timezone.utc).isoformat()
            alerts_changed = True

        # Превентивный погодный алерт
        fi = (wext or {}).get("flood_index", 0)
        if wext and (serp.get("level_cm") or 0) < ALERT_ATTENTION and fi >= 3:
            key = f"WEATHER_ALERT_{fi}"
            if should_send_alert(alerts, key, cooldown_h=12):
                fl_label   = wext.get("flood_label", "")
                fl_summary = wext.get("flood_summary", "")
                msg = (
                    f"🌧️ <b>[ПРОГНОЗ ПОГОДЫ]</b> Паводковый индекс: <b>{_h(fl_label)}</b> ({fi}/4)\n\n"
                    f"{_h(fl_summary)}\n\n"
                    "⚠️ Условия указывают на возможный подъём в ближайшие 2–3 дня."
                )
                tg_send(CHAT_ADMIN, msg)
                tg_send(CHAT_MY_GROUP, msg)
                alerts[key] = datetime.now(timezone.utc).isoformat()
                alerts_changed = True

        if alerts_changed:
            save_alerts(alerts)

        # Дайджест (группа) — в 08:00 и 20:00 МСК
        if msk_hour in (8, 20):
            digest = build_digest_message(data, analytics, composite, wext, glofas, now_msk)
            tg_send(CHAT_MY_GROUP, digest)
            tg_send(CHAT_ADMIN, digest)

            # Соседский дайджест — только в 08:00
            if msk_hour == 8:
                neighbors_msg = build_neighbors_digest(data, analytics, composite, glofas, now_msk)
                if CHAT_NEIGHBORS:
                    tg_send(CHAT_NEIGHBORS, neighbors_msg)
                if CHAT_ZMSS:
                    tg_send(CHAT_ZMSS, neighbors_msg)

            # Mailing list
            for cid in load_mailing_list():
                neighbors_msg = build_neighbors_digest(data, analytics, composite, glofas, now_msk)
                tg_send(str(cid), neighbors_msg)
    else:
        print("[TG] TG_TOKEN не установлен, пропускаем.")

    # ─── 10. GIT PUSH ───────────────────────────────────────────────────────
    # git_push()  # отключено: push делает GitHub Actions "Commit HTML/data" step

    print(
        f"✅ OkaFloodMonitor v7.7 DONE | Серпухов: {serp.get('level_cm')} см | "
        f"Статус: {verdict_label} | "
        f"Источники OK: {data.get('sources_ok')}"
    )


if __name__ == "__main__":
    main()
