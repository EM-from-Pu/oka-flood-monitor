#!/usr/bin/env python3
"""
monitor.py v6.0 — OkaFloodMonitor
HTML-генерация + аналитика + Telegram-оповещения
Источники: serpuhov.ru (PRIMARY) | КИМ API | ЦУГМС | Open-Meteo
"""
import os
import re
import json
import csv
import math
import subprocess
from datetime import datetime, timedelta, timezone, date as date_cls

# Импорт из fetch_module v2.0
try:
    from fetch_module import fetch_all_data, fetch_weather_extended
    from fetch_module import (
        LUKYANNOVO_ZERO_M_BS, LUKYANNOVO_NYA_M_BS, LUKYANNOVO_OYA_M_BS,
        ZONE_GREEN_MAX, ZONE_YELLOW_MAX, ZONE_ORANGE_MAX,
        WAVE_OREL_TO_SERPUHOV, WAVE_KALUGA_TO_SERPUHOV,
        WAVE_ALEKSIN_TO_SERPUHOV, WAVE_SERPUHOV_TO_ZHERNIVKA,
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
            "fetch_time": datetime.now(timezone.utc).isoformat(),
            "sources_ok": [], "sources_failed": ["serpuhov.ru", "kim", "cugms", "weather"],
        }

    def fetch_weather_extended():
        return None

    LUKYANNOVO_ZERO_M_BS = 107.54
    LUKYANNOVO_NYA_M_BS  = 113.99
    LUKYANNOVO_OYA_M_BS  = 115.54
    ZONE_GREEN_MAX  = 400
    ZONE_YELLOW_MAX = 600
    ZONE_ORANGE_MAX = 800
    WAVE_OREL_TO_SERPUHOV     = (5, 7)
    WAVE_KALUGA_TO_SERPUHOV   = (2, 3)
    WAVE_ALEKSIN_TO_SERPUHOV  = (1, 2)
    WAVE_SERPUHOV_TO_ZHERNIVKA = (0.25, 0.5)


# ─── ENV VARS ──────────────────────────────────────────────────────────────────
TG_TOKEN       = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN     = os.environ.get("TG_CHAT_ID", "49747475")
CHAT_MY_GROUP  = os.environ.get("TG_GROUP_ID", "-5234360275")
CHAT_NEIGHBORS = os.environ.get("TG_NEIGHBORS_ID", "")

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
ALERTS_FILE       = os.path.join(DATA_DIR, "alerts_sent.json")  # НЕ в docs/!
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

# ─── КОЛОНКИ HISTORY.CSV ─────────────────────────────────────────────────────
HISTORY_COLS = [
    "datetime",
    "serp_level_m", "serp_level_cm", "serp_daily_change_cm",
    "serp_abs_m_bs", "serp_source",
    "kim_kashira_cm", "kim_kaluga_cm", "kim_ryazan_cm",
    "cugms_serp_change_cm", "cugms_kashira_change_cm", "cugms_review_number",
    "temp", "precip_mm", "snow_depth_cm", "flood_weather_index",
    "alert_level", "days_to_nya", "days_to_oya",
    "notes",
]

# ─── НАЗВАНИЯ СТАНЦИЙ ─────────────────────────────────────────────────────────
STATION_NAMES = {
    "orel":     "Орёл",
    "belev":    "Белёв",
    "kaluga":   "Калуга",
    "serpuhov": "Серпухов",
    "kashira":  "Кашира",
    "kolomna":  "Коломна",
    "ryazan":   "Рязань",
}


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
    """Сохраняет data/history.json (полный список)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_JSON, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def append_history_row(history: list, data: dict, analytics: dict, wext) -> list:
    """
    Добавляет новую запись в историю.
    Не добавляет дубликат за тот же час (dedup по datetime[:13]).
    """
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})

    now_iso  = datetime.now(timezone.utc).isoformat()
    hour_key = now_iso[:13]  # "2026-03-28T12"

    if history and history[-1].get("datetime", "")[:13] == hour_key:
        print(f"[history] Дубликат пропущен: {hour_key}")
        return history

    # Определяем today_weather из wext.days (индекс 4 — это "сегодня" при past_days=4)
    today_day = {}
    if wext and wext.get("days"):
        days = wext["days"]
        # past_days=4 → индекс [3] = вчера, [4] = сегодня (если forecast_days>=1)
        # Берём последний прошедший или первый прогнозный
        for d in days:
            if not d.get("is_forecast", True):
                today_day = d  # последний реальный день

    row = {
        "datetime":               now_iso,
        "serp_level_m":           serp.get("level_m"),
        "serp_level_cm":          serp.get("level_cm"),
        "serp_daily_change_cm":   serp.get("daily_change_cm"),
        "serp_abs_m_bs":          serp.get("abs_level_m_bs"),
        "serp_source":            serp.get("source_status", "unknown"),
        "kim_kashira_cm":         (kim.get("kashira") or {}).get("level_cm"),
        "kim_kaluga_cm":          (kim.get("kaluga") or {}).get("level_cm"),
        "kim_ryazan_cm":          (kim.get("ryazan") or {}).get("level_cm"),
        "cugms_serp_change_cm":   cugms.get("serpuhov_change_cm"),
        "cugms_kashira_change_cm":cugms.get("kashira_change_cm"),
        "cugms_review_number":    cugms.get("review_number"),
        "temp":                   today_day.get("tmax"),
        "precip_mm":              today_day.get("precip"),
        "snow_depth_cm":          (wext or {}).get("snow_depth_cm"),
        "flood_weather_index":    (wext or {}).get("flood_index"),
        "alert_level":            analytics.get("alert_level", "GREEN"),
        "days_to_nya":            analytics.get("days_to_nya"),
        "days_to_oya":            analytics.get("days_to_oya"),
        "notes":                  analytics.get("notes", ""),
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
    """Читает data/mailing_list.json. Возвращает список chat_id."""
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
    Возвращает (zone_name, color, bg_color, label) по уровню в см.
    Зоны: GREEN / YELLOW / ORANGE / RED
    """
    if level_cm is None:
        return ("UNKNOWN", "#8b949e", "#1a2635", "Нет данных")
    if level_cm < ZONE_GREEN_MAX:
        return ("GREEN",  "#3fb950", "#0d1f0d", "НОРМА")
    if level_cm < ZONE_YELLOW_MAX:
        return ("YELLOW", "#d29922", "#1f1a00", "ВНИМАНИЕ")
    if level_cm < ZONE_ORANGE_MAX:
        return ("ORANGE", "#db6d28", "#2a1000", "ОПАСНОСТЬ")
    return ("RED", "#f85149", "#2d0000", "КРИТИЧНО")


