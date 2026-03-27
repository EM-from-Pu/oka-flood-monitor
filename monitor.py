#!/usr/bin/env python3
# =============================================================================
# OkaFloodMonitor v5.0  —  27.03.2026
# ПОЛНАЯ ЧИСТАЯ ПЕРЕПИСКА (clean rewrite, не патч!)
#
# Структура:
#   1. CONFIG + CONSTANTS
#   2. fetch_all_levels()          — через fetch_module.py (GOLDEN)
#   3. fetch_weather()             — OWM → Open-Meteo fallback
#   4. fetch_weather_extended()    — Open-Meteo 8-day (4 past + 4 forecast)
#   5. 6 анализаторов погоды       — ROS, snow, frost, tmin, warm, precip
#   6. compute_weather_flood_index() — паводковый индекс 0-4
#   7. generate_weather_commentary() — сводка ≤4 строки
#   8. history I/O                 — load/save CSV
#   9. alerts dedup                — load/save/should_send
#  10. 2024 reference              — load_2024_ref, get_2024_value
#  11. compute_analytics()         — дельты, сценарии, insights
#  12. format helpers              — fmt_delta, trend, dist, wind_dir_str
#  13. check_kim_triggers()        — KIM threshold alerts
#  14. tg_send()                   — Telegram API
#  15. format_heartbeat()          — краткая сводка (+ wext)
#  16. format_digest()             — полный дайджест (+ wext)
#  16a. format_neighbors_digest()  — НОВОЕ: упрощённый для соседей
#  17. format_group_draft()        — ПЕРЕПИСАН: от первого лица Егора (+ wext)
#  18. generate_action_block()     — НОВОЕ: рекомендации для жителей
#  19. compute_simple_regression() — НОВОЕ: ML-прогноз (чистый Python)
#  20. generate_chart_js_block()   — НОВОЕ: Chart.js график
#  21. load_mailing_list()         — НОВОЕ: динамическая рассылка
#  22. generate_html()             — ПОЛНАЯ HTML-страница (13 блоков + CSS)
#  23. main()                      — orchestrator
#
# NO-GO:
#   - НЕ трогаем fetch_module.py, fetch_report.py, fetch_2024.py, monitor.yml
#   - НЕ используем assert/str.replace для патчей
#   - snow_depth_max (метры → *100 = см) — единственный рабочий daily-параметр
#   - alerts_sent.json → data/ (не docs/)
#   - PDF URL: reports/{filename} (не reports/reports/)
# =============================================================================

import os
import json
import csv
import math
import requests
from datetime import datetime, timedelta, timezone

# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONFIG + CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

TG_TOKEN       = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN     = os.environ.get("TG_CHAT_ID", "49747475")
CHAT_MY_GROUP  = os.environ.get("TG_GROUP_ID", "-5234360275")
CHAT_NEIGHBORS = os.environ.get("TG_NEIGHBORS_ID", "")
OWM_KEY        = os.environ.get("WEATHER_API_KEY", "")

# Координаты поста Серпухов
SERP_LAT, SERP_LON = 54.834050, 37.742901

# KIM-пороги Серпухов (см)
CRITICAL_LEVEL = 945   # Дом под угрозой
PEAK_2024      = 920   # Пик 2024
PODTOP_LEVEL   = 800   # Критический — дачи затапливает
POYMA_LEVEL    = 645   # Опасный — пойма
NORM_LEVEL     = 500   # Выше нормы

KIM_THRESHOLDS = [500, 645, 800, 920, 945, 965]
KIM_EMOJI = {500: "🟡", 645: "🟠", 800: "🔴", 920: "🆘", 945: "💀", 965: "⚫"}
KIM_LABEL = {
    500: "L1 выше нормы",
    645: "L2 опасный (пойма)",
    800: "L3 критический (дачи)",
    920: "L4 уровень 2024",
    945: "L5 ДОМ ПОД УГРОЗОЙ",
    965: "L6 подвал залит",
}

# ─── Пути ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_DIR     = os.path.join(BASE_DIR, "data")
DOCS_DIR     = os.path.join(BASE_DIR, "docs")
HISTORY_FILE = os.path.join(DATA_DIR, "history.csv")
REF_2024     = os.path.join(DATA_DIR, "2024_ref.json")
DATA_JSON    = os.path.join(DOCS_DIR, "data.json")
INDEX_HTML   = os.path.join(DOCS_DIR, "index.html")
GROUP_DRAFT  = os.path.join(DOCS_DIR, "group_draft.txt")
STATUS_FILE  = os.path.join(DOCS_DIR, "status.txt")
ALERTS_FILE  = os.path.join(DATA_DIR, "alerts_sent.json")
MAILING_LIST = os.path.join(DATA_DIR, "mailing_list.json")  # НОВОЕ v5

# Притоки (B4) — заглушка, заполняется вручную если найдены на fishingsib.ru
EXTRA_STATIONS = {
    # "nara": {"url": "https://...", "name": "Нара (Серпухов)"},
    # "protva": {"url": "https://...", "name": "Протва (Обнинск)"},
}

# Колонки CSV (v5 = v4.2 + 2 новых)
HISTORY_COLS = [
    "datetime",
    "orel", "belev", "kaluga", "shukina", "serpukhov", "kashira", "kolomna",
    "delta_serp_24h", "delta_serp_48h", "delta_orel_24h", "delta_kaluga_24h",
    "temp", "humidity", "wind_ms", "wind_dir", "clouds", "precip_mm",
    "alert_level", "forecast_days_to_945", "forecast_days_to_peak",
    "scenario_base_peak", "scenario_base_date", "notes",
    "snow_depth_cm", "flood_weather_index",
]

SLUG_NAMES = {
    "orel": "Орёл", "belev": "Белёв", "kaluga": "Калуга",
    "shukina": "Щукина/Алексин",
    "serpukhov": "Серпухов", "kashira": "Кашира", "kolomna": "Коломна",
}
STATION_KEYS = ["orel", "belev", "kaluga", "shukina", "serpukhov", "kashira", "kolomna"]

# SLUG_LAG — fallback если fetch_module недоступен
_SLUG_LAG_FALLBACK = {
    "orel": 96, "belev": 72, "kaluga": 48, "shukina": 24,
    "serpukhov": 0, "kashira": -12, "kolomna": -24,
}

# Попытка вычислить из fetch_module.STATIONS
try:
    from fetch_module import STATIONS as _FM_STATIONS
    SLUG_LAG = {
        s["slug"].replace("oka-", "").replace("serpuhov", "serpukhov"): s["lag_h"]
        for s in _FM_STATIONS
    }
    SLUG_LAG["shukina"] = SLUG_LAG.pop("shukina", 24)  # fix oka-shukina → shukina
except Exception:
    SLUG_LAG = _SLUG_LAG_FALLBACK

# Alert colors/emojis
ALERT_EMOJI = {
    "GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠",
    "RED": "🔴", "CRITICAL": "🆘", "UNKNOWN": "⚪",
}
ALERT_COLOR = {
    "GREEN": "#27ae60", "YELLOW": "#f39c12", "ORANGE": "#e67e22",
    "RED": "#c0392b", "CRITICAL": "#8e0000", "UNKNOWN": "#7f8c8d",
}


def printf(fmt, *a):
    """Удобный принт с форматированием."""
    print(fmt % a if a else fmt)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FETCH ALL LEVELS (через fetch_module.py — GOLDEN v3.0)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_all_levels():
    """Получает уровни 7 станций через fetch_module.fetch_level (fishingsib.ru)."""
    try:
        from fetch_module import fetch_level as fish_fetch, STATIONS
    except ImportError:
        printf("WARNING: fetch_module not found, using stub")
        return {k: None for k in STATION_KEYS}

    printf("OkaMonitor v5.0 | %d станций fishingsib…", len(STATIONS))
    levels = {}
    for st in STATIONS:
        slug_key = st["slug"].replace("oka-", "").replace("serpuhov", "serpukhov")
        url = f"https://allrivers.info/gauge/{st['slug']}"
        val = fish_fetch(url, st["name"])
        levels[slug_key] = val
        printf("  %s → %s", st["name"], val)
    printf("levels: %s", levels)
    return levels


def fetch_extra_levels():
    """Получает уровни притоков (Нара, Протва) если настроены."""
    result = {}
    for slug, info in EXTRA_STATIONS.items():
        try:
            from fetch_module import fetch_level as fish_fetch
            val = fish_fetch(info["url"], info["name"])
            result[slug] = val
        except Exception as e:
            printf("extra fetch %s: %s", slug, e)
            result[slug] = None
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FETCH WEATHER (OWM → Open-Meteo fallback, базовый блок)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_weather():
    """Текущая погода: OWM (приоритет) или Open-Meteo (fallback)."""
    printf("fetch_weather…")

    # Попытка OWM
    if OWM_KEY:
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={
                    "lat": SERP_LAT, "lon": SERP_LON,
                    "appid": OWM_KEY, "units": "metric", "lang": "ru",
                },
                timeout=12,
            )
            if r.status_code == 200:
                d = r.json()
                return dict(
                    temp=round(d["main"]["temp"], 1),
                    humidity=d["main"]["humidity"],
                    wind_ms=round(d["wind"]["speed"], 1),
                    wind_dir=d["wind"].get("deg", 0),
                    clouds=d["clouds"]["all"],
                    precip_mm=round(
                        d.get("rain", {}).get("1h", 0) +
                        d.get("snow", {}).get("1h", 0), 1
                    ),
                    weather=d["weather"][0]["description"],
                )
        except Exception as e:
            printf("OWM err: %s", e)

    # Open-Meteo fallback
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=[
                ("latitude", SERP_LAT), ("longitude", SERP_LON),
                ("current_weather", "true"),
                ("daily", "temperature_2m_max"), ("daily", "temperature_2m_min"),
                ("daily", "precipitation_sum"),
                ("daily", "wind_speed_10m_max"),
                ("hourly", "relative_humidity_2m"),
                ("forecast_days", 2), ("timezone", "Europe/Moscow"),
            ],
            timeout=12,
        )
        if r.status_code == 200:
            d = r.json()
            cw = d.get("current_weather", {})
            daily = d.get("daily", {})
            hourly = d.get("hourly", {})
            return dict(
                temp=cw.get("temperature"),
                humidity=(hourly.get("relative_humidity_2m") or [None])[0],
                wind_ms=cw.get("windspeed"),
                wind_dir=cw.get("winddirection", 0),
                clouds=None,
                precip_mm=(daily.get("precipitation_sum") or [None])[0],
                weather="Open-Meteo",
                temp_max=(daily.get("temperature_2m_max") or [None])[0],
                temp_min=(daily.get("temperature_2m_min") or [None])[0],
                wind_max=(daily.get("wind_speed_10m_max") or [None])[0],
            )
    except Exception as e:
        printf("OpenMeteo err: %s", e)

    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FETCH WEATHER EXTENDED (Open-Meteo 8-day)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_weather_extended():
    """
    Open-Meteo Forecast API: 4 прошлых дня + сегодня + 3 дня вперёд.
    ВАЖНО: параметр snow_depth_max (НЕ snow_depth!) — Open-Meteo daily API
    не поддерживает snow_depth, только snow_depth_max.
    Возвращается в МЕТРАХ → умножаем на 100 = сантиметры.
    """
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=[
                ("latitude", SERP_LAT),
                ("longitude", SERP_LON),
                ("daily", "temperature_2m_max"),
                ("daily", "temperature_2m_min"),
                ("daily", "precipitation_sum"),
                ("daily", "rain_sum"),
                ("daily", "snowfall_sum"),
                ("daily", "snow_depth_max"),         # ← МЕТРЫ, *100 = см
                ("daily", "wind_speed_10m_max"),
                ("daily", "weather_code"),
                ("past_days", 4),
                ("forecast_days", 4),
                ("timezone", "Europe/Moscow"),
                ("wind_speed_unit", "ms"),
            ],
            timeout=12,
        )
        r.raise_for_status()
        d = r.json()
        daily = d.get("daily", {})
        dates = daily.get("time", [])
        today = datetime.now().date().isoformat()

        days = []
        for i, date_str in enumerate(dates):
            snow_raw = daily.get("snow_depth_max", [None] * len(dates))[i]
            days.append({
                "date":          date_str,
                "is_forecast":   date_str > today,
                "tmax":          daily["temperature_2m_max"][i],
                "tmin":          daily["temperature_2m_min"][i],
                "precip":        daily["precipitation_sum"][i] or 0,
                "rain_sum":      daily["rain_sum"][i] or 0,
                "snowfall_cm":   daily["snowfall_sum"][i] or 0,
                "snow_depth_cm": round((snow_raw or 0) * 100, 1),  # метры → см
                "wind_ms":       daily["wind_speed_10m_max"][i],
                "weather_code":  daily["weather_code"][i],
            })

        # Последний фактический день → snow_depth_cm
        past_days_list = [dd for dd in days if not dd["is_forecast"]]
        snow_depth_cm = past_days_list[-1]["snow_depth_cm"] if past_days_list else 0

        flood_level, flood_label, flood_color, flood_summary = \
            compute_weather_flood_index(days, snow_depth_cm)
        commentary = generate_weather_commentary(days, snow_depth_cm)

        return {
            "days":          days,
            "snow_depth_cm": snow_depth_cm,
            "flood_index":   flood_level,
            "flood_label":   flood_label,
            "flood_color":   flood_color,
            "flood_summary": flood_summary,
            "commentary":    commentary,
        }
    except Exception as e:
        printf("fetch_weather_extended: %s", e)
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ШЕСТЬ АНАЛИЗАТОРОВ ПОГОДЫ
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_ros(days, snow_depth_cm):
    """Rain-on-Snow: дождь на снег при плюсе — максимальный фактор паводка."""
    for i, day in enumerate(days[4:], 1):
        rain = day.get("rain_sum", 0) or 0
        tmax = day.get("tmax", 0) or 0
        if rain >= 5 and tmax > 0 and snow_depth_cm >= 3:
            return [
                f"⚠️ ОПАСНО: через {i} дн. дождь ({rain:.0f}мм) при +{tmax:.0f}°C "
                f"на снег ({snow_depth_cm:.0f}см) — Rain-on-Snow, максимальный риск!"
            ]
        elif rain >= 2 and tmax > 0 and snow_depth_cm >= 1:
            return [
                f"🟡 Через {i} дн. умеренный дождь ({rain:.0f}мм) при плюсе "
                f"— дополнительная нагрузка на реку."
            ]
    return []


