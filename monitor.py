#!/usr/bin/env python3
"""
monitor.py v7.5 — OkaFloodMonitor
HTML-генерация + аналитика + Telegram-оповещения
Источники: serpuhov.ru (PRIMARY) | КИМ API | ЦУГМС | Open-Meteo | GloFAS

v7.5 changelog:
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
        "nearest_hydro_post": "Серпухов (выше, 522 км) и Кашира (ниже, 573 км)",
        "flood_risk": "Сам наукоград на высоком берегу; СНТ и дачи в пойме ниже по течению",
        "notable_floods": [
            (2013, "(Серпухов: 843 см)", "Высокий берег защитил наукоград; пойма левого берега затоплена"),
        ],
        "description": (
            "Деревня Пущино впервые упоминается в писцовых книгах 1578–79 гг. "
            "Город науки с 1966 года — центр биологических исследований АН СССР. "
            "Расположен на высоком правом берегу Оки (120–140 м над уровнем моря). "
            "Напротив — Приокско-Террасный заповедник (зубры, реликтовые степные растения). "
            "Ширина поймы Оки у Пущино — до 3–5 км в половодье. "
            "Ближайший гидропост — д. Лукьяново (17 км вверх по реке, ~4–5 ч волны). "
            "В 2024 году разлив доходил до корней деревьев у пляжа Пущино. "
            "Знаменитый маршрут: пешком по правому берегу Пущино → Кашира (40 км). "
            "Зимой из Приокско-Террасного заповедника через замёрзшую Оку переходят лоси, кабаны, зайцы. "
            "Легенда про коров на льдине — широко известный фольклорный сюжет на Оке: "
            "в 1908 году при катастрофическом разливе 12+ метров у Серпухова смывало целые деревни, "
            "скот уносило на льдинах."
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
            "safe":      ("🟢 НОРМА",                  "🟢"),
            "watch":     ("🟡 БДИТЕЛЬНОСТЬ",            "🟡"),
            "warning":   ("🟠 РАСТУЩАЯ ОПАСНОСТЬ",      "🟠"),
            "danger":    ("🔴 КРИТИЧЕСКАЯ УГРОЗА",       "🔴"),
            "emergency": ("🟣 ЧРЕЗВЫЧАЙНАЯ СИТУАЦИЯ",    "🟣"),
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
    Полный дайджест.
    v7: добавлена секция upstream GloFAS.
    """
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})

    now_date  = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y")
    level_cm  = serp.get("level_cm")
    abs_bs    = serp.get("abs_level_m_bs")
    change    = serp.get("daily_change_cm")
    src_stat  = serp.get("source_status", "?")
    arrow     = _trend(change)

    level_str = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
    abs_str   = f"{abs_bs:.2f} м БС" if abs_bs is not None else "?"

    # Другие станции
    stations_lines = ""
    kashira_cm = (kim.get("kashira") or {}).get("level_cm")
    kaluga_cm  = (kim.get("kaluga") or {}).get("level_cm")
    ryazan_cm  = (kim.get("ryazan") or {}).get("level_cm")
    if kashira_cm:
        k_chg = cugms.get("kashira_change_cm")
        k_str = f" ({k_chg:+.0f} см/сут)" if k_chg is not None else ""
        stations_lines += f"🔸 Кашира: {kashira_cm} см{k_str}\n"
    if kaluga_cm:
        stations_lines += f"🔸 Калуга: {kaluga_cm} см\n"
    if ryazan_cm:
        stations_lines += f"🔸 Рязань: {ryazan_cm} см\n"

    # ЦУГМС
    cugms_block = ""
    if cugms.get("review_number"):
        n        = cugms.get("review_number")
        c_date   = cugms.get("review_date", "?")
        s_chg    = cugms.get("serpuhov_change_cm")
        k_chg    = cugms.get("kashira_change_cm")
        ice      = cugms.get("ice_status", {})
        f_intens = cugms.get("forecast_intensity_mps", "нет данных")
        ice_parts = [f"{st}: {st_ice}" for st, st_ice in ice.items()] if ice else []
        ice_str  = ", ".join(ice_parts) if ice_parts else "нет особых явлений"
        s_chg_str = f"{s_chg:+.0f} см/сут" if s_chg is not None else "нет данных"
        k_chg_str = f"{k_chg:+.0f} см/сут" if k_chg is not None else "нет данных"
        cugms_block = (
            f"━━ ЦУГМС (обзор №{n} от {c_date}) ━━━━━\n"
            f"Серпухов: {s_chg_str}\n"
            f"Кашира: {k_chg_str}\n"
            f"Ледовая обстановка: {ice_str}\n"
            f"Прогноз: {f_intens}"
        )

    # Погода
    weather_block = ""
    if wext:
        days        = wext.get("days", [])
        today       = next((d for d in days if not d.get("is_forecast", True)), {})
        tmax        = today.get("tmax", "?")
        tmin        = today.get("tmin", "?")
        precip      = today.get("precip", 0) or 0
        snow        = wext.get("snow_depth_cm", 0) or 0
        fl_label    = wext.get("flood_label", "?")
        fl_index    = wext.get("flood_index", 0)
        fl_summary  = wext.get("flood_summary", "")
        commentary  = wext.get("commentary", [])
        c_lines     = "\n".join(commentary[:2]) if commentary else ""
        weather_block = (
            f"━━ ПОГОДА ━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌡 {tmax}°C / {tmin}°C | 💧{precip:.1f}мм | ❄️ Снег: {snow:.0f} см\n"
            f"📈 Паводковый индекс: <b>{fl_label}</b> ({fl_index}/4)\n"
            f"{fl_summary}\n"
            f"{c_lines}"
        )

    # GloFAS upstream block (NEW v7)
    glofas_block = ""
    if glofas and glofas.get("_status") in ("ok", "partial"):
        glofas_block = "\n📡 Верховья Оки (GloFAS):\n"
        for slug in ["belev", "kaluga", "aleksin", "tarusa"]:
            st = glofas.get(slug, {})
            if st.get("source_status") != "ok":
                continue
            name = st.get("name", slug)
            cur  = st.get("current_discharge")
            fr   = st.get("flood_ratio") or 0
            arr  = (st.get("wave_arrival_serpukhov") or {})
            cur_str = f"{cur:.0f}" if cur is not None else "?"
            arr_str = ""
            if arr:
                e = arr.get("earliest", "")[:10]
                l = arr.get("latest", "")[:10]
                arr_str = f" → волна {e[8:10]}.{e[5:7]}–{l[8:10]}.{l[5:7]}"
            trend_arrow = st.get("trend_arrow", "→")
            glofas_block += f"  {name}: {cur_str} м³/с {trend_arrow} (×{fr:.1f}){arr_str}\n"

    # Прогноз пика
    peak      = analytics.get("peak_prediction", {})
    peak_text = peak.get("trend_text", "Недостаточно данных") if peak else "Недостаточно данных"
    reg       = analytics.get("regression") or (peak.get("regression") if peak else None)
    reg_line  = ""
    if reg and reg.get("r_squared", 0) > 0.6:
        reg_line = f"🤖 ML: {reg.get('trend_text_ml', '')} | R²={reg.get('r_squared', 0):.2f}\n"

    # Пороги
    nya_rem = analytics.get("nya_remaining_m")
    oya_rem = analytics.get("oya_remaining_m")
    nya_str = f"{nya_rem:.2f} м" if nya_rem is not None else "нет данных"
    oya_str = f"{oya_rem:.2f} м" if oya_rem is not None else "нет данных"

    verdict_label = (composite.get("verdict") or {}).get("label", "—")

    return (
        f"🌊 <b>ПАВОДОК ОКА — ПОЛНАЯ СВОДКА {now_date}</b>\n"
        f"🎯 Статус: {verdict_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n📊 <b>СЕРПУХОВ (пост д. Лукьяново)</b>\n"
        f"• Уровень: <b>{level_str}</b> ({abs_str})\n"
        f"• Изменение: <b>{_fmt_delta(change)} см</b> за сутки\n"
        f"• Источник: serpuhov.ru | статус: {src_stat}\n"
        f"\n━━ ДРУГИЕ СТАНЦИИ ━━━━━━━━━━━━━━━━━━\n"
        f"{stations_lines if stations_lines else 'нет данных'}"
        f"\n{cugms_block}\n"
        f"{glofas_block}"
        f"\n{weather_block}\n"
        f"\n━━ ПРОГНОЗ ПИКА ━━━━━━━━━━━━━━━━━━\n"
        f"{peak_text}\n"
        f"{reg_line}"
        f"\n━━ ПОРОГИ ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"До НЯ ({LUKYANNOVO_NYA_M_BS} м БС): {nya_str}\n"
        f"До ОЯ ({LUKYANNOVO_OYA_M_BS} м БС): {oya_str}\n"
        f"\n🔗 https://em-from-pu.github.io/oka-flood-monitor"
    )


