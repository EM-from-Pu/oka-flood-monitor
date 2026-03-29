#!/usr/bin/env python3
"""
monitor.py v7.0 — OkaFloodMonitor
HTML-генерация + аналитика + Telegram-оповещения
Источники: serpuhov.ru (PRIMARY) | КИМ API | ЦУГМС | Open-Meteo | GloFAS

v7 changelog:
- Glassmorphism UI + Inter font
- Composite Status hero (4 sub-indicators + verdict banner)
- Forecast Hydrograph (Chart.js, 2 оси, НЯ/ОЯ аннотации, «СЕЙЧАС»)
- GloFAS station cards с inline SVG sparklines, flood ratio, пик
- Wave Arrival CSS Timeline
- Исправлены баги: GREEN→НОРМА, action block через composite, X-ось графика
- HISTORY_COLS расширен на 6 GloFAS колонок
- data.json расширен секцией glofas
- TG: heartbeat+GloFAS, digest+upstream, neighbors+wave arrival
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


def compute_analytics(serp: dict, kim: dict, cugms: dict, history: list, wext) -> dict:
    """
    Собирает всю аналитику в один словарь.
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

    # Дней до порогов
    days_to_nya = None
    days_to_oya = None
    if change_cm and change_cm > 0 and nya_remaining_m is not None:
        change_m_per_day = change_cm / 100.0
        days_to_nya = round(nya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None
        days_to_oya = round(oya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None

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
        "alert_level":      alert_level,
        "days_to_nya":      days_to_nya,
        "days_to_oya":      days_to_oya,
        "nya_remaining_m":  nya_remaining_m,
        "oya_remaining_m":  oya_remaining_m,
        "nya_fill_pct":     round(nya_fill_pct, 1),
        "oya_fill_pct":     round(oya_fill_pct, 1),
        "wave_dynamic_text": wave_text,
        "peak_prediction":  peak,
        "notes":            notes,
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
            "Уровень воды в норме. Продолжайте следить за дашбордом 1–2 раза в день. "
            "При приближении к НЯ — перейдите в режим бдительности. "
            "Проверьте наличие насоса, убедитесь в доступности дачи.",
            "#10b981",
        ),
        "watch": (
            "🟡",
            "Бдительность — Готовность к действиям",
            "Уровень повышается или GloFAS фиксирует рост выше по течению. "
            "Следите за дашбордом каждые 3–4 часа. Подготовьте список имущества для эвакуации. "
            "Проверьте насос и дренажную систему. Уточните прогноз ЦУГМС.",
            "#f59e0b",
        ),
        "warning": (
            "🟠",
            "Опасность — Подготовьтесь немедленно",
            "Уровень быстро растёт и/или GloFAS прогнозирует пик в ближайшие дни. "
            "Вывезите ценные вещи с нижнего этажа. Подготовьте дом к затоплению. "
            "Договоритесь о временном жилье. Мониторинг каждый час. "
            "Зарядите телефон, подготовьте документы.",
            "#f97316",
        ),
        "danger": (
            "🔴",
            "Критично — Действуйте прямо сейчас",
            "Уровень достиг критических значений. Высокий риск затопления. "
            "Немедленно эвакуируйте людей, животных, ценное имущество. "
            "Отключите электричество на даче. Свяжитесь с соседями. "
            "Следите за каналом соседей в Telegram. Будьте готовы к полному подтоплению.",
            "#ef4444",
        ),
        "emergency": (
            "🟣",
            "ЧРЕЗВЫЧАЙНАЯ СИТУАЦИЯ",
            "Уровень превысил ОЯ (394 см). Массовое затопление. "
            "Все должны быть эвакуированы. Не пытайтесь добраться до дачи без необходимости. "
            "Звоните 112. Фиксируйте ущерб фото/видео для страховки. "
            "Ждите официальных сводок от МЧС.",
            "#a855f7",
        ),
        "unknown": (
            "⚪",
            "Нет данных",
            "Данные временно недоступны. Проверьте serpuhov.ru вручную. "
            "При необходимости позвоните в ЕДДС Серпухова.",
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
    """Возвращает полный CSS v7 (glassmorphism + Inter + 5-level colors)."""
    return """
/* ═══════════════════════════════════════════════════════════════
   OkaFloodMonitor v7 Design System — Glassmorphism Dark Theme
   ═══════════════════════════════════════════════════════════════ */
:root {
  --safe:      #10b981;
  --watch:     #f59e0b;
  --warning:   #f97316;
  --danger:    #ef4444;
  --emergency: #a855f7;
  --accent:    #3b82f6;

  --bg-primary: #0c1222;
  --bg-card: rgba(17, 25, 40, 0.75);
  --bg-card-hover: rgba(17, 25, 40, 0.9);
  --bg-glass: rgba(255, 255, 255, 0.04);

  --border: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.15);

  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-dim: #64748b;

  --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.2);
  --shadow-glow-safe:      0 0 20px rgba(16, 185, 129, 0.25);
  --shadow-glow-watch:     0 0 20px rgba(245, 158, 11, 0.25);
  --shadow-glow-warning:   0 0 20px rgba(249, 115, 22, 0.25);
  --shadow-glow-danger:    0 0 20px rgba(239, 68, 68, 0.25);
  --shadow-glow-emergency: 0 0 20px rgba(168, 85, 247, 0.25);
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
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── CARD ────────────────────────────────────────────────────── */
.card {
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: var(--shadow-card);
  transition: all 0.3s ease;
}
.card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
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
  z-index: 100;
  background: rgba(12, 18, 34, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
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
.header-nav {
  display: flex;
  gap: 4px;
  list-style: none;
}
.header-nav a {
  display: block;
  padding: 6px 14px;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.88rem;
  font-weight: 500;
  transition: all 0.2s ease;
}
.header-nav a:hover, .header-nav a.active {
  background: var(--bg-glass);
  color: var(--text-primary);
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
}
.hero-section::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 0%, rgba(59,130,246,0.12) 0%, transparent 70%);
  pointer-events: none;
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
  font-size: clamp(3.5rem, 8vw, 6rem);
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1;
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
.therm-mark-cur { background: var(--text-primary); height: 3px; }
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
  grid-template-columns: repeat(4, 1fr);
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.info-card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.85rem 0.65rem;
  text-align: center;
  transition: border-color 0.2s, transform 0.2s;
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
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  width: 100%;
  max-width: 800px;
}
.sub-indicator {
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.3s ease;
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
  background: rgba(255,255,255,0.08);
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
  backdrop-filter: blur(12px);
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
  backdrop-filter: blur(12px);
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
}
.station-card:hover {
  background: var(--bg-card-hover);
  border-color: var(--border-hover);
  transform: translateY(-2px);
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
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 16px;
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
  background: rgba(255,255,255,0.08);
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
  background: var(--bg-primary);
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
  backdrop-filter: blur(12px);
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
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 16px 20px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  border-left: 3px solid;
}
.wfi-label { font-size: 0.82rem; color: var(--text-dim); font-weight: 500; }
.wfi-value { font-size: 1.1rem; font-weight: 700; }
.wfi-summary { color: var(--text-secondary); font-size: 0.85rem; flex: 1; min-width: 200px; }

/* ── ACCORDION SECTIONS ────────────────────────────────────────── */
.accordion-section { padding: 0 24px 8px; }
.accordion-header {
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.95rem;
  transition: all 0.2s ease;
  user-select: none;
}
.accordion-header:hover { background: var(--bg-card-hover); }
.accordion-body {
  display: none;
  background: var(--bg-card);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-top: none;
  border-radius: 0 0 12px 12px;
  padding: 20px;
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
.weather-table .forecast-col { background: rgba(59,130,246,0.05); }
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
#histTable th { color: var(--text-dim); font-size: 0.72rem; font-weight: 600; }
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
  padding: 6px 10px; background: var(--bg-glass);
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
  background: rgba(255,255,255,0.03); border-left: 3px solid var(--accent);
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
  background: var(--bg-glass); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; min-width: 200px; flex: 1;
}
.report-meta { font-size: 0.75rem; color: var(--text-dim); margin-top: 4px; }

/* ── FOOTER ────────────────────────────────────────────────────── */
.site-footer {
  background: rgba(12, 18, 34, 0.8);
  border-top: 1px solid var(--border);
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
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  margin: 12px 0;
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

@media (max-width: 480px) {
  .sub-indicators { grid-template-columns: 1fr 1fr; }
  .header-nav { display: none; }
  .header-right { gap: 6px; }
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: HEADER v7
# ══════════════════════════════════════════════════════════════════════════════

def _generate_header_v7(serp: dict, kim: dict, cugms: dict, glofas: dict,
                         now_msk: str) -> str:
    """Генерирует sticky header с лого, навигацией, часами, бейджами."""
    src_stat    = serp.get("source_status", "unavailable")
    kim_stat    = (kim.get("_api_status") or "unavailable")
    glofas_stat = (glofas or {}).get("_status", "unavailable")

    def _badge(label, status):
        cls = "ok" if status == "ok" else ("cached" if status in ("cached", "partial") else "unavailable")
        return f'<span class="source-badge {cls}">{_h(label)}</span>'

    return f"""
<header class="site-header">
  <div class="header-logo">🌊 <span>Oka</span>FloodMonitor</div>

  <nav>
    <ul class="header-nav">
      <li><a href="index.html" class="active">Главная</a></li>
      <li><a href="links.html">Ссылки</a></li>
      <li><a href="instructions.html">Инструкции</a></li>
    </ul>
  </nav>

  <div class="header-right">
    <span class="clock-display" id="clock">--:--:-- МСК</span>
    <span style="color:var(--text-dim); font-size:0.72rem;">обн. {_h(now_msk)}</span>
    {_badge("serp", src_stat)}
    {_badge("kim", kim_stat)}
    {_badge("GloFAS", glofas_stat)}
  </div>
</header>"""


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

    def _si_html(label, icon, status_label, value, color):
        return f"""
  <div class="sub-indicator">
    <div class="si-label">{_h(label)}</div>
    <div class="si-status" style="color:{color};">{icon} {_h(status_label)}</div>
    <div class="si-value">{_h(value)}</div>
  </div>"""

    si_html  = _si_html("Уровень",       ZONE_ICONS.get(level_comp.get("zone", "unknown"), "⚪"),
                          level_comp.get("label", "—"), level_comp.get("value", "—"),
                          level_comp.get("color", "#64748b"))
    si_html += _si_html("Тренд",         ZONE_ICONS.get(trend_comp.get("zone", "unknown"), "⚪"),
                          trend_comp.get("label", "—"), trend_comp.get("value", "—"),
                          trend_comp.get("color", "#64748b"))
    si_html += _si_html("Прогноз GloFAS", ZONE_ICONS.get(glofas_comp.get("zone", "unknown"), "⚪"),
                          glofas_comp.get("label", "—"), glofas_comp.get("value", "—"),
                          glofas_comp.get("color", "#64748b"))
    si_html += _si_html("Погода",        ZONE_ICONS.get(weather_comp.get("zone", "unknown"), "⚪"),
                          weather_comp.get("label", "—"), weather_comp.get("value", "—"),
                          weather_comp.get("color", "#64748b"))

    verdict_color = verdict.get("color", "#64748b")
    verdict_label = verdict.get("label", "⚪ НЕТ ДАННЫХ")
    verdict_banner = f"""
<div class="verdict-banner" style="background: {verdict_color}18; border-color: {verdict_color}40; color: {verdict_color};">
  {_h(verdict_label)}
</div>"""

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

    # ── Данные для мини-карточек ─────────────────────────────────
    snow_cm   = (wext or {}).get("snow_depth_cm", 0) or 0
    change_cm = serp.get("daily_change_cm")
    change_str = f"{change_cm:+.0f}" if change_cm is not None else "—"
    change_lbl = "рост" if change_cm and change_cm > 0 else ("спад" if change_cm and change_cm < 0 else "стабильно")

    days_nya_val = analytics.get("days_to_nya")
    days_nya_card = f"{days_nya_val:.0f}" if days_nya_val and days_nya_val < 200 else "—"

    fl_idx = (wext or {}).get("flood_index", 0) or 0
    fl_label_short = {0: "минимальный", 1: "низкий", 2: "умеренный", 3: "высокий", 4: "экстремальный"}.get(fl_idx, "?")

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
        <div class="thermometer-wrap">
          <div class="therm-labels">
            <div class="therm-label therm-oya" style="bottom:{therm_oya_pct:.1f}%;" title="{_h(oya_explained)}">
              <span class="therm-tag danger">ОЯ {oya_cm:.0f}</span>
            </div>
            <div class="therm-label therm-nya" style="bottom:{therm_nya_pct:.1f}%;" title="{_h(nya_explained)}">
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
          <div class="level-number {zone_css}" title="Уровень воды от нуля гидропоста д. Лукьяново (нуль поста = {LUKYANNOVO_ZERO_M_BS:.2f} м БС)">{_h(level_str)}</div>
          <div class="level-explain">уровень от нуля поста д. Лукьяново</div>
          <div class="level-label">р. Ока{_h(water_str)}</div>
          {f'<div class="level-abs" title="Абсолютная отметка уровня в Балтийской системе высот">{_h(abs_str)}</div>' if abs_str else ''}
        </div>

        <div class="sub-indicators">
          {si_html}
        </div>

        {verdict_banner}
      </div>

    </div>

    <!-- Мини-карточки инфографики -->
    <div class="info-cards-row">
      <div class="info-card">
        <div class="ic-icon">❄️</div>
        <div class="ic-value">{snow_cm:.0f} <span class="ic-unit">см</span></div>
        <div class="ic-title">Снежный покров</div>
        <div class="ic-hint">запас воды в снеге (SWE) по Open-Meteo</div>
      </div>
      <div class="info-card">
        <div class="ic-icon">📈</div>
        <div class="ic-value">{change_str} <span class="ic-unit">см/сут</span></div>
        <div class="ic-title">Прирост уровня</div>
        <div class="ic-hint">скорость изменения за последние сутки — {change_lbl}</div>
      </div>
      <div class="info-card">
        <div class="ic-icon">⏳</div>
        <div class="ic-value">{days_nya_card} <span class="ic-unit">дней</span></div>
        <div class="ic-title">До НЯ</div>
        <div class="ic-hint">при текущем темпе прироста до уровня {nya_cm:.0f} см</div>
      </div>
      <div class="info-card">
        <div class="ic-icon">🌧️</div>
        <div class="ic-value">{fl_idx}/4</div>
        <div class="ic-title">Паводковый индекс</div>
        <div class="ic-hint">{fl_label_short} — комплексная оценка осадков и таяния</div>
      </div>
    </div>

    <!-- Прогресс-бары -->
    <div class="progress-bars">
      <div class="progress-item">
        <div class="pi-label" title="{_h(nya_explained)}">До НЯ {nya_cm:.0f} см <span class="pi-q" title="Неблагоприятное гидрологическое явление — подтопление пойменных территорий">?</span></div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill nya" style="width:{nya_fill_pct:.1f}%;"></div>
        </div>
        <div class="pi-value">{_h(nya_rem_str)}{_h(nya_days_str)}</div>
      </div>
      <div class="progress-item">
        <div class="pi-label" title="{_h(oya_explained)}">До ОЯ {oya_cm:.0f} см <span class="pi-q" title="Опасное гидрологическое явление — затопление дорог и построек">?</span></div>
        <div class="progress-bar-track">
          <div class="progress-bar-fill oya" style="width:{oya_fill_pct:.1f}%;"></div>
        </div>
        <div class="pi-value">{_h(oya_rem_str)}{_h(oya_days_str)}</div>
      </div>
    </div>

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

    html = '<section class="stations-section fade-in-section">\n'
    html += '<h2>↑ Бассейн Оки по течению</h2>\n'
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

        html += f"""
<div class="{card_classes}">
  <div class="sc-name">{_h(name)}</div>
  <div class="sc-river">{_h(river)}</div>
  <div class="sc-value" style="color: {'var(--accent)' if is_main else 'var(--text-primary)'};">
    {_h(val_str)}
  </div>
  <div class="sc-sparkline">{sparkline}</div>
  <div class="sc-trend">
    {_h(trend_arr)}
    <span class="sc-badge {fr_cls}">{_h(fr_label)}</span>
  </div>
  {f'<div class="sc-peak">{_h(peak_str)}</div>' if peak_str else ''}
  {f'<div class="sc-travel">{_h(wave_label)}</div>' if wave_label else ''}
</div>
"""
        if slug != "kashira":
            html += '<div class="station-arrow">›</div>\n'

    html += '</div>\n</section>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# HTML: WAVE ARRIVAL TIMELINE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_wave_timeline(glofas: dict) -> str:
    """
    Генерирует CSS-only горизонтальный timeline прихода паводковой волны.
    Показывает: сегодня → +16 дней. Маркеры: пики станций + прибытие в Серпухов.
    """
    if not glofas or glofas.get("_status") not in ("ok", "partial", "cached"):
        return ""

    today  = datetime.now(timezone.utc).date()
    end_dt = today + timedelta(days=16)
    total_range_days = 16

    events = []

    STATION_ORDER  = ["orel", "mtsensk", "belev", "kozelsk", "kaluga", "aleksin", "tarusa"]
    STATION_COLORS = {
        "orel":    "#64748b",
        "mtsensk": "#94a3b8",
        "belev":   "#3b82f6",
        "kozelsk": "#6366f1",
        "kaluga":  "#f59e0b",
        "aleksin": "#f97316",
        "tarusa":  "#ef4444",
    }

    for slug in STATION_ORDER:
        st = glofas.get(slug, {})
        if st.get("source_status") != "ok":
            continue
        peak_date = st.get("peak_date")
        wave = st.get("wave_arrival_serpukhov")
        if not peak_date:
            continue

        try:
            peak_dt = datetime.strptime(peak_date, "%Y-%m-%d").date()
        except Exception:
            continue

        if today <= peak_dt <= end_dt:
            offset_days = (peak_dt - today).days
            pct = offset_days / total_range_days * 100
            events.append({
                "name":  st.get("name", slug),
                "date":  peak_date,
                "pct":   min(95, max(2, pct)),
                "color": STATION_COLORS.get(slug, "#64748b"),
                "type":  "peak",
                "label": f"пик {peak_dt.day}.{peak_dt.month:02d}",
            })

        if wave:
            try:
                arr_dt = datetime.strptime(wave["earliest"], "%Y-%m-%d").date()
                if today <= arr_dt <= end_dt:
                    offset_days = (arr_dt - today).days
                    pct = offset_days / total_range_days * 100
                    events.append({
                        "name":  f"↓Серпухов ({st.get('name', slug)})",
                        "date":  wave["earliest"],
                        "pct":   min(95, max(2, pct)),
                        "color": "#10b981",
                        "type":  "arrival",
                        "label": f"прибытие {arr_dt.day}.{arr_dt.month:02d}",
                    })
            except Exception:
                pass

    if not events:
        return ""

    markers_html = ""
    for ev in events:
        dot_size   = "16px" if ev["type"] == "arrival" else "10px"
        bg_style   = f"background:{ev['color']};" if ev["type"] == "arrival" else ""
        markers_html += f"""
<div class="timeline-marker" style="left:{ev['pct']:.1f}%;">
  <div class="timeline-dot" style="width:{dot_size}; height:{dot_size};
    border-color:{ev['color']}; {bg_style}"></div>
  <div class="timeline-marker-label" style="color:{ev['color']};">{_h(ev['label'])}</div>
  <div class="timeline-marker-name">{_h(ev['name'])}</div>
</div>"""

    date_labels = ""
    for i in [0, 4, 8, 12, 16]:
        d   = today + timedelta(days=i)
        pct = i / total_range_days * 100
        date_labels += f"""
<div style="position:absolute; left:{pct:.1f}%; transform:translateX(-50%);
  font-size:0.65rem; color:var(--text-dim); bottom:-20px; white-space:nowrap;">
  {d.day}.{d.month:02d}
</div>"""

    return f"""
<section class="timeline-section fade-in-section">
  <div class="timeline-card">
    <h3>⏱ Прогноз прихода волны в Серпухов</h3>
    <div class="timeline-bar-container">
      <div class="timeline-track" style="position:relative;">
        {markers_html}
        {date_labels}
      </div>
    </div>
    <p style="font-size:0.75rem; color:var(--text-dim); margin-top:28px;">
      🟢 зелёные маркеры = расчётное прибытие волны в Серпухов | серые/цветные = пик на станции
    </p>
  </div>
</section>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: ACTION SECTION
# ══════════════════════════════════════════════════════════════════════════════

def _generate_action_section(icon: str, title: str, text: str, color: str) -> str:
    """Генерирует action block в glassmorphism стиле."""
    return f"""
<section class="action-section">
  <div class="action-card" style="border-left-color: {color};">
    <div class="action-icon">{icon}</div>
    <div class="action-title" style="color: {color};">{_h(title)}</div>
    <div class="action-text">{_h(text)}</div>
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
  <div style="font-size:0.82rem; color:var(--text-dim);">Снежный покров: {snow_d:.0f} см</div>
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

    return f"""
<section class="weather-section fade-in-section">
  <div class="accordion-header" onclick="toggleAccordion('weatherAcc')">
    ☁️ Погода и паводковый индекс
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

    return f"""
<div class="history-controls">
  <button onclick="filterHistory(7)"  class="hist-btn">7 дней</button>
  <button onclick="filterHistory(30)" class="hist-btn">30 дней</button>
  <button onclick="filterHistory(0)"  class="hist-btn">Всё</button>
  <a href="history.csv" download class="hist-btn">⬇ CSV</a>
</div>
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
</div>"""


def _generate_reports_section() -> str:
    """Генерирует секцию PDF-архива из reports_index.json."""
    reports_index_path = os.path.join(DOCS_DIR, "reports", "reports_index.json")
    try:
        with open(reports_index_path, "r", encoding="utf-8") as f:
            reports = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        reports = []

    if not reports:
        return ""

    cards_html = ""
    for rep in reports[-10:]:
        filename = rep.get("filename", "")
        title    = _h(rep.get("title", filename))
        date_str = _h(rep.get("date", ""))
        size_str = _h(rep.get("size", ""))
        link     = f"reports/{filename}"
        cards_html += f"""
<div class="report-card">
  <a href="{_h(link)}" target="_blank">📄 {title}</a>
  <div class="report-meta">{date_str} {size_str}</div>
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

    reports_acc = ""
    if reports_html:
        reports_acc = f"""
<div class="accordion-section">
  <div class="accordion-header" onclick="toggleAccordion('reportsAcc')">
    📁 PDF-архив обзоров
    <span class="toggle-icon" id="reportsAcc-icon">▼</span>
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
  var msk = new Date(now.getTime() + (3 * 60 - now.getTimezoneOffset()) * 60000);
  var h = String(msk.getUTCHours()).padStart(2,'0');
  var m = String(msk.getUTCMinutes()).padStart(2,'0');
  var s = String(msk.getUTCSeconds()).padStart(2,'0');
  var el = document.getElementById('clock');
  if (el) el.textContent = h + ':' + m + ':' + s + ' МСК';
}
setInterval(updateClock, 1000);
updateClock();

// ── ACCORDION ─────────────────────────────────────────────────────────
function toggleAccordion(id) {
  var body = document.getElementById(id);
  var icon = document.getElementById(id + '-icon');
  if (!body) return;
  var isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  if (icon) icon.textContent = isOpen ? '▼' : '▲';
}

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
"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: FOOTER
# ══════════════════════════════════════════════════════════════════════════════

def _generate_footer(now_msk: str) -> str:
    """Генерирует footer."""
    return f"""
<footer class="site-footer">
  OkaFloodMonitor v7.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS Flood API<br>
  Обновлено: {_h(now_msk)} МСК |
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: ГЛАВНЫЙ ГЕНЕРАТОР
# ══════════════════════════════════════════════════════════════════════════════

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

  {details_html}
</main>

{footer_html}

<script>
{js_html}
</script>

</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# LINKS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _generate_links_css() -> str:
    """CSS для страниц links и instructions — использует базовый дизайн v7."""
    return """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --safe:      #10b981;
  --watch:     #f59e0b;
  --warning:   #f97316;
  --danger:    #ef4444;
  --emergency: #a855f7;
  --accent:    #3b82f6;
  --bg-primary: #0c1222;
  --bg-card: rgba(17, 25, 40, 0.75);
  --bg-card-hover: rgba(17, 25, 40, 0.9);
  --bg-glass: rgba(255, 255, 255, 0.04);
  --border: rgba(255, 255, 255, 0.08);
  --border-hover: rgba(255, 255, 255, 0.15);
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-dim: #64748b;
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
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.8rem; font-weight: 800; padding: 20px 24px; }
h2 { font-size: 1.2rem; font-weight: 600; color: var(--text-secondary); margin: 24px 0 12px; }
h3 { font-size: 1rem; font-weight: 600; margin: 16px 0 8px; }
.container { max-width: 1100px; margin: 0 auto; padding: 0 24px 40px; }
.site-header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(12, 18, 34, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px; height: 56px;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.header-logo { font-size: 1.1rem; font-weight: 700; color: var(--text-primary); white-space: nowrap; letter-spacing: -0.02em; }
.header-logo span { color: var(--accent); }
.header-nav { display: flex; gap: 4px; list-style: none; }
.header-nav a {
  display: block; padding: 6px 14px; border-radius: 8px;
  color: var(--text-secondary); text-decoration: none; font-size: 0.88rem; font-weight: 500; transition: all 0.2s ease;
}
.header-nav a:hover, .header-nav a.active { background: var(--bg-glass); color: var(--text-primary); }
.card {
  background: var(--bg-card); backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--border); border-radius: 16px; margin-bottom: 16px; padding: 20px;
}
.section-card { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; }
.explainer { background: rgba(59,130,246,0.05); border-left: 3px solid var(--accent); padding: 10px 14px; margin: 8px 0 16px; font-size: 0.88em; color: var(--text-secondary); border-radius: 0 6px 6px 0; }
.zone-row { padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 0.88em; }
.zone-row.green  { background: rgba(16,185,129,0.1); border-left: 3px solid var(--safe); }
.zone-row.yellow { background: rgba(245,158,11,0.1); border-left: 3px solid var(--watch); }
.zone-row.orange { background: rgba(249,115,22,0.1); border-left: 3px solid var(--warning); }
.zone-row.red    { background: rgba(239,68,68,0.1);  border-left: 3px solid var(--danger); }
.action-table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin: 10px 0; }
.action-table th { background: rgba(255,255,255,0.04); padding: 6px 8px; text-align: left; color: var(--text-dim); }
.action-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); color: var(--text-secondary); }
.dead-sources { background: rgba(239,68,68,0.05); border: 1px solid rgba(239,68,68,0.2); border-radius: 8px; padding: 12px 16px; margin-top: 10px; }
.dead-sources ul { padding-left: 20px; }
.dead-sources li { margin: 5px 0; color: var(--text-secondary); font-size: 0.9em; }
.site-footer {
  background: rgba(12, 18, 34, 0.8); border-top: 1px solid var(--border);
  padding: 20px 24px; text-align: center; color: var(--text-dim); font-size: 0.78rem;
}
@media (max-width: 768px) { .header-nav { display: none; } }
"""


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

<header class="site-header">
  <div class="header-logo">🌊 <span>Oka</span>FloodMonitor</div>
  <nav><ul class="header-nav">
    <li><a href="index.html">Главная</a></li>
    <li><a href="links.html" class="active">Ссылки</a></li>
    <li><a href="instructions.html">Инструкции</a></li>
  </ul></nav>
</header>

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
  OkaFloodMonitor v7.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

<script>
(function() {{
  function updateClock() {{
    var now = new Date();
    var msk = new Date(now.getTime() + (3 * 60 - now.getTimezoneOffset()) * 60000);
    var h = String(msk.getUTCHours()).padStart(2,'0');
    var m = String(msk.getUTCMinutes()).padStart(2,'0');
    var s = String(msk.getUTCSeconds()).padStart(2,'0');
    var el = document.getElementById('clock');
    if (el) el.textContent = h + ':' + m + ':' + s + ' МСК';
  }}
  setInterval(updateClock, 1000);
  updateClock();
}})();
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

<header class="site-header">
  <div class="header-logo">🌊 <span>Oka</span>FloodMonitor</div>
  <nav><ul class="header-nav">
    <li><a href="index.html">Главная</a></li>
    <li><a href="links.html">Ссылки</a></li>
    <li><a href="instructions.html" class="active">Инструкции</a></li>
  </ul></nav>
</header>

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

<div class="section-card">
  <h2>📱 Telegram-уведомления</h2>
  <p style="color:var(--text-secondary);">Бот <b style="color:var(--text-primary);">@OkaFlood2026EMbot</b> автоматически отправляет:</p>
  <ul style="padding-left:20px; color: var(--text-secondary); margin-top:8px; line-height:2;">
    <li>Ежедневные сводки в 08:00 и 20:00 МСК</li>
    <li>Экстренные алерты при пересечении пороговых отметок ({ALERT_ATTENTION}, {ALERT_DANGER}, {ALERT_CRITICAL}, {ALERT_EMERGENCY} см)</li>
    <li>Сводки GloFAS с прогнозом прихода волны в Серпухов</li>
    <li>Watchdog-уведомления при недоступности источников</li>
  </ul>
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
  OkaFloodMonitor v7.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo | GloFAS<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

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
# ГЛАВНАЯ ФУНКЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    """
    Точка входа monitor.py v7.0.

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
        f"OkaFloodMonitor v7.0 START"
    )

    # ─── 1. ДАННЫЕ ───────────────────────────────────────────────────────────
    data   = fetch_all_data()
    wext   = data.get("weather")
    serp   = data.get("serpuhov", {})
    kim    = data.get("kim", {})
    cugms  = data.get("cugms", {})
    glofas = data.get("glofas", {})

    print(f"[v7] Источники OK: {data.get('sources_ok')}")
    print(f"[v7] Источники FAILED: {data.get('sources_failed')}")
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
            if msk_hour == 8 and CHAT_NEIGHBORS:
                neighbors_msg = build_neighbors_digest(data, analytics, composite, glofas, now_msk)
                tg_send(CHAT_NEIGHBORS, neighbors_msg)

            # Mailing list
            for cid in load_mailing_list():
                neighbors_msg = build_neighbors_digest(data, analytics, composite, glofas, now_msk)
                tg_send(str(cid), neighbors_msg)
    else:
        print("[TG] TG_TOKEN не установлен, пропускаем.")

    # ─── 10. GIT PUSH ───────────────────────────────────────────────────────
    git_push()

    print(
        f"✅ OkaFloodMonitor v7.0 DONE | Серпухов: {serp.get('level_cm')} см | "
        f"Статус: {verdict_label} | "
        f"Источники OK: {data.get('sources_ok')}"
    )


if __name__ == "__main__":
    main()