def analyze_snow_depth(days):
    """Анализ снежного покрова и его динамики за 4 дня."""
    depths = [d["snow_depth_cm"] for d in days[:4] if d.get("snow_depth_cm") is not None]
    if not depths:
        return ["❓ Данные о снежном покрове недоступны."]
    c = depths[-1]
    delta = c - depths[0] if len(depths) > 1 else 0
    if c < 1:
        return ["✅ Снежный покров исчез — талые воды уже не добавятся."]
    if c < 5:
        return [f"🔵 Снежный покров минимальный ({c:.0f} см) — растает за 1–2 дня тепла."]
    if c < 15:
        return [f"❄️ Снежный покров: {c:.0f} см (Δ4 дня: {delta:+.0f} см). Прогноз — постепенное таяние."]
    return [
        f"⚠️ Значительный снежный покров: {c:.0f} см (Δ4 дня: {delta:+.0f} см) — "
        f"серьёзный вклад в паводок при потеплении. РИСК ПАВОДКА."
    ]


def analyze_frost_nights(days):
    """Анализ ночных заморозков (прошлые 4 + будущие 4 дня)."""
    fp = sum(1 for d in days[:4] if (d.get("tmin") or 0) < 0)
    ff = sum(1 for d in days[4:] if (d.get("tmin") or 0) < 0)
    if ff >= 2:
        return [f"❄️ Прогноз: {ff} ночи с морозом — сдерживает таяние, рост уровня притормозит."]
    if ff == 1:
        return ["❄️ Одна морозная ночь в прогнозе — неустойчивая ситуация, кратковременное замедление."]
    if fp >= 2:
        return [f"🌡 Последние ночи с морозом ({fp}/4), прогноз — потепление: таяние ускорится."]
    return ["🌡 Все ночи тёплые — снег тает круглосуточно, таяние ускоряется."]


def analyze_tmin_trend(days):
    """Тренд Tmin за прогнозные дни."""
    tmins = [d["tmin"] for d in days[4:] if d.get("tmin") is not None]
    if len(tmins) < 2:
        return []
    tr = tmins[-1] - tmins[0]
    avg = sum(tmins) / len(tmins)
    if tr > 3 and avg > 0:
        return [f"📈 Ночи теплеют (+{tr:.0f}°C за прогноз), выше нуля — ускорение таяния."]
    if tr > 3 and avg < 0:
        return [f"📈 Ночи теплеют (+{tr:.0f}°C за прогноз), рост к нулю — скоро ускорение таяния."]
    if tr < -3:
        return [f"📉 Резкое похолодание ночью ({tr:.0f}°C за прогноз) — замедление таяния."]
    if avg > 0:
        return ["🌡 Ночные температуры устойчиво выше нуля — снег тает круглосуточно."]
    if avg < 0:
        return ["🌡 Ночные температуры устойчиво ниже нуля — заморозки, таяние только днём."]
    return []


def analyze_warm_days(days):
    """Серии Tmax > 10°C — затяжная оттепель."""
    # Считаем подряд горячих дней в прошлом (с конца)
    sp = 0
    for d in reversed(days[:4]):
        if (d.get("tmax") or 0) > 10:
            sp += 1
        else:
            break
    # Считаем подряд горячих дней в будущем
    sf = 0
    for d in days[4:]:
        if (d.get("tmax") or 0) > 10:
            sf += 1
        else:
            break
    total = sp + sf
    if total >= 5:
        return [f"☀️ Затяжная оттепель: {total} дней подряд >+10°C — интенсивное снеготаяние, УСКОРЕНИЕ."]
    if sf >= 2:
        return [f"☀️ Прогноз: {sf} тёплых дня (>+10°C) впереди — ускорение таяния."]
    return []


def analyze_precipitation(days):
    """Анализ осадков за прошлые и будущие 4 дня."""
    fr = sum(d.get("rain_sum", 0) or 0 for d in days[4:])
    pr = sum(d.get("rain_sum", 0) or 0 for d in days[:4])
    results = []
    if fr >= 20:
        results.append(f"🌧 СИЛЬНЫЕ осадки в прогнозе: {fr:.0f} мм за 4 дня — высокий приток в реку.")
    elif fr >= 8:
        results.append(f"🌧 Ожидается {fr:.0f} мм осадков за 4 дня — умеренно.")
    if pr >= 15:
        results.append(f"🌧 За последние 4 дня выпало {pr:.0f} мм — почва насыщена, сток повышен.")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 6. COMPUTE WEATHER FLOOD INDEX (0-4)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_weather_flood_index(days, snow_depth_cm):
    """
    Вычисляет паводковый индекс погоды (0-4) по формуле из ТЗ.
    Возвращает: (level, label, color, summary)
    """
    score = 0

    # Тёплые ночи (Tmin > 0 в прогнозе): каждая +2
    warm_nights_future = sum(1 for d in days[4:] if (d.get("tmin", -5) or -5) > 0)
    score += warm_nights_future * 2

    # Жаркие дни (Tmax > 10 в прогнозе): каждый +1
    hot_days_future = sum(1 for d in days[4:] if (d.get("tmax", 0) or 0) > 10)
    score += hot_days_future * 1

    # Дождь в прогнозе: min(rain/5, 4) баллов
    rain_future = sum(d.get("rain_sum", 0) or 0 for d in days[4:])
    score += min(rain_future / 5, 4)

    # Снег: ≥20см = +2, ≥5см = +1
    if snow_depth_cm >= 20:
        score += 2
    elif snow_depth_cm >= 5:
        score += 1

    # Rain-on-Snow: +3
    ros = any(
        (d.get("rain_sum", 0) or 0) >= 5 and (d.get("tmax", 0) or 0) > 0 and snow_depth_cm >= 3
        for d in days[4:]
    )
    if ros:
        score += 3

    # Маппинг score → (level 0-4, label, color, summary)
    if score >= 10:
        return (4, "КРИТИЧЕСКИЙ", "#8e0000",
                "Активное таяние + осадки. Все факторы против нас. Максимально быстрый рост уровня.")
    elif score >= 7:
        return (3, "ВЫСОКИЙ", "#c0392b",
                "Значительный риск подъёма. Ночи тёплые, осадки, таяние активное.")
    elif score >= 4:
        return (2, "ПОВЫШЕННЫЙ", "#e67e22",
                "Снег тает, осадки умеренные. Следим.")
    elif score >= 2:
        return (1, "УМЕРЕННЫЙ", "#f39c12",
                "Незначительное таяние. Ночные заморозки сдерживают.")
    else:
        return (0, "СТАБИЛЬНЫЙ", "#27ae60",
                "Морозы сдерживают таяние.")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. GENERATE WEATHER COMMENTARY (≤4 строки)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_weather_commentary(days, snow_depth_cm):
    """
    Собирает результаты всех 6 анализаторов, дедуплицирует, возвращает ≤4 самых важных.
    Порядок приоритета: ROS → снег → заморозки → Tmin тренд → тёплые дни → осадки.
    """
    c = []
    c += analyze_ros(days, snow_depth_cm)
    c += analyze_snow_depth(days)
    c += analyze_frost_nights(days)
    c += analyze_tmin_trend(days)
    c += analyze_warm_days(days)
    c += analyze_precipitation(days)
    return c[:4]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. HISTORY I/O
# ═══════════════════════════════════════════════════════════════════════════════