def build_neighbors_digest(data: dict, analytics: dict, composite: dict,
                            glofas: dict, now_msk: str) -> str:
    """
    Упрощённый дайджест для соседей.
    v7: добавлен прогноз прихода волны.
    """
    serp   = data.get("serpuhov", {})
    wext   = data.get("weather") or {}
    level  = serp.get("level_cm")
    change = serp.get("daily_change_cm")
    arrow  = _trend(change)

    now_date  = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y")
    level_str = f"{level:.0f} см" if level is not None else "нет данных"

    icon, title, text, _ = generate_action_block(level, (wext or {}).get("flood_index", 0), composite)

    fl_label  = (wext or {}).get("flood_label", "нет данных")
    fl_summary = (wext or {}).get("flood_summary", "")

    nya_rem = analytics.get("nya_remaining_m")
    oya_rem = analytics.get("oya_remaining_m")
    nya_str = f"{nya_rem:.1f} м" if nya_rem is not None else "нет данных"
    oya_str = f"{oya_rem:.1f} м" if oya_rem is not None else "нет данных"

    # Прогноз прихода волны (NEW v7)
    wave_info = calculate_wave_arrival(glofas or {})
    serp_arr  = wave_info.get("serpukhov_arrival", {})
    wave_block = ""
    if serp_arr:
        e     = serp_arr.get("earliest", "")[:10]
        l     = serp_arr.get("latest", "")[:10]
        based = serp_arr.get("based_on", "")

        def _fmt_dd(d):
            return d[8:10] + "." + d[5:7] if len(d) >= 10 else d

        wave_block = (
            f"\n🌊 Прогноз пика в Серпухове: {_fmt_dd(e)}–{_fmt_dd(l)}\n"
            f"   (по данным ст. {based}, GloFAS)\n"
            f"   Жерновка: +6–12 ч от Серпухова\n"
        )

    return (
        f"🌊 <b>ПАВОДОК ОКА — {now_date}</b>\n"
        f"\n📊 Серпухов (д. Лукьяново): <b>{level_str}</b>\n"
        f"{arrow} За сутки: <b>{_fmt_delta(change)} см</b>\n"
        f"\n{icon} <b>{title}</b>\n"
        f"{text}\n"
        f"\n🌡 Погода: {fl_label}\n"
        f"{fl_summary}\n"
        f"\nДо выхода на пойму: {nya_str}\n"
        f"До подтопления НП: {oya_str}\n"
        f"{wave_block}"
        f"\n🔗 Подробнее: https://em-from-pu.github.io/oka-flood-monitor"
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
    """Возвращает полный CSS v7.5 (Light Theme + Inter + 5-level colors)."""
    return """
/* ═══════════════════════════════════════════════════════════════
   OkaFloodMonitor v7.5 Design System — Light Theme
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
  background: radial-gradient(circle at 20% 50%, rgba(186,230,253,0.15) 0%, transparent 50%),
              radial-gradient(circle at 80% 20%, rgba(186,230,253,0.12) 0%, transparent 40%),
              radial-gradient(circle at 50% 80%, rgba(186,230,253,0.10) 0%, transparent 45%);
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
    linear-gradient(180deg, rgba(224,242,254,0.85) 0%, rgba(247,249,252,0.95) 100%),
    url('https://geonovosti.terratech.ru/upload/geonovosti/oka/aft.jpg') center/cover no-repeat;
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
  cursor: help;
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
  cursor: help;
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
  height: 350px;
  width: 100%;
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
.table-wrap { overflow-x: auto; }

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
[data-tooltip] { position: relative; cursor: help; }
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


# ══════════════════════════════════════════════════════════════════════════════
# HTML: HEADER v7
# ══════════════════════════════════════════════════════════════════════════════

def _generate_header_v7(serp: dict, kim: dict, cugms: dict, glofas: dict,
                         now_msk: str) -> str:
    """Генерирует sticky header v7.5 с навигацией, часами, бейджами."""
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

    return f"""
<section class="hero-section">
  <div class="composite-status">

    <div class="hero-main-row">

      <!-- Термометр (левая часть) -->
      <div class="thermometer-col">
        <div class="thermometer-wrap" data-tooltip="\u0412\u0438\u0437\u0443\u0430\u043b\u044c\u043d\u0430\u044f \u0448\u043a\u0430\u043b\u0430: \u043e\u0442 \u043d\u0443\u043b\u044f \u043f\u043e\u0441\u0442\u0430 \u0434\u043e \u041e\u042f">
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
            <div class="therm-mark therm-mark-nya" style="bottom:{therm_nya_pct:.1f}%;"></div>
            <div class="therm-mark therm-mark-oya" style="bottom:{therm_oya_pct:.1f}%;"></div>
            <div class="therm-mark therm-mark-cur" style="bottom:{therm_cur_pct:.1f}%;"></div>
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
      <a class="info-card" href="#weatherAcc">
        <div class="ic-icon">❄️</div>
        <div class="ic-value">{snow_cm:.0f} <span class="ic-unit">см</span></div>
        <div class="ic-title-colored" style="color:{snow_title_color};">Снег у Серпухова</div>
        <div class="ic-hint">глубина снега по Open-Meteo (локально)</div>
      </a>
      <a class="info-card{'  info-card-conflict' if conflict else ''}" href="#cugmsAcc">
        <div class="ic-icon">📈</div>
        <div class="ic-value">{change_3d_str} <span class="ic-unit">см/сут</span></div>
        <div class="ic-title-colored" style="color:{trend_title_color};">Тренд (3 дня) {accel_str}</div>
        <div class="ic-hint">Сейчас: {change_str} см/сут (serpuhov.ru)</div>
        {conflict_html}
      </a>
      <a class="info-card info-card-scenarios" href="#threshAcc">
        <div class="ic-icon">⏳</div>
        <div class="ic-title-colored" style="color:#f59e0b;">Сценарии до НЯ</div>
        <div class="ic-scenarios">{sc_rows}</div>
        <div class="ic-hint">История: пик обычно 1–20 апр. Линейная оценка неприменима.</div>
      </a>
      <a class="info-card" href="#weatherAcc">
        <div class="ic-icon">🌧️</div>
        <div class="ic-value">{fl_idx}/4</div>
        <div class="ic-title-colored" style="color:{weather_title_color};">Паводковый индекс</div>
        <div class="ic-hint">{fl_label_short} — осадки и таяние</div>
      </a>
      <a class="info-card" href="#peakAcc">
        <div class="ic-icon">{phase_icon}</div>
        <div class="ic-value" style="font-size:0.95rem;">{_h(phase_lbl)}</div>
        <div class="ic-title-colored" style="color:{phase_title_color};">Фаза паводка</div>
        <div class="ic-hint">{_h(phase_hint)}</div>
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
    Генерирует Forecast Hydrograph — Chart.js с 2 осями.
    Левая ось: уровень Серпухова (см). Правая: расход GloFAS (м³/с).
    Линии: факт (синяя), GloFAS прогноз (фиолетовая пунктир), 2024 (серая).
    Аннотации: НЯ / ОЯ. Разделитель «СЕЙЧАС».
    ИСПРАВЛЕНИЕ v7: X-ось — HH:MM для свежих, DD.MM для старых.
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
            break

    # Fallback: проекция из тренда истории
    if not glofas_pts and len(hist_pts) >= 3:
        last_val = hist_pts[-1][1]
        last_chg = (hist_pts[-1][1] - hist_pts[-3][1]) / 2 if len(hist_pts) >= 3 else 5
        for i in range(1, 15):
            d = (datetime.now(timezone.utc) + timedelta(days=i)).isoformat()[:10]
            projected = last_val + last_chg * i * (0.85 ** i)
            glofas_pts.append((d, max(projected, 0)))

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

    hist_labels   = json.dumps([p[0] for p in hist_pts])
    hist_values   = json.dumps([p[1] for p in hist_pts])
    glofas_labels = json.dumps([p[0] for p in glofas_pts])
    glofas_values = json.dumps([p[1] for p in glofas_pts])
    ref_labels    = json.dumps([p[0] for p in ref_pts])
    ref_values    = json.dumps([p[1] for p in ref_pts])
    nya_val       = json.dumps(round(nya_cm, 1))
    oya_val       = json.dumps(round(oya_cm, 1))
    today_label   = json.dumps(today_iso[:10])

    return f"""
<section class="hydrograph-section fade-in-section">
  <div class="hydrograph-card">
    <h3>📈 Гидрограф: история + прогноз</h3>
    <div class="chart-container">
      <canvas id="hydrograph"></canvas>
    </div>
  </div>
</section>

<script>
(function() {{
  var ctx = document.getElementById('hydrograph');
  if (!ctx) return;

  var histLabels   = {hist_labels};
  var histValues   = {hist_values};
  var glofasLabels = {glofas_labels};
  var glofasValues = {glofas_values};
  var refLabels    = {ref_labels};
  var refValues    = {ref_values};
  var NYA          = {nya_val};
  var OYA          = {oya_val};
  var todayLabel   = {today_label};

  var allLabels = Array.from(new Set([].concat(histLabels, glofasLabels))).sort();

  function alignValues(labels, dataLabels, dataValues) {{
    return labels.map(function(l) {{
      var idx = dataLabels.indexOf(l);
      return idx >= 0 ? dataValues[idx] : null;
    }});
  }}

  var histAligned   = alignValues(allLabels, histLabels, histValues);
  var glofasAligned = alignValues(allLabels, glofasLabels, glofasValues);
  var refAligned    = refLabels.length ? alignValues(allLabels, refLabels, refValues) : [];

  var nowPlugin = {{
    id: 'nowLine',
    afterDraw: function(chart) {{
      var idx = allLabels.indexOf(todayLabel);
      if (idx < 0) return;
      var x = chart.scales.x.getPixelForValue(idx);
      var ctx2 = chart.ctx;
      var top    = chart.chartArea.top;
      var bottom = chart.chartArea.bottom;
      ctx2.save();
      ctx2.strokeStyle = 'rgba(255,255,255,0.4)';
      ctx2.lineWidth   = 1.5;
      ctx2.setLineDash([6, 4]);
      ctx2.beginPath();
      ctx2.moveTo(x, top);
      ctx2.lineTo(x, bottom);
      ctx2.stroke();
      ctx2.setLineDash([]);
      ctx2.fillStyle = 'rgba(255,255,255,0.6)';
      ctx2.font = '11px Inter, sans-serif';
      ctx2.textAlign = 'center';
      ctx2.fillText('СЕЙЧАС', x, top - 4);
      ctx2.restore();
    }}
  }};

  var datasets = [
    {{
      label: 'Уровень (см) — serpuhov.ru',
      data: histAligned,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      borderWidth: 2.5,
      tension: 0.3,
      fill: true,
      pointRadius: 2,
      spanGaps: false,
    }}
  ];

  if (glofasAligned.some(function(v) {{ return v !== null; }})) {{
    datasets.push({{
      label: 'Прогноз GloFAS (тренд)',
      data: glofasAligned,
      borderColor: '#a855f7',
      backgroundColor: 'transparent',
      borderWidth: 2,
      borderDash: [6, 4],
      tension: 0.3,
      fill: false,
      pointRadius: 1,
      spanGaps: false,
      yAxisID: 'y2',
    }});
  }}

  if (refAligned.length && refAligned.some(function(v) {{ return v !== null; }})) {{
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

  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: allLabels, datasets: datasets }},
    plugins: [nowPlugin],
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
            callback: function(value, index) {{
              var label = allLabels[value];
              if (!label) return '';
              if (label.length > 10) {{
                // ISO datetime: HH:MM для последних 2 дней, DD.MM для старых
                var dt = new Date(label + 'Z');
                var now = new Date();
                var diffDays = (now - dt) / 86400000;
                if (diffDays < 2) {{
                  return String(dt.getUTCHours()).padStart(2,'0') + ':' + String(dt.getUTCMinutes()).padStart(2,'0');
                }} else {{
                  return dt.getUTCDate() + '.' + String(dt.getUTCMonth()+1).padStart(2,'0');
                }}
              }}
              // ISO date: DD.MM
              var parts = label.split('-');
              return parts.length === 3 ? parts[2] + '.' + parts[1] : label;
            }}
          }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
        }},
        y: {{
          position: 'left',
          ticks: {{ color: '#64748b' }},
          grid: {{ color: 'rgba(255,255,255,0.04)' }},
          title: {{ display: true, text: 'Уровень, см', color: '#64748b', font: {{ size: 11 }} }},
        }},
        y2: {{
          position: 'right',
          ticks: {{ color: '#a855f7' }},
          grid: {{ display: false }},
          title: {{ display: true, text: 'Расход, м³/с (GloFAS)', color: '#a855f7', font: {{ size: 11 }} }},
        }},
      }},
    }},
  }});
}})();
</script>"""


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
        ("orel",     False),
        ("mtsensk",  False),
        ("belev",    False),
        ("kaluga",   False),
        ("aleksin",  False),
        ("tarusa",   False),
        ("serpuhov", True),
        ("kashira",  False),
    ]

    WAVE_LABELS = {
        "orel":    "7 дн до Серпухова",
        "mtsensk": "5–6 дн до Серпухова",
        "belev":   "4–5 дн до Серпухова",
        "kaluga":  "2–3 дн до Серпухова",
        "aleksin": "1–2 дн до Серпухова",
        "tarusa":  "0.5–1 дн до Серпухова",
        "serpuhov": "",
        "kashira": "↓ ниже по течению",
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
                val_str   = "нет данных"
                unit_str  = "GloFAS"
                trend_arr = "?"
                fr        = None
                fr_cls    = "fr-unknown"
                fr_label  = "недоступно"
                peak_str  = ""
                sparkline = ""
                src_note  = "GloFAS (недоступно)"

        wave_label = WAVE_LABELS.get(slug, "")

        # v7.3: city page links
        city_href = f"cities/{slug}.html"
        city_tooltip = "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u0430\u044f \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u0433\u043e\u0440\u043e\u0434\u0430 (\u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0435)"

        card_inner = f"""
<div class="{card_classes}">
  <div class="sc-name">{_h(name)}</div>
  <div class="sc-river">{_h(river)}</div>
  <div class="sc-value" style="color: {'var(--accent)' if is_main else 'var(--text-primary)'};">\n    {_h(val_str)}\n  </div>
  <div class="sc-sparkline">{sparkline}</div>
  <div class="sc-trend">
    {_h(trend_arr)}
    <span class="sc-badge {fr_cls}">{_h(fr_label)}</span>
  </div>
  {f'<div class="sc-peak">{_h(peak_str)}</div>' if peak_str else ''}
  {f'<div class="sc-travel">{_h(wave_label)}</div>' if wave_label else ''}
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

    html += '</div>\n</section>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# HTML: WAVE ARRIVAL TIMELINE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_wave_timeline(glofas: dict) -> str:
    """
    v7.3: HYBRID wave timeline.
    1. Simplified horizontal timeline — only green arrival markers for Serpukhov.
    2. Below — detailed table with all stations, peaks and arrivals.
    """
    if not glofas or glofas.get("_status") not in ("ok", "partial", "cached"):
        return ""

    today            = datetime.now(timezone.utc).date()
    end_dt           = today + timedelta(days=16)
    total_range_days = 16

    STATION_ORDER = ["orel", "mtsensk", "belev", "kozelsk", "kaluga", "aleksin", "tarusa"]

    # ── Collect data for table and timeline ────────────────────────────
    rows         = []   # table rows
    arrivals     = []   # timeline markers (arrival events only)

    for slug in STATION_ORDER:
        st = glofas.get(slug, {})
        if not st:
            continue
        name      = st.get("name", slug.capitalize())
        peak_date = st.get("peak_date")
        wave      = st.get("wave_arrival_serpukhov")

        peak_str   = ""
        arr_str    = ""
        to_zhern   = ""
        arr_dt     = None

        if peak_date:
            try:
                pd_obj   = datetime.strptime(peak_date, "%Y-%m-%d").date()
                peak_str = f"{pd_obj.day:02d}.{pd_obj.month:02d}"
            except Exception:
                peak_str = peak_date[:10]

        if wave:
            try:
                arr_dt   = datetime.strptime(wave["earliest"], "%Y-%m-%d").date()
                arr_late = datetime.strptime(wave["latest"],   "%Y-%m-%d").date()
                arr_str  = f"{arr_dt.day:02d}.{arr_dt.month:02d}\u2013{arr_late.day:02d}.{arr_late.month:02d}"
                # Жерновка arrives ~7 hours after Serpukhov → same day or next
                to_zhern = f"~{arr_dt.day:02d}\u2013{(arr_dt + timedelta(days=1)).day:02d}.{arr_dt.month:02d}"
            except Exception:
                arr_str  = wave.get("earliest", "?")[:10]
                to_zhern = ""

        rows.append({
            "name":     name,
            "peak_str": peak_str,
            "arr_str":  arr_str,
            "to_zhern": to_zhern,
            "arr_dt":   arr_dt,
        })

        if arr_dt and today <= arr_dt <= end_dt:
            offset_days = (arr_dt - today).days
            pct = offset_days / total_range_days * 100
            arrivals.append({
                "name":  name,
                "pct":   min(95, max(2, pct)),
                "label": f"{arr_dt.day:02d}.{arr_dt.month:02d}",
                "tooltip": f"{name} \u2192 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432: {arr_str}",
            })

    if not rows:
        return ""

    # ── Horizontal timeline: only arrival markers (green dots) ────────
    # Spread out markers that are very close to avoid text overlap
    arrivals.sort(key=lambda e: e["pct"])
    MIN_GAP_PCT = 6.0  # minimum gap between markers in %
    for i in range(1, len(arrivals)):
        if arrivals[i]["pct"] - arrivals[i - 1]["pct"] < MIN_GAP_PCT:
            arrivals[i]["pct"] = arrivals[i - 1]["pct"] + MIN_GAP_PCT

    markers_html = ""
    for idx, ev in enumerate(arrivals):
        # Alternate label above/below to reduce overlap
        if idx % 2 == 0:
            label_pos = "bottom: 24px;"
            name_pos  = "bottom: 40px;"
        else:
            label_pos = "top: 24px;"
            name_pos  = "top: 40px;"
        tip = ev["tooltip"]
        markers_html += f"""
<div class="timeline-marker" style="left:{ev['pct']:.1f}%;" data-tooltip="{_h(tip)}">
  <div class="timeline-dot" style="width:14px; height:14px;
    border-color:#10b981; background:#10b981;"></div>
  <div style="position:absolute; {label_pos} font-size:0.63rem;
    white-space:nowrap; color:#10b981; text-align:center;
    transform:translateX(-50%); left:50%;">{_h(ev['label'])}</div>
  <div style="position:absolute; {name_pos} font-size:0.58rem;
    white-space:nowrap; color:var(--text-dim); text-align:center;
    transform:translateX(-50%); left:50%;">{_h(ev['name'])}</div>
</div>"""

    date_labels = ""
    for i in [0, 4, 8, 12, 16]:
        d   = today + timedelta(days=i)
        pct = i / total_range_days * 100
        date_labels += f"""
<div style="position:absolute; left:{pct:.1f}%; transform:translateX(-50%);
  font-size:0.62rem; color:var(--text-dim); bottom:-50px; white-space:nowrap;">
  {d.day:02d}.{d.month:02d}
</div>"""

    # ── Table rows HTML ───────────────────────────────────────────────
    table_rows_html = ""
    for row in rows:
        peak_disp  = _h(row["peak_str"])  if row["peak_str"]  else '<span style="color:var(--text-dim)">—</span>'
        arr_disp   = _h(row["arr_str"])   if row["arr_str"]   else '<span style="color:var(--text-dim)">—</span>'
        zhern_disp = _h(row["to_zhern"]) if row["to_zhern"] else '<span style="color:var(--text-dim)">—</span>'
        table_rows_html += f"""
<tr>
  <td class="col-station">{_h(row['name'])}</td>
  <td>{peak_disp}</td>
  <td class="col-arrival">{arr_disp}</td>
  <td style="color:var(--text-dim);">{zhern_disp}</td>
</tr>"""

    timeline_part = ""
    if arrivals:
        timeline_part = f"""
    <div class="timeline-bar-container" style="padding: 70px 20px 80px; overflow-x:auto;">
      <div class="timeline-track" style="position:relative; min-width:600px;">
        {markers_html}
        {date_labels}
      </div>
    </div>
    <p style="font-size:0.75rem; color:var(--text-dim); margin-top:8px; margin-bottom:12px;">
      \U0001f7e2 \u0437\u0435\u043b\u0451\u043d\u044b\u0435 \u043c\u0430\u0440\u043a\u0435\u0440\u044b = \u0440\u0430\u0441\u0447\u0451\u0442\u043d\u043e\u0435 \u043f\u0440\u0438\u0431\u044b\u0442\u0438\u0435 \u0432\u043e\u043b\u043d\u044b \u0432 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432. \u041d\u0430\u0432\u0435\u0434\u0438\u0442\u0435 \u0434\u043b\u044f \u0434\u0435\u0442\u0430\u043b\u0435\u0439.
    </p>"""

    return f"""
<section class="timeline-section fade-in-section">
  <div class="timeline-card">
    <h3>\u23f1 \u041f\u0440\u043e\u0433\u043d\u043e\u0437 \u043f\u0440\u0438\u0445\u043e\u0434\u0430 \u0432\u043e\u043b\u043d\u044b \u0432 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432</h3>
    {timeline_part}
    <table class="wave-table">
      <thead>
        <tr>
          <th>\u0421\u0442\u0430\u043d\u0446\u0438\u044f</th>
          <th>\u041f\u0438\u043a \u043d\u0430 \u0441\u0442\u0430\u043d\u0446\u0438\u0438</th>
          <th>\u041f\u0440\u0438\u0431\u044b\u0442\u0438\u0435 \u0432 \u0421\u0435\u0440\u043f\u0443\u0445\u043e\u0432</th>
          <th>\u0414\u043e \u0416\u0435\u0440\u043d\u043e\u0432\u043a\u0438</th>
        </tr>
      </thead>
      <tbody>
        {table_rows_html}
      </tbody>
    </table>
    <p style="font-size:0.72rem; color:var(--text-dim); margin-top:8px;">
      \u0414\u0430\u043d\u043d\u044b\u0435 GloFAS Flood API. \u0412\u0440\u0435\u043c\u044f \u0434\u043e\u0445\u043e\u0434\u0430 \u0432\u043e\u043b\u043d\u044b \u2014 \u043e\u0446\u0435\u043d\u043e\u0447\u043d\u043e, \u043f\u043e\u0433\u0440\u0435\u0448\u043d\u043e\u0441\u0442\u044c \xb11\u20132 \u0434\u043d\u044f.
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

def _generate_weather_section(wext) -> str:
    """Генерирует секцию погоды с glassmorphism стилем."""
    if not wext:
        return ""

    fl_idx     = wext.get("flood_index", 0)
    fl_label   = _h(wext.get("flood_label", "?"))
    fl_summary = _h(wext.get("flood_summary", ""))
    fl_colors  = {0: "#10b981", 1: "#10b981", 2: "#f59e0b", 3: "#f97316", 4: "#ef4444"}
    fl_color   = fl_colors.get(fl_idx, "#64748b")
    snow_d     = wext.get("snow_depth_cm", 0) or 0

    flood_index_block = f"""
<div class="weather-flood-index" style="border-left-color:{fl_color};">
  <div>
    <span class="wfi-label">Паводковый индекс погоды (0–4)</span>
    <span class="wfi-value" style="color:{fl_color};">{fl_label} ({fl_idx}/4)</span>
  </div>
  <div class="wfi-summary">{fl_summary}</div>
  <div style="font-size:0.82rem; color:var(--text-dim);">Глубина снега (локально): {snow_d:.0f} см — глубина снежного покрова по Open-Meteo (не SWE)</div>
</div>"""

    weather_table_html = _generate_weather_table(wext)

    commentary = wext.get("commentary", [])
    commentary_html = ""
    if commentary:
        items = "\n".join(f"<li style='padding:4px 0; color:var(--text-secondary); font-size:0.88rem;'>{_h(c)}</li>" for c in commentary)
        commentary_html = f"""
<div style="margin-top:12px;">
  <div style="font-size:0.85rem; font-weight:600; color:var(--text-secondary); margin-bottom:6px;">📝 Аналитика погодных факторов</div>
  <ul style="list-style:none; padding:0;">{items}</ul>
</div>"""

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

    nya_status = thresh_status(LUKYANNOVO_NYA_M_BS, abs_bs)
    oya_status = thresh_status(LUKYANNOVO_OYA_M_BS, abs_bs)
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
      <tr class="row-current">
        <td><b>Текущий</b></td><td><b>{serp_abs_str}</b></td>
        <td>Прямо сейчас</td><td><b>{_h(cur_status)}</b></td>
      </tr>
    </tbody>
  </table>
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

    return f"""
<div class="peak-trend" style="color: {trend_color}; border-left-color: {trend_color};">
  {trend_text}
</div>
{reg_block}
<p class="disclaimer-small">⚠️ {disclaimer}</p>"""


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
    """v7.5: Автосканирует reports/ папку для PDF файлов. Сортирует по дате в имени."""
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
    """Генерирует footer v7.5."""
    return f"""
<footer class="site-footer">
  OkaFloodMonitor v7.5 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
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
      <span style="font-size:0.82rem; color:var(--accent); white-space:nowrap;">Полная история паводков →</span>
    </div>
    <div class="hist-peaks-bar">{bars_html}</div>
    <div style="font-size:0.75rem; color:var(--text-dim); text-align:center; margin-top:4px;">
      Ока, как и положено великой реке, не любит спешить — но когда решается, удивляет даже бывалых.
    </div>
  </div>
  </a>
</section>"""


def generate_html(data: dict, analytics: dict, history: list, wext,
                  regression, ref_2024) -> str:
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
    action_html       = _generate_action_section(action_icon, action_title, action_text, action_color)
    weather_html      = _generate_weather_section(wext)
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
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js"></script>
  <style>{css}</style>
</head>
<body>

{header_html}

<div id="stale-banner" class="stale-banner" style="display:none;">
  ⚠️ Данные устарели. Автоматическое обновление может быть нарушено.
  Последнее обновление: <span id="stale-time"></span>
</div>

<main>
  {hero_html}

  <div class="fade-in-section">
    {hydrograph_html}
  </div>

  {station_cards_html}

  {timeline_html}

  <div class="fade-in-section">
    {action_html}
  </div>

  {weather_html}

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
    """CSS для страниц links и instructions — использует базовый дизайн v7.5 light."""
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
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
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
  <p>Весной 1970&nbsp;года советский Орёл готовился к 100-летию со дня рождения Ленина.
  Первомайские транспаранты уже печатали, речи репетировали, концертные программы
  утверждали. Ока, однако, о юбилее не слышала — у неё было своё расписание.</p>

  <p><b>5&nbsp;апреля 1970&nbsp;года</b> вода в Орле перевалила за <b>10&nbsp;метров</b> (1010&nbsp;см),
  установив абсолютный рекорд для города. По улицам пошёл лёд с Оки. В городе ввели
  чрезвычайное положение. Орловский обком КПСС написал в ЦК письмо — просил отменить
  праздничные мероприятия. ЦК ответил уже после того, как торжества прошли. Водная стихия
  оказалась более оперативной, чем советская бюрократия.</p>

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

  <table class="hist-table">
    <thead><tr><th>Гидропост</th><th>Уровень</th><th>Порог НЯ</th><th>Примечания</th></tr></thead>
    <tbody>
      <tr><td>Белёв</td><td>~1250&nbsp;см*</td><td>1155&nbsp;см</td><td>Предполагаемый абсолютный рекорд у Белёва</td></tr>
      <tr><td>Алексин (Щукина)</td><td>~1155&nbsp;см</td><td>1120&nbsp;см</td><td>НЯ превышен</td></tr>
      <tr><td>Орёл</td><td>935&nbsp;см</td><td>880&nbsp;см</td><td>29 улиц, 654 дома, 2 школы</td></tr>
      <tr><td>Орёл — зона затопления</td><td>—</td><td>—</td><td>3120 человек в зоне затопления, эвакуировано 65</td></tr>
    </tbody>
  </table>

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
  <p>2024&nbsp;год переписал рекордную книгу XXI&nbsp;века для Серпухова. Уровень достиг
  <b>~850&nbsp;см</b> — побив рекорд 2013&nbsp;года (843&nbsp;см). Официально подтверждено
  главой Серпуховского округа Алексеем Шимко: «В 2024 году паводок достиг максимальной
  отметки в 850&nbsp;см, но благодаря заблаговременной подготовке последствия удалось
  минимизировать без происшествий».</p>

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
  <table class="hist-table">
    <thead><tr><th>Место</th><th>Прирост</th><th>Дата</th></tr></thead>
    <tbody>
      <tr><td>Ранова у с. Троица</td><td>+108&nbsp;см/сутки</td><td>30 марта 2024</td></tr>
      <tr><td>Калуга</td><td>+132&nbsp;см/сутки</td><td>27 марта 2024</td></tr>
      <tr><td>Серпухов</td><td>+39&nbsp;см/сутки</td><td>март 2023</td></tr>
      <tr><td>Луховицкий р-н (2026)</td><td>+75&nbsp;см за 2 суток</td><td>март 2026</td></tr>
    </tbody>
  </table>

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
  OkaFloodMonitor v7.3 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
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
        "main":         (f"{p}index.html",        "Главная"),
        "cities":       (f"{p}cities/index.html", "Города"),
        "history":      (f"{p}history.html",       "История паводков"),
        "guide":        (f"{p}flood-guide.html",   "Физика половодья"),
        "links":        (f"{p}links.html",         "Ссылки"),
        "instructions": (f"{p}instructions.html",  "Инструкции"),
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
    for key, (href, label) in nav_items.items():
        cls = ' class="active"' if key == current_page else ""
        dd = dd_map.get(key, "")
        if dd:
            nav_html += f"""
      <li>{dd}
        <a href="{href}"{cls}>{label} <span style="font-size:0.7rem;opacity:0.6;">▾</span></a>
      </li>"""
        else:
            nav_html += f"""
      <li><a href="{href}"{cls}>{label}</a></li>"""

    # Mobile nav items (flat)
    mobile_html = ""
    for key, (href, label) in nav_items.items():
        cls = ' class="active"' if key == current_page else ""
        mobile_html += f'<a href="{href}"{cls}>{label}</a>'

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
    """Генерирует SVG-карту реки Ока с городами v7.5."""
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
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
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
  OkaFloodMonitor v7.5 | Города на Оке | <a href="../index.html">← На главную</a><br>
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
  <h1 style="font-size:2.5rem; font-weight:800; letter-spacing:-0.04em; margin-bottom:10px;">{_h(name)}</h1>
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
<table class="flood-table">
  <thead><tr><th>Уровень</th><th>Значение</th></tr></thead>
  <tbody>{crit_rows}</tbody>
</table>"""

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
  <p>Для {_h(name)} отдельной станции GloFAS нет.
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
  <table class="flood-table">
    <thead><tr><th>Год</th><th>Уровень</th><th>Последствия</th></tr></thead>
    <tbody>{flood_rows}</tbody>
  </table>
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
  <link rel="icon" href="../favicon.svg" type="image/svg+xml">
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
  OkaFloodMonitor v7.2 | {_h(name)}, {_h(river)}<br>
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
      <p>
        Расстояние от Орла до Серпухова по руслу Оки — около 550 км. До Коломны — примерно 700 км.
        Это не трасса М2, а извилистая равнинная река с широкой поймой.
      </p>
      <h3>Типичный временно́й диапазон</h3>
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
          — актуальные уровни на всех постах, графики за прошлые годы</li>
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
      <p>
        В России паводковые уровни делятся на несколько категорий, и это не просто бюрократическая
        классификация — за ними стоят конкретные действия властей и конкретные последствия для жителей.
      </p>

      <h3>Система уровней</h3>
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
      <div class="guide-blockquote">
        Если кто-то говорит «в прошлый раз вода до нас не дошла» — уточните, какой именно год он имеет
        в виду. 1970-й по сей день стоит маяком, и не зря.
      </div>
    </div>

    <!-- SECTION 8 -->
    <div class="guide-section" id="s8">
      <h2><span class="section-number">8</span>Кузьминский и Белоомутский гидроузлы: плотины, которые не спасают от паводка</h2>
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
      <table class="guide-summary-table">
        <thead>
          <tr><th>Вопрос</th><th>Ответ</th></tr>
        </thead>
        <tbody>
          <tr><td>Что такое паводочная волна?</td><td>Гребень повышенного уровня, движущийся вниз по реке медленно и плавно</td></tr>
          <tr><td>Скорость волны на Оке?</td><td>40–80 км/сутки (7–14 дней от Орла до Серпухова)</td></tr>
          <tr><td>Почему бывает несколько волн?</td><td>Разновременное таяние, дожди, сбросы с плотин, ледовые заторы</td></tr>
          <tr><td>Главный фактор высоты паводка?</td><td>Запасы воды в снеге + промёрзлость грунта</td></tr>
          <tr><td>Как следить за уровнем?</td><td>allrivers.info, сайт регионального МЧС, ЕСИМО</td></tr>
          <tr><td>НЯ — что делать?</td><td>Готовиться к эвакуации, следить за обстановкой каждые 2 часа</td></tr>
          <tr><td>ОЯ — что делать?</td><td>Эвакуироваться немедленно</td></tr>
          <tr><td>Помогут ли плотины Белоомут/Кузьминск?</td><td>Нет — они для судоходства, не для защиты от паводка</td></tr>
          <tr><td>Когда оформлять страховку?</td><td>Осенью или в начале зимы — до паводкового сезона</td></tr>
        </tbody>
      </table>
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
        <li><a href="https://allrivers.info/river/oka" style="color:var(--accent);">Allrivers.info: река Ока</a> — гидропосты, уровни, история наблюдений</li>
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
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
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
  OkaFloodMonitor v7.2 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
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
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
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
  <table class="action-table">
    <tr><th>Уровень (см)</th><th>Статус</th><th>Рекомендации</th></tr>
    <tr><td>&lt; {ZONE_GREEN_MAX}</td><td>🟢 НОРМА</td><td style="color:var(--text-secondary);">Следите за динамикой. Обновления 4 раза в день.</td></tr>
    <tr><td>{ZONE_GREEN_MAX}–{ZONE_YELLOW_MAX}</td><td>🟡 ВНИМАНИЕ</td><td style="color:var(--text-secondary);">Проверьте участок. Уберите ценности с низких мест.</td></tr>
    <tr><td>{ZONE_YELLOW_MAX}–{ZONE_ORANGE_MAX}</td><td>🟠 ОПАСНОСТЬ</td><td style="color:var(--text-secondary);">Подготовьтесь к эвакуации. Насосы наготове.</td></tr>
    <tr><td>&gt; {ZONE_ORANGE_MAX}</td><td>🔴 КРИТИЧНО</td><td style="color:var(--text-secondary);">Немедленно вывезите ценные вещи. Звоните 112.</td></tr>
  </table>
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

  <h3 style="color:var(--text-primary); margin:16px 0 8px;">Как подключиться</h3>
  <p style="color:var(--text-secondary);">В настоящее время уведомления рассылаются по закрытому списку подписчиков.
  Чтобы попасть в список, напишите администратору в Telegram — ссылка будет добавлена на сайт.
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
      >🚨 АЛЕРТ: Уровень превысил порог ОПАСНОСТИ
Серпухов (пост Лукьяново): 603 см
Порог ОЯ (800 см) — ещё 197 см до опасного явления
Динамика: +47 см за последние 24 часа
Рекомендация: готовьтесь к эвакуации ценных вещей</span>
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
  OkaFloodMonitor v7.2 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
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
        f"OkaFloodMonitor v7.2 START"
    )

    # ─── 1. ДАННЫЕ ───────────────────────────────────────────────────────────
    data   = fetch_all_data()
    wext   = data.get("weather") or {}
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})

    # v7.5: при timeout погоды — подгружаем кеш из latest.json
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

    # ─── 6. HTML ГЕНЕРАЦИЯ ──────────────────────────────────────────────────
    html_content = generate_html(data, analytics, history, wext, regression, ref_2024)
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
    git_push()

    print(
        f"✅ OkaFloodMonitor v7.5 DONE | Серпухов: {serp.get('level_cm')} см | "
        f"Статус: {verdict_label} | "
        f"Источники OK: {data.get('sources_ok')}"
    )


if __name__ == "__main__":
    main()