def compute_analytics(serp: dict, kim: dict, cugms: dict, history: list, wext) -> dict:
    """
    Собирает всю аналитику в один словарь.
    Возвращает: alert_level, days_to_nya, days_to_oya, nya_remaining_m,
                oya_remaining_m, wave_dynamic_text, peak_prediction, notes
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

    # Дней до порогов (при текущем темпе роста)
    days_to_nya = None
    days_to_oya = None
    if change_cm and change_cm > 0 and nya_remaining_m is not None:
        change_m_per_day = change_cm / 100.0
        days_to_nya = round(nya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None
        days_to_oya = round(oya_remaining_m / change_m_per_day, 1) if change_m_per_day > 0 else None

    # Уровень опасности
    zone_name, _, _, _ = get_level_zone(level_cm)
    alert_level = zone_name

    # Прогресс-бары до НЯ и ОЯ
    total_nya_range = LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS  # ≈6.45 м
    total_oya_range = LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS  # ≈8.00 м
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
        "wave_dynamic_text":wave_text,
        "peak_prediction":  peak,
        "notes":            notes,
    }


def compute_wave_analysis(data: dict) -> str:
    """
    Генерирует текст о движении волны на основе данных ЦУГМС и КИМ.
    """
    cugms = data.get("cugms", {})
    kim   = data.get("kim", {})

    msgs = []

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
    """
    Простая модель предсказания пика.
    Берёт последние 10 записей, ищет замедление прироста.
    """
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

    regression = compute_simple_regression(history)

    return {
        "trend":         trend,
        "trend_text":    trend_text,
        "decel_days":    decel_days,
        "est_peak_days": est_days,
        "regression":    regression,
        "disclaimer":    "Модель приблизительная. Реальный пик зависит от погоды и таяния снега.",
    }


def compute_simple_regression(history: list):
    """
    Линейная регрессия уровня Серпухова за последние 14 дней.
    Только stdlib + math. Без scikit-learn / numpy.
    """
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

    # Берём последние 14 точек
    pts = points[-14:]
    n   = len(pts)

    # Приводим время к числу (часы от первой точки)
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

    # Линейная регрессия (МНК)
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

    # R²
    y_mean = sy / n
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Прогнозы через 3 и 7 дней
    last_x  = xs[-1]
    pred_3d = round(intercept + slope * (last_x + 72), 1)
    pred_7d = round(intercept + slope * (last_x + 168), 1)

    # Дата достижения НЯ
    nya_cm      = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    peak_date   = None
    peak_date_str = None
    if slope > 0:
        hours_to_nya = (nya_cm - intercept) / slope if slope != 0 else None
        if hours_to_nya and hours_to_nya > 0:
            try:
                peak_dt   = t0 + timedelta(hours=hours_to_nya)
                peak_date = peak_dt.strftime("%d.%m.%Y")
                peak_date_str = peak_date
            except Exception:
                pass

    current_level = ys[-1]
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
        "current_level":  current_level,
    }


def generate_action_block(serp_level_cm, flood_index: int) -> tuple:
    """
    Генерирует рекомендации для жителей.
    Возвращает: (icon, title, text, color)
    """
    sl = serp_level_cm or 0
    fi = flood_index or 0

    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)

    if sl >= ZONE_ORANGE_MAX:
        icon, title = "🚨", "КРИТИЧЕСКАЯ СИТУАЦИЯ"
        text = (
            f"Уровень воды {sl:.0f} см — критическая зона. "
            "Рекомендуем: вывезти ценные вещи, проверить пути эвакуации, "
            "связаться с ЕДДС (112). Следите за обновлениями каждые 3 часа."
        )
        color = "#8e0000"
    elif sl >= ZONE_YELLOW_MAX:
        icon, title = "⚠️", "ПОВЫШЕННАЯ ОПАСНОСТЬ"
        text = (
            f"Уровень {sl:.0f} см, прирост продолжается. "
            f"До ОЯ (подтопление НП) остаётся {max(0, oya_cm - sl):.0f} см. "
            "Уберите ценности с низких мест. Следите за сводками."
        )
        color = "#bc4c00"
    elif sl >= ZONE_GREEN_MAX:
        icon, title = "🟡", "УРОВЕНЬ ПОВЫШЕН"
        text = (
            f"Уровень {sl:.0f} см — паводковый сезон в активной фазе. "
            "Пойма начинает заполняться. Дачникам: проверьте состояние участков."
        )
        color = "#9a6700"
    else:
        icon, title = "✅", "СИТУАЦИЯ НОРМАЛЬНАЯ"
        text = (
            f"Уровень {sl:.0f} см — в пределах нормы. "
            "Обновления 4 раза в день. Следите за динамикой."
        )
        color = "#1a7f37"

    # Дополнение про погодный индекс (не меняет зону, но предупреждает)
    if fi >= 3 and sl < ZONE_YELLOW_MAX:
        text += f" ⚠️ Погодный индекс паводковой опасности: {fi}/5 — возможен быстрый подъём в ближайшие дни."

    return icon, title, text, color


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
    """
    Проверяет пересечение пороговых отметок.
    Cooldown: 6 ч для низких уровней, 4 ч для высоких.
    """
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
    """Возвращает стрелку-эмодзи по значению дельты."""
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


def format_heartbeat(serp: dict, kim: dict, cugms: dict, wext) -> str:
    """Краткий пульс-сигнал."""
    now_msk  = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m %H:%M")
    level_cm = serp.get("level_cm")
    abs_bs   = serp.get("abs_level_m_bs")
    change   = serp.get("daily_change_cm")
    arrow    = _trend(change)

    level_str = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
    abs_str   = f"{abs_bs:.2f} м БС" if abs_bs is not None else "?"

    weather_line = ""
    if wext:
        days        = wext.get("days", [])
        today       = next((d for d in days if not d.get("is_forecast", True)), {})
        tmax        = today.get("tmax", "?")
        precip      = today.get("precip", 0) or 0
        snow        = wext.get("snow_depth_cm", 0) or 0
        fl_label    = wext.get("flood_label", "?")
        weather_line = f"\n🌡 {tmax}°C | 💧{precip:.1f}мм | ❄️ Снег: {snow:.0f} см\n📈 Паводковый индекс: <b>{fl_label}</b>"

    cugms_line = ""
    if cugms.get("review_number"):
        n   = cugms.get("review_number")
        chg = cugms.get("serpuhov_change_cm")
        chg_str = f"{chg:+.0f} см/сут" if chg is not None else "нет данных"
        cugms_line = f"\n📋 ЦУГМС (обзор №{n}): Серпухов {chg_str}"

    return (
        f"🌊 <b>ОКА | Серпухов | {now_msk} МСК</b>\n"
        f"\n📊 Уровень: <b>{level_str}</b> ({abs_str})"
        f"\n{arrow} Изменение: <b>{_fmt_delta(change)} см</b> за сутки"
        f"\n📍 Пост: д. Лукьяново | serpuhov.ru"
        f"{weather_line}"
        f"{cugms_line}"
        f"\n\n🔗 https://em-from-pu.github.io/oka-flood-monitor"
    )


def format_digest(data: dict, history: list, wext, analytics: dict, regression) -> str:
    """Полный дайджест для ADMIN / MY_GROUP."""
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

    # Прогноз пика
    peak      = analytics.get("peak_prediction", {})
    peak_text = peak.get("trend_text", "Недостаточно данных") if peak else "Недостаточно данных"
    reg_line  = ""
    if regression and regression.get("r_squared", 0) > 0.6:
        reg_line = f"🤖 ML: {regression.get('trend_text_ml', '')} | R²={regression.get('r_squared', 0):.2f}\n"

    # Пороги
    nya_rem = analytics.get("nya_remaining_m")
    oya_rem = analytics.get("oya_remaining_m")
    nya_str = f"{nya_rem:.2f} м" if nya_rem is not None else "нет данных"
    oya_str = f"{oya_rem:.2f} м" if oya_rem is not None else "нет данных"

    return (
        f"🌊 <b>ПАВОДОК ОКА — ПОЛНАЯ СВОДКА {now_date}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\n📊 <b>СЕРПУХОВ (пост д. Лукьяново)</b>\n"
        f"• Уровень: <b>{level_str}</b> ({abs_str})\n"
        f"• Изменение: <b>{_fmt_delta(change)} см</b> за сутки\n"
        f"• Источник: serpuhov.ru | статус: {src_stat}\n"
        f"\n━━ ДРУГИЕ СТАНЦИИ ━━━━━━━━━━━━━━━━━━\n"
        f"{stations_lines if stations_lines else 'нет данных'}"
        f"\n{cugms_block}\n"
        f"\n{weather_block}\n"
        f"\n━━ ПРОГНОЗ ПИКА ━━━━━━━━━━━━━━━━━━\n"
        f"{peak_text}\n"
        f"{reg_line}"
        f"\n━━ ПОРОГИ ━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"До НЯ ({LUKYANNOVO_NYA_M_BS} м БС): {nya_str}\n"
        f"До ОЯ ({LUKYANNOVO_OYA_M_BS} м БС): {oya_str}\n"
        f"\n🔗 https://em-from-pu.github.io/oka-flood-monitor"
    )


def format_neighbors_digest(data: dict, wext, analytics: dict) -> str:
    """Упрощённый дайджест для соседей."""
    serp   = data.get("serpuhov", {})
    level  = serp.get("level_cm")
    change = serp.get("daily_change_cm")
    arrow  = _trend(change)

    now_date  = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y")
    level_str = f"{level:.0f} см" if level is not None else "нет данных"

    icon, title, text, _ = generate_action_block(level, (wext or {}).get("flood_index", 0))

    fl_label  = (wext or {}).get("flood_label", "нет данных")
    fl_summary = (wext or {}).get("flood_summary", "")

    nya_rem = analytics.get("nya_remaining_m")
    oya_rem = analytics.get("oya_remaining_m")
    nya_str = f"{nya_rem:.1f} м" if nya_rem is not None else "нет данных"
    oya_str = f"{oya_rem:.1f} м" if oya_rem is not None else "нет данных"

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
    """Возвращает CSS-класс бейджа по статусу источника."""
    if status in ("ok",):
        return "ok"
    if status in ("cached",):
        return "cached"
    return "fail"


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


def _generate_nav(active: str = "index") -> str:
    """Генерирует sticky-навигацию."""
    pages = [
        ("index.html",        "🌊 Дашборд",      "index"),
        ("instructions.html", "📖 Инструкции",   "instructions"),
        ("links.html",        "🔗 Ссылки",        "links"),
    ]
    btns = ""
    for href, label, key in pages:
        cls = "nav-btn active" if key == active else "nav-btn"
        btns += f'<a href="{href}" class="{cls}">{_h(label)}</a>\n'
    return f"""
<nav class="top-nav">
  <div class="nav-links">
    {btns}
  </div>
  <div class="nav-widget">
    <span id="clock" class="nav-time"></span>
  </div>
</nav>
"""


def _generate_common_css() -> str:
    """Возвращает общий CSS для всех страниц."""
    return """