def load_history():
    """Загружает history.csv → list[dict]."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_history(rows):
    """Сохраняет list[dict] → history.csv с HISTORY_COLS."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def get_past_level(history, station, hours_ago):
    """Ищет уровень станции N часов назад в истории (±6ч)."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=hours_ago)
    best, best_diff = None, timedelta(days=999)
    for row in history:
        try:
            dt = datetime.fromisoformat(row["datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            diff = abs(dt - target)
            if diff < best_diff:
                best_diff = diff
                v = row.get(station, "")
                best = int(float(v)) if v and v != "—" else None
        except Exception:
            pass
    return best if best_diff < timedelta(hours=6) else None


# ═══════════════════════════════════════════════════════════════════════════════
# 9. ALERTS DEDUP
# ═══════════════════════════════════════════════════════════════════════════════

def load_alerts():
    """Загружает alerts_sent.json из data/."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_alerts(d):
    """Сохраняет alerts_sent.json в data/."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERTS_FILE, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def should_send_alert(alerts, key, cooldown_h=6):
    """Проверяет, прошёл ли cooldown с последнего алерта по ключу."""
    ts = alerts.get(key)
    if not ts:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > cooldown_h * 3600
    except Exception:
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# 10. 2024 REFERENCE
# ═══════════════════════════════════════════════════════════════════════════════

def load_2024_ref():
    """Загружает данные 2024 для сравнения (data/2024_ref.json)."""
    if not os.path.exists(REF_2024):
        return {}
    try:
        with open(REF_2024) as f:
            return json.load(f)
    except Exception:
        return {}


def get_2024_value(ref, day_of_year):
    """Получает уровень Серпухова на этот день в 2024."""
    # Пробуем разные форматы ключа
    val = ref.get(str(day_of_year))
    if val is not None:
        return val
    val = ref.get(f"{day_of_year:03d}")
    if val is not None:
        return val
    # Пробуем statbydate формат
    sbd = ref.get("statbydate", {})
    if sbd:
        return sbd.get(str(day_of_year))
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 11. COMPUTE ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_analytics(levels, history, weather):
    """Вычисляет дельты, сценарии пика, insights, сравнение с 2024."""
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    ka = levels.get("kashira")
    sh = levels.get("shukina")

    s24 = get_past_level(history, "serpukhov", 24)
    s48 = get_past_level(history, "serpukhov", 48)
    o24 = get_past_level(history, "orel", 24)
    k24 = get_past_level(history, "kaluga", 24)

    ds24 = (s - s24)     if s is not None and s24 is not None else None
    ds48 = (s - s48) / 2 if s is not None and s48 is not None else None
    do24 = (o - o24)     if o is not None and o24 is not None else None
    dk24 = (k - k24)     if k is not None and k24 is not None else None

    # Волновой прогноз
    wave_msg = None
    if o is not None and do24 is not None:
        arrow = "↑" if do24 > 0 else "↓"
        wave_msg = f"🌊 Орёл {o} {arrow}{round(do24)} → волна в Серпухов ~96ч"

    # Сценарии пика
    pb_days = pb_level = pb_date = None
    po_level = po_date = None
    pp_level = pp_date = None

    orel_decl   = do24 is not None and do24 < -5
    kaluga_decl = dk24 is not None and dk24 < -5
    serp_slow   = ds24 is not None and ds48 is not None and ds24 < ds48 and ds24 > 0

    if s is not None:
        if orel_decl and kaluga_decl:
            extra = abs(dk24) / max(ds24 or 1, 1) if dk24 and ds24 else 3
            pb_days = round(min(max(extra, 1), 6), 1)
        elif orel_decl:
            pb_days = 4.0
        elif serp_slow and s > 600:
            ratio = ds24 / ds48 if ds48 else 1
            pb_days = round(min(1 / (1 - ratio + 0.01) if ratio < 1 else 5, 10), 1)

        if pb_days is not None:
            pb_level = round(s + (ds24 or 0) * pb_days)
            pb_date  = (datetime.now() + timedelta(days=pb_days)).strftime("%d.%m")
            po_level = round(s + (ds24 or 0) * 0.5 * pb_days * 0.7)
            po_date  = (datetime.now() + timedelta(days=pb_days * 0.7)).strftime("%d.%m")
            pp_level = round(s + (ds24 or 0) * 1.2 * pb_days * 1.5)
            pp_date  = (datetime.now() + timedelta(days=pb_days * 1.5)).strftime("%d.%m")

    # До 945
    days_to_945 = date_to_945 = None
    if s is not None and ds24 and ds24 > 0:
        days_to_945 = round((CRITICAL_LEVEL - s) / ds24, 1)
        date_to_945 = (datetime.now() + timedelta(days=days_to_945)).strftime("%d.%m")
    elif s is not None and s >= CRITICAL_LEVEL:
        days_to_945 = 0

    # Danger percent
    danger_pct = 0
    if s is not None:
        base_pct  = min(s / CRITICAL_LEVEL * 100, 100)
        speed_pct = min(abs(ds24 or 0) / 50 * 20, 20) if ds24 and ds24 > 0 else 0
        danger_pct = round(min(base_pct + speed_pct, 100), 1)

    # Alert level
    alert_level = "GREEN"
    if s is not None:
        if s >= CRITICAL_LEVEL:
            alert_level = "CRITICAL"
        elif s >= PEAK_2024:
            alert_level = "RED"
        elif s >= PODTOP_LEVEL:
            alert_level = "ORANGE"
        elif s >= POYMA_LEVEL:
            alert_level = "YELLOW"
        elif ds24 and ds24 >= 40:
            alert_level = "RED"
        elif ds24 and ds24 >= 20:
            alert_level = "YELLOW"
    elif s is None:
        alert_level = "UNKNOWN"

    # Insights
    insights = []
    t  = weather.get("temp") or weather.get("temp_max")
    pr = weather.get("precip_mm", 0) or 0
    if t is not None and t > 10 and pr > 5:
        insights.append(f"🌧 Тепло +{t}°C + дождь {pr}мм — ускоренное таяние!")
    elif t is not None and t > 8:
        insights.append(f"☀️ Активное дневное таяние (+{t}°C)")
    elif t is not None and t < 0:
        insights.append(f"❄️ Мороз {t}°C — таяние заморожено")

    if ds24 and ds24 >= 40:
        insights.append(f"🚨 Сверхбыстрый рост: +{round(ds24)} см/сут!")
    elif ds24 and ds24 >= 20:
        insights.append(f"⚡ Быстрый рост: +{round(ds24)} см/сут")

    if orel_decl and kaluga_decl:
        insights.append("📉 Орёл и Калуга падают — пик волны приближается к Серпухову")

    if wave_msg:
        insights.append(wave_msg)

    # 2024 reference
    ref    = load_2024_ref()
    doy    = datetime.now().timetuple().tm_yday
    s2024  = get_2024_value(ref, doy)
    vs2024 = (s - int(s2024)) if s is not None and s2024 is not None else None

    return dict(
        ds24=ds24, ds48=ds48, do24=do24, dk24=dk24,
        days_to_945=days_to_945, date_to_945=date_to_945,
        peak_base_days=pb_days, peak_base_level=pb_level, peak_base_date=pb_date,
        peak_opt_level=po_level, peak_opt_date=po_date,
        peak_pess_level=pp_level, peak_pess_date=pp_date,
        alert_level=alert_level, danger_pct=danger_pct,
        insights=insights, wave_msg=wave_msg,
        orel_declining=orel_decl, kaluga_declining=kaluga_decl, serp_slowing=serp_slow,
        serp_2024=s2024, vs_2024=vs2024,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 12. FORMAT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt_delta(d):
    """Форматирует дельту: +N или -N."""
    if d is None:
        return ""
    return f"+{round(d)}" if d > 0 else str(round(d))


def _trend(d):
    """Emoji тренда по дельте."""
    if d is None:
        return ""
    if d > 20:
        return "🔺"
    if d > 5:
        return "↑"
    if d < -10:
        return "↓↓"
    if d < -2:
        return "↓"
    return "→"


def _dist(s, target, ds24):
    """Расстояние до порога + прогноз даты."""
    if s is None:
        return ""
    if s >= target:
        return "✅"
    rem = target - s
    if ds24 and ds24 > 0:
        days_est = round(rem / ds24, 1)
        dt = (datetime.now() + timedelta(days=days_est)).strftime("%d.%m")
        return f"{rem}см → {days_est}дн. ({dt})"
    return f"{rem}см"


def wind_dir_str(deg):
    """Градусы → направление ветра (рус.)."""
    dirs = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    return dirs[int(deg / 45 + 0.5) % 8]


# ═══════════════════════════════════════════════════════════════════════════════
# 13. CHECK KIM TRIGGERS
# ═══════════════════════════════════════════════════════════════════════════════

def check_kim_triggers(levels, analytics, alerts):
    """Проверяет KIM-пороги и быстрый рост, возвращает list[(key, text)]."""
    s = levels.get("serpukhov")
    ds24 = analytics.get("ds24")
    triggered = []

    for thr in KIM_THRESHOLDS:
        key = f"KIM_{thr}"
        if s is not None and s >= thr and should_send_alert(alerts, key, cooldown_h=12):
            triggered.append((key,
                f"<b>🚨 ALERT: Серпухов {s}</b> ≥ {thr}\n"
                f"{KIM_EMOJI[thr]} {KIM_LABEL[thr]}\n"
                f"Δ24ч={_fmt_delta(ds24)} | Опасность {analytics.get('danger_pct', 0):.0f}%\n"
                f"До 945: {_dist(s, CRITICAL_LEVEL, ds24)}"
            ))

    if ds24 and ds24 >= 20:
        key = "RATE_FAST"
        if should_send_alert(alerts, key, cooldown_h=6):
            triggered.append((key,
                f"⚡ <b>Быстрый рост</b> +{round(ds24)} см/сут | Серпухов {s}"
            ))

    if ds24 and ds24 >= 40:
        key = "RATE_STORM"
        if should_send_alert(alerts, key, cooldown_h=4):
            triggered.append((key,
                f"🆘 <b>ЭКСТРЕМАЛЬНЫЙ рост</b> +{round(ds24)} см/сут! | Серпухов {s}"
            ))

    return triggered


# ═══════════════════════════════════════════════════════════════════════════════
# 14. TG SEND
# ═══════════════════════════════════════════════════════════════════════════════

def tg_send(chat_id, text, parse_mode="HTML"):
    """Отправляет сообщение в Telegram."""
    if not TG_TOKEN:
        print(f"TG-skip {chat_id}: {text[:120].replace(chr(10), ' ')}")
        return
    if not chat_id:
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        printf("TG→%s: %d", chat_id, r.status_code)
    except Exception as e:
        printf("TG err: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 15. FORMAT HEARTBEAT (v5 = v4.2 + wext)
# ═══════════════════════════════════════════════════════════════════════════════

def format_heartbeat(levels, analytics, weather, wext=None):
    """Краткая сводка — ADMIN + MY_GROUP."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    al = analytics
    em = ALERT_EMOJI.get(al.get("alert_level"), "⚪")
    ds24 = al.get("ds24")

    lines = [f"<b>HEARTBEAT {now}</b>", f"{em} {al.get('danger_pct', 0):.0f}%", ""]

    for key in STATION_KEYS:
        v   = levels.get(key)
        nm  = SLUG_NAMES.get(key, key)
        lag = SLUG_LAG.get(key, 0)
        lags = f"+{lag}ч" if lag > 0 else (f"{lag}ч" if lag < 0 else "")
        vs = f"{v}" if v is not None else "—"
        d24 = (
            al.get("ds24") if key == "serpukhov" else
            al.get("do24") if key == "orel" else
            al.get("dk24") if key == "kaluga" else None
        )
        mark = " ◀" if key == "serpukhov" else ""
        lines.append(f"{nm}{lags}: {vs} {_trend(d24)}{_fmt_delta(d24)}{mark}")

    if ds24 and ds24 > 0 and al.get("days_to_945"):
        lines.append(f"До 945: {_dist(levels.get('serpukhov'), CRITICAL_LEVEL, ds24)}")

    if al.get("wave_msg"):
        lines.append(al["wave_msg"])

    # Погода
    t  = weather.get("temp")
    pr = weather.get("precip_mm", 0) or 0
    wm = weather.get("wind_ms")
    if t is not None:
        lines.append(f"🌡 {t}°C | 💧{pr}мм | 💨{wm}м/с")

    # v5: расширенная погода
    if wext:
        snow_cm     = wext.get("snow_depth_cm", 0)
        flood_label = wext.get("flood_label", "—")
        lines.append(f"❄️ Снег: {snow_cm:.0f} см | Паводковый индекс: {flood_label}")

    lines.append("https://em-from-pu.github.io/oka-flood-monitor")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. FORMAT DIGEST (v5 = v4.2 + wext)
# ═══════════════════════════════════════════════════════════════════════════════