:root {
    --bg: #0f1923; --card: #1a2635; --border: #2d3748;
    --text: #e6edf3; --text-muted: #8b949e; --text-dim: #6e7681;
    --blue: #388bfd; --green: #3fb950; --yellow: #d29922;
    --orange: #db6d28; --red: #f85149; --critical: #8e0000;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg); color: var(--text); margin: 0; padding: 0;
    line-height: 1.5;
}
a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { color: #fff; margin: 0; padding: 20px 24px; font-size: 1.6em; }
h2 { color: #79c0ff; margin: 20px 0 10px; font-size: 1.2em; }
h3 { color: #79c0ff; margin: 14px 0 8px; font-size: 1.05em; }
h4 { color: #e3b341; margin: 10px 0 5px; font-size: 0.95em; }
.container { max-width: 1200px; margin: 0 auto; padding: 16px; }
/* ═══ НАВИГАЦИЯ ═══ */
.top-nav {
    position: sticky; top: 0; z-index: 100;
    background: #0d1117; border-bottom: 1px solid #21262d;
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 16px; gap: 12px; flex-wrap: wrap;
}
.nav-links { display: flex; gap: 8px; flex-wrap: wrap; }
.nav-btn {
    padding: 6px 14px; border-radius: 6px; font-size: 0.85em;
    text-decoration: none; color: #8b949e;
    background: #161b22; border: 1px solid #30363d; transition: background 0.2s;
}
.nav-btn:hover, .nav-btn.active { background: #1f6feb; color: #fff; border-color: var(--blue); }
.nav-widget { display: flex; align-items: center; gap: 10px; }
.nav-time { font-size: 0.8em; color: #79c0ff; font-family: monospace; }
.nav-weather { font-size: 0.8em; color: var(--text-muted); }
/* ═══ HERO БЛОК ═══ */
.hero-block {
    background: var(--card); border-radius: 16px;
    padding: 28px 24px; text-align: center; margin: 16px 0;
    border: 2px solid var(--border);
}
.hero-level { font-size: 5em; font-weight: 900; line-height: 1; letter-spacing: -2px; }
.hero-unit { font-size: 0.25em; color: var(--text-muted); vertical-align: super; }
.hero-delta { font-size: 1.4em; margin: 10px 0; font-weight: 600; }
.hero-delta.rising { color: var(--red); }
.hero-delta.falling { color: var(--green); }
.hero-delta.stable { color: var(--text-muted); }
.hero-abs { font-size: 0.9em; color: var(--text-muted); margin-bottom: 20px; }
.threshold-bars { margin-top: 16px; text-align: left; max-width: 500px; margin: 16px auto 0; }
.tbar-row { display: flex; align-items: center; gap: 10px; margin: 8px 0; }
.tbar-label { font-size: 0.8em; color: var(--text-muted); min-width: 160px; }
.tbar-track { flex: 1; height: 8px; background: #21262d; border-radius: 4px; overflow: hidden; }
.tbar-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
.nya-fill { background: linear-gradient(90deg, var(--green), var(--yellow)); }
.oya-fill { background: linear-gradient(90deg, var(--green), var(--yellow), var(--red)); }
.tbar-val { font-size: 0.85em; color: var(--text); min-width: 60px; text-align: right; font-weight: 600; }
/* ═══ КАРТОЧКИ СТАНЦИЙ ═══ */
.station-cards { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0; }
.station-card {
    background: #161b22; border: 1px solid #30363d; border-radius: 10px;
    padding: 14px 16px; min-width: 120px; flex: 1; text-align: center;
    transition: border-color 0.2s;
}
.station-card.main-station { border: 2px solid #388bfd; background: #1c2128; min-width: 200px; flex: 2; }
.st-name { font-size: 0.9em; font-weight: 700; color: var(--text); margin-bottom: 2px; }
.st-river { font-size: 0.72em; color: var(--text-dim); margin-bottom: 8px; }
.st-level { font-size: 1.7em; font-weight: 800; margin-bottom: 4px; }
.level-green { color: var(--green); }
.level-yellow { color: var(--yellow); }
.level-orange { color: var(--orange); }
.level-red { color: var(--red); }
.level-unknown { color: var(--text-dim); font-size: 0.75em; font-weight: 400; }
.st-change { font-size: 0.85em; color: var(--text-muted); margin-bottom: 4px; }
.st-status { font-size: 0.8em; margin-bottom: 4px; }
.st-source { font-size: 0.65em; color: var(--text-dim); }
/* ═══ ДИСКЛЕЙМЕР / АККОРДЕОН ═══ */
.disclaimer-block {
    background: rgba(255,255,255,0.02); border: 1px solid #30363d;
    border-radius: 8px; margin: 12px 0;
}
.disclaimer-header {
    padding: 12px 16px; cursor: pointer; font-size: 0.9em; color: var(--text-muted);
    display: flex; justify-content: space-between; align-items: center;
}
.disclaimer-header:hover { color: var(--text); }
.disclaimer-body { padding: 0 16px 16px; display: none; }
.disclaimer-alert {
    background: rgba(248,81,73,0.08); border-left: 3px solid var(--red);
    padding: 8px 12px; border-radius: 0 6px 6px 0; margin: 10px 0; font-size: 0.85em;
}
.sources-table { width: 100%; border-collapse: collapse; font-size: 0.82em; margin-top: 10px; }
.sources-table th { background: #161b22; color: var(--text-muted); padding: 6px 8px; text-align: left; }
.sources-table td { padding: 5px 8px; border-bottom: 1px solid #21262d; color: var(--text); }
/* ═══ ПОРОГИ ═══ */
.thresholds-section { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.threshold-scale-container { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }
.v-scale-wrapper {
    position: relative; width: 220px; height: 280px;
    background: linear-gradient(to top, #1a7f37 0%, #d29922 50%, #f85149 85%, #8e0000 100%);
    border-radius: 8px; overflow: visible; flex-shrink: 0;
}
.v-scale-inner {
    position: absolute; left: 0; top: 0; bottom: 0; right: 0;
    background: linear-gradient(to top, rgba(0,0,0,0.6) 0%, rgba(0,0,0,0.3) 100%);
    border-radius: 8px;
}
.v-marker {
    position: absolute; left: 0; right: 0;
    display: flex; align-items: center; gap: 8px;
}
.v-marker-line { height: 2px; background: rgba(255,255,255,0.7); flex: 1; }
.v-marker-label {
    font-size: 0.7em; color: #fff; white-space: nowrap;
    background: rgba(0,0,0,0.5); padding: 1px 5px; border-radius: 3px;
}
.v-current-indicator {
    position: absolute; left: -6px; right: -6px;
    height: 4px; background: #79c0ff;
    box-shadow: 0 0 8px #79c0ff;
}
.thresh-table { width: 100%; border-collapse: collapse; font-size: 0.88em; flex: 1; }
.thresh-table th { background: #161b22; color: var(--text-muted); padding: 6px 8px; text-align: left; }
.thresh-table td { padding: 6px 8px; border-bottom: 1px solid #21262d; }
.thresh-table tr.row-nya td { background: rgba(210,153,34,0.1); }
.thresh-table tr.row-oya td { background: rgba(248,81,73,0.1); }
.thresh-table tr.row-current td { background: rgba(56,139,253,0.1); font-weight: 700; }
/* ═══ ВОЛНА И ПИК ═══ */
.wave-section, .peak-section { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.wave-cards { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0; }
.wave-card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 12px 14px; min-width: 140px; flex: 1;
}
.wave-card.highlight { border-color: #388bfd; background: rgba(56,139,253,0.05); }
.wave-from { font-size: 0.85em; color: var(--text-muted); margin-bottom: 4px; }
.wave-time { font-size: 1.2em; font-weight: 700; color: #79c0ff; }
.wave-dist { font-size: 0.75em; color: var(--text-dim); margin-top: 2px; }
.wave-dynamic { font-size: 0.88em; color: var(--text-muted); margin: 8px 0; }
.peak-trend { font-size: 1.05em; font-weight: 600; margin: 8px 0; padding: 10px 14px; border-radius: 6px; background: rgba(255,255,255,0.03); }
.regression-block { background: rgba(56,139,253,0.05); border: 1px solid #30363d; border-radius: 8px; padding: 12px 14px; margin-top: 10px; font-size: 0.88em; }
.regression-block p { color: var(--text-muted); margin: 4px 0; }
/* ═══ ЦУГМС ═══ */
.cugms-section { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.cugms-meta { font-size: 0.85em; color: var(--text-muted); margin-bottom: 12px; }
.cugms-data { display: flex; flex-wrap: wrap; gap: 10px; }
.cugms-row { display: flex; align-items: center; gap: 8px; padding: 6px 10px; background: #161b22; border-radius: 6px; min-width: 180px; }
.cugms-station { font-size: 0.88em; color: var(--text-muted); min-width: 80px; }
.cugms-value { font-size: 1.05em; font-weight: 700; color: var(--text); }
.cugms-value.ice { color: #79c0ff; }
.cugms-forecast {
    background: rgba(56,139,253,0.05); border-left: 3px solid #388bfd;
    padding: 10px 14px; border-radius: 0 6px 6px 0; font-size: 0.85em;
    color: var(--text-muted); margin-top: 10px; width: 100%;
}
/* ═══ ИСТОРИЯ ═══ */
.history-section { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.history-controls { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.hist-btn {
    padding: 5px 12px; border-radius: 6px; font-size: 0.82em;
    background: #161b22; border: 1px solid #30363d; color: var(--text-muted);
    cursor: pointer; text-decoration: none; display: inline-block;
}
.hist-btn:hover { background: #1f6feb; color: #fff; border-color: var(--blue); }
.dl-btn { color: var(--blue); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.82em; }
th { background: #161b22; color: var(--text-muted); padding: 6px 8px; text-align: left; white-space: nowrap; }
td { padding: 5px 8px; border-bottom: 1px solid #21262d; white-space: nowrap; }
.row-GREEN td { background: rgba(13,32,22,0.5); }
.row-YELLOW td { background: rgba(42,29,0,0.5); }
.row-ORANGE td { background: rgba(42,20,0,0.5); }
.row-RED td, .row-CRITICAL td { background: rgba(45,0,0,0.5); }
/* ═══ ACTION BLOCK ═══ */
.action-block {
    background: rgba(255,255,255,0.02); border-radius: 0 8px 8px 0;
    padding: 16px 20px; margin: 16px 0;
}
.action-block h3 { margin: 0 0 8px; font-size: 1.1em; }
.action-block p { color: var(--text-muted); font-size: 0.9em; margin: 4px 0; line-height: 1.5; }
.action-meta { color: var(--text-dim); font-size: 0.8em; margin-top: 8px; }
/* ═══ ПОГОДА ═══ */
.weather-ext-block { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.weather-flood-index {
    border: 2px solid; border-radius: 10px; padding: 14px 18px;
    margin-bottom: 16px; background: rgba(255,255,255,0.03);
}
.wfi-label { font-size: 0.85em; color: #95a5a6; display: block; }
.wfi-value { font-size: 1.6em; font-weight: 900; display: block; margin: 4px 0; }
.wfi-summary { margin: 0; color: var(--text-muted); font-size: 0.95em; }
.weather-table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin-bottom: 12px; }
.weather-table th, .weather-table td {
    padding: 6px 8px; text-align: center;
    border-bottom: 1px solid var(--border); white-space: nowrap;
}
.weather-table td:first-child { text-align: left; color: #95a5a6; }
td.frost { background: rgba(192,57,43,0.25); color: #ff6b6b; font-weight: bold; }
td.zero { background: rgba(243,156,18,0.20); color: #f39c12; }
td.warm-night { background: rgba(39,174,96,0.20); color: #27ae60; }
td.hot { color: #e74c3c; font-weight: bold; }
td.forecast-col, th.forecast-col {
    background: rgba(52,152,219,0.08); border-left: 1px dashed #3498db;
}
th.forecast-col:first-of-type { border-left: 2px solid #3498db; }
.weather-commentary ul { list-style: none; padding: 0; }
.weather-commentary li {
    padding: 5px 0; border-bottom: 1px solid var(--border);
    font-size: 0.9em; color: var(--text-muted);
}
/* ═══ BADGES ═══ */
.meta-bar {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 16px; background: #0d1117; font-size: 0.82em; color: var(--text-muted);
    flex-wrap: wrap; gap: 8px;
}
.source-badges { display: flex; gap: 6px; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 0.75em; }
.badge.ok { background: #1a7f37; color: #fff; }
.badge.cached { background: #9a6700; color: #fff; }
.badge.fail { background: #6e0000; color: #fff; }
/* ═══ УТИЛИТЫ ═══ */
.section-card { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.explainer {
    background: rgba(255,255,255,0.03); border-left: 3px solid #3498db;
    padding: 10px 14px; margin: 8px 0 16px; font-size: 0.85em;
    color: var(--text-muted); border-radius: 0 6px 6px 0;
}
.explainer b { color: var(--text); }
.disclaimer-small { font-size: 0.8em; color: var(--text-dim); margin-top: 8px; }
.no-data { color: var(--text-dim); font-size: 0.9em; font-style: italic; padding: 10px; }
/* ═══ REPORTS ═══ */
.reports-section { background: var(--card); border-radius: 12px; padding: 16px; margin: 12px 0; }
.report-cards { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; }
.report-card {
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 12px 14px; min-width: 200px; flex: 1;
}
.report-card a { font-weight: 600; }
.report-meta { font-size: 0.75em; color: var(--text-dim); margin-top: 4px; }
/* ═══ FOOTER ═══ */
footer {
    color: var(--text-dim); font-size: 0.8em; text-align: center;
    padding: 24px 16px; border-top: 1px solid var(--border); margin-top: 24px;
    line-height: 1.8;
}
/* ═══ ИНСТРУКЦИИ ═══ */
.instr-section { background: var(--card); border-radius: 12px; padding: 16px 20px; margin: 12px 0; }
.instr-section ul, .instr-section ol { padding-left: 20px; }
.instr-section li { margin: 5px 0; color: var(--text-muted); }
.zone-table { margin: 10px 0; }
.zone-row { padding: 8px 12px; margin: 4px 0; border-radius: 6px; font-size: 0.88em; }
.zone-row.green  { background: rgba(63,185,80,0.1); border-left: 3px solid var(--green); }
.zone-row.yellow { background: rgba(210,153,34,0.1); border-left: 3px solid var(--yellow); }
.zone-row.orange { background: rgba(219,109,40,0.1); border-left: 3px solid var(--orange); }
.zone-row.red    { background: rgba(248,81,73,0.1);  border-left: 3px solid var(--red); }
.action-table { width: 100%; border-collapse: collapse; font-size: 0.88em; margin: 10px 0; }
.action-table th { background: #161b22; padding: 6px 8px; text-align: left; color: var(--text-muted); }
.action-table td { padding: 7px 8px; border-bottom: 1px solid #21262d; }
/* ═══ ССЫЛКИ ═══ */
.links-section { background: var(--card); border-radius: 12px; padding: 16px 20px; margin: 12px 0; }
.links-section ul { padding-left: 20px; }
.links-section li { margin: 8px 0; }
.dead-sources {
    background: rgba(248,81,73,0.05); border: 1px solid rgba(248,81,73,0.2);
    border-radius: 8px; padding: 12px 16px; margin-top: 10px;
}
/* ═══ CHART.JS WRAPPER ═══ */
.chart-container { position: relative; height: 280px; margin: 16px 0; }
/* ═══ АНИМАЦИЯ ═══ */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}
/* ═══ МОБИЛЬНАЯ АДАПТАЦИЯ ═══ */
@media (max-width: 768px) {
    .station-cards { flex-direction: column; }
    .station-card, .station-card.main-station { min-width: 100%; flex: none; }
    .wave-cards { flex-direction: column; }
    .wave-card { min-width: 100%; }
    .top-nav { flex-direction: column; align-items: flex-start; }
    h1 { font-size: 1.1em; padding: 14px 12px; }
    .container { padding: 8px; }
    .hero-level { font-size: 3.5em; }
    .wfi-value { font-size: 1.3em; }
    .cugms-data { flex-direction: column; }
    .threshold-scale-container { flex-direction: column; }
    .v-scale-wrapper { width: 100%; }
}
@media (max-width: 480px) {
    .hero-level { font-size: 2.8em; }
    .hero-delta { font-size: 1.1em; }
    .weather-table { font-size: 0.75em; }
    .tbar-label { min-width: 110px; font-size: 0.72em; }
}
@media (prefers-color-scheme: light) {
    :root {
        --bg: #f6f8fa; --card: #ffffff; --border: #d0d7de;
        --text: #24292f; --text-muted: #57606a; --text-dim: #8c959f;
    }
    body { background: var(--bg); color: var(--text); }
    .station-card, .wave-card { background: #f6f8fa; }
    th { background: #f6f8fa; }
    .top-nav { background: #f6f8fa; }
    .meta-bar { background: #f6f8fa; }
    .nav-btn { background: #f6f8fa; border-color: #d0d7de; }
    .hist-btn { background: #f6f8fa; }
    .report-card { background: #f6f8fa; }
}
"""


def _generate_clock_js() -> str:
    """JS для часов MSK."""
    return """
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
"""


def _generate_disclaimer_js() -> str:
    """JS для аккордеона дисклеймера."""
    return """
function toggleDisclaimer() {
    var body = document.getElementById('disclaimer-body');
    var icon = document.querySelector('.toggle-icon');
    if (!body) return;
    if (body.style.display === 'none' || body.style.display === '') {
        body.style.display = 'block';
        if (icon) icon.textContent = '▲';
    } else {
        body.style.display = 'none';
        if (icon) icon.textContent = '▼';
    }
}
"""


def _generate_filter_js() -> str:
    """JS для фильтрации таблицы истории."""
    return """
function filterHistory(days) {
    var rows = document.querySelectorAll('#histTable tbody tr');
    var cutoff = days > 0 ? new Date(Date.now() - days * 86400000) : null;
    rows.forEach(function(row) {
        if (!cutoff) { row.style.display = ''; return; }
        var dateStr = row.cells[0] ? row.cells[0].textContent.trim() : '';
        var d = new Date(dateStr);
        row.style.display = (!isNaN(d) && d >= cutoff) ? '' : 'none';
    });
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML: ГЕНЕРАЦИЯ БЛОКОВ
# ══════════════════════════════════════════════════════════════════════════════

def generate_chart_js_block(history: list, ref_2024) -> str:
    """
    Генерирует Chart.js-блок с историей уровней Серпухова.
    Использует данные из history.json по ключу serp_level_cm.
    """
    # Берём последние 30 точек истории
    pts = []
    for row in history[-30:]:
        val = row.get("serp_level_cm")
        dt  = row.get("datetime", "")
        if val is not None:
            try:
                pts.append((dt[:10], float(val)))
            except (ValueError, TypeError):
                pass

    if not pts:
        return ""

    labels = json.dumps([p[0] for p in pts], ensure_ascii=False)
    values = json.dumps([p[1] for p in pts])

    # 2024 референс
    ref_labels = "[]"
    ref_values = "[]"
    if ref_2024 and isinstance(ref_2024, list):
        ref_pts = []
        for row in ref_2024[-30:]:
            v = row.get("serp_level_cm") or row.get("serpukhov")
            d = row.get("datetime", "")
            if v is not None:
                try:
                    ref_pts.append((d[:10], float(v)))
                except (ValueError, TypeError):
                    pass
        if ref_pts:
            ref_labels = json.dumps([p[0] for p in ref_pts], ensure_ascii=False)
            ref_values = json.dumps([p[1] for p in ref_pts])

    return f"""
<div class="chart-container">
<canvas id="levelChart"></canvas>
</div>
<script>
(function() {{
var ctx = document.getElementById('levelChart');
if (!ctx) return;
var labels = {labels};
var values = {values};
var refLabels = {ref_labels};
var refValues = {ref_values};
var datasets = [{{
    label: '2026 (Серпухов, см)',
    data: values,
    borderColor: '#388bfd',
    backgroundColor: 'rgba(56,139,253,0.12)',
    tension: 0.3,
    fill: true,
    pointRadius: 3,
}}];
if (refValues.length > 0) {{
    datasets.push({{
        label: '2024 (справочно)',
        data: refValues,
        borderColor: '#8b949e',
        borderDash: [4,4],
        tension: 0.3,
        fill: false,
        pointRadius: 2,
    }});
}}
new Chart(ctx, {{
    type: 'line',
    data: {{ labels: labels, datasets: datasets }},
    options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{
            legend: {{ labels: {{ color: '#8b949e' }} }},
            tooltip: {{ mode: 'index', intersect: false }},
        }},
        scales: {{
            x: {{ ticks: {{ color: '#8b949e', maxTicksLimit: 7 }}, grid: {{ color: '#21262d' }} }},
            y: {{ ticks: {{ color: '#8b949e' }}, grid: {{ color: '#21262d' }},
                  title: {{ display: true, text: 'см', color: '#8b949e' }} }},
        }},
    }},
}});
}})();
</script>
"""


def _generate_weather_table(wext) -> str:
    """Генерирует 8-дневную таблицу погоды."""
    if not wext or not wext.get("days"):
        return '<div class="no-data">Данные погоды недоступны.</div>'

    days = wext["days"]
    header_cells = ""
    tmax_cells   = ""
    tmin_cells   = ""
    precip_cells = ""
    snow_cells   = ""
    wind_cells   = ""
    desc_cells   = ""

    for d in days:
        is_fc = d.get("is_forecast", False)
        fc_cls = " forecast-col" if is_fc else ""
        date_str = d.get("date", "")
        try:
            dt_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_fmt = dt_obj.strftime("%d.%m")
            day_of_week = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][dt_obj.weekday()]
            label = f"{day_of_week} {date_fmt}"
        except ValueError:
            label = date_str

        header_cells += f'<th class="{fc_cls}">{_h(label)}</th>'

        tmax = d.get("tmax")
        tmin = d.get("tmin")
        precip = d.get("precip") or 0
        rain   = d.get("rain_sum") or 0
        snow   = d.get("snowfall_cm") or 0
        wind   = d.get("wind_ms") or 0
        code   = d.get("weather_code")

        def tmax_cls(v):
            if v is None: return ""
            if v >= 25: return " class=\"hot\""
            return ""

        def tmin_cls(v):
            if v is None: return ""
            if v < -5: return " class=\"frost\""
            if -5 <= v < 0: return " class=\"zero\""
            if v >= 2: return " class=\"warm-night\""
            return ""

        tmax_str  = f"{tmax:.0f}°" if tmax is not None else "?"
        tmin_str  = f"{tmin:.0f}°" if tmin is not None else "?"
        pre_str   = f"{precip:.1f}"
        rain_str  = f"{rain:.1f}"
        snow_str  = f"{snow:.0f}"
        wind_str  = f"{wind:.0f}"
        desc_str  = _weather_code_to_desc(code)

        tmax_cells   += f'<td class="{fc_cls}"{tmax_cls(tmax)}>{tmax_str}</td>'
        tmin_cells   += f'<td class="{fc_cls}"{tmin_cls(tmin)}>{tmin_str}</td>'
        precip_cells += f'<td class="{fc_cls}">{pre_str}</td>'
        snow_cells   += f'<td class="{fc_cls}">{snow_str}</td>'
        wind_cells   += f'<td class="{fc_cls}">{wind_str}</td>'
        desc_cells   += f'<td class="{fc_cls}">{_h(desc_str)}</td>'

    return f"""
<div class="table-wrap">
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
</table>
</div>
"""


def _generate_station_cards(data: dict) -> str:
    """Генерирует карточки станций по течению."""
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})

    stations = [
        ("orel",     "Орёл",     "р. Ока"),
        ("belev",    "Белёв",    "р. Ока"),
        ("kaluga",   "Калуга",   "р. Ока"),
        ("serpuhov", "Серпухов", "р. Ока"),
        ("kashira",  "Кашира",   "р. Ока"),
        ("kolomna",  "Коломна",  "р. Ока"),
        ("ryazan",   "Рязань",   "р. Ока"),
    ]

    cards_html = '<div class="station-cards">\n'
    for slug, name, river in stations:
        level_cm  = None
        change_cm = None
        source_lbl = "нет данных"
        is_main    = (slug == "serpuhov")

        if slug == "serpuhov":
            level_cm   = serp.get("level_cm")
            change_cm  = serp.get("daily_change_cm")
            source_lbl = "serpuhov.ru / д. Лукьяново"
        elif slug == "kashira":
            level_cm   = (kim.get("kashira") or {}).get("level_cm")
            change_cm  = cugms.get("kashira_change_cm")
            source_lbl = "КИМ + ЦУГМС"
        elif slug == "kaluga":
            level_cm   = (kim.get("kaluga") or {}).get("level_cm")
            change_cm  = None
            source_lbl = "КИМ API"
        elif slug == "ryazan":
            level_cm   = (kim.get("ryazan") or {}).get("level_cm")
            change_cm  = None
            source_lbl = "КИМ API"
        elif slug == "orel":
            level_cm   = None
            change_cm  = None
            source_lbl = "нет данных"
        elif slug == "belev":
            level_cm   = None
            change_cm  = cugms.get("belev_change_cm")
            source_lbl = "ЦУГМС (прирост)"
        elif slug == "kolomna":
            level_cm  = (kim.get("kolomna") or {}).get("level_cm")
            change_cm = cugms.get("kolomna_change_cm")
            source_lbl = "КИМ / ЦУГМС (прирост)"

        # Цветовой класс по уровню
        if level_cm is None:
            color_cls  = "level-unknown"
            status_ico = "⚪"
        elif level_cm < ZONE_GREEN_MAX:
            color_cls  = "level-green"
            status_ico = "✅"
        elif level_cm < ZONE_YELLOW_MAX:
            color_cls  = "level-yellow"
            status_ico = "⚠️"
        elif level_cm < ZONE_ORANGE_MAX:
            color_cls  = "level-orange"
            status_ico = "🟠"
        else:
            color_cls  = "level-red"
            status_ico = "🔴"

        level_str  = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
        change_str = _fmt_change(change_cm)
        arrow      = _trend(change_cm)

        card_cls   = "station-card main-station" if is_main else "station-card"
        cards_html += f"""
  <div class="{card_cls}">
    <div class="st-name">{_h(name)}</div>
    <div class="st-river">{_h(river)}</div>
    <div class="st-level {color_cls}">{_h(level_str)}</div>
    <div class="st-change">{arrow} {_h(change_str)}</div>
    <div class="st-status">{status_ico}</div>
    <div class="st-source">{_h(source_lbl)}</div>
  </div>
"""

    cards_html += "</div>\n"
    return cards_html


def _generate_threshold_section(serp: dict, analytics: dict) -> str:
    """Генерирует секцию пороговых значений с вертикальной шкалой."""
    level_cm = serp.get("level_cm")
    abs_bs   = serp.get("abs_level_m_bs")

    if abs_bs is None and level_cm is not None:
        abs_bs = LUKYANNOVO_ZERO_M_BS + level_cm / 100.0

    # Вычисляем позиции на шкале (0% = нуль поста, 100% = ОЯ)
    total_range = LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS  # ≈ 8.00 м
    nya_pct = min(100, max(0, (LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) / total_range * 100))
    oya_pct = 100.0

    current_pct = 0.0
    if abs_bs is not None:
        current_pct = min(100, max(0, (abs_bs - LUKYANNOVO_ZERO_M_BS) / total_range * 100))

    # Статусы строк таблицы
    def thresh_status(threshold_m_bs, current):
        if current is None:
            return "нет данных"
        if current >= threshold_m_bs:
            return "⚠️ ДОСТИГНУТ"
        delta = threshold_m_bs - current
        return f"не достигнут (до порога {delta:.2f} м)"

    nya_status = thresh_status(LUKYANNOVO_NYA_M_BS, abs_bs)
    oya_status = thresh_status(LUKYANNOVO_OYA_M_BS, abs_bs)
    cur_status  = (f"{abs_bs:.3f} м БС" if abs_bs is not None else "нет данных")

    serp_abs_str = f"{abs_bs:.3f}" if abs_bs is not None else "?"

    return f"""
<section class="thresholds-section">
  <h3>📏 Пороговые отметки (пост д. Лукьяново)</h3>
  <div class="threshold-scale-container">
    <div class="v-scale-wrapper" style="position:relative; height:280px; width:220px; background:linear-gradient(to top, #1a7f37 0%, #d29922 55%, #db6d28 80%, #f85149 100%); border-radius:8px; overflow:visible;">
      <div style="position:absolute; left:0; top:0; bottom:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0.2) 100%); border-radius:8px;"></div>
      <!-- НЯ marker -->
      <div style="position:absolute; bottom:{nya_pct:.1f}%; left:0; right:0; display:flex; align-items:center; gap:4px; padding: 0 8px;">
        <div style="height:2px; background:rgba(255,220,100,0.9); flex:1;"></div>
        <span style="font-size:0.68em; color:#fff; background:rgba(0,0,0,0.55); padding:1px 5px; border-radius:3px; white-space:nowrap;">НЯ {LUKYANNOVO_NYA_M_BS} м</span>
      </div>
      <!-- ОЯ marker -->
      <div style="position:absolute; bottom:96%; left:0; right:0; display:flex; align-items:center; gap:4px; padding: 0 8px;">
        <div style="height:2px; background:rgba(255,120,100,0.9); flex:1;"></div>
        <span style="font-size:0.68em; color:#fff; background:rgba(0,0,0,0.55); padding:1px 5px; border-radius:3px; white-space:nowrap;">ОЯ {LUKYANNOVO_OYA_M_BS} м</span>
      </div>
      <!-- Текущий уровень -->
      <div style="position:absolute; bottom:{current_pct:.1f}%; left:-6px; right:-6px; height:4px; background:#79c0ff; box-shadow:0 0 8px #79c0ff; border-radius:2px;"></div>
      <div style="position:absolute; bottom:{current_pct:.1f}%; left:8px; transform:translateY(50%);">
        <span style="font-size:0.72em; color:#79c0ff; font-weight:700; background:rgba(0,0,0,0.7); padding:2px 6px; border-radius:3px; white-space:nowrap;">▶ {serp_abs_str} м БС</span>
      </div>
      <!-- Нуль поста -->
      <div style="position:absolute; bottom:2px; left:8px;">
        <span style="font-size:0.65em; color:rgba(255,255,255,0.7); white-space:nowrap;">Нуль ~{LUKYANNOVO_ZERO_M_BS} м</span>
      </div>
    </div>
    <table class="thresh-table">
      <thead><tr><th>Отметка</th><th>м БС</th><th>Значение</th><th>Статус</th></tr></thead>
      <tbody>
        <tr>
          <td>Нуль поста</td><td>~{LUKYANNOVO_ZERO_M_BS}</td>
          <td>База измерения (приблиз.)</td><td>—</td>
        </tr>
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
    Нуль поста ~{LUKYANNOVO_ZERO_M_BS} м БС (значение приблизительное).
  </p>
</section>
"""


def _generate_wave_section(data: dict, analytics: dict) -> str:
    """Генерирует секцию прогноза прихода волны."""
    wave_text = analytics.get("wave_dynamic_text", "")

    return f"""
<section class="wave-section">
  <h3>🌊 Прогноз прихода паводковой волны</h3>
  <div class="wave-cards">
    <div class="wave-card">
      <div class="wave-from">Орёл → Серпухов</div>
      <div class="wave-time">≈ 5–7 дней</div>
      <div class="wave-dist">~600 км</div>
    </div>
    <div class="wave-card">
      <div class="wave-from">Калуга → Серпухов</div>
      <div class="wave-time">≈ 2–3 дня</div>
      <div class="wave-dist">~180 км</div>
    </div>
    <div class="wave-card">
      <div class="wave-from">Алексин → Серпухов</div>
      <div class="wave-time">≈ 1–2 дня</div>
      <div class="wave-dist">~90 км</div>
    </div>
    <div class="wave-card highlight">
      <div class="wave-from">Серпухов → Жерновка</div>
      <div class="wave-time">≈ 6–12 часов</div>
      <div class="wave-dist">~8 км ниже Пущино</div>
    </div>
  </div>
  {f'<p class="wave-dynamic">{_h(wave_text)}</p>' if wave_text else ""}
  <p class="disclaimer-small">
    ⚠️ Оценочные данные на основе расстояния и типичной скорости течения.
    Реальное время зависит от уклона реки, заторов и осадков.
  </p>
</section>
"""


def _generate_peak_section(analytics: dict, regression) -> str:
    """Генерирует секцию прогноза пика."""
    peak = analytics.get("peak_prediction", {})
    if not peak:
        return ""

    trend      = peak.get("trend", "unknown")
    trend_text = _h(peak.get("trend_text", "Недостаточно данных"))
    disclaimer = _h(peak.get("disclaimer", ""))

    trend_colors = {
        "accelerating": "#f85149",
        "decelerating": "#d29922",
        "stable":       "#8b949e",
        "falling":      "#3fb950",
        "unknown":      "#8b949e",
    }
    trend_color = trend_colors.get(trend, "#8b949e")

    reg_block = ""
    if regression and regression.get("r_squared", 0) >= 0.5:
        r2        = regression.get("r_squared", 0)
        ml_text   = _h(regression.get("trend_text_ml", ""))
        pred3     = regression.get("pred_3d")
        pred7     = regression.get("pred_7d")
        peak_date = regression.get("peak_date")
        nya_cm    = regression.get("nya_cm", 645)
        pred3_str = f"{pred3:.0f}" if pred3 is not None else "?"
        pred7_str = f"{pred7:.0f}" if pred7 is not None else "?"
        peak_dt_str = f"<p>При текущем темпе НЯ ({nya_cm:.0f} см) может быть достигнута ~{_h(peak_date)}</p>" if peak_date else ""
        reg_block = f"""
  <div class="regression-block">
    <h4>🤖 Линейная регрессия (R²={r2:.2f}, {regression.get('n_points', 0)} точек)</h4>
    <p>{ml_text}</p>
    <p>Прогноз: через 3 дня ≈ <b>{pred3_str} см</b> | через 7 дней ≈ <b>{pred7_str} см</b></p>
    {peak_dt_str}
  </div>
"""

    return f"""
<section class="peak-section">
  <h3>📈 Прогноз пика</h3>
  <div class="peak-trend" style="color: {trend_color}; border-left: 3px solid {trend_color};">
    {trend_text}
  </div>
  {reg_block}
  <p class="disclaimer-small">⚠️ {disclaimer}</p>
</section>
"""


def _generate_cugms_section(cugms: dict) -> str:
    """Генерирует секцию обзора ЦУГМС."""
    status = cugms.get("source_status", "unavailable")

    if status == "unavailable" or not cugms.get("review_number"):
        return """
<section class="cugms-section">
  <h3>📋 Последний обзор ЦУГМС</h3>
  <div class="no-data">Данные ЦУГМС временно недоступны. Проверьте вручную:
    <a href="https://cugms.ru/gidrologiya/vesennee-polovode-i-dozhdevye-pavodki-2026/" target="_blank">
    cugms.ru</a>
  </div>
</section>
"""

    n          = cugms.get("review_number", "?")
    c_date     = _h(cugms.get("review_date", "?"))
    src_url    = cugms.get("source_url", "#")
    s_chg      = cugms.get("serpuhov_change_cm")
    k_chg      = cugms.get("kashira_change_cm")
    ko_chg     = cugms.get("kolomna_change_cm")
    ice_dict   = cugms.get("ice_status", {})
    forecast   = _h((cugms.get("forecast_text") or "")[:350])
    f_intens   = _h(cugms.get("forecast_intensity_mps") or "")
    dangerous  = cugms.get("dangerous_expected", False)

    s_chg_str  = f"{s_chg:+.0f} см/сут" if s_chg is not None else "нет данных"
    k_chg_str  = f"{k_chg:+.0f} см/сут" if k_chg is not None else "нет данных"

    kol_ice    = ice_dict.get("Коломна", "")
    kol_str    = kol_ice if kol_ice else (f"{ko_chg:+.0f} см/сут" if ko_chg is not None else "нет данных")

    danger_block = ""
    if dangerous:
        danger_block = '<div style="background:rgba(248,81,73,0.1); border-left:3px solid #f85149; padding:8px 12px; border-radius:0 6px 6px 0; font-size:0.88em; color:#f85149; margin:8px 0;">⚠️ ЦУГМС: ожидаются опасные явления!</div>'

    status_badge = "cached" if status == "cached" else "ok"
    status_label = "(из кеша)" if status == "cached" else ""

    return f"""
<section class="cugms-section">
  <h3>📋 Последний обзор ЦУГМС <span class="badge {status_badge}" style="vertical-align:middle;">{status_label}</span></h3>
  <div class="cugms-meta">
    Обзор №{n} от {c_date}
    <a href="{_h(src_url)}" target="_blank" rel="noopener">→ Полный текст</a>
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
      <span class="cugms-value ice">{_h(kol_str)}</span>
    </div>
    {f'<div class="cugms-forecast"><b>Прогноз ({_h(f_intens)}):</b> {forecast}…</div>' if forecast else ""}
  </div>
  <p class="explainer">
    ЦУГМС публикует только суточные приросты и качественные данные.
    Абсолютные уровни в см — платная услуга Росгидромета.
  </p>
</section>
"""


def _generate_history_section(history: list) -> str:
    """Генерирует секцию таблицы истории (последние 100 записей, newest first)."""
    rows = list(reversed(history[-100:]))

    rows_html = ""
    for row in rows:
        dt_str    = _h((row.get("datetime") or "")[:19].replace("T", " "))
        lv_cm     = row.get("serp_level_cm")
        lv_str    = f"{lv_cm:.0f}" if lv_cm is not None else "—"
        chg       = row.get("serp_daily_change_cm")
        chg_str   = _fmt_change(chg)
        abs_bs    = row.get("serp_abs_m_bs")
        abs_str   = f"{abs_bs:.3f}" if abs_bs is not None else "—"
        kashira   = row.get("kim_kashira_cm")
        kal       = row.get("kim_kaluga_cm")
        cugms_ch  = row.get("cugms_serp_change_cm")
        snow      = row.get("snow_depth_cm")
        al        = row.get("alert_level", "GREEN")
        src       = row.get("serp_source", "")

        delta_cls = ""
        if chg is not None:
            try:
                fchg = float(chg)
                if fchg > 5:
                    delta_cls = "style=\"color:#f85149;\""
                elif fchg < -5:
                    delta_cls = "style=\"color:#3fb950;\""
            except (ValueError, TypeError):
                pass

        rows_html += f"""
<tr class="row-{_h(al)}">
  <td>{dt_str}</td>
  <td>{_h(lv_str)}</td>
  <td {delta_cls}>{_h(chg_str)}</td>
  <td>{_h(abs_str)}</td>
  <td>{_h(str(kashira) if kashira is not None else "—")}</td>
  <td>{_h(str(kal) if kal is not None else "—")}</td>
  <td>{_h(str(cugms_ch) if cugms_ch is not None else "—")}</td>
  <td>{_h(str(int(snow)) if snow is not None else "—")}</td>
  <td>{_h(al)}</td>
  <td>{_h(src)}</td>
</tr>"""

    return f"""
<section class="history-section">
  <h3>📊 История наблюдений</h3>
  <div class="history-controls">
    <button onclick="filterHistory(7)" class="hist-btn">7 дней</button>
    <button onclick="filterHistory(30)" class="hist-btn">30 дней</button>
    <button onclick="filterHistory(0)" class="hist-btn">Всё</button>
    <a href="history.csv" download class="hist-btn dl-btn">⬇ CSV</a>
  </div>
  <div class="table-wrap">
    <table id="histTable">
      <thead>
        <tr>
          <th>Дата/время</th>
          <th>Уровень (см)</th>
          <th>Изменение</th>
          <th>м БС</th>
          <th>Кашира</th>
          <th>Калуга</th>
          <th>ЦУГМС см/сут</th>
          <th>Снег (см)</th>
          <th>Статус</th>
          <th>Источник</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
</section>
"""


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
<section class="reports-section">
  <h3>📁 PDF-архив обзоров</h3>
  <div class="report-cards">
    {cards_html}
  </div>
</section>
"""


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ HTML-ГЕНЕРАТОР
# ══════════════════════════════════════════════════════════════════════════════

def generate_html(data: dict, analytics: dict, history: list, wext,
                  regression, ref_2024) -> str:
    """
    Генерирует полную HTML-страницу index.html.
    Возвращает строку HTML с встроенными CSS и JS.
    """
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})

    level_cm  = serp.get("level_cm")
    change_cm = serp.get("daily_change_cm")
    abs_bs    = serp.get("abs_level_m_bs")
    src_stat  = serp.get("source_status", "unavailable")
    water_st  = serp.get("water_status", "")

    zone_name, zone_color, zone_bg, zone_label = get_level_zone(level_cm)

    # Цвет заголовка
    if zone_name == "GREEN":
        h1_bg = "#1a7f37"
    elif zone_name == "YELLOW":
        h1_bg = "#9a6700"
    elif zone_name == "ORANGE":
        h1_bg = "#bc4c00"
    else:
        h1_bg = "#8e0000"

    pulse_anim = "animation: pulse 1.5s infinite;" if zone_name == "RED" else ""
    alert_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "ORANGE": "🟠", "RED": "🔴"}.get(zone_name, "⚪")

    level_str = f"{level_cm:.0f} см" if level_cm is not None else "нет данных"
    abs_str   = f"{abs_bs:.3f} м БС" if abs_bs is not None else ""

    # Дельта
    delta_arrow = _trend(change_cm)
    if change_cm is not None:
        fchg = float(change_cm)
        delta_cls = "rising" if fchg > 5 else ("falling" if fchg < -5 else "stable")
    else:
        delta_cls = "stable"

    # Прогресс-бары
    nya_fill_pct = analytics.get("nya_fill_pct", 0)
    oya_fill_pct = analytics.get("oya_fill_pct", 0)
    nya_rem      = analytics.get("nya_remaining_m")
    oya_rem      = analytics.get("oya_remaining_m")
    nya_rem_str  = f"{nya_rem:.2f} м" if nya_rem is not None else "нет данных"
    oya_rem_str  = f"{oya_rem:.2f} м" if oya_rem is not None else "нет данных"

    # Время обновления
    now_msk = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")

    # Бейджи источников
    kim_stat   = (kim.get("_api_status") or "unavailable")
    cugms_stat = cugms.get("source_status", "unavailable")

    serp_badge  = _badge_class(src_stat)
    kim_badge   = _badge_class(kim_stat)
    cugms_badge = _badge_class(cugms_stat)

    # Action block
    fi                         = (wext or {}).get("flood_index", 0)
    action_icon, action_title, action_text, action_color = generate_action_block(level_cm, fi)

    # Погода: flood index block
    flood_index_block = ""
    weather_table_html = ""
    commentary_html    = ""
    if wext:
        fl_idx     = wext.get("flood_index", 0)
        fl_label   = _h(wext.get("flood_label", "?"))
        fl_summary = _h(wext.get("flood_summary", ""))
        fl_colors  = {0: "#3fb950", 1: "#3fb950", 2: "#d29922", 3: "#db6d28", 4: "#f85149"}
        fl_color   = fl_colors.get(fl_idx, "#8b949e")
        snow_d     = wext.get("snow_depth_cm", 0) or 0
        flood_index_block = f"""
<div class="weather-flood-index" style="border-color:{fl_color};">
  <span class="wfi-label">Паводковый индекс погоды (0–4)</span>
  <span class="wfi-value" style="color:{fl_color};">{fl_label} ({fl_idx}/4)</span>
  <p class="wfi-summary">{fl_summary}</p>
  <p style="font-size:0.82em; color:var(--text-muted); margin-top:4px;">Снежный покров: {snow_d:.0f} см</p>
</div>"""
        weather_table_html = _generate_weather_table(wext)
        commentary = wext.get("commentary", [])
        if commentary:
            items = "\n".join(f"<li>{_h(c)}</li>" for c in commentary)
            commentary_html = f"""
<div class="weather-commentary">
  <h4>📝 Аналитика погодных факторов</h4>
  <ul>{items}</ul>
</div>"""

    # Собираем полный HTML
    css  = _generate_common_css()
    nav  = _generate_nav("index")

    # Chart.js
    chart_block = generate_chart_js_block(history, ref_2024)

    # Threshold + wave + peak + cugms + history + reports
    thresh_block  = _generate_threshold_section(serp, analytics)
    wave_block    = _generate_wave_section(data, analytics)
    peak_block    = _generate_peak_section(analytics, regression)
    cugms_block   = _generate_cugms_section(cugms)
    history_block = _generate_history_section(history)
    reports_block = _generate_reports_section()
    station_cards = _generate_station_cards(data)

    water_st_str  = f" | Состояние: {_h(water_st)}" if water_st and water_st not in ("—", "-", "") else ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="OkaFloodMonitor — мониторинг паводка на реке Ока в районе Серпухова. Данные обновляются 4 раза в день.">
  <title>OkaFloodMonitor — Паводок Ока 2026</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
  {css}
  </style>
</head>
<body>

{nav}

<h1 style="background: {h1_bg}; {pulse_anim}">
  🌊 ПАВОДОК ОКА 2026 &nbsp; {alert_emoji} &nbsp; {_h(level_str)} &nbsp;|&nbsp; {_h(zone_label)}
</h1>
<div class="meta-bar">
  <span>Пост д. Лукьяново | serpuhov.ru | обновлено {now_msk} МСК{water_st_str}</span>
  <span class="source-badges">
    <span class="badge {serp_badge}" title="serpuhov.ru">serpuhov.ru</span>
    <span class="badge {kim_badge}" title="КИМ API">КИМ</span>
    <span class="badge {cugms_badge}" title="ЦУГМС">ЦУГМС</span>
  </span>
</div>

<div class="container">

  <!-- HERO BLOCK -->
  <section class="hero-block" style="border-color: {zone_color};">
    <div class="hero-level" style="color: {zone_color};">
      {_h(str(int(level_cm)) if level_cm is not None else "—")}<span class="hero-unit"> см</span>
    </div>
    <div class="hero-delta {delta_cls}">
      {delta_arrow} {_h(_fmt_change(change_cm))} / сут
    </div>
    <div class="hero-abs">{_h(abs_str)}</div>

    <div class="threshold-bars">
      <div class="tbar-row">
        <span class="tbar-label">До НЯ (пойма)</span>
        <div class="tbar-track">
          <div class="tbar-fill nya-fill" style="width: {nya_fill_pct:.1f}%;"></div>
        </div>
        <span class="tbar-val">{_h(nya_rem_str)}</span>
      </div>
      <div class="tbar-row">
        <span class="tbar-label">До ОЯ (подтопление)</span>
        <div class="tbar-track">
          <div class="tbar-fill oya-fill" style="width: {oya_fill_pct:.1f}%;"></div>
        </div>
        <span class="tbar-val">{_h(oya_rem_str)}</span>
      </div>
    </div>
  </section>

  <!-- СТАНЦИИ ПО ТЕЧЕНИЮ -->
  <h3>🗺️ Станции по течению (верховье → низовье)</h3>
  {station_cards}

  <!-- ДИСКЛЕЙМЕР / ИСТОЧНИКИ -->
  <div class="disclaimer-block">
    <div class="disclaimer-header" onclick="toggleDisclaimer()">
      ⚠️ О данных и источниках
      <span class="toggle-icon">▼</span>
    </div>
    <div id="disclaimer-body" class="disclaimer-body">
      <p class="disclaimer-alert">
        <b>⚠️ Росгидромет не публикует оперативные данные гидропостов в открытом доступе.</b>
        Сервис агрегирует данные из открытых источников.
      </p>
      <table class="sources-table">
        <thead><tr><th>Источник</th><th>Данные</th><th>Обновление</th><th>Ограничения</th></tr></thead>
        <tbody>
          <tr>
            <td><a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">serpuhov.ru</a></td>
            <td>Абсолютный уровень, пост д. Лукьяново</td>
            <td>ежедневно ~09:00</td>
            <td>Только 1 пост, данные за прошедшие сутки</td>
          </tr>
          <tr>
            <td><a href="https://ris.kim-online.ru/" target="_blank" rel="noopener">КИМ API</a></td>
            <td>Абсолютные уровни Кашира, Калуга, Рязань</td>
            <td>несколько раз в день</td>
            <td>Серпухов — данные 2022, не используется</td>
          </tr>
          <tr>
            <td><a href="https://cugms.ru/gidrologiya/vesennee-polovode-i-dozhdevye-pavodki-2026/" target="_blank" rel="noopener">ЦУГМС</a></td>
            <td>Суточные приросты, ледовая обстановка, прогнозы</td>
            <td>ежедневно (весенний период)</td>
            <td>Только приросты, без абсолютных уровней</td>
          </tr>
          <tr>
            <td><a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a></td>
            <td>Погода, снежный покров (snow_depth_max), прогноз</td>
            <td>несколько раз в день</td>
            <td>—</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- ACTION BLOCK: ЧТО ДЕЛАТЬ -->
  <div class="action-block" style="border-left: 4px solid {action_color};">
    <h3>{action_icon} {_h(action_title)}</h3>
    <p>{_h(action_text)}</p>
    <p class="action-meta">Обновлено: {now_msk} МСК</p>
  </div>

  <!-- ПОГОДА -->
  <div class="weather-ext-block">
    <h3>🌦 Расширенный прогноз погоды</h3>
    {flood_index_block}
    {weather_table_html}
    {chart_block}
    {commentary_html}
  </div>

  <!-- ПОРОГОВЫЕ ЗНАЧЕНИЯ -->
  {thresh_block}

  <!-- ПРОГНОЗ ВОЛНЫ -->
  {wave_block}

  <!-- ПРОГНОЗ ПИКА -->
  {peak_block}

  <!-- ОБЗОР ЦУГМС -->
  {cugms_block}

  <!-- ИСТОРИЯ -->
  {history_block}

  <!-- PDF-АРХИВ -->
  {reports_block}

</div>

<footer>
  OkaFloodMonitor v6.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

<script>
{_generate_clock_js()}
{_generate_disclaimer_js()}
{_generate_filter_js()}
</script>

</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# СТРАНИЦА: ССЫЛКИ
# ══════════════════════════════════════════════════════════════════════════════

def generate_links_page(data: dict) -> None:
    """Генерирует docs/links.html."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    nav = _generate_nav("links")
    css = _generate_common_css()

    serp = data.get("serpuhov", {}) if data else {}
    src_stat = serp.get("source_status", "unavailable")
    serp_badge = _badge_class(src_stat)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ссылки — OkaFloodMonitor</title>
  <style>
  {css}
  </style>
</head>
<body>
{nav}
<div class="container">
<h1>🔗 Полезные ссылки</h1>

<section class="links-section">
  <h2>🌊 Данные о паводке на Оке</h2>
  <ul>
    <li>
      <a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">
        serpuhov.ru — Паводковая обстановка Серпухова</a>
      — ежедневные данные о уровне воды у д. Лукьяново
      <span class="badge {serp_badge}" style="vertical-align:middle; margin-left:6px;">{src_stat}</span>
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
  </ul>
</section>

<section class="links-section">
  <h2>🌦 Погода</h2>
  <ul>
    <li><a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a>
      — погода и снежный покров (бесплатный API, используется в мониторинге)</li>
    <li><a href="https://meteoinfo.ru/" target="_blank" rel="noopener">Meteoinfo.ru</a>
      — прогноз погоды ФГБУ ЦПГиМ</li>
    <li><a href="https://rp5.ru/" target="_blank" rel="noopener">rp5.ru</a>
      — подробный прогноз для Серпухова</li>
  </ul>
</section>

<section class="links-section">
  <h2>🚨 Экстренные службы</h2>
  <ul>
    <li><b>Единый номер экстренных служб:</b> 112</li>
    <li><b>МЧС России (бесплатно):</b> 8-800-775-17-17</li>
    <li><a href="https://mchs.gov.ru/" target="_blank" rel="noopener">mchs.gov.ru</a>
      — официальный сайт МЧС России</li>
    <li><a href="https://serpuhov.ru/bezopasnost/grazhdanskaya-oborona/" target="_blank" rel="noopener">
      Гражданская оборона Серпухова</a></li>
    <li><a href="https://serpuhov.ru" target="_blank" rel="noopener">serpuhov.ru</a>
      — Администрация г.о. Серпухов</li>
  </ul>
</section>

<section class="links-section">
  <h2>📱 Местные ресурсы</h2>
  <ul>
    <li><a href="https://vk.com/selodedinovo" target="_blank" rel="noopener">ВКонтакте — село Дединово</a>
      — уровни воды у Луховиц (#Уровень_воды_Ока)</li>
    <li>
      <a href="https://em-from-pu.github.io/oka-flood-monitor" target="_blank" rel="noopener">
        OkaFloodMonitor — GitHub Pages</a>
      — основная страница мониторинга
    </li>
  </ul>
</section>

<section class="links-section">
  <h2>⚠️ Почему нет других источников?</h2>
  <div class="dead-sources">
    <p>Следующие ресурсы <b>прекратили публикацию данных</b> и не используются:</p>
    <ul>
      <li>fishingsib.ru — последние данные по Оке: март 2024</li>
      <li>allrivers.info/gauge/oka-serpuhov — последние данные: май 2024</li>
      <li>ЕСИМО — прекратил открытую публикацию данных Росгидромета ~2020</li>
      <li>КИМ API (Серпухов) — последние данные: ноябрь 2022 (используется только для Каширы, Калуги, Рязани)</li>
    </ul>
  </div>
</section>

<section class="links-section">
  <h2>📂 Публичные данные мониторинга</h2>
  <ul>
    <li><a href="history.csv" download>history.csv</a> — история уровней воды в формате CSV</li>
    <li><a href="data.json" target="_blank">data.json</a> — текущие данные в формате JSON</li>
  </ul>
</section>

</div>

<footer>
  OkaFloodMonitor v6.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

<script>
{_generate_clock_js()}
</script>
</body>
</html>
"""
    with open(LINKS_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] Сохранено: {LINKS_HTML}")


# ══════════════════════════════════════════════════════════════════════════════
# СТРАНИЦА: ИНСТРУКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

def generate_instructions_page() -> None:
    """Генерирует docs/instructions.html."""
    os.makedirs(DOCS_DIR, exist_ok=True)
    nav = _generate_nav("instructions")
    css = _generate_common_css()

    nya_cm = round((LUKYANNOVO_NYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)
    oya_cm = round((LUKYANNOVO_OYA_M_BS - LUKYANNOVO_ZERO_M_BS) * 100, 1)

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Инструкции — OkaFloodMonitor</title>
  <style>
  {css}
  </style>
</head>
<body>
{nav}
<div class="container">
<h1>📖 Инструкция по использованию мониторинга</h1>

<section class="instr-section">
  <h2>🌊 Что такое OkaFloodMonitor?</h2>
  <p>Автоматическая система мониторинга паводка на реке Оке в районе Серпухова.
  Работает 24/7, данные обновляются 4 раза в день (08:00, 12:00, 17:00, 20:00 МСК).</p>
  <p>Система агрегирует данные из нескольких открытых источников:
  официальный сайт г. Серпухова, навигационный сервис КИМ, ежедневные обзоры ЦУГМС
  и метеорологический сервис Open-Meteo.</p>
</section>

<section class="instr-section">
  <h2>📊 Откуда берутся данные?</h2>
  <p><b>Уровень воды в Серпухове</b> — сайт администрации г. Серпухова
  (<a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">serpuhov.ru</a>),
  пост наблюдения д. Лукьяново на р. Ока.
  Публикуется ежедневно в ~09:00. Данные: подъём воды в метрах
  относительно нуля поста и суточное изменение.</p>

  <p><b>Другие станции (Кашира, Калуга, Рязань)</b> — API навигационного
  сервиса <a href="https://ris.kim-online.ru/" target="_blank" rel="noopener">КИМ</a>.
  Абсолютные уровни воды в сантиметрах от нуля соответствующего поста
  (<em>не сравниваются напрямую с Серпуховом: у каждого поста свой нуль!</em>).</p>

  <p><b>Суточные приросты и прогнозы</b> —
  <a href="https://cugms.ru/" target="_blank" rel="noopener">Центральное УГМС (ЦУГМС)</a>,
  ежедневные обзоры развития весеннего половодья. Только качественные данные
  (приросты и ледовая обстановка), без абсолютных уровней.</p>

  <p><b>Погода и снежный покров</b> —
  <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo API</a> (бесплатный).
  Температура, осадки, глубина снежного покрова (snow_depth_max, в метрах×100=см).</p>
</section>

<section class="instr-section">
  <h2>🔢 Как читать данные?</h2>
  <h3>Уровень воды (см)</h3>
  <p>Высота воды над нулём водомерного поста д. Лукьяново.
  Нуль поста ≈ {LUKYANNOVO_ZERO_M_BS} м БС (Балтийская система высот, значение приблизительное).
  Формула: <b>абсолютный уровень = {LUKYANNOVO_ZERO_M_BS} + уровень_м</b></p>

  <div class="zone-table">
    <div class="zone-row green">
      &lt; {ZONE_GREEN_MAX} см — <b>Норма</b>. Паводковый сезон в начальной фазе.
    </div>
    <div class="zone-row yellow">
      {ZONE_GREEN_MAX}–{ZONE_YELLOW_MAX} см — <b>Внимание</b>. Пойма начинает заполняться.
    </div>
    <div class="zone-row orange">
      {ZONE_YELLOW_MAX}–{ZONE_ORANGE_MAX} см — <b>Опасность</b>. Пойма затоплена, приближаемся к НЯ.
    </div>
    <div class="zone-row red">
      &gt; {ZONE_ORANGE_MAX} см — <b>Критический уровень</b>. Немедленно следите за сводками.
    </div>
  </div>

  <h3>НЯ и ОЯ</h3>
  <p><b>НЯ ({LUKYANNOVO_NYA_M_BS} м БС, ≈{nya_cm:.0f} см от нуля поста)</b> —
  «неблагоприятное явление» — уровень выхода воды на пойму.
  При достижении этой отметки пойменные луга затопляются.</p>

  <p><b>ОЯ ({LUKYANNOVO_OYA_M_BS} м БС, ≈{oya_cm:.0f} см от нуля поста)</b> —
  «опасное явление» — уровень подтопления населённых пунктов.
  Вода начинает угрожать постройкам.</p>

  <h3>Изменение за сутки</h3>
  <p>Знак «+» означает рост уровня, «–» — спад.
  Интенсивный рост (&gt; 30 см/сут) — признак активного таяния снега или дождевого паводка.</p>

  <h3>Разные нули постов</h3>
  <p>Данные КИМ (Кашира, Калуга, Рязань) измеряются в сантиметрах
  <em>от нуля поста КИМ</em>, который отличается от нуля поста Лукьяново.
  Не сравнивайте уровни напрямую между разными станциями!</p>
</section>

<section class="instr-section">
  <h2>🌡 Паводковый индекс погоды</h2>
  <p>Комплексный показатель риска подъёма воды (0–4), вычисляется по данным Open-Meteo:</p>
  <ul>
    <li><b>0 — СТАБИЛЬНЫЙ</b>: морозы сдерживают таяние</li>
    <li><b>1 — УМЕРЕННЫЙ</b>: незначительное таяние</li>
    <li><b>2 — ПОВЫШЕННЫЙ</b>: снег тает, осадки умеренные</li>
    <li><b>3 — ВЫСОКИЙ</b>: значительный риск подъёма</li>
    <li><b>4 — КРИТИЧЕСКИЙ</b>: активное таяние + осадки + возможен Rain-on-Snow</li>
  </ul>
  <p><b>Rain-on-Snow</b> — дождь на снег при температуре выше 0°С — самый опасный фактор
  паводка: одновременно таяние снега + добавление дождевой воды.</p>
</section>

<section class="instr-section">
  <h2>🚨 Что делать при разных уровнях?</h2>
  <table class="action-table">
    <tr><th>Уровень (см)</th><th>Статус</th><th>Рекомендации</th></tr>
    <tr><td>&lt; {ZONE_GREEN_MAX}</td><td>🟢 Норма</td><td>Следите за динамикой. Обновления 4 раза в день.</td></tr>
    <tr><td>{ZONE_GREEN_MAX}–{ZONE_YELLOW_MAX}</td><td>🟡 Внимание</td><td>Проверьте дачный участок. Уберите ценности с низких мест.</td></tr>
    <tr><td>{ZONE_YELLOW_MAX}–{ZONE_ORANGE_MAX}</td><td>🟠 Опасность</td><td>Подготовьтесь к возможной эвакуации. Насосы наготове.</td></tr>
    <tr><td>&gt; {ZONE_ORANGE_MAX}</td><td>🔴 Критично</td><td>Немедленно вывезите ценные вещи. Свяжитесь с ЕДДС Серпухова.</td></tr>
  </table>
</section>

<section class="instr-section">
  <h2>📞 Контакты экстренных служб</h2>
  <ul>
    <li>Единый номер экстренных служб: <b>112</b></li>
    <li>МЧС России (бесплатно): <b>8-800-775-17-17</b></li>
    <li>Администрация Серпухова:
      <a href="https://serpuhov.ru" target="_blank" rel="noopener">serpuhov.ru</a></li>
    <li>Официальная информация о паводке:
      <a href="https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/" target="_blank" rel="noopener">
      serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/</a></li>
  </ul>
</section>

<section class="instr-section">
  <h2>📱 Telegram-уведомления</h2>
  <p>Бот <b>@OkaFlood2026EMbot</b> автоматически отправляет:</p>
  <ul>
    <li>Ежедневные сводки в 08:00 и 20:00 МСК</li>
    <li>Экстренные алерты при пересечении пороговых отметок
      ({ALERT_ATTENTION}, {ALERT_DANGER}, {ALERT_CRITICAL}, {ALERT_EMERGENCY} см)</li>
    <li>Погодные предупреждения при высоком паводковом индексе (≥3/4)</li>
    <li>Watchdog-уведомления при недоступности источников данных</li>
  </ul>
</section>

<section class="instr-section">
  <h2>🤖 Линейная регрессия (ML-прогноз)</h2>
  <p>Система строит простую линейную регрессию уровня за последние 14 дней.
  Метод наименьших квадратов, без внешних библиотек.
  Значение R² показывает качество аппроксимации (0–1, чем выше — тем точнее).</p>
  <p><b>Прогноз приблизительный</b> — реальное поведение реки зависит от темпа
  таяния снега, осадков и гидрологической обстановки в бассейне.</p>
</section>

<section class="instr-section">
  <h2>❓ Часто задаваемые вопросы</h2>
  <p><b>Почему данные обновляются только раз в день?</b><br>
  serpuhov.ru публикует данные ежедневно ~09:00 МСК. GitHub Actions запускает
  скрипт 4 раза в день, но новые данные serpuhov.ru появляются раз в сутки.</p>

  <p><b>Почему нет данных Серпухова в КИМ?</b><br>
  В КИМ API последние данные по посту Серпухов датируются ноябрём 2022.
  В v6 Серпухов полностью переведён на serpuhov.ru.</p>

  <p><b>Что такое «Жерновка»?</b><br>
  Локальное название местности примерно в 8 км ниже Пущино по реке Ока.
  Паводковая волна от Серпухова доходит туда примерно за 6–12 часов.</p>
</section>

</div>

<footer>
  OkaFloodMonitor v6.0 | 54.834050, 37.742901 | Жерновка, р. Ока<br>
  Источники: serpuhov.ru | КИМ | ЦУГМС | Open-Meteo<br>
  <a href="https://em-from-pu.github.io/oka-flood-monitor">em-from-pu.github.io/oka-flood-monitor</a>
</footer>

<script>
{_generate_clock_js()}
</script>
</body>
</html>
"""
    with open(INSTRUCTIONS_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[HTML] Сохранено: {INSTRUCTIONS_HTML}")


# ══════════════════════════════════════════════════════════════════════════════
# GIT
# ══════════════════════════════════════════════════════════════════════════════

def git_push() -> None:
    """Выполняет git add, commit, push."""
    try:
        now_str = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
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
            ["git", "commit", "-m", f"auto: monitor v6.0 update {now_str} МСК"],
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
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC] "
        f"OkaFloodMonitor v6.0 START"
    )

    # ─── 1. ДАННЫЕ ───────────────────────────────────────────────────────
    data  = fetch_all_data()
    serp  = data.get("serpuhov", {})
    kim   = data.get("kim", {})
    cugms = data.get("cugms", {})
    wext  = data.get("weather")

    serp_level_cm  = serp.get("level_cm")
    serp_change_cm = serp.get("daily_change_cm")

    print(f"  serpuhov.ru: {serp_level_cm} см ({serp.get('source_status')})")
    kash_cm = (kim.get("kashira") or {}).get("level_cm")
    kal_cm  = (kim.get("kaluga") or {}).get("level_cm")
    print(f"  КИМ: Кашира={kash_cm} Калуга={kal_cm}")
    print(
        f"  ЦУГМС: обзор №{cugms.get('review_number')}, "
        f"Серпухов {cugms.get('serpuhov_change_cm')} см/сут"
    )

    # ─── 2. ИСТОРИЯ: загрузка ────────────────────────────────────────────
    history = load_history()

    # ─── 3. АНАЛИТИКА ────────────────────────────────────────────────────
    analytics  = compute_analytics(serp, kim, cugms, history, wext)
    regression = compute_simple_regression(history)

    # ─── 4. ИСТОРИЯ: добавление строки и сохранение ──────────────────────
    history = append_history_row(history, data, analytics, wext)
    save_history(history)
    export_history_csv(history)
    print(f"  История: {len(history)} записей сохранено.")

    # ─── 5. АЛЕРТЫ ───────────────────────────────────────────────────────
    alerts = load_alerts()
    alerts_changed = False

    level_triggered = check_level_triggers(serp_level_cm, alerts)
    for key, text in level_triggered:
        tg_send(CHAT_ADMIN, text)
        if serp_level_cm and serp_level_cm >= ALERT_DANGER:
            tg_send(CHAT_MY_GROUP, text)
        alerts[key]   = datetime.now(timezone.utc).isoformat()
        alerts_changed = True

    watchdog_triggered = check_watchdog(data, alerts)
    for key, text in watchdog_triggered:
        tg_send(CHAT_ADMIN, text)
        alerts[key]   = datetime.now(timezone.utc).isoformat()
        alerts_changed = True

    # Превентивный погодный алерт
    fi = (wext or {}).get("flood_index", 0)
    if wext and (serp_level_cm or 0) < ALERT_ATTENTION and fi >= 3:
        key = f"WEATHER_ALERT_{fi}"
        if should_send_alert(alerts, key, cooldown_h=12):
            label   = wext.get("flood_label", "")
            summary = wext.get("flood_summary", "")
            msg = (
                f"🌧️ <b>[ПРОГНОЗ ПОГОДЫ]</b> Паводковый индекс: <b>{_h(label)}</b> ({fi}/4)\n\n"
                f"{_h(summary)}\n\n"
                "⚠️ Вода пока спокойна, но условия указывают на возможный "
                "подъём в ближайшие 2–3 дня."
            )
            tg_send(CHAT_ADMIN, msg)
            tg_send(CHAT_MY_GROUP, msg)
            alerts[key]   = datetime.now(timezone.utc).isoformat()
            alerts_changed = True

    if alerts_changed:
        save_alerts(alerts)

    # ─── 6. TELEGRAM: регулярные сообщения ───────────────────────────────
    msk_hour = (datetime.now(timezone.utc) + timedelta(hours=3)).hour

    heartbeat = format_heartbeat(serp, kim, cugms, wext)
    tg_send(CHAT_ADMIN, heartbeat)
    tg_send(CHAT_MY_GROUP, heartbeat)

    digest = format_digest(data, history, wext, analytics, regression)
    tg_send(CHAT_ADMIN, digest)

    if (serp_level_cm or 0) >= ALERT_DANGER or analytics.get("alert_level") in ("ORANGE", "RED"):
        tg_send(CHAT_MY_GROUP, digest)

    if CHAT_NEIGHBORS and msk_hour in (8, 20):
        neighbors_msg = format_neighbors_digest(data, wext, analytics)
        tg_send(CHAT_NEIGHBORS, neighbors_msg)

    if msk_hour in (8, 20):
        for cid in load_mailing_list():
            neighbors_msg = format_neighbors_digest(data, wext, analytics)
            tg_send(str(cid), neighbors_msg)

    group_draft = format_group_draft(data, wext)
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(GROUP_DRAFT, "w", encoding="utf-8") as f:
        f.write(group_draft)

    # ─── 7. HTML ГЕНЕРАЦИЯ ───────────────────────────────────────────────
    ref_2024 = load_2024_ref()

    html_content = generate_html(
        data=data, analytics=analytics, history=history,
        wext=wext, regression=regression, ref_2024=ref_2024,
    )
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[HTML] Сохранено: {INDEX_HTML} ({len(html_content)} символов)")

    generate_links_page(data)
    generate_instructions_page()

    # ─── 8. DATA.JSON ────────────────────────────────────────────────────
    data_out = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "serpuhov": {
            "level_cm":       serp_level_cm,
            "level_m":        serp.get("level_m"),
            "daily_change_cm":serp_change_cm,
            "abs_m_bs":       serp.get("abs_level_m_bs"),
            "nya_m_bs":       serp.get("nya_m_bs", LUKYANNOVO_NYA_M_BS),
            "oya_m_bs":       serp.get("oya_m_bs", LUKYANNOVO_OYA_M_BS),
            "water_status":   serp.get("water_status"),
            "source":         "serpuhov.ru",
            "source_status":  serp.get("source_status"),
            "cache_age_h":    serp.get("cache_age_h", 0),
        },
        "kim": {
            "kashira_cm": kash_cm,
            "kaluga_cm":  kal_cm,
            "ryazan_cm":  (kim.get("ryazan") or {}).get("level_cm"),
            "api_status": kim.get("_api_status"),
        },
        "cugms": {
            "review_number":    cugms.get("review_number"),
            "review_date":      cugms.get("review_date"),
            "serpuhov_change_cm": cugms.get("serpuhov_change_cm"),
            "kashira_change_cm":  cugms.get("kashira_change_cm"),
            "forecast_intensity": cugms.get("forecast_intensity_mps"),
            "dangerous_expected": cugms.get("dangerous_expected", False),
            "source_status":    cugms.get("source_status"),
        },
        "weather": {
            "flood_index":   (wext or {}).get("flood_index"),
            "flood_label":   (wext or {}).get("flood_label"),
            "flood_summary": (wext or {}).get("flood_summary"),
            "snow_depth_cm": (wext or {}).get("snow_depth_cm"),
        },
        "analytics": analytics,
        "regression": regression,
        "sources_ok":     data.get("sources_ok", []),
        "sources_failed": data.get("sources_failed", []),
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    print(f"[data.json] Сохранено: {DATA_JSON}")

    # ─── 9. GIT PUSH ─────────────────────────────────────────────────────
    git_push()

    print(
        f"✅ OkaFloodMonitor v6.0 DONE | Серпухов: {serp_level_cm} см | "
        f"Алерт: {analytics.get('alert_level')} | "
        f"Источники OK: {data.get('sources_ok')}"
    )


if __name__ == "__main__":
    main()