def format_digest(levels, analytics, weather, history, wext=None):
    """Полный дайджест — ADMIN + условно MY_GROUP."""
    now = datetime.now().strftime("%d.%m.%Y")
    al = analytics
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    sh = levels.get("shukina")
    ka = levels.get("kashira")
    ko = levels.get("kolomna")

    ds24 = al.get("ds24")
    ds48 = al.get("ds48")
    do24 = al.get("do24")
    dk24 = al.get("dk24")

    pb     = al.get("peak_base_level")
    pbd    = al.get("peak_base_date")
    pbdays = al.get("peak_base_days")
    po     = al.get("peak_opt_level")
    pod    = al.get("peak_opt_date")
    pp     = al.get("peak_pess_level")
    ppd    = al.get("peak_pess_date")

    vs2024 = al.get("vs_2024")
    s2024  = al.get("serp_2024")
    em     = ALERT_EMOJI.get(al.get("alert_level"), "⚪")
    dpct   = al.get("danger_pct", 0)

    # Прогноз до 945
    fcast = ""
    if s is not None and s >= CRITICAL_LEVEL:
        fcast = f"🆘 Серпухов {s} — КРИТИЧЕСКИЙ УРОВЕНЬ!\n"
    elif al.get("days_to_945") and ds24 and ds24 > 0:
        fcast = f"До 945: {_dist(s, CRITICAL_LEVEL, ds24)}\n"

    # Сценарии пика
    peak_b = ""
    if pb and pbd:
        peak_b = (
            f"\n🔺 Оптим.: {po or '?'} ({pod or '?'})"
            f"\n🔸 Базов.: {pb} ({pbd}, ~{pbdays}дн.)"
            f"\n🔻 Пессим.: {pp or '?'} ({ppd or '?'})"
        )

    wave_t = f"\n{al['wave_msg']}" if al.get("wave_msg") else ""
    vs_t = ""
    if vs2024 is not None and s2024 is not None:
        sign = "+" if vs2024 >= 0 else ""
        vs_t = f"\nVS 2024: {s2024}→{s} ({sign}{vs2024})"

    ins_t = "\n".join(f"• {i}" for i in al.get("insights", [])[:5])

    # Погода
    t    = weather.get("temp")
    pr   = weather.get("precip_mm", 0) or 0
    wm   = weather.get("wind_ms")
    wd   = wind_dir_str(weather.get("wind_dir", 0))
    hm   = weather.get("humidity")
    tmax = weather.get("temp_max")
    tmin = weather.get("temp_min")
    snowd = weather.get("snow_depth")

    wline = ""
    if t is not None:
        wline = f"\n🌡{t}°C (min{tmin}/max{tmax}) | 💧{pr}мм | 💨{wm}м/с {wd} | 💦{hm}%"
        if snowd is not None:
            wline += f" | ❄{snowd}м снега"

    # v5: Расширенный прогноз из wext
    wfl = ""
    if wext:
        wfl += "\n\n━━━ РАСШИРЕННЫЙ ПРОГНОЗ ━━━━━━━━━━━━━"
        wfl += f"\n❄️ Снег: {wext.get('snow_depth_cm', 0):.0f} см"
        wfl += f"\n🌡 Паводковый индекс: <b>{wext.get('flood_label', '—')}</b> ({wext.get('flood_index', '—')}/4)"
        wfl += f"\n{wext.get('flood_summary', '')}"
        if wext.get("commentary"):
            for c in wext["commentary"][:3]:
                wfl += f"\n  {c}"

    return (
        f"<b>📊 Паводок Ока 2026</b>  {now}  {em} {dpct:.0f}%\n\n"
        f"🏔 Орёл (96ч): {o or '—'} {_trend(do24)}{_fmt_delta(do24)}\n"
        f"  Белёв (72ч): {b or '—'}\n"
        f"  Калуга (48ч): {k or '—'} {_trend(dk24)}{_fmt_delta(dk24)}\n"
        f"  Щукина (24ч): {sh or '—'}\n"
        f"<b>⭐ Серпухов: {s or '—'}</b> {_trend(ds24)}{_fmt_delta(ds24)}"
        f" (48ч:{_fmt_delta(ds48)}) {dpct:.0f}%\n"
        f"  Кашира (-12ч): {ka or '—'}\n"
        f"  Коломна (-24ч): {ko or '—'}\n\n"
        f"🎯 500: {_dist(s, NORM_LEVEL, ds24)}\n"
        f"🎯 645: {_dist(s, POYMA_LEVEL, ds24)}\n"
        f"🎯 800: {_dist(s, PODTOP_LEVEL, ds24)}\n"
        f"🎯 920: {_dist(s, PEAK_2024, ds24)}\n"
        f"🎯 945: {_dist(s, CRITICAL_LEVEL, ds24)}\n\n"
        f"{fcast}{peak_b}{wave_t}{vs_t}"
        f"{wline}{wfl}\n\n"
        f"{ins_t}\n"
        "https://em-from-pu.github.io/oka-flood-monitor | fishingsib.ru"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 16a. FORMAT NEIGHBORS DIGEST (НОВОЕ! — упрощённый для соседей)
# ═══════════════════════════════════════════════════════════════════════════════

def format_neighbors_digest(levels, analytics, weather, wext=None):
    """
    Упрощённый дайджест для соседей.
    Без технических деталей (без дельт станций кроме Серпухова).
    Без таблицы порогов КИМ.
    Простой человеческий язык + практические рекомендации.
    """
    now = datetime.now().strftime("%d.%m.%Y")
    al = analytics
    s = levels.get("serpukhov")
    ds24 = al.get("ds24")
    dpct = al.get("danger_pct", 0)

    # Тренд простым языком
    if ds24 is not None:
        if ds24 > 20:
            trend_txt = f"быстро растёт (+{round(ds24)} см/сут)"
        elif ds24 > 5:
            trend_txt = f"растёт (+{round(ds24)} см/сут)"
        elif ds24 > 0:
            trend_txt = f"медленно растёт (+{round(ds24)} см/сут)"
        elif ds24 < -5:
            trend_txt = f"падает ({round(ds24)} см/сут)"
        elif ds24 < 0:
            trend_txt = f"медленно падает ({round(ds24)} см/сут)"
        else:
            trend_txt = "без изменений"
    else:
        trend_txt = "нет данных за 24ч"

    # Рекомендация из generate_action_block
    action_icon, action_title, action_text = generate_action_block(analytics, wext)

    # Погодный индекс
    flood_line = ""
    if wext:
        flood_line = (
            f"\n🌡 Погода: {wext.get('flood_label', '—')}\n"
            f"{wext.get('flood_summary', '')}"
        )

    serp_str = str(s) if s is not None else "н/д"

    return (
        f"🌊 <b>ПАВОДОК ОКА — СВОДКА {now}</b>\n\n"
        f"📊 Серпухов: {serp_str} см ({trend_txt})\n"
        f"⚠️ Опасность: {dpct:.0f}%\n\n"
        f"{action_icon} <b>{action_title}</b>\n"
        f"{action_text}\n"
        f"{flood_line}\n\n"
        f"🔗 Подробнее: https://em-from-pu.github.io/oka-flood-monitor"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 17. FORMAT GROUP DRAFT (ПЕРЕПИСАН — от первого лица Егора + wext)
# ═══════════════════════════════════════════════════════════════════════════════

def format_group_draft(levels, analytics, wext=None):
    """Draft для ручной отправки в общие группы — от первого лица (Егора)."""
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    al  = analytics
    s   = levels.get("serpukhov")
    ds24 = al.get("ds24")
    dpct = al.get("danger_pct", 0)

    # Тренд
    if ds24 is not None:
        sign = "+" if ds24 > 0 else ""
        delta_txt = f"{sign}{round(ds24)} см/сут"
        if ds24 > 0:
            trend_word = "растёт"
        elif ds24 < 0:
            trend_word = "падает"
        else:
            trend_word = "стабилен"
    else:
        delta_txt = "нет данных"
        trend_word = "нет данных за 24ч"

    # Сценарии пика
    po = al.get("peak_opt_level")
    pod = al.get("peak_opt_date")
    pb = al.get("peak_base_level")
    pbd = al.get("peak_base_date")
    pp = al.get("peak_pess_level")
    ppd = al.get("peak_pess_date")

    peak_lines = ""
    if pb and pbd:
        peak_lines = (
            f"\n📈 Прогноз пика:\n"
            f"- Оптимистичный: {po or '?'} см к {pod or '?'}\n"
            f"- Базовый: {pb} см к {pbd}\n"
            f"- Пессимистичный: {pp or '?'} см к {ppd or '?'}"
        )

    # Волновой прогноз
    wave = al.get("wave_msg")
    wave_txt = wave if wave else "Паводковая волна пока не сформировалась."

    # Погодный индекс
    weather_lines = ""
    if wext:
        fi = wext.get("flood_index", 0)
        fl = wext.get("flood_label", "—")
        fs = wext.get("flood_summary", "")
        weather_lines = f"\n\n🌡 Погодный индекс: {fl} ({fi}/4)\n{fs}"

    serp_str = str(s) if s is not None else "нет данных"

    return (
        f"Привет! Это Егор, обновление паводковой обстановки на Оке.\n\n"
        f"📊 Серпухов сейчас: {serp_str} см (вчера {trend_word}, {delta_txt})\n"
        f"⚠️ Уровень опасности: {dpct:.0f}%\n\n"
        f"🌊 Что происходит:\n"
        f"{wave_txt}"
        f"{peak_lines}"
        f"{weather_lines}\n\n"
        f"💡 Как работает система:\n"
        f"Бот собирает данные с 7 гидропостов Оки (от Орла до Коломны) + погоду\n"
        f"из Open-Meteo. Анализирует скорость подъёма воды, снежный покров,\n"
        f"температуру и осадки. Обновление — 4 раза в сутки автоматически.\n\n"
        f"🔗 Полная аналитика: https://em-from-pu.github.io/oka-flood-monitor\n"
        f"🤖 Бот: @OkaFlood2026EMbot"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 18. GENERATE ACTION BLOCK (НОВОЕ — Блок 13)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_action_block(analytics, wext):
    """
    Генерирует текст 'Что делать жителям/дачникам в ближайшие 48 часов'.
    Возвращает (icon, title, text).
    """
    al = analytics.get("alert_level", "GREEN")
    fi = wext.get("flood_index", 0) if wext else 0
    serp = 0
    # Вычисляем уровень Серпухова из danger_pct (обратная формула)
    # или используем косвенные данные
    dpct = analytics.get("danger_pct", 0)
    # Приблизительный уровень из danger_pct
    serp = round(dpct / 100 * CRITICAL_LEVEL) if dpct > 0 else 0

    if al == "CRITICAL" or serp >= 920:
        icon = "🚨"
        title = "КРИТИЧЕСКАЯ СИТУАЦИЯ"
        text = ("Вода приближается к отметке затопления жилых домов. "
                "Рекомендуем: вывезти ценные вещи из подвалов, подготовить "
                "насосы, проверить пути эвакуации. Следите за обновлениями каждый час.")
    elif al == "RED" or serp >= 800:
        icon = "⚠️"
        title = "ПОВЫШЕННАЯ ОПАСНОСТЬ"
        text = ("Дачные участки начинают подтапливаться. Проверьте свои участки, "
                "уберите вещи с низких мест. До критической отметки дома осталось "
                f"{945 - serp} см.")
    elif al == "ORANGE" or serp >= 645:
        icon = "🟠"
        title = "ПОЙМА ЗАТОПЛЕНА"
        text = ("Пойма Оки у Серпухова затоплена. Не выходите на пойменные луга. "
                "Дачным участкам пока ничего не угрожает, но следите за динамикой.")
    elif fi >= 3:
        icon = "🌧️"
        title = "ПРОГНОЗ НЕБЛАГОПРИЯТНЫЙ"
        text = ("Вода пока спокойна, но погодный индекс высокий: ожидаются "
                "условия для быстрого подъёма (потепление + осадки). "
                "Рекомендуем проверять сайт ежедневно.")
    else:
        icon = "✅"
        title = "СИТУАЦИЯ СТАБИЛЬНАЯ"
        text = ("Уровень воды в пределах нормы. Паводковый индекс погоды не вызывает "
                "опасений. Обновления — 4 раза в день.")

    return icon, title, text


# ═══════════════════════════════════════════════════════════════════════════════
# 19. COMPUTE SIMPLE REGRESSION (НОВОЕ — ML-прогноз, чистый Python)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_simple_regression(history):
    """
    Линейная регрессия уровня Серпухова за последние 14 дней.
    НЕ использует scikit-learn (не установлен в GitHub Actions).
    Реализация на чистом Python (least squares).

    Возвращает:
    {
      "slope_per_day": float,        # см/день
      "r_squared": float,            # R² (качество фита)
      "predicted_3d": float,         # прогноз через 3 дня
      "predicted_7d": float,         # прогноз через 7 дней
      "predicted_peak_date": str,    # когда достигнет 945 при текущем тренде
      "trend_text": str,             # "рост X см/день" или "спад" или "стабильно"
    }
    """
    # Берём последние 14 записей с непустым serpukhov
    points = []
    for row in history[-100:]:
        val = row.get("serpukhov")
        if val and str(val).strip():
            try:
                points.append((row["datetime"], int(float(val))))
            except (ValueError, TypeError):
                pass

    if len(points) < 5:
        return None

    # Последние 14 уникальных по дате
    seen_dates = set()
    daily = []
    for dt_str, val in reversed(points):
        d = dt_str[:10]
        if d not in seen_dates:
            seen_dates.add(d)
            daily.append((d, val))
        if len(daily) >= 14:
            break
    daily.reverse()

    if len(daily) < 5:
        return None

    n = len(daily)
    xs = list(range(n))  # 0, 1, 2, ...
    ys = [v for _, v in daily]

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ss_xy = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
    ss_yy = sum((ys[i] - y_mean) ** 2 for i in range(n))

    if ss_xx == 0:
        return None

    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy != 0 else 0

    last_x = n - 1
    pred_3d = slope * (last_x + 3) + intercept
    pred_7d = slope * (last_x + 7) + intercept

    # Когда достигнет 945
    peak_date = None
    if slope > 0.5:
        days_to_945 = (945 - ys[-1]) / slope
        if 0 < days_to_945 < 365:
            peak_date = (datetime.now() + timedelta(days=days_to_945)).strftime("%d.%m")

    if slope > 1:
        trend_text = f"📈 Рост {slope:.1f} см/день"
    elif slope < -1:
        trend_text = f"📉 Спад {abs(slope):.1f} см/день"
    else:
        trend_text = "➡️ Стабильно"

    return {
        "slope_per_day": round(slope, 2),
        "r_squared": round(r_squared, 3),
        "predicted_3d": round(pred_3d),
        "predicted_7d": round(pred_7d),
        "predicted_peak_date": peak_date,
        "trend_text": trend_text,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 20. GENERATE CHART.JS BLOCK (НОВОЕ — Chart.js график, Зона C)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_chart_js_block(history, ref_2024):
    """
    Генерирует HTML+JS блок с Chart.js графиком:
    - 14 дней Серпухов
    - 2024 overlay (тот же день года)
    - Линии порогов 645, 800, 945
    Если данных < 3 дней → возвращает пустую строку.
    """
    # Собираем последние 14 дней из history
    seen_dates = {}
    for row in reversed(history):
        dt_str = row.get("datetime", "")[:10]
        if dt_str and dt_str not in seen_dates:
            val = row.get("serpukhov", "")
            if val and str(val).strip():
                try:
                    seen_dates[dt_str] = int(float(val))
                except (ValueError, TypeError):
                    pass
        if len(seen_dates) >= 14:
            break

    if len(seen_dates) < 3:
        return ""

    # Сортируем по дате
    sorted_dates = sorted(seen_dates.keys())
    labels = []
    values_2026 = []
    values_2024 = []

    for d_str in sorted_dates:
        # Формат для лейбла: DD.MM
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            labels.append(dt.strftime("%d.%m"))
            values_2026.append(seen_dates[d_str])
            # 2024 overlay
            doy = dt.timetuple().tm_yday
            v2024 = get_2024_value(ref_2024, doy) if ref_2024 else None
            values_2024.append(int(v2024) if v2024 is not None else "null")
        except Exception:
            labels.append(d_str[5:])
            values_2026.append(seen_dates[d_str])
            values_2024.append("null")

    labels_js = ", ".join(f'"{l}"' for l in labels)
    values_2026_js = ", ".join(str(v) for v in values_2026)
    values_2024_js = ", ".join(str(v) for v in values_2024)

    # Threshold datasets (горизонтальные пунктирные линии)
    n_points = len(labels)
    thresh_645 = ", ".join(["645"] * n_points)
    thresh_800 = ", ".join(["800"] * n_points)
    thresh_945 = ", ".join(["945"] * n_points)

    return f'''<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<div style="position:relative; height:300px; margin:16px 0;">
  <canvas id="levelChart"></canvas>
</div>
<script>
(function() {{
  var ctx = document.getElementById('levelChart').getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: [{labels_js}],
      datasets: [
        {{
          label: '🔵 Серпухов 2026',
          data: [{values_2026_js}],
          borderColor: '#388bfd',
          backgroundColor: 'rgba(56,139,253,0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 3,
        }},
        {{
          label: '⚫ 2024 (тот же день)',
          data: [{values_2024_js}],
          borderColor: '#6e7681',
          borderDash: [5, 5],
          fill: false,
          tension: 0.3,
          pointRadius: 2,
        }},
        {{
          label: '645 пойма',
          data: [{thresh_645}],
          borderColor: 'rgba(243,156,18,0.4)',
          borderDash: [8, 4],
          pointRadius: 0,
          borderWidth: 1,
          fill: false,
        }},
        {{
          label: '800 дачи',
          data: [{thresh_800}],
          borderColor: 'rgba(231,76,60,0.4)',
          borderDash: [8, 4],
          pointRadius: 0,
          borderWidth: 1,
          fill: false,
        }},
        {{
          label: '945 дом',
          data: [{thresh_945}],
          borderColor: 'rgba(142,0,0,0.5)',
          borderDash: [8, 4],
          pointRadius: 0,
          borderWidth: 1,
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ labels: {{ color: '#8b949e' }} }},
        title: {{ display: true, text: '📈 Уровень воды Серпухов — 14 дней', color: '#79c0ff' }}
      }},
      scales: {{
        x: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }} }},
        y: {{
          ticks: {{ color: '#8b949e' }},
          grid: {{ color: '#21262d' }},
          title: {{ display: true, text: 'см', color: '#8b949e' }}
        }}
      }}
    }}
  }});
}})();
</script>
<div class="explainer">
  <b>Как читать график?</b> Синяя линия — уровень воды в Серпухове за последние 14 дней.
  Серая пунктирная — уровень в тот же день в 2024 году (для сравнения).
  Горизонтальные линии — пороги КИМ: 645 см (пойма), 800 см (дачи), 945 см (дом).
</div>'''


# ═══════════════════════════════════════════════════════════════════════════════
# 21. LOAD MAILING LIST (НОВОЕ — динамическая рассылка)
# ═══════════════════════════════════════════════════════════════════════════════

def load_mailing_list():
    """Читает data/mailing_list.json, возвращает list[str] chat_ids."""
    try:
        with open(MAILING_LIST, "r") as f:
            data = json.load(f)
        return [r["chat_id"] for r in data.get("recipients", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# 21a. GENERATE RIVER MAP SVG (B1 — мини-карта)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_river_map_svg(levels):
    """Генерирует inline SVG мини-карту бассейна Оки с 7 станциями."""
    stations_pos = [
        ("Орёл", 50, 100, "orel"),
        ("Белёв", 130, 80, "belev"),
        ("Калуга", 220, 60, "kaluga"),
        ("Щукина", 310, 80, "shukina"),
        ("Серпухов", 400, 100, "serpukhov"),
        ("Кашира", 480, 90, "kashira"),
        ("Коломна", 560, 70, "kolomna"),
    ]

    def _color_for_level(val):
        if val is None:
            return "#6e7681"
        if val >= 800:
            return "#e74c3c"
        if val >= 645:
            return "#e67e22"
        if val >= 500:
            return "#f39c12"
        return "#27ae60"

    # River path
    path_points = " ".join(f"{x},{y}" for _, x, y, _ in stations_pos)
    river_path = f'<polyline points="{path_points}" stroke="#388bfd" stroke-width="3" fill="none" opacity="0.5"/>'

    circles = ""
    for name, x, y, slug in stations_pos:
        val = levels.get(slug)
        color = _color_for_level(val)
        r = 18 if slug == "serpukhov" else 12
        stroke_w = 3 if slug == "serpukhov" else 1
        val_str = str(val) if val is not None else "—"
        circles += (
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}" opacity="0.8" '
            f'stroke="#e6edf3" stroke-width="{stroke_w}"/>'
            f'<text x="{x}" y="{y + 4}" text-anchor="middle" fill="#fff" '
            f'font-size="8" font-weight="bold">{val_str}</text>'
            f'<text x="{x}" y="{y - r - 5}" text-anchor="middle" fill="#8b949e" '
            f'font-size="7">{name}</text>'
        )

    return (
        '<div style="overflow-x:auto; margin:8px 0">'
        '<svg viewBox="0 0 620 160" style="width:100%;max-width:620px;height:auto" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'{river_path}'
        f'{circles}'
        '<text x="310" y="150" text-anchor="middle" fill="#6e7681" font-size="8">'
        'Орёл → → → Серпухов → → → Коломна  (направление течения Оки)</text>'
        '</svg></div>'
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 22. GENERATE HTML — ПОЛНАЯ ПЕРЕПИСКА С НУЛЯ (13 блоков + CSS)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_html(levels, analytics, weather, history, wext=None,
                  ref_2024=None, regression=None, extra_levels=None):
    """
    Генерирует полную HTML-страницу (dark theme, 13 блоков, встроенный CSS).
    Все тексты на русском языке.

    Параметры:
        ref_2024     — dict с данными 2024 для Chart.js
        regression   — dict с результатами compute_simple_regression
        extra_levels — dict с уровнями притоков (Нара, Протва)
    """
    # === Подготовка данных ===
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    sh = levels.get("shukina")
    ka = levels.get("kashira")
    ko = levels.get("kolomna")

    al          = analytics
    now_str     = datetime.now().strftime("%d.%m.%Y %H:%M МСК")
    ds24        = al.get("ds24")
    pb_level    = al.get("peak_base_level")
    pb_date     = al.get("peak_base_date")
    pb_days     = al.get("peak_base_days")
    po_level    = al.get("peak_opt_level")
    po_date     = al.get("peak_opt_date")
    pp_level    = al.get("peak_pess_level")
    pp_date     = al.get("peak_pess_date")
    danger_pct  = al.get("danger_pct", 0)
    vs2024      = al.get("vs_2024")
    s2024       = al.get("serp_2024")
    alert_level = al.get("alert_level", "UNKNOWN")
    alert_color = ALERT_COLOR.get(alert_level, "#7f8c8d")
    alert_em    = ALERT_EMOJI.get(alert_level, "⚪")

    # danger bar width
    pct = min(round(s / CRITICAL_LEVEL * 100, 1) if s else 0, 100)

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 1: GAUGE CARDS (7 станций)
    # ══════════════════════════════════════════════════════════════════════

    def _gauge_card(name, val, delta, note, is_main=False):
        dstr = ""
        if delta is not None:
            sign = "+" if delta > 0 else ""
            dstr = f'<div class="gauge-delta">{sign}{round(delta)} см/сут</div>'
        cls = "gauge-card main" if is_main else "gauge-card"
        vh = str(val) if val is not None else '<span class="na">н/д</span>'
        return (
            f'<div class="{cls}">'
            f'<div class="gauge-name">{name}</div>'
            f'<div class="gauge-level">{vh}</div>'
            f'{dstr}'
            f'<div class="gauge-note">{note}</div>'
            f'</div>'
        )

    gauges_html = (
        _gauge_card("Орёл",     o,  al.get("do24"), "96ч до Серп.")
        + _gauge_card("Белёв",    b,  None,            "72ч")
        + _gauge_card("Калуга",   k,  al.get("dk24"), "48ч")
        + _gauge_card("Щукина",   sh, None,            "24ч")
        + _gauge_card("Серпухов", s,  ds24,            "★ ключевой пост", is_main=True)
        + _gauge_card("Кашира",   ka, None,            "-12ч")
        + _gauge_card("Коломна",  ko, None,            "-24ч")
    )

    # SVG мини-карта
    river_map_html = generate_river_map_svg(levels)

    # Притоки (если настроены)
    tributaries_html = ""
    if extra_levels:
        tribs = ""
        for slug, info in EXTRA_STATIONS.items():
            val = extra_levels.get(slug)
            tribs += _gauge_card(info["name"], val, None, "приток")
        tributaries_html = (
            '<div style="margin:8px 0">'
            '<h4 style="color:#8b949e;font-size:0.85em">🔀 Притоки (leading indicators)</h4>'
            f'<div class="gauges">{tribs}</div>'
            '</div>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 3: ПОРОГИ КИМ
    # ══════════════════════════════════════════════════════════════════════

    def _ms_dist(target):
        if s is None:
            return ""
        if s >= target:
            return "✅ достигнут"
        rem = target - s
        if ds24 and ds24 > 0:
            d = round(rem / ds24, 1)
            dt = (datetime.now() + timedelta(days=d)).strftime("%d.%m")
            return f"ещё {rem} см (~{d} дн, {dt})"
        return f"ещё {rem} см"

    thresh_rows = ""
    for t in KIM_THRESHOLDS:
        thresh_rows += (
            f'<tr>'
            f'<td>{KIM_EMOJI[t]}</td>'
            f'<td><b>{t}</b></td>'
            f'<td>{KIM_LABEL[t]}</td>'
            f'<td>{_ms_dist(t)}</td>'
            f'</tr>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 4: СЦЕНАРИИ ПИКА
    # ══════════════════════════════════════════════════════════════════════

    if pb_level:
        scenario_html = (
            '<div class="scenario-cards">'
            '<div class="sc-card green">'
            '<div class="sc-title">🟢 Оптимистичный</div>'
            f'<div class="sc-level">{po_level or "?"}</div>'
            f'<div class="sc-date">{po_date or "?"}</div>'
            '</div>'
            '<div class="sc-card yellow">'
            '<div class="sc-title">🔸 Базовый</div>'
            f'<div class="sc-level">{pb_level}</div>'
            f'<div class="sc-date">{pb_date} (~{pb_days} дн.)</div>'
            '</div>'
            '<div class="sc-card red">'
            '<div class="sc-title">🔴 Пессимистичный</div>'
            f'<div class="sc-level">{pp_level or "?"}</div>'
            f'<div class="sc-date">{pp_date or "?"}</div>'
            '</div>'
            '</div>'
        )
    else:
        scenario_html = (
            '<div class="scenario-cards">'
            '<p style="color:#8b949e;">Недостаточно данных для построения сценариев. '
            'Прогноз пика формируется по накопленной истории.</p>'
            '</div>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 5: РАСШИРЕННЫЙ БЛОК ПОГОДЫ (weather-ext-block)
    # ══════════════════════════════════════════════════════════════════════

    weather_ext_html = ""
    if wext and wext.get("days"):
        wdays       = wext["days"]
        flood_color_w = wext.get("flood_color", "#7f8c8d")
        flood_label = wext.get("flood_label", "—")
        flood_sum   = wext.get("flood_summary", "")
        commentary  = wext.get("commentary", [])
        snow_cm     = wext.get("snow_depth_cm", 0)

        # Зона A: Паводковый индекс погоды
        zone_a = (
            f'<div class="weather-flood-index" style="border-color:{flood_color_w}">'
            f'<span class="wfi-label">Паводковый индекс погоды</span>'
            f'<span class="wfi-value" style="color:{flood_color_w}">{flood_label}</span>'
            f'<p class="wfi-summary">{flood_sum}</p>'
            f'</div>'
        )

        # Зона B: 8-дневная таблица (6 строк: Tmax, Tmin, Осадки, Дождь, Снег, Ветер)
        fc_start = next((i for i, dd in enumerate(wdays) if dd["is_forecast"]), len(wdays))

        def _hdr_cls(idx):
            if idx < fc_start:
                return ""
            if idx == fc_start:
                return ' class="forecast-col" style="border-left:2px solid #3498db"'
            return ' class="forecast-col"'

        def _td_cls_tmax(day):
            classes = []
            if day["is_forecast"]:
                classes.append("forecast-col")
            if (day.get("tmax") or 0) > 10:
                classes.append("hot")
            return f' class="{" ".join(classes)}"' if classes else ""

        def _td_cls_tmin(day):
            v = day.get("tmin")
            if v is None:
                v = 0
            if v < 0:
                base = "frost"
            elif v == 0:
                base = "zero"
            else:
                base = "warm-night"
            if day["is_forecast"]:
                base += " forecast-col"
            return f' class="{base}"'

        def _td_cls_fc(day):
            return ' class="forecast-col"' if day["is_forecast"] else ""

        def _fmt_temp(v):
            if v is None:
                return "—"
            rv = round(v)
            return f"+{rv}" if rv > 0 else str(rv)

        # Заголовки
        ths = ""
        for i, dd in enumerate(wdays):
            label = dd["date"][5:]  # MM-DD
            if dd["is_forecast"]:
                label += " ▸"
            ths += f'<th{_hdr_cls(i)}>{label}</th>'

        # Строка Tmax
        r_tmax = ""
        for dd in wdays:
            r_tmax += f'<td{_td_cls_tmax(dd)}>{_fmt_temp(dd.get("tmax"))}</td>'

        # Строка Tmin
        r_tmin = ""
        for dd in wdays:
            r_tmin += f'<td{_td_cls_tmin(dd)}>{_fmt_temp(dd.get("tmin"))}</td>'

        # Строка Осадки
        r_prec = ""
        for dd in wdays:
            val = dd.get("precip", 0)
            r_prec += f'<td{_td_cls_fc(dd)}>{val if val else "—"}</td>'

        # Строка Дождь мм (rain_sum) — НОВОЕ: отдельная строка!
        r_rain = ""
        for dd in wdays:
            val = dd.get("rain_sum", 0) or 0
            r_rain += f'<td{_td_cls_fc(dd)}>{val if val else "—"}</td>'

        # Строка Снег
        r_snow = ""
        for dd in wdays:
            if dd["is_forecast"]:
                r_snow += f'<td{_td_cls_fc(dd)}>—</td>'
            else:
                sc = dd.get("snow_depth_cm", 0)
                r_snow += f'<td>{sc if sc > 0 else "0"}</td>'

        # Строка Ветер
        r_wind = ""
        for dd in wdays:
            wval = dd.get("wind_ms")
            txt = str(round(wval)) if wval is not None else "—"
            r_wind += f'<td{_td_cls_fc(dd)}>{txt}</td>'

        zone_b = (
            '<div style="overflow-x:auto">'
            '<table class="weather-table">'
            f'<thead><tr><th></th>{ths}</tr></thead>'
            '<tbody>'
            f'<tr><td>Tmax °C</td>{r_tmax}</tr>'
            f'<tr><td>Tmin °C</td>{r_tmin}</tr>'
            f'<tr><td>Осадки мм</td>{r_prec}</tr>'
            f'<tr><td>🌧 Дождь мм</td>{r_rain}</tr>'
            f'<tr><td>❄ Снег см</td>{r_snow}</tr>'
            f'<tr><td>Ветер м/с</td>{r_wind}</tr>'
            '</tbody></table></div>'
        )

        # Пояснительный текст под таблицей
        zone_b_explainer = (
            '<div class="explainer">'
            '<b>Как читать таблицу?</b> Слева 4 дня факт, справа 4 дня прогноз (выделены синим). '
            'Красные ячейки Tmin = ночные заморозки (замедляют таяние). '
            'Зелёные ячейки Tmin = тёплые ночи (ускоряют таяние). '
            'Дождь мм — отдельная строка от общих осадков; важна для Rain-on-Snow индикации. '
            'Rain-on-Snow = дождь на снег при T&gt;0 — самый опасный фактор паводка.'
            '</div>'
        )

        # Зона C: Chart.js график (НОВОЕ!)
        zone_c = ""
        if ref_2024 is not None:
            zone_c = generate_chart_js_block(history, ref_2024)
        elif history:
            zone_c = generate_chart_js_block(history, {})

        # Зона D: Комментарии аналитики
        zone_d = ""
        if commentary:
            li_items = "".join(f"<li>{c}</li>" for c in commentary)
            zone_d = (
                '<div class="weather-commentary">'
                '<h3>📝 Выводы</h3>'
                f'<ul>{li_items}</ul>'
                '</div>'
            )

        weather_ext_html = (
            '<div class="weather-ext-block">'
            '<h3>🌡 Расширенный прогноз погоды (8 дней)</h3>'
            f'{zone_a}'
            f'{zone_b}'
            f'{zone_b_explainer}'
            f'{zone_c}'
            f'{zone_d}'
            '</div>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 6: ВОЛНОВОЙ ПРОГНОЗ
    # ══════════════════════════════════════════════════════════════════════

    wave_html = ""
    if al.get("wave_msg"):
        wave_html = f'<div class="wave-block">{al["wave_msg"]}</div>'

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 7: vs 2024
    # ══════════════════════════════════════════════════════════════════════

    vs24_html = ""
    if vs2024 is not None and s2024 is not None:
        sign = "+" if vs2024 >= 0 else ""
        vs24_html = (
            f'<div class="vs2024">'
            f'📊 vs 2024: {s2024} → сейчас {s} ({sign}{vs2024})'
            f'</div>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 8: INSIGHTS
    # ══════════════════════════════════════════════════════════════════════

    ins_items = al.get("insights", [])
    ins_html = "".join(f"<li>{i}</li>" for i in ins_items) if ins_items else "<li>Нет особых наблюдений</li>"

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК: ML-РЕГРЕССИЯ (после insights)
    # ══════════════════════════════════════════════════════════════════════

    regression_html = ""
    if regression:
        r2 = regression.get("r_squared", 0)
        tt = regression.get("trend_text", "")
        p3 = regression.get("predicted_3d", "?")
        p7 = regression.get("predicted_7d", "?")
        peak_d = regression.get("predicted_peak_date")

        regression_html = (
            '<div class="regression-block">'
            f'<h4>🤖 ML-прогноз (линейная регрессия, R²={r2})</h4>'
            f'<p>{tt}</p>'
            f'<p>Прогноз: через 3 дня ≈ {p3} см, через 7 дней ≈ {p7} см</p>'
        )
        if peak_d:
            regression_html += f'<p>При текущем темпе 945 см будет достигнут ~{peak_d}</p>'
        regression_html += '</div>'

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 9: ДЕЛЬТЫ И РАССТОЯНИЯ
    # ══════════════════════════════════════════════════════════════════════

    deltas_html = (
        f'<div class="deltas-block">'
        f'<p>Δ24ч Серпухов: <b>{_fmt_delta(ds24)}</b> | '
        f'Δ48ч: <b>{_fmt_delta(al.get("ds48"))}</b></p>'
        f'<p>Δ24ч Орёл: <b>{_fmt_delta(al.get("do24"))}</b> | '
        f'Δ24ч Калуга: <b>{_fmt_delta(al.get("dk24"))}</b></p>'
    )
    if ds24 and ds24 > 0 and al.get("days_to_945"):
        d945 = al["days_to_945"]
        dt945 = al.get("date_to_945", "")
        rem = CRITICAL_LEVEL - s if s is not None else 0
        deltas_html += f'<p>До 945 см: ещё {rem} см (~{d945} дн, {dt945})</p>'
    deltas_html += '</div>'

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 10: ТАБЛИЦА ИСТОРИИ (rolling 50 записей)
    # ══════════════════════════════════════════════════════════════════════

    cl_map = {
        "GREEN": "row-green", "YELLOW": "row-yellow",
        "ORANGE": "row-orange", "RED": "row-red", "CRITICAL": "row-critical",
    }

    def _cv(row, key):
        v = row.get(key, "")
        if not v:
            return ""
        try:
            return str(round(float(v)))
        except (ValueError, TypeError):
            return str(v)

    t_rows = []
    sorted_hist = sorted(history, key=lambda x: x.get("datetime", ""), reverse=True)[:50]
    for row in sorted_hist:
        rcls = cl_map.get(row.get("alert_level", ""), "")
        t_rows.append(
            f'<tr class="{rcls}">'
            f'<td>{row.get("datetime", "")[:16]}</td>'
            f'<td>{_cv(row, "orel")}</td>'
            f'<td>{_cv(row, "belev")}</td>'
            f'<td>{_cv(row, "kaluga")}</td>'
            f'<td>{_cv(row, "shukina")}</td>'
            f'<td><b>{_cv(row, "serpukhov")}</b></td>'
            f'<td>{_cv(row, "kashira")}</td>'
            f'<td>{_cv(row, "kolomna")}</td>'
            f'<td>{_cv(row, "delta_serp_24h")}</td>'
            f'<td>{_cv(row, "temp")}</td>'
            f'<td>{_cv(row, "precip_mm")}</td>'
            f'</tr>'
        )
    t_rows_html = "".join(t_rows) if t_rows else "<tr><td colspan='11'>Нет данных</td></tr>"

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 11: PDF-АРХИВ ОТЧЁТОВ
    # ══════════════════════════════════════════════════════════════════════

    reports_html = ""
    reports_index_path = os.path.join(DOCS_DIR, "reports", "reports_index.json")
    try:
        if os.path.exists(reports_index_path):
            with open(reports_index_path, encoding="utf-8") as rf:
                reports_data = json.load(rf)
            if reports_data:
                cards = ""
                for rpt in reports_data:
                    fname = rpt.get("filename", "")
                    title = rpt.get("title", fname)
                    rdate = rpt.get("date", "")
                    cards += (
                        '<div class="report-card">'
                        '<div class="report-icon">📄</div>'
                        f'<div class="report-title">{title}</div>'
                        f'<div class="report-date">{rdate}</div>'
                        f'<a href="reports/{fname}" target="_blank">Скачать PDF</a>'
                        '</div>'
                    )
                reports_html = (
                    '<h3>📄 Архив бюллетеней</h3>'
                    f'<div class="reports-grid">{cards}</div>'
                )
    except Exception:
        reports_html = ""

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК: Сравнение с МЧС (B2)
    # ══════════════════════════════════════════════════════════════════════

    mchs_html = ""
    mchs_path = os.path.join(DATA_DIR, "mchs_forecast.json")
    try:
        if os.path.exists(mchs_path):
            with open(mchs_path, encoding="utf-8") as mf:
                mchs = json.load(mf)
            mchs_date = mchs.get("date", "")
            # Проверяем что данные не старше 7 дней
            if mchs_date:
                mchs_dt = datetime.strptime(mchs_date, "%Y-%m-%d")
                if (datetime.now() - mchs_dt).days <= 7:
                    mchs_peak = mchs.get("peak_forecast_cm", "?")
                    mchs_peak_date = mchs.get("peak_forecast_date", "?")
                    mchs_source = mchs.get("source", "ЦУГМС")
                    our_peak = pb_level or "?"
                    our_date = pb_date or "?"
                    mchs_html = (
                        '<div class="mchs-compare">'
                        '<h4>📋 Прогноз ЦУГМС vs Наша модель</h4>'
                        '<table>'
                        '<tr><th></th><th>ЦУГМС</th><th>Наша модель</th></tr>'
                        f'<tr><td>Пик</td><td>{mchs_peak} см</td><td>{our_peak} см</td></tr>'
                        f'<tr><td>Дата</td><td>{mchs_peak_date}</td><td>{our_date}</td></tr>'
                        '</table>'
                        f'<p class="mchs-source">Источник: {mchs_source}</p>'
                        '</div>'
                    )
    except Exception:
        mchs_html = ""

    # ══════════════════════════════════════════════════════════════════════
    # Погода сейчас (базовый блок)
    # ══════════════════════════════════════════════════════════════════════

    wt   = weather.get("temp")
    whm  = weather.get("humidity")
    wwm  = weather.get("wind_ms")
    wwd  = wind_dir_str(weather.get("wind_dir", 0))
    wpr  = weather.get("precip_mm", 0) or 0
    wtmax = weather.get("temp_max")
    wtmin = weather.get("temp_min")
    wdesc = weather.get("weather", "")

    basic_weather_html = ""
    if wt is not None:
        basic_weather_html = (
            '<div class="weather-block">'
            '<h3>🌤 Погода сейчас</h3>'
            '<div class="weather-grid">'
            f'<div>🌡 {wt}°C {wdesc}</div>'
            f'<div>min {wtmin} / max {wtmax}</div>'
            f'<div>💧 {wpr} мм</div>'
            f'<div>💨 {wwm} м/с {wwd}</div>'
            f'<div>💦 {whm}%</div>'
            '</div></div>'
        )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 13: ACTION BLOCK (рекомендации для жителей)
    # ══════════════════════════════════════════════════════════════════════

    action_icon, action_title, action_text = generate_action_block(analytics, wext)
    # Цвет border по alert_level
    action_color = alert_color
    action_html = (
        f'<div class="action-block" style="border-left:4px solid {action_color}">'
        f'<h3>{action_icon} {action_title}</h3>'
        f'<p>{action_text}</p>'
        f'<p class="action-meta">Обновлено: {now_str}</p>'
        '</div>'
    )

    # ══════════════════════════════════════════════════════════════════════
    # БЛОК 12: ИНСТРУКЦИЯ С НУЛЯ
    # ══════════════════════════════════════════════════════════════════════

    instruction_html = '''<div class="instruction-block">
  <h2>📖 Как читать эту страницу — инструкция с нуля</h2>

  <div class="instr-section">
    <h4>🌊 Что это за система?</h4>
    <p>OkaFloodMonitor — автоматическая система мониторинга паводка на реке Оке
    в районе Серпухова. Работает 24/7, данные обновляются 4 раза в день
    (08:00, 12:00, 17:00, 20:00 МСК). Автор — Егор Мельников.</p>
  </div>

  <div class="instr-section">
    <h4>📊 Откуда берутся данные?</h4>
    <p><b>Уровни воды</b> — с 7 гидропостов Росгидромета (fishingsib.ru): Орёл, Белёв,
    Калуга, Щукина/Алексин, Серпухов, Кашира, Коломна. Это реальные показания
    автоматических уровнемеров.</p>
    <p><b>Погода</b> — Open-Meteo API: температура, осадки, снежный покров, ветер.
    Факт за 4 дня + прогноз на 4 дня.</p>
    <p><b>PDF-бюллетени</b> — официальные сводки ЦУГМС (Центральное управление
    гидрометеорологической службы).</p>
  </div>

  <div class="instr-section">
    <h4>🔢 Что означают цифры?</h4>
    <p><b>Уровень (см)</b> — высота воды над нулём водомерного поста.
    Серпухов — ключевой пост. При 645 см затапливается пойма.
    При 800 см — дачные участки. При 945 см — вода у фундамента дома.</p>
    <p><b>Δ/сут</b> — изменение уровня за последние 24 часа.
    Положительное = вода поднимается. Отрицательное = вода спадает.</p>
    <p><b>Опасность %</b> — насколько текущий уровень близок к критической
    отметке 945 см (0% = далеко, 100% = достигнут).</p>
  </div>

  <div class="instr-section">
    <h4>🌡 Паводковый индекс погоды</h4>
    <p>Комплексный показатель от 0 до 4, учитывающий: температуру (днём и ночью),
    осадки, снежный покров и Rain-on-Snow (дождь на снег — самый опасный фактор).
    СТАБИЛЬНЫЙ → УМЕРЕННЫЙ → ПОВЫШЕННЫЙ → ВЫСОКИЙ → КРИТИЧЕСКИЙ.</p>
  </div>

  <div class="instr-section">
    <h4>🌊 Паводковая волна</h4>
    <p>Вода движется от верховья к низовью. Если в Орле уровень начал падать —
    значит волна прошла через него и через ~96 часов дойдёт до Серпухова.
    Калуга — промежуточный индикатор (~48 ч до Серпухова).</p>
  </div>

  <div class="instr-section">
    <h4>📈 Три сценария пика</h4>
    <p><b>Оптимистичный</b> — если потепление замедлится и осадков не будет.
    <b>Базовый</b> — при текущем темпе роста.
    <b>Пессимистичный</b> — если потепление усилится + Rain-on-Snow.</p>
  </div>

  <div class="instr-section">
    <h4>📱 Как получать уведомления?</h4>
    <p>1️⃣ Группа «Ока Паводок 🌊» в Telegram — присоединяйтесь.
    2️⃣ Бот @OkaFlood2026EMbot — можно добавить в любую группу.
    3️⃣ Личная рассылка — напишите Егору, добавит в список.</p>
  </div>
</div>'''

    # ══════════════════════════════════════════════════════════════════════
    # ПОЛНЫЙ HTML
    # ══════════════════════════════════════════════════════════════════════

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🌊 ОКА Паводок 2026</title>
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<style>
/* ═══ GLOBAL ═══ */
:root {{ --bg: #0f1923; --card: #1a2635; --border: #2d3748; }}
body {{ font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
        background: var(--bg); color: #e6edf3; margin: 0; padding: 0; }}
h1 {{ color: #fff; margin: 0; padding: 20px 24px; font-size: 1.6em; }}
h3 {{ color: #79c0ff; margin: 12px 0 6px; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 16px; }}
.meta {{ color: #8b949e; font-size: .85em; margin-bottom: 16px; }}

/* ═══ ПОЯСНИТЕЛЬНЫЕ БЛОКИ ═══ */
.explainer {{ background: rgba(255,255,255,0.03); border-left: 3px solid #3498db;
              padding: 10px 14px; margin: 8px 0 16px; font-size: 0.85em;
              color: #8b949e; border-radius: 0 6px 6px 0; }}
.explainer b {{ color: #bdc3c7; }}

/* ═══ GAUGE CARDS ═══ */
.gauges {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }}
.gauge-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
               padding: 12px 16px; min-width: 120px; text-align: center; flex: 1; }}
.gauge-card.main {{ border: 2px solid {alert_color}; background: #1c2128; }}
.gauge-name {{ font-size: .8em; color: #8b949e; margin-bottom: 4px; }}
.gauge-level {{ font-size: 2em; font-weight: 700; color: #e6edf3; }}
.gauge-delta {{ font-size: .9em; color: #3fb950; margin-top: 2px; }}
.gauge-note {{ font-size: .75em; color: #6e7681; margin-top: 4px; }}
.na {{ color: #6e7681; font-size: .7em; }}

/* ═══ DANGER BAR ═══ */
.danger-bar {{ height: 10px; background: #21262d; border-radius: 5px; margin: 12px 0; }}
.danger-fill {{ height: 10px; border-radius: 5px;
                background: linear-gradient(90deg, #3fb950, #d29922, #db6d28, #f85149); }}

/* ═══ ACTION BLOCK (Блок 13) ═══ */
.action-block {{ background: rgba(255,255,255,0.03); border-radius: 0 8px 8px 0;
                padding: 14px 18px; margin: 16px 0; }}
.action-block h3 {{ margin: 0 0 8px; font-size: 1.05em; color: #e6edf3; }}
.action-block p {{ color: #bdc3c7; font-size: 0.9em; margin: 4px 0; line-height: 1.5; }}
.action-meta {{ color: #6e7681; font-size: 0.8em; }}

/* ═══ TABLES ═══ */
table {{ width: 100%; border-collapse: collapse; font-size: .82em; }}
th {{ background: #161b22; color: #8b949e; padding: 6px 8px; text-align: left; }}
td {{ padding: 5px 8px; border-bottom: 1px solid #21262d; }}
.thresh-table td:first-child {{ font-size: 1.1em; }}
.row-green td {{ background: #0d2016; }}
.row-yellow td {{ background: #2a1d00; }}
.row-orange td {{ background: #2a1400; }}
.row-red td {{ background: #2d0000; }}
.row-critical td {{ background: #1a0000; }}

/* ═══ SCENARIO CARDS ═══ */
.scenario-cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 8px 0; }}
.sc-card {{ background: #161b22; border-radius: 8px; padding: 12px; min-width: 120px; text-align: center; flex: 1; }}
.sc-card.green {{ border-left: 3px solid #3fb950; }}
.sc-card.yellow {{ border-left: 3px solid #d29922; }}
.sc-card.red {{ border-left: 3px solid #f85149; }}
.sc-title {{ font-size: .8em; color: #8b949e; }}
.sc-level {{ font-size: 1.6em; font-weight: 700; }}
.sc-date {{ font-size: .8em; color: #6e7681; }}

/* ═══ WEATHER EXTENDED BLOCK ═══ */
.weather-ext-block {{ background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }}
.weather-flood-index {{ border: 2px solid; border-radius: 10px; padding: 14px 18px;
                         margin-bottom: 16px; background: rgba(255,255,255,0.03); }}
.wfi-label {{ font-size: 0.85em; color: #95a5a6; display: block; }}
.wfi-value {{ font-size: 1.6em; font-weight: 900; display: block; margin: 4px 0; }}
.wfi-summary {{ margin: 0; color: #bdc3c7; font-size: 0.95em; }}

.weather-table {{ width: 100%; border-collapse: collapse; font-size: 0.88em; }}
.weather-table th, .weather-table td {{ padding: 6px 8px; text-align: center;
                                         border-bottom: 1px solid var(--border); white-space: nowrap; }}
.weather-table td:first-child {{ text-align: left; color: #95a5a6; }}
td.frost {{ background: rgba(192,57,43,0.25); color: #ff6b6b; font-weight: bold; }}
td.zero {{ background: rgba(243,156,18,0.20); color: #f39c12; }}
td.warm-night {{ background: rgba(39,174,96,0.20); color: #27ae60; }}
td.hot {{ color: #e74c3c; font-weight: bold; }}
td.forecast-col, th.forecast-col {{ background: rgba(52,152,219,0.08);
                                      border-left: 1px dashed #3498db; }}

.weather-commentary {{ margin-top: 14px; }}
.weather-commentary h3 {{ font-size: 1em; margin-bottom: 8px; }}
.weather-commentary ul {{ list-style: none; padding: 0; }}
.weather-commentary li {{ padding: 5px 0; border-bottom: 1px solid var(--border);
                           font-size: 0.9em; color: #bdc3c7; }}

/* ═══ WEATHER BASIC / WAVE / VS2024 ═══ */
.weather-block, .wave-block, .vs2024 {{ background: #161b22; border-radius: 8px;
                                         padding: 12px 16px; margin: 12px 0; }}
.weather-grid {{ display: flex; flex-wrap: wrap; gap: 12px 24px; font-size: .9em; }}
.wave-block {{ border-left: 3px solid #388bfd; color: #79c0ff; }}
.vs2024 {{ border-left: 3px solid #d29922; color: #e3b341; }}

/* ═══ DELTAS BLOCK ═══ */
.deltas-block {{ background: #161b22; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }}
.deltas-block p {{ margin: 4px 0; font-size: 0.9em; }}

/* ═══ REGRESSION BLOCK (ML) ═══ */
.regression-block {{ background: rgba(56,139,253,0.08); border-left: 3px solid #388bfd;
                    border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 12px 0; }}
.regression-block h4 {{ color: #79c0ff; margin: 0 0 6px; font-size: 0.9em; }}
.regression-block p {{ color: #bdc3c7; font-size: 0.88em; margin: 3px 0; }}

/* ═══ MCHS COMPARE ═══ */
.mchs-compare {{ background: rgba(211,153,34,0.08); border-left: 3px solid #d29922;
                border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 12px 0; }}
.mchs-compare h4 {{ color: #e3b341; margin: 0 0 8px; font-size: 0.95em; }}
.mchs-source {{ color: #6e7681; font-size: 0.75em; margin-top: 8px; }}

/* ═══ PDF REPORT CARDS ═══ */
.reports-grid {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0; }}
.report-card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
                padding: 12px 16px; min-width: 200px; text-align: center; }}
.report-icon {{ font-size: 2em; }}
.report-title {{ font-size: .85em; color: #e6edf3; margin: 6px 0; }}
.report-date {{ font-size: .75em; color: #6e7681; margin-bottom: 8px; }}
.report-card a {{ color: #388bfd; text-decoration: none; font-size: .85em; }}

/* ═══ INSTRUCTION BLOCK (Блок 12) ═══ */
.instruction-block {{ background: var(--card); border-radius: 12px; padding: 20px 24px;
                     margin: 20px 0; border: 1px solid var(--border); }}
.instruction-block h2 {{ color: #79c0ff; margin-top: 0; font-size: 1.2em; }}
.instr-section {{ margin: 16px 0; }}
.instr-section h4 {{ color: #e3b341; margin: 0 0 6px; font-size: 0.95em; }}
.instr-section p {{ color: #bdc3c7; font-size: 0.88em; margin: 4px 0; line-height: 1.5; }}

/* ═══ LINKS & FOOTER ═══ */
a {{ color: #388bfd; }}
footer {{ color: #6e7681; font-size: .8em; text-align: center; padding: 20px; }}

/* ═══ МОБИЛЬНАЯ АДАПТАЦИЯ ═══ */
@media (max-width: 768px) {{
  .gauges {{ flex-direction: column; }}
  .gauge-card {{ min-width: 100%; }}
  .scenario-cards {{ flex-direction: column; }}
  .sc-card {{ min-width: 100%; }}
  .reports-grid {{ flex-direction: column; }}
  .report-card {{ min-width: 100%; }}
  h1 {{ font-size: 1.1em; padding: 14px 12px; }}
  .container {{ padding: 8px; }}
  .weather-flood-index {{ padding: 10px 12px; }}
  .wfi-value {{ font-size: 1.3em; }}
  .instruction-block {{ padding: 14px 12px; }}
}}
@media (max-width: 480px) {{
  .gauge-level {{ font-size: 1.5em; }}
  .sc-level {{ font-size: 1.3em; }}
  .weather-table {{ font-size: 0.75em; }}
}}
</style>
</head>
<body>

<!-- ═══ HEADER ═══ -->
<h1 style="background:{alert_color}">
  🌊 ПАВОДОК ОКА 2026 &nbsp; {alert_em} &nbsp; {s if s is not None else "н/д"} см &nbsp;|&nbsp; ⚠️{danger_pct:.0f}%
</h1>

<div class="container">
<p class="meta">Обновлено: {now_str} | Источник: fishingsib.ru</p>

<!-- ═══ БЛОК 1: БОЛЬШИЕ ЦИФРЫ ═══ -->
<h3>📊 7 гидропостов Оки</h3>
<div class="gauges">
{gauges_html}
</div>
{river_map_html}
{tributaries_html}
<div class="explainer">
  <b>Что означают цифры?</b> Уровень воды (см) на 7 гидропостах Оки —
  от Орла (верховье) до Коломны (низовье). Паводковая волна идёт сверху вниз:
  Орёл → Серпухов за ~96 часов. Δ/сут = изменение за последние 24ч.
  🟢 Серпухов — наш ключевой пост (дом в зоне затопления при 945 см).
</div>

<!-- ═══ БЛОК 2: DANGER BAR ═══ -->
<div class="danger-bar"><div class="danger-fill" style="width:{pct}%"></div></div>

<!-- ═══ БЛОК 13: ACTION BLOCK (ЧТО ДЕЛАТЬ ПРЯМО СЕЙЧАС) ═══ -->
{action_html}

<!-- ═══ БЛОК 3: ПОРОГИ КИМ ═══ -->
<h3>🚨 Пороги КИМ (Серпухов)</h3>
<div style="overflow-x:auto">
<table class="thresh-table">
<tr><th>🎯</th><th>Порог</th><th>Название</th><th>До порога</th></tr>
{thresh_rows}
</table>
</div>
<div class="explainer">
  <b>КИМ-пороги</b> — контрольные уровни по Серпухову.
  500 см — весенний подъём; 645 — пойма затапливается;
  800 — дачные участки; 920 — пик 2024 года;
  945 — вода у фундамента дома; 965 — подвал.
</div>

<!-- ═══ БЛОК 4: СЦЕНАРИИ ПИКА ═══ -->
<h3>📈 Сценарии пика</h3>
{scenario_html}

<!-- ═══ БЛОК 5: РАСШИРЕННЫЙ БЛОК ПОГОДЫ ═══ -->
{weather_ext_html}

<!-- ═══ БЛОК 6: ВОЛНОВОЙ ПРОГНОЗ ═══ -->
{wave_html}

<!-- ═══ БЛОК 7: vs 2024 ═══ -->
{vs24_html}

<!-- ═══ БЛОК 8: INSIGHTS ═══ -->
<h3>🧠 Аналитика</h3>
<ul>{ins_html}</ul>

<!-- ═══ ML-РЕГРЕССИЯ ═══ -->
{regression_html}

<!-- ═══ СРАВНЕНИЕ С МЧС ═══ -->
{mchs_html}

<!-- ═══ БЛОК 9: ДЕЛЬТЫ И РАССТОЯНИЯ ═══ -->
{deltas_html}

<!-- ═══ ПОГОДА СЕЙЧАС (базовый блок) ═══ -->
{basic_weather_html}

<!-- ═══ БЛОК 10: ТАБЛИЦА ИСТОРИИ ═══ -->
<h3>📋 История (последние 50 записей)</h3>
<div style="overflow-x:auto">
<table>
<tr>
  <th>Дата/время</th><th>Орёл</th><th>Белёв</th><th>Калуга</th><th>Щукина</th>
  <th>Серпухов</th><th>Кашира</th><th>Коломна</th><th>Δ/сут</th><th>T°</th><th>Осадки</th>
</tr>
{t_rows_html}
</table>
</div>

<!-- ═══ БЛОК 11: PDF-АРХИВ ОТЧЁТОВ ═══ -->
{reports_html}

<!-- ═══ БЛОК 12: ИНСТРУКЦИЯ С НУЛЯ ═══ -->
{instruction_html}

<!-- ═══ FOOTER ═══ -->
<footer>
OkaFloodMonitor v5.0 | 54.834050, 37.742901<br>
<a href="https://fishingsib.ru">fishingsib.ru</a> |
<a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

</div>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════════════════════
# 23. MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    printf("=" * 60)
    printf("OkaFloodMonitor v5.0 | %s", datetime.now().isoformat())
    printf("=" * 60)

    # 1. Данные
    levels  = fetch_all_levels()
    weather = fetch_weather()
    wext    = fetch_weather_extended()
    history = load_history()
    alerts  = load_alerts()
    ref_2024 = load_2024_ref()

    # 1a. Притоки (если настроены)
    extra_levels = {}
    if EXTRA_STATIONS:
        extra_levels = fetch_extra_levels()

    # 2. Аналитика
    analytics = compute_analytics(levels, history, weather)
    printf("alert=%s, ds24=%s, days945=%s, danger=%.1f%%",
           analytics.get("alert_level"), analytics.get("ds24"),
           analytics.get("days_to_945"), analytics.get("danger_pct", 0))

    # 2a. ML-регрессия
    regression = compute_simple_regression(history)

    # 3. Сохраняем историю (CSV с 26 колонками)
    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "datetime":             now_iso,
        "orel":                 levels.get("orel", ""),
        "belev":                levels.get("belev", ""),
        "kaluga":               levels.get("kaluga", ""),
        "shukina":              levels.get("shukina", ""),
        "serpukhov":            levels.get("serpukhov", ""),
        "kashira":              levels.get("kashira", ""),
        "kolomna":              levels.get("kolomna", ""),
        "delta_serp_24h":       analytics.get("ds24", ""),
        "delta_serp_48h":       analytics.get("ds48", ""),
        "delta_orel_24h":       analytics.get("do24", ""),
        "delta_kaluga_24h":     analytics.get("dk24", ""),
        "temp":                 weather.get("temp", ""),
        "humidity":             weather.get("humidity", ""),
        "wind_ms":              weather.get("wind_ms", ""),
        "wind_dir":             weather.get("wind_dir", ""),
        "clouds":               weather.get("clouds", ""),
        "precip_mm":            weather.get("precip_mm", ""),
        "alert_level":          analytics.get("alert_level", ""),
        "forecast_days_to_945": analytics.get("days_to_945", ""),
        "forecast_days_to_peak": analytics.get("peak_base_days", ""),
        "scenario_base_peak":   analytics.get("peak_base_level", ""),
        "scenario_base_date":   analytics.get("peak_base_date", ""),
        "notes":                "",
        "snow_depth_cm":        wext.get("snow_depth_cm", "") if wext else "",
        "flood_weather_index":  wext.get("flood_index", "") if wext else "",
    }
    history.append(row)
    save_history(history)
    printf("History saved: %d rows", len(history))

    # 4. KIM алерты (dedup с cooldown)
    triggered = check_kim_triggers(levels, analytics, alerts)
    for key, text in triggered:
        printf("KIM trigger: %s", key)
        tg_send(CHAT_ADMIN, text)
        if any(str(t) in key for t in [645, 800, 920, 945, 965]):
            tg_send(CHAT_MY_GROUP, text)
        alerts[key] = datetime.now().isoformat()
    if triggered:
        save_alerts(alerts)

    # Watchdog T10: Серпухов None > 6ч
    serp_val = levels.get("serpukhov")
    if serp_val is None:
        key = "WATCHDOG_SERP"
        if should_send_alert(alerts, key, cooldown_h=6):
            tg_send(CHAT_ADMIN,
                    "❌ <b>WATCHDOG</b>: Серпухов не отвечает! "
                    "Проверить fishingsib.ru / allrivers.info")
            alerts[key] = datetime.now().isoformat()
            save_alerts(alerts)

    # Watchdog TOTAL: все 7 = None (НОВОЕ v5!)
    all_none = all(levels.get(k) is None for k in STATION_KEYS)
    if all_none:
        key = "WATCHDOG_TOTAL"
        if should_send_alert(alerts, key, cooldown_h=6):
            tg_send(CHAT_ADMIN,
                    "🚨 <b>WATCHDOG TOTAL</b>: Все 7 станций не отвечают!\n"
                    "Возможен сбой источника данных fishingsib.ru.\n"
                    "Проверьте вручную: https://allrivers.info")
            alerts[key] = datetime.now().isoformat()
            save_alerts(alerts)

    # Превентивный погодный алерт (НОВОЕ v5!)
    if wext and serp_val is not None and serp_val < NORM_LEVEL:
        fi = wext.get("flood_index", 0)
        if fi >= 3:
            key = f"WEATHER_ALERT_{fi}"
            if should_send_alert(alerts, key, cooldown_h=12):
                label = wext.get("flood_label", "")
                summary = wext.get("flood_summary", "")
                msg = (f"🌧️ <b>[ПРОГНОЗ ПОГОДЫ]</b> Паводковый индекс: "
                       f"<b>{label}</b> ({fi}/4)\n\n"
                       f"{summary}\n\n"
                       "⚠️ Вода пока спокойна, но погодные условия "
                       "указывают на возможный резкий подъём уровня "
                       "в ближайшие 2–3 дня.\n\n"
                       "Следите за обновлениями!")
                tg_send(CHAT_ADMIN, msg)
                tg_send(CHAT_MY_GROUP, msg)
                alerts[key] = datetime.now().isoformat()
                save_alerts(alerts)

    # 5. Heartbeat → ADMIN + MY_GROUP
    heartbeat = format_heartbeat(levels, analytics, weather, wext)
    printf("Heartbeat: %s…", heartbeat[:100].replace("\n", " "))
    tg_send(CHAT_ADMIN, heartbeat)
    tg_send(CHAT_MY_GROUP, heartbeat)

    # 6. Digest → ADMIN (всегда)
    digest = format_digest(levels, analytics, weather, history, wext)
    printf("Digest: %s…", digest[:100].replace("\n", " "))
    tg_send(CHAT_ADMIN, digest)

    # T4: ≥645 → в группу тоже digest
    if (serp_val is not None and serp_val >= POYMA_LEVEL) or \
       analytics.get("alert_level") in ("ORANGE", "RED", "CRITICAL"):
        tg_send(CHAT_MY_GROUP, digest)

    # NEIGHBORS: УПРОЩЁННЫЙ digest в 08 и 20 MSK (НОВОЕ v5!)
    msk_hour = (datetime.now(timezone.utc) + timedelta(hours=3)).hour
    neighbors_digest = format_neighbors_digest(levels, analytics, weather, wext)
    if CHAT_NEIGHBORS and msk_hour in (8, 20):
        tg_send(CHAT_NEIGHBORS, neighbors_digest)

    # Персональная рассылка (НОВОЕ v5!)
    if msk_hour in (8, 20):
        for cid in load_mailing_list():
            tg_send(cid, neighbors_digest)

    # 7. Group draft (ПЕРЕПИСАН — от первого лица Егора + wext)
    group_draft = format_group_draft(levels, analytics, wext)
    with open(GROUP_DRAFT, "w", encoding="utf-8") as f:
        f.write(group_draft)
    printf("Group draft → %s", GROUP_DRAFT)

    # 8. HTML + JSON
    html = generate_html(levels, analytics, weather, history, wext,
                         ref_2024=ref_2024, regression=regression,
                         extra_levels=extra_levels)
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    printf("HTML → %s (%d bytes)", INDEX_HTML, len(html))

    data_out = {
        "updated": now_iso,
        "levels": levels,
        "analytics": {
            k: analytics.get(k) for k in (
                "ds24", "ds48", "do24", "dk24",
                "alert_level", "danger_pct",
                "days_to_945", "date_to_945",
                "peak_base_level", "peak_base_date", "peak_base_days",
                "peak_opt_level", "peak_opt_date",
                "peak_pess_level", "peak_pess_date",
                "wave_msg", "insights",
                "serp_2024", "vs_2024",
            )
        },
        "weather": weather,
        "weather_extended": {
            k: wext.get(k) for k in (
                "flood_index", "flood_label", "flood_color",
                "flood_summary", "snow_depth_cm", "commentary",
            )
        } if wext else None,
        "regression": regression,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    printf("JSON → %s", DATA_JSON)

    # 9. Status file
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(f"{analytics.get('alert_level')} | {serp_val or 'н/д'} | {now_iso}")
    printf("Status → %s", STATUS_FILE)

    printf("=" * 60)
    printf("OkaFloodMonitor v5.0 — DONE")
    printf("=" * 60)


if __name__ == "__main__":
    main()
