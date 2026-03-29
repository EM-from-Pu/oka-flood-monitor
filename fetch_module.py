#!/usr/bin/env python3
"""
fetch_module.py v3.0 — OkaFloodMonitor v7.0
Источники данных: serpuhov.ru | КИМ API | ЦУГМС | Open-Meteo | GloFAS Flood API

Архитектура: 5 уровней приоритета
  УРОВЕНЬ 1 (PRIMARY):       serpuhov.ru    — абсолютный уровень Серпухов/Лукьяново
  УРОВЕНЬ 2 (SECONDARY):     КИМ API        — Кашира
  УРОВЕНЬ 3 (SUPPLEMENTARY): ЦУГМС обзоры   — суточные приросты, лёд, прогноз
  УРОВЕНЬ 4 (WEATHER):       Open-Meteo API — погода, снег, прогноз
  УРОВЕНЬ 5 (GLOFAS):        GloFAS API     — расход 7 станций выше Серпухова

Все HTTP-вызовы — в try/except с таймаутом.
При падении источника — graceful degradation с кешем.

Изменения v3.0 относительно v2.0:
  - ДОБАВЛЕНО: GloFAS Flood API (УРОВЕНЬ 5) — 7 станций выше Серпухова
  - ИСПРАВЛЕНО: fetch_cugms_review() — парсер теперь извлекает только тело статьи
  - ИСПРАВЛЕНО: _parse_cugms_text() — улучшен парсинг прогнозного текста
  - ИСПРАВЛЕНО: snow_depth_max (не snow_depth) в параметрах Open-Meteo
  - ИСПРАВЛЕНО: alerts_sent.json в data/ (не docs/)
  - ДОБАВЛЕНО: GLOFAS_STATIONS dict (7 станций)
  - ДОБАВЛЕНО: fetch_glofas_station(), fetch_all_glofas_upstream()
  - ДОБАВЛЕНО: calculate_wave_arrival(), calculate_flood_ratio()
  - ДОБАВЛЕНО: _svg_sparkline() — inline SVG для карточек станций
  - ОБНОВЛЕНО: fetch_all_data() — 5 sources, 5 workers
"""

import os
import re
import json
import logging
import concurrent.futures
from datetime import datetime, date as date_cls, timezone, timedelta

import requests
from bs4 import BeautifulSoup

# ─── ЛОГИРОВАНИЕ ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fetch_module")

# ─── ПУТИ ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Кеш-файлы
SERPUHOV_CACHE = os.path.join(DATA_DIR, "serpuhov_cache.json")
KIM_CACHE      = os.path.join(DATA_DIR, "kim_cache.json")
CUGMS_CACHE    = os.path.join(DATA_DIR, "cugms_cache.json")
GLOFAS_CACHE   = os.path.join(DATA_DIR, "glofas_cache.json")   # NEW v3.0

# ─── КОНСТАНТЫ ПОСТА ЛУКЬЯНОВО (serpuhov.ru) ─────────────────────────────────
LUKYANNOVO_ZERO_M_BS = 107.54   # Нуль поста д. Лукьяново (приблизительно, м БС)
LUKYANNOVO_NYA_M_BS  = 113.99   # НЯ — выход воды на пойму (м БС)
LUKYANNOVO_OYA_M_BS  = 115.54   # ОЯ — подтопление населённых пунктов (м БС)

# ─── ЦВЕТОВЫЕ ЗОНЫ (уровень в СМ от нуля поста) ──────────────────────────────
ZONE_GREEN_MAX  = 400   # До 400 см — норма (зелёный)
ZONE_YELLOW_MAX = 600   # 400–600 см — внимание (жёлтый)
ZONE_ORANGE_MAX = 800   # 600–800 см — опасность (оранжевый)
# Выше 800 см — критический (красный)

# ─── ОРИЕНТИРЫ ДЛЯ ПРИХОДА ВОЛНЫ ─────────────────────────────────────────────
# Приблизительно, на основе расстояния и скорости течения
WAVE_OREL_TO_SERPUHOV      = (5, 7)       # 5–7 дней
WAVE_MTSENSK_TO_SERPUHOV   = (5, 6)       # 5–6 дней
WAVE_BELEV_TO_SERPUHOV     = (4, 5)       # 4–5 дней
WAVE_KALUGA_TO_SERPUHOV    = (2, 3)       # 2–3 дня
WAVE_ALEKSIN_TO_SERPUHOV   = (1, 2)       # 1–2 дня
WAVE_TARUSA_TO_SERPUHOV    = (0.5, 1)     # 0.5–1 день
WAVE_SERPUHOV_TO_ZHERNIVKA = (0.25, 0.5)  # 6–12 часов (Жерновка ~8 км ниже Пущино)

# ─── КООРДИНАТЫ ────────────────────────────────────────────────────────────────
SERPUHOV_LAT = 54.834050
SERPUHOV_LON = 37.742901
SERP_LAT = SERPUHOV_LAT   # псевдоним для совместимости
SERP_LON = SERPUHOV_LON

# ─── GLOFAS: КОНФИГУРАЦИЯ СТАНЦИЙ ─────────────────────────────────────────────
# NEW v3.0 — 7 upstream monitoring stations
GLOFAS_STATIONS = {
    "orel": {
        "name": "Орёл",
        "river": "р. Ока",
        "lat": 52.925,
        "lon": 36.025,
        "wave_to_serpuhov": WAVE_OREL_TO_SERPUHOV,      # (min_days, max_days)
    },
    "mtsensk": {
        "name": "Мценск",
        "river": "р. Ока",
        "lat": 53.275,
        "lon": 36.575,
        "wave_to_serpuhov": WAVE_MTSENSK_TO_SERPUHOV,
    },
    "belev": {
        "name": "Белёв",
        "river": "р. Ока",
        "lat": 53.775,
        "lon": 36.125,
        "wave_to_serpuhov": WAVE_BELEV_TO_SERPUHOV,
    },
    "kaluga": {
        "name": "Калуга",
        "river": "р. Ока",
        "lat": 54.475,
        "lon": 36.275,
        "wave_to_serpuhov": WAVE_KALUGA_TO_SERPUHOV,
    },
    "aleksin": {
        "name": "Алексин",
        "river": "р. Ока",
        "lat": 54.475,
        "lon": 37.025,
        "wave_to_serpuhov": WAVE_ALEKSIN_TO_SERPUHOV,
    },
    "tarusa": {
        "name": "Таруса",
        "river": "р. Ока",
        "lat": 54.725,
        "lon": 37.175,
        "wave_to_serpuhov": WAVE_TARUSA_TO_SERPUHOV,
    },
    "kozelsk": {
        "name": "Козельск (Жиздра)",
        "river": "р. Жиздра",
        "lat": 54.025,
        "lon": 35.775,
        "wave_to_serpuhov": (3, 5),   # Жиздра впадает в Оку у Перемышля
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КЕША
# ══════════════════════════════════════════════════════════════════════════════

def _save_cache(filepath: str, data: dict) -> None:
    """Сохраняет данные в JSON-кеш. Создаёт директорию при необходимости."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Кеш сохранён: %s", filepath)
    except Exception as exc:
        logger.error("Ошибка записи кеша %s: %s", filepath, exc)


def _load_cache(filepath: str) -> dict | None:
    """Загружает данные из JSON-кеша. Возвращает None если файл не существует или повреждён."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    except Exception as exc:
        logger.error("Ошибка чтения кеша %s: %s", filepath, exc)
        return None


def _cache_age_h(timestamp_iso: str) -> float:
    """Возраст кеша в часах от ISO-timestamp до текущего момента UTC."""
    try:
        ts = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return round(delta.total_seconds() / 3600, 1)
    except Exception:
        return 999.0


def _now_msk_iso() -> str:
    """Возвращает текущее время MSK (UTC+3) в формате ISO."""
    msk = timezone(timedelta(hours=3))
    return datetime.now(msk).isoformat()


def _now_utc_iso() -> str:
    """Возвращает текущее время UTC в формате ISO."""
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 1: serpuhov.ru — ГЛАВНЫЙ ИСТОЧНИК (пост д. Лукьяново)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_ru_float(s: str) -> float:
    """
    Парсит число в русском формате: '2,03' → 2.03; '+2,03' → 2.03; '-0,49' → -0.49.
    Убирает лидирующий '+', заменяет запятую на точку.
    """
    s = s.strip().replace(",", ".").replace(" ", "").replace("\u00a0", "")
    if s.startswith("+"):
        s = s[1:]
    return float(s)


def fetch_serpuhov_level() -> dict:
    """
    УРОВЕНЬ 1 (PRIMARY): парсит HTML-таблицу паводковой обстановки на serpuhov.ru.

    URL: https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/
    Обновление сайта: ежедневно ~09:00 MSK.

    Таблица содержит одну строку данных для поста д. Лукьяново на р. Ока:
    - Текущий уровень подъёма воды (м) — ОТНОСИТЕЛЬНО нуля поста (≈107,54 м БС)
    - Изменение за сутки (м)
    - НЯ, ОЯ (м БС) — постоянные отметки

    Возвращает:
        {
          "level_m": float,          # подъём в метрах (напр. 2.03)
          "level_cm": float,         # подъём в см (напр. 203.0)
          "daily_change_m": float,   # изменение за сутки в метрах (напр. 0.49)
          "daily_change_cm": float,  # изменение за сутки в см (напр. 49.0)
          "nya_m_bs": float,         # отметка НЯ в м БС (113.99)
          "oya_m_bs": float,         # отметка ОЯ в м БС (115.54)
          "abs_level_m_bs": float,   # абсолютный уровень = ZERO + level_m
          "water_status": str,       # состояние водного объекта
          "timestamp": str,          # ISO timestamp запроса (UTC)
          "source": "serpuhov.ru",
          "source_status": "ok" | "cached" | "unavailable",
          "cache_age_h": float,      # возраст кеша в часах (0.0 если свежие данные)
        }
    """
    url = "https://serpuhov.ru/bezopasnost/pavodkovaya-obstanovka/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    try:
        logger.info("[serpuhov.ru] Запрос: %s", url)
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")

        # Ищем таблицу с данными паводка
        table = soup.find("table")
        if not table:
            raise ValueError("Таблица не найдена на странице serpuhov.ru")

        rows = table.find_all("tr")
        data_rows = [r for r in rows if r.find("td")]
        if not data_rows:
            raise ValueError("Строки данных (td) не найдены в таблице")

        # Берём последнюю строку с данными
        cells = [td.get_text(separator=" ", strip=True) for td in data_rows[-1].find_all("td")]
        if len(cells) < 7:
            raise ValueError(f"Недостаточно ячеек в строке: {len(cells)} (ожидалось ≥7)")

        # cells[0] = №
        # cells[1] = водный объект (р. Ока)
        # cells[2] = пост наблюдения (д. Лукьяново)
        # cells[3] = НЯ (м БС)
        # cells[4] = ОЯ (м БС)
        # cells[5] = Текущий уровень подъёма воды (м)
        # cells[6] = Изменение за сутки (м)
        # cells[7] = Состояние водного объекта (необязательно)

        nya_m_bs       = _parse_ru_float(cells[3])
        oya_m_bs       = _parse_ru_float(cells[4])
        level_m        = _parse_ru_float(cells[5])
        daily_change_m = _parse_ru_float(cells[6])
        water_status   = cells[7].strip() if len(cells) > 7 else "—"

        # Нормализуем прочерк
        if not water_status or water_status in ("", "-"):
            water_status = "—"

        result = {
            "level_m":         level_m,
            "level_cm":        round(level_m * 100, 1),
            "daily_change_m":  daily_change_m,
            "daily_change_cm": round(daily_change_m * 100, 1),
            "nya_m_bs":        nya_m_bs,
            "oya_m_bs":        oya_m_bs,
            "abs_level_m_bs":  round(LUKYANNOVO_ZERO_M_BS + level_m, 3),
            "water_status":    water_status,
            "timestamp":       _now_utc_iso(),
            "source":          "serpuhov.ru",
            "source_status":   "ok",
            "cache_age_h":     0.0,
        }

        logger.info(
            "[serpuhov.ru] OK — уровень %.2f м (%.0f см), Δ24ч: %+.2f м",
            level_m, level_m * 100, daily_change_m,
        )
        _save_cache(SERPUHOV_CACHE, result)
        return result

    except Exception as exc:
        logger.warning("[serpuhov.ru] Ошибка: %s", exc)

        cached = _load_cache(SERPUHOV_CACHE)
        if cached:
            cached["source_status"] = "cached"
            cached["cache_age_h"] = _cache_age_h(cached.get("timestamp", ""))
            logger.info("[serpuhov.ru] Используем кеш (возраст %.1f ч)", cached["cache_age_h"])
            return cached

        logger.error("[serpuhov.ru] Кеш недоступен — возвращаем unavailable")
        return {
            "level_m":         None,
            "level_cm":        None,
            "daily_change_m":  None,
            "daily_change_cm": None,
            "nya_m_bs":        LUKYANNOVO_NYA_M_BS,
            "oya_m_bs":        LUKYANNOVO_OYA_M_BS,
            "abs_level_m_bs":  None,
            "water_status":    "нет данных",
            "timestamp":       _now_utc_iso(),
            "source":          "serpuhov.ru",
            "source_status":   "unavailable",
            "cache_age_h":     0.0,
        }


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 2: КИМ API — Кашира, Калуга, Рязань (НЕ Серпухов!)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_kim_stations() -> dict:
    """
    УРОВЕНЬ 2 (SECONDARY): КИМ API для станций на р. Ока — Кашира, Калуга, Рязань.

    URL: https://ris.kim-online.ru/api.php?demand=water_levels
    Таймаут: 10 секунд.

    ВАЖНО: Серпухов из КИМ API НЕ использовать — данные с ноября 2022 года!
    Источник данных для Серпухова: serpuhov.ru (уровень 1).

    Возвращает:
        {
          "kashira": {"level_cm": int, "date": str, "source": "kim", "status": "ok"},
          "kaluga":  {"level_cm": int, "date": str, "source": "kim", "status": "ok"},
          "ryazan":  {"level_cm": int, "date": str, "source": "kim", "status": "ok"},
          "kolomna": {"level_cm": int|None, "date": str, "source": "kim", "status": str},
          "_api_status": "ok" | "cached" | "unavailable",
          "_timestamp": str,
        }
    """
    url = "https://ris.kim-online.ru/api.php?demand=water_levels"

    # Станции, которые нам нужны (slug → варианты написания в API, нижний регистр)
    WANTED = {
        "kashira": ["кашира", "kashira"],
        "kaluga":  ["калуга", "kaluga"],
        "ryazan":  ["рязань", "ryazan"],
        "kolomna": ["коломна", "kolomna"],
    }

    # Названия рек Ока (для фильтра)
    OKA_VARIANTS = ["ока", "oka"]

    try:
        logger.info("[КИМ API] Запрос: %s", url)
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            raise ValueError(f"КИМ API вернул не список, а {type(data).__name__}")

        result: dict = {}

        for entry in data:
            if not isinstance(entry, dict):
                continue

            name  = (entry.get("station_name") or "").lower().strip()
            river = (entry.get("river_name")   or "").lower().strip()

            # Явно пропускаем Серпухов — данные 2022 года, мертвы
            if "серпухов" in name or "serpukhov" in name or "serpuhov" in name:
                logger.debug("[КИМ API] Пропускаем Серпухов (данные 2022)")
                continue

            # Фильтруем только р. Ока
            if not any(oka in river for oka in OKA_VARIANTS):
                continue

            for slug, aliases in WANTED.items():
                if slug in result:
                    # Уже нашли эту станцию — не перезаписываем
                    continue
                if any(alias in name for alias in aliases):
                    level = entry.get("level_cm")
                    date_str = entry.get("date", "")
                    result[slug] = {
                        "level_cm": int(level) if level is not None else None,
                        "date":     date_str,
                        "source":   "kim",
                        "status":   "ok" if level is not None else "no_data",
                    }
                    logger.info(
                        "[КИМ API] Станция %s (%s): уровень=%s см, дата=%s",
                        slug, name, level, date_str,
                    )

        # Гарантируем наличие всех ключей
        for slug in WANTED:
            if slug not in result:
                result[slug] = {
                    "level_cm": None,
                    "date":     "",
                    "source":   "kim",
                    "status":   "not_found",
                }

        result["_api_status"] = "ok"
        result["_timestamp"]  = _now_utc_iso()

        _save_cache(KIM_CACHE, result)
        return result

    except Exception as exc:
        logger.warning("[КИМ API] Ошибка: %s", exc)

        cached = _load_cache(KIM_CACHE)
        if cached:
            cached["_api_status"] = "cached"
            logger.info("[КИМ API] Используем кеш")
            return cached

        logger.error("[КИМ API] Кеш недоступен — возвращаем unavailable")
        return {
            "kashira":    None,
            "kaluga":     None,
            "ryazan":     None,
            "kolomna":    None,
            "_api_status": "unavailable",
            "_timestamp":  _now_utc_iso(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 3: ЦУГМС — суточные приросты, ледовая обстановка, прогноз
# ══════════════════════════════════════════════════════════════════════════════

def _build_cugms_urls(target_date: date_cls) -> list[tuple]:
    """
    Строит список URL для обзоров ЦУГМС для заданной даты.

    Возвращает список кортежей (review_number, date_str, url_series_a, url_series_b).

    Серия A: Москва и Московская область
    Серия B: Вся территория ЦУГМС

    Нумерация обзоров: номер 1 = 10 марта 2026, каждый следующий день +1.
    """
    START_DATE = date_cls(2026, 3, 10)
    MONTHS_RU = {
        3: "marta",
        4: "aprelya",
        5: "maya",
        6: "iyunya",
        7: "iyulya",
        8: "avgusta",
        9: "sentyabrya",
        10: "oktyabrya",
    }
    BASE = "https://cugms.ru"
    ENCODED_N = "%e2%84%96"  # URL-encoded символ №

    urls = []
    for delta in [0, -1, -2]:
        d = target_date + timedelta(days=delta)
        n = max(1, (d - START_DATE).days + 1)
        month_str = MONTHS_RU.get(d.month, f"mesyac{d.month}")
        dd_str = str(d.day)
        date_str = d.strftime("%d.%m.%Y")

        url_a = (
            f"{BASE}/obzor-{ENCODED_N}{n}-razvitiya-vesennego-polovodya"
            f"-na-rekah-i-vodoemah-moskvy-i-moskovskoj-oblasti"
            f"-{dd_str}-{month_str}-2026-goda/"
        )
        url_b = (
            f"{BASE}/obzor-{ENCODED_N}{n}-razvitiya-vesennego-polovodya"
            f"-na-rekah-i-vodoemah-na-territorii-deyatelnosti-fgbu-czentralnoe-ugms"
            f"-{dd_str}-{month_str}-2026-goda/"
        )
        urls.append((n, date_str, url_a, url_b))

    return urls


def _extract_change_cm(city_pattern: str, text: str) -> float | None:
    """
    Извлекает суточный прирост уровня воды (в см) для заданного города из текста обзора ЦУГМС.

    Ищет паттерны вида:
    - «Серпухов ... +38 см» (город → число)
    - «+38 см за сутки ... Серпухов» (число → город)
    """
    # Прямой порядок: город, потом число
    pattern_fwd = (
        city_pattern
        + r".{0,250}?"
        + r"([+\-]?\d+)\s*(?:см\s*(?:за\s*сутки|/сут|\bв\s*сутки)|см\b)"
    )
    m = re.search(pattern_fwd, text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            val = m.group(1).lstrip("+")
            return float(val)
        except ValueError:
            pass

    # Обратный порядок: число, потом город
    pattern_rev = (
        r"([+\-]?\d+)\s*(?:см\s*(?:за\s*сутки|/сут|\bв\s*сутки))"
        + r".{0,250}?"
        + city_pattern
    )
    m2 = re.search(pattern_rev, text, re.IGNORECASE | re.DOTALL)
    if m2:
        try:
            val = m2.group(1).lstrip("+")
            return float(val)
        except ValueError:
            pass

    return None


def _parse_cugms_text(text: str, review_number: int, date_str: str, url: str) -> dict | None:
    """
    Извлекает структурированные данные из текста обзора ЦУГМС.

    Извлекаемые данные:
    1. Суточные приросты уровней для Серпухова, Каширы, Коломны (regex по городу)
    2. Прирост на участке Костомарово–Белёв
    3. Ледовая обстановка по станциям (ледоход, забереги, затор, шуга)
    4. Прогноз интенсивности (м/сут)
    5. Прогнозный текст
    6. Ожидаются ли опасные явления

    Возвращает None если в тексте не найдено ни одного числового значения
    (признак того, что страница не является обзором паводка).
    """
    serpuhov_cm = _extract_change_cm(r"Серпухов", text)
    kashira_cm  = _extract_change_cm(r"Кашир[аы]", text)
    kolomna_cm  = _extract_change_cm(r"Коломн[аы]", text)
    kaluga_cm   = _extract_change_cm(r"Калуг[аи]", text)

    # Прирост на участке Костомарово–Белёв
    belev_cm: float | None = None
    m_belev_m = re.search(
        r"Костомарово.{0,60}Бел[её].{0,250}?(\d+)[,.](\d+)\s*м",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m_belev_m:
        belev_cm = float(m_belev_m.group(1) + "." + m_belev_m.group(2)) * 100
    else:
        m_belev = re.search(
            r"Костомарово.{0,60}Бел[её].{0,250}?(\d+)\s*(?:см|м\b)",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m_belev:
            unit_match = re.search(
                r"Костомарово.{0,60}Бел[её].{0,250}?" + re.escape(m_belev.group(1)) + r"\s*(см|м\b)",
                text, re.IGNORECASE | re.DOTALL,
            )
            unit = unit_match.group(1).lower() if unit_match else "см"
            val = float(m_belev.group(1))
            belev_cm = val * 100 if unit == "м" else val

    # Ледовая обстановка
    ice_status: dict = {}
    ice_keywords = {
        "ледоход":  ["ледоход"],
        "забереги": ["забереги", "заберег"],
        "затор":    ["затор", "зажор"],
        "шуга":     ["шуга", "шугоход"],
        "вскрытие": ["вскрытие", "вскрылась", "вскрылся"],
    }
    STATIONS = ["Серпухов", "Кашира", "Коломна", "Калуга", "Рязань", "Белёв", "Орёл", "Алексин"]
    for station in STATIONS:
        city_match = re.search(
            rf"{station}.{{0,400}}", text, re.IGNORECASE | re.DOTALL
        )
        if city_match:
            snippet = city_match.group(0)
            for kw, variants in ice_keywords.items():
                if any(v.lower() in snippet.lower() for v in variants):
                    ice_status[station] = kw
                    break

    # Прогноз интенсивности (м/сут)
    forecast_intensity: str | None = None
    m_intensity = re.search(
        r"(\d+[,.]?\d*)\s*[–\-]\s*(\d+[,.]?\d*)\s*м/сут",
        text,
    )
    if m_intensity:
        lo = m_intensity.group(1).replace(",", ".")
        hi = m_intensity.group(2).replace(",", ".")
        forecast_intensity = f"{lo}–{hi} м/сут"

    # Прогнозный текст — ИСПРАВЛЕНИЕ v3.0
    # Ищем абзац ПОСЛЕ слова "прогноз" (не навигационную ссылку)
    # Паттерн: "прогноз на" + текст (минимум 30 символов)
    forecast_text = "Прогноз не найден в тексте обзора"
    m_prog = re.search(
        r"прогноз\s+на\s+.{5,50}?(?:\.|:)\s*(.{30,500})",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m_prog:
        forecast_text = m_prog.group(1)[:400].strip()
    else:
        # Запасной вариант: ищем "в ближайшие N дн"
        m_prog2 = re.search(
            r"(?:в\s+ближайшие\s+[23]\s+дн\w*).{10,500}",
            text, re.IGNORECASE | re.DOTALL,
        )
        if m_prog2:
            forecast_text = m_prog2.group(0)[:400].strip()
        else:
            # Последний fallback: строка с "подъём" или "спад" после "прогноз"
            m_prog3 = re.search(
                r"прогноз\w*\s*[:.].{0,200}(подъём|спад|стабили).{0,200}",
                text, re.IGNORECASE | re.DOTALL,
            )
            if m_prog3:
                forecast_text = m_prog3.group(0)[:400].strip()

    # Опасные явления
    dangerous_signs     = bool(re.search(r"превышени[ея].{0,50}опасн", text, re.IGNORECASE))
    not_dangerous_signs = bool(re.search(
        r"опасн\S*\s+(?:отметки?\s+)?не\s+ожидаю?тся", text, re.IGNORECASE,
    ))
    dangerous_expected = dangerous_signs and not not_dangerous_signs

    # Если не нашли ни одного числового значения — страница не является обзором
    if all(v is None for v in [serpuhov_cm, kashira_cm, kolomna_cm, kaluga_cm, belev_cm]):
        logger.debug("[ЦУГМС] Числовые данные не найдены в тексте по URL: %s", url)
        return None

    return {
        "review_number":          review_number,
        "review_date":            date_str,
        "serpuhov_change_cm":     serpuhov_cm,
        "kashira_change_cm":      kashira_cm,
        "kolomna_change_cm":      kolomna_cm,
        "kaluga_change_cm":       kaluga_cm,
        "belev_change_cm":        belev_cm,
        "ice_status":             ice_status,
        "forecast_text":          forecast_text,
        "forecast_intensity_mps": forecast_intensity,
        "dangerous_expected":     dangerous_expected,
        "source_url":             url,
        "source":                 "cugms.ru",
        "source_status":          "ok",
        "_timestamp":             _now_utc_iso(),
    }


def fetch_cugms_review() -> dict:
    """
    УРОВЕНЬ 3 (SUPPLEMENTARY): парсит последний ежедневный обзор паводка ЦУГМС.

    v3.0: ИСПРАВЛЕН парсер — извлекаем только контент статьи, не всю страницу.

    Адаптивно определяет текущий номер обзора по дате (1 = 10 марта 2026).
    Пробует сегодня, вчера, позавчера — для каждого: Серия A (МО), затем Серия B (весь ЦУГМС).

    Извлекает:
    - Суточные приросты уровней для Серпухова, Каширы, Коломны, Калуги (регексы)
    - Ледовую обстановку по станциям
    - Прогноз текст и интенсивность
    - Флаг ожидания опасных явлений

    При ошибке — возвращает кеш (source_status: "cached") или пустую структуру ("unavailable").

    Возвращает:
        {
          "review_number": int,
          "review_date": str,                  # "ДД.ММ.ГГГГ"
          "serpuhov_change_cm": float|None,    # суточный прирост Серпухов, см
          "kashira_change_cm": float|None,     # суточный прирост Кашира, см
          "kolomna_change_cm": float|None,     # суточный прирост Коломна, см
          "kaluga_change_cm": float|None,      # суточный прирост Калуга, см
          "belev_change_cm": float|None,       # суточный прирост участок Белёв, см
          "ice_status": dict,                  # {станция: тип_льда}
          "forecast_text": str,
          "forecast_intensity_mps": str|None,  # "0.2–0.7 м/сут"
          "dangerous_expected": bool,
          "source_url": str,
          "source": "cugms.ru",
          "source_status": "ok"|"cached"|"unavailable",
          "_timestamp": str,
        }
    """
    today = date_cls.today()
    urls_to_try = _build_cugms_urls(today)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    for n, date_str, url_a, url_b in urls_to_try:
        for url in [url_a, url_b]:
            try:
                logger.info("[ЦУГМС] Попытка: %s", url)
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code != 200:
                    logger.debug("[ЦУГМС] HTTP %d: %s", resp.status_code, url)
                    continue

                resp.encoding = resp.apparent_encoding or "utf-8"
                soup = BeautifulSoup(resp.text, "html.parser")

                # ── КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ v3.0 ──────────────────────────────
                # Извлекаем только тело статьи, отбрасывая меню и навигацию.
                # Баг v2.0: soup.get_text() включал навигационные ссылки cugms.ru,
                # из-за чего _parse_cugms_text() находил "прогноз" в nav-меню.
                article_el = (
                    soup.find("article")
                    or soup.find("main")
                    or soup.find("div", class_=re.compile(
                        r"entry.content|post.content|article.content", re.I
                    ))
                    or soup.find("div", class_=re.compile(r"content", re.I))
                )

                if article_el:
                    body_text = article_el.get_text(separator=" ", strip=True)
                else:
                    # Fallback: удаляем известные навигационные блоки
                    for nav_el in soup.find_all(["nav", "header", "footer"]):
                        nav_el.decompose()
                    body_text = soup.get_text(separator=" ", strip=True)
                # ──────────────────────────────────────────────────────────────

                result = _parse_cugms_text(body_text, n, date_str, url)
                if result:
                    logger.info(
                        "[ЦУГМС] OK — Обзор №%d от %s, Серпухов Δ: %s см",
                        n, date_str, result.get("serpuhov_change_cm"),
                    )
                    _save_cache(CUGMS_CACHE, result)
                    return result

            except Exception as exc:
                logger.debug("[ЦУГМС] Ошибка для %s: %s", url, exc)
                continue

    # Все попытки провалились — используем кеш
    logger.warning("[ЦУГМС] Все URL недоступны, пробуем кеш")
    cached = _load_cache(CUGMS_CACHE)
    if cached:
        cached["source_status"] = "cached"
        logger.info("[ЦУГМС] Используем кеш (обзор №%s)", cached.get("review_number"))
        return cached

    logger.error("[ЦУГМС] Кеш недоступен — возвращаем unavailable")
    return {
        "review_number":          None,
        "review_date":            None,
        "serpuhov_change_cm":     None,
        "kashira_change_cm":      None,
        "kolomna_change_cm":      None,
        "kaluga_change_cm":       None,
        "belev_change_cm":        None,
        "ice_status":             {},
        "forecast_text":          "Нет данных",
        "forecast_intensity_mps": None,
        "dangerous_expected":     False,
        "source_url":             "",
        "source":                 "cugms.ru",
        "source_status":          "unavailable",
        "_timestamp":             _now_utc_iso(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 4: Open-Meteo — погода и снег
# ══════════════════════════════════════════════════════════════════════════════

def get_weather_description(weather_code: int) -> str:
    """
    Возвращает человекочитаемое описание погоды по WMO weather code.

    WMO Weather interpretation codes (WW):
    https://open-meteo.com/en/docs#weathervariables
    """
    if weather_code is None:
        return "Нет данных"

    wmo_descriptions = {
        0:  "Ясно",
        1:  "Преимущественно ясно",
        2:  "Переменная облачность",
        3:  "Пасмурно",
        45: "Туман",
        48: "Инейный туман",
        51: "Лёгкая морось",
        53: "Умеренная морось",
        55: "Сильная морось",
        56: "Лёгкая ледяная морось",
        57: "Сильная ледяная морось",
        61: "Слабый дождь",
        63: "Умеренный дождь",
        65: "Сильный дождь",
        66: "Слабый ледяной дождь",
        67: "Сильный ледяной дождь",
        71: "Слабый снегопад",
        73: "Умеренный снегопад",
        75: "Сильный снегопад",
        77: "Ледяная крупа",
        80: "Слабые ливни",
        81: "Умеренные ливни",
        82: "Сильные ливни",
        85: "Слабые снежные ливни",
        86: "Сильные снежные ливни",
        95: "Гроза",
        96: "Гроза с небольшим градом",
        99: "Гроза с крупным градом",
    }
    return wmo_descriptions.get(weather_code, f"Код {weather_code}")


def _weather_code_emoji(weather_code: int) -> str:
    """
    Возвращает emoji для погодного кода WMO.
    """
    if weather_code is None:
        return "❓"
    if weather_code == 0:
        return "☀️"
    if weather_code in (1, 2):
        return "🌤️"
    if weather_code == 3:
        return "☁️"
    if weather_code in (45, 48):
        return "🌫️"
    if weather_code in (51, 53, 55, 56, 57):
        return "🌧️"
    if weather_code in (61, 63, 65, 66, 67):
        return "🌧️"
    if weather_code in (71, 73, 75, 77):
        return "❄️"
    if weather_code in (80, 81, 82):
        return "🌦️"
    if weather_code in (85, 86):
        return "🌨️"
    if weather_code in (95, 96, 99):
        return "⛈️"
    return "🌡️"


def analyze_temperature_trend(weather_data: dict) -> list[str]:
    """
    Анализирует температурный тренд по данным Open-Meteo.

    Сравнивает максимальные температуры прошлых и будущих дней.
    Определяет направление тренда (потепление / похолодание / стабильность).

    Аргументы:
        weather_data: результат fetch_weather_extended()

    Возвращает:
        Список строк с описанием тренда (0–2 строки).
    """
    if not weather_data:
        return []

    days = weather_data.get("days", [])
    if len(days) < 5:
        return []

    past_days     = [d for d in days if not d.get("is_forecast")]
    forecast_days = [d for d in days if d.get("is_forecast")]

    if not past_days or not forecast_days:
        return []

    # Средние температуры прошлых и будущих дней
    avg_past_tmax  = sum(d.get("tmax", 0) or 0 for d in past_days) / len(past_days)
    avg_fcast_tmax = sum(d.get("tmax", 0) or 0 for d in forecast_days) / len(forecast_days)
    delta = avg_fcast_tmax - avg_past_tmax

    results = []

    if delta >= 5:
        results.append(
            f"📈 Потепление: прогноз Tmax выше прошлых дней на +{delta:.0f}°C "
            f"(ср. {avg_past_tmax:.0f}°C → {avg_fcast_tmax:.0f}°C) — ускорение таяния."
        )
    elif delta >= 2:
        results.append(
            f"📈 Умеренное потепление: прогноз Tmax +{delta:.0f}°C к прошлым дням."
        )
    elif delta <= -5:
        results.append(
            f"📉 Похолодание: прогноз Tmax ниже на {abs(delta):.0f}°C "
            f"({avg_past_tmax:.0f}°C → {avg_fcast_tmax:.0f}°C) — замедление таяния."
        )
    elif delta <= -2:
        results.append(
            f"📉 Умеренное похолодание: прогноз Tmax на {abs(delta):.0f}°C ниже прошлых дней."
        )
    else:
        results.append(
            f"🌡 Стабильная температура: Tmax ≈ {avg_fcast_tmax:.0f}°C в прогнозе."
        )

    # Анализ ночного тренда
    if forecast_days:
        tmins   = [d.get("tmin", 0) or 0 for d in forecast_days]
        avg_tmin = sum(tmins) / len(tmins)
        if avg_tmin > 0:
            results.append(
                f"🌡 Ночные температуры в прогнозе устойчиво выше нуля (ср. +{avg_tmin:.0f}°C) — "
                f"круглосуточное таяние."
            )
        elif avg_tmin < -3:
            results.append(
                f"❄️ Ночные морозы в прогнозе (ср. {avg_tmin:.0f}°C) — замедляют таяние."
            )

    return results[:2]


def analyze_snow_status(weather_data: dict) -> list[str]:
    """
    Анализирует снежную обстановку: запас снега и динамику таяния.

    Рассчитывает:
    - Текущую глубину снежного покрова
    - Изменение за последние 4 дня
    - Оценку вклада снеготаяния в паводок

    Аргументы:
        weather_data: результат fetch_weather_extended()

    Возвращает:
        Список строк с оценкой снежной обстановки (1–2 строки).
    """
    if not weather_data:
        return ["❓ Данные о снежном покрове недоступны."]

    days = weather_data.get("days", [])
    snow_depth_cm = weather_data.get("snow_depth_cm", 0) or 0

    past_days = [d for d in days if not d.get("is_forecast")]
    depths = [d.get("snow_depth_cm") for d in past_days if d.get("snow_depth_cm") is not None]

    if not depths:
        return ["❓ Данные о снежном покрове недоступны."]

    current_depth = depths[-1]
    delta_4d = current_depth - depths[0] if len(depths) > 1 else 0

    results = []

    if current_depth < 1:
        results.append("✅ Снежный покров отсутствует — талые воды уже не добавятся.")
    elif current_depth < 5:
        results.append(
            f"🔵 Снежный покров минимальный ({current_depth:.0f} см) — "
            f"растает за 1–2 дня при положительных температурах."
        )
    elif current_depth < 15:
        sign = "+" if delta_4d >= 0 else ""
        results.append(
            f"❄️ Снежный покров: {current_depth:.0f} см (Δ за 4 дня: {sign}{delta_4d:.0f} см) — "
            f"умеренный вклад в паводок."
        )
    else:
        sign = "+" if delta_4d >= 0 else ""
        results.append(
            f"⚠️ Значительный снежный покров: {current_depth:.0f} см "
            f"(Δ за 4 дня: {sign}{delta_4d:.0f} см) — "
            f"серьёзный вклад в паводок при потеплении. РИСК ПАВОДКА."
        )

    # Анализ ожидаемого снегопада
    forecast_days = [d for d in days if d.get("is_forecast")]
    snowfall_total = sum(d.get("snowfall_cm", 0) or 0 for d in forecast_days)
    if snowfall_total >= 5:
        results.append(
            f"❄️ Прогноз: новый снегопад {snowfall_total:.0f} см за 3 дня — "
            f"увеличение снежного запаса."
        )

    return results[:2]


def analyze_precipitation(weather_data: dict) -> list[str]:
    """
    Анализирует осадки: прошедшие и ожидаемые.

    Оценивает насыщение почвы (прошедшие осадки) и приток в реку (прогнозные).
    Особое внимание к Rain-on-Snow (дождь на снег при плюсе).

    Аргументы:
        weather_data: результат fetch_weather_extended()

    Возвращает:
        Список строк с оценкой осадков (0–2 строки).
    """
    if not weather_data:
        return []

    days = weather_data.get("days", [])
    snow_depth_cm = weather_data.get("snow_depth_cm", 0) or 0

    past_days     = [d for d in days if not d.get("is_forecast")]
    forecast_days = [d for d in days if d.get("is_forecast")]

    past_rain  = sum(d.get("rain_sum", 0) or 0 for d in past_days)
    fcast_rain = sum(d.get("rain_sum", 0) or 0 for d in forecast_days)

    results = []

    # Дождь на снег (Rain-on-Snow) — критический фактор
    for i, day in enumerate(forecast_days, 1):
        rain = day.get("rain_sum", 0) or 0
        tmax = day.get("tmax", 0) or 0
        if rain >= 5 and tmax > 0 and snow_depth_cm >= 3:
            results.append(
                f"⚠️ ОПАСНО: через {i} дн. дождь ({rain:.0f} мм) при +{tmax:.0f}°C "
                f"на снег ({snow_depth_cm:.0f} см) — Rain-on-Snow, максимальный риск паводка!"
            )
            break
        elif rain >= 2 and tmax > 0 and snow_depth_cm >= 1:
            results.append(
                f"🟡 Через {i} дн. дождь ({rain:.0f} мм) при плюсовой температуре "
                f"— дополнительная нагрузка на реку."
            )
            break

    # Прогнозные осадки
    if not results:
        if fcast_rain >= 20:
            results.append(
                f"🌧 СИЛЬНЫЕ осадки в прогнозе: {fcast_rain:.0f} мм за 3 дня — "
                f"высокий приток в реку."
            )
        elif fcast_rain >= 8:
            results.append(
                f"🌧 Ожидается {fcast_rain:.0f} мм осадков за 3 дня — умеренно."
            )

    # Прошедшие осадки → насыщение почвы
    if past_rain >= 15:
        results.append(
            f"🌧 За последние 4 дня выпало {past_rain:.0f} мм — "
            f"почва насыщена, поверхностный сток повышен."
        )

    return results[:2]


def analyze_wind(weather_data: dict) -> list[str]:
    """
    Анализирует ветровую обстановку: усиление ветра может влиять на нагон воды.

    Аргументы:
        weather_data: результат fetch_weather_extended()

    Возвращает:
        Список из 0–1 строк с анализом ветра.
    """
    if not weather_data:
        return []

    days = weather_data.get("days", [])
    forecast_days = [d for d in days if d.get("is_forecast")]
    if not forecast_days:
        return []

    max_wind = max((d.get("wind_ms") or 0 for d in forecast_days), default=0)
    if max_wind >= 15:
        return [f"💨 Сильный ветер в прогнозе: до {max_wind:.0f} м/с — возможен нагон воды."]
    if max_wind >= 10:
        return [f"💨 Умеренный ветер в прогнозе: до {max_wind:.0f} м/с."]
    return []


def analyze_ros(days: list, snow_depth_cm: float) -> list[str]:
    """
    Rain-on-Snow: дождь на снег при положительной температуре — максимальный фактор паводка.

    Аргументы:
        days: список дней из weather_data["days"]
        snow_depth_cm: текущая глубина снега в см

    Возвращает:
        Список из 0–1 строк предупреждения.
    """
    for i, day in enumerate(days[4:], 1):
        rain = day.get("rain_sum", 0) or 0
        tmax = day.get("tmax", 0) or 0
        if rain >= 5 and tmax > 0 and snow_depth_cm >= 3:
            return [
                f"⚠️ ОПАСНО: через {i} дн. дождь ({rain:.0f} мм) при +{tmax:.0f}°C "
                f"на снег ({snow_depth_cm:.0f} см) — Rain-on-Snow, максимальный риск!"
            ]
        elif rain >= 2 and tmax > 0 and snow_depth_cm >= 1:
            return [
                f"🟡 Через {i} дн. умеренный дождь ({rain:.0f} мм) при плюсе "
                f"— дополнительная нагрузка на реку."
            ]
    return []


def analyze_snow_depth(days: list) -> list[str]:
    """
    Анализ снежного покрова и его динамики за 4 дня наблюдений.

    Аргументы:
        days: список дней из weather_data["days"]

    Возвращает:
        Список из 1 строки с оценкой снежного покрова.
    """
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


def analyze_frost_nights(days: list) -> list[str]:
    """
    Анализ ночных заморозков за прошлые 4 и будущие 4 дня.

    Аргументы:
        days: список дней из weather_data["days"]

    Возвращает:
        Список из 1 строки с анализом заморозков.
    """
    fp = sum(1 for d in days[:4] if (d.get("tmin") or 0) < 0)
    ff = sum(1 for d in days[4:] if (d.get("tmin") or 0) < 0)

    if ff >= 2:
        return [f"❄️ Прогноз: {ff} ночи с морозом — сдерживает таяние, рост уровня притормозит."]
    if ff == 1:
        return ["❄️ Одна морозная ночь в прогнозе — неустойчивая ситуация, кратковременное замедление."]
    if fp >= 2:
        return [f"🌡 Последние {fp} ночи с морозом, прогноз — потепление: таяние ускорится."]
    return ["🌡 Все ночи тёплые — снег тает круглосуточно, таяние ускоряется."]


def analyze_tmin_trend(days: list) -> list[str]:
    """
    Тренд минимальных ночных температур в прогнозные дни.

    Аргументы:
        days: список дней из weather_data["days"]

    Возвращает:
        Список из 0–1 строк с описанием тренда.
    """
    tmins = [d["tmin"] for d in days[4:] if d.get("tmin") is not None]
    if len(tmins) < 2:
        return []

    tr  = tmins[-1] - tmins[0]
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


def analyze_warm_days(days: list) -> list[str]:
    """
    Серии дней с Tmax > +10°C — признак затяжной оттепели, ускорения таяния.

    Аргументы:
        days: список дней из weather_data["days"]

    Возвращает:
        Список из 0–1 строк с оценкой серии тёплых дней.
    """
    # Подряд горячих дней в прошлом (с конца)
    sp = 0
    for d in reversed(days[:4]):
        if (d.get("tmax") or 0) > 10:
            sp += 1
        else:
            break

    # Подряд горячих дней в будущем
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


def analyze_precipitation_raw(days: list) -> list[str]:
    """
    Анализ осадков за прошлые и будущие 4 дня (низкоуровневая версия без weather_data).

    Аргументы:
        days: список дней из weather_data["days"]

    Возвращает:
        Список строк с оценкой осадков.
    """
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


def compute_weather_flood_index(days: list, snow_depth_cm: float) -> tuple:
    """
    Вычисляет паводковый индекс погоды (0–4) по совокупности факторов.

    Факторы и веса:
    - Тёплые ночи (Tmin > 0) в прогнозе: +2 за каждую
    - Жаркие дни (Tmax > 10) в прогнозе: +1 за каждый
    - Дождь в прогнозе: min(мм/5, 4)
    - Снег ≥ 20 см: +2; ≥ 5 см: +1
    - Rain-on-Snow (дождь ≥ 5 мм при плюсе на снег ≥ 3 см): +3

    Возвращает:
        (level: int, label: str, color: str, summary: str)
    """
    score = 0.0

    # Тёплые ночи в прогнозе
    warm_nights_future = sum(1 for d in days[4:] if (d.get("tmin", -5) or -5) > 0)
    score += warm_nights_future * 2

    # Жаркие дни в прогнозе
    hot_days_future = sum(1 for d in days[4:] if (d.get("tmax", 0) or 0) > 10)
    score += hot_days_future * 1

    # Дождь в прогнозе
    rain_future = sum(d.get("rain_sum", 0) or 0 for d in days[4:])
    score += min(rain_future / 5, 4)

    # Снежный покров
    if snow_depth_cm >= 20:
        score += 2
    elif snow_depth_cm >= 5:
        score += 1

    # Rain-on-Snow
    ros = any(
        (d.get("rain_sum", 0) or 0) >= 5
        and (d.get("tmax", 0) or 0) > 0
        and snow_depth_cm >= 3
        for d in days[4:]
    )
    if ros:
        score += 3

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


def generate_weather_commentary(days: list, snow_depth_cm: float) -> list[str]:
    """
    Собирает результаты всех 6 анализаторов, возвращает ≤4 наиболее важных строки.

    Порядок приоритета: ROS → снег → заморозки → Tmin тренд → тёплые дни → осадки.

    Аргументы:
        days: список дней из weather_data["days"]
        snow_depth_cm: текущая глубина снега в см

    Возвращает:
        Список из ≤4 строк с погодным комментарием.
    """
    commentary = []
    commentary += analyze_ros(days, snow_depth_cm)
    commentary += analyze_snow_depth(days)
    commentary += analyze_frost_nights(days)
    commentary += analyze_tmin_trend(days)
    commentary += analyze_warm_days(days)
    commentary += analyze_precipitation_raw(days)
    return commentary[:4]


def fetch_weather_extended() -> dict | None:
    """
    УРОВЕНЬ 4 (WEATHER): Open-Meteo Forecast API — погода и снег для Серпухова.

    URL: https://api.open-meteo.com/v1/forecast
    Бесплатный API, без ключа. Таймаут: 12 секунд.

    КРИТИЧНО: используется параметр snow_depth_max (НЕ snow_depth!).
    Значения snow_depth_max приходят в МЕТРАХ → умножаем × 100 = сантиметры.

    Параметры запроса передаются как список кортежей (не строкой через запятую)
    для корректной передачи множественных значений daily.

    Возвращает 8 дней: 4 прошлых + сегодня + 3 будущих.

    Возвращает:
        {
          "days": [
            {
              "date": "2026-03-23",
              "is_forecast": bool,
              "tmax": float,
              "tmin": float,
              "precip": float,
              "rain_sum": float,
              "snowfall_cm": float,
              "snow_depth_cm": float,
              "wind_ms": float,
              "weather_code": int,
            }, ...
          ],
          "snow_depth_cm": float,       # последний фактический день
          "flood_index": int,           # 0–4
          "flood_label": str,           # "СТАБИЛЬНЫЙ" / "УМЕРЕННЫЙ" / ...
          "flood_color": str,           # hex-цвет
          "flood_summary": str,
          "commentary": list[str],      # ≤4 строки анализа
        }
        или None при ошибке.
    """
    try:
        logger.info("[Open-Meteo] Запрос прогноза для Серпухова (%.4f, %.4f)", SERP_LAT, SERP_LON)

        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=[
                ("latitude",         str(SERP_LAT)),
                ("longitude",        str(SERP_LON)),
                ("daily",            "temperature_2m_max"),
                ("daily",            "temperature_2m_min"),
                ("daily",            "precipitation_sum"),
                ("daily",            "rain_sum"),
                ("daily",            "snowfall_sum"),
                ("daily",            "snow_depth_max"),     # МЕТРЫ → ×100 = см
                ("daily",            "wind_speed_10m_max"),
                ("daily",            "weather_code"),
                ("past_days",        "4"),
                ("forecast_days",    "4"),
                ("timezone",         "Europe/Moscow"),
                ("wind_speed_unit",  "ms"),
            ],
            timeout=12,
        )
        resp.raise_for_status()
        raw = resp.json()

        daily = raw.get("daily", {})
        dates = daily.get("time", [])
        if not dates:
            raise ValueError("Open-Meteo: пустой ответ (нет 'time')")

        today = datetime.now().date().isoformat()
        days = []

        for i, date_str in enumerate(dates):
            snow_raw = (daily.get("snow_depth_max") or [None] * len(dates))[i]
            days.append({
                "date":          date_str,
                "is_forecast":   date_str > today,
                "tmax":          (daily.get("temperature_2m_max") or [None] * len(dates))[i],
                "tmin":          (daily.get("temperature_2m_min") or [None] * len(dates))[i],
                "precip":        (daily.get("precipitation_sum") or [0] * len(dates))[i] or 0,
                "rain_sum":      (daily.get("rain_sum") or [0] * len(dates))[i] or 0,
                "snowfall_cm":   (daily.get("snowfall_sum") or [0] * len(dates))[i] or 0,
                "snow_depth_cm": round((snow_raw or 0) * 100, 1),  # метры → см
                "wind_ms":       (daily.get("wind_speed_10m_max") or [None] * len(dates))[i],
                "weather_code":  (daily.get("weather_code") or [None] * len(dates))[i],
            })

        # Последний фактический день → snow_depth_cm
        past_days_list = [d for d in days if not d["is_forecast"]]
        snow_depth_cm = past_days_list[-1]["snow_depth_cm"] if past_days_list else 0.0

        flood_level, flood_label, flood_color, flood_summary = \
            compute_weather_flood_index(days, snow_depth_cm)

        commentary = generate_weather_commentary(days, snow_depth_cm)

        logger.info(
            "[Open-Meteo] OK — %d дней, снег=%.0f см, индекс=%d (%s)",
            len(days), snow_depth_cm, flood_level, flood_label,
        )

        return {
            "days":          days,
            "snow_depth_cm": snow_depth_cm,
            "flood_index":   flood_level,
            "flood_label":   flood_label,
            "flood_color":   flood_color,
            "flood_summary": flood_summary,
            "commentary":    commentary,
            "source_status": "ok",
        }

    except Exception as exc:
        logger.error("[Open-Meteo] Ошибка: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# УРОВЕНЬ 5: GloFAS Flood API — NEW v3.0
# 7 станций выше Серпухова: Орёл, Мценск, Белёв, Калуга, Алексин, Таруса, Козельск
# ══════════════════════════════════════════════════════════════════════════════

def fetch_glofas_station(lat: float, lon: float, past_days: int = 7,
                          forecast_days: int = 16) -> dict | None:
    """
    УРОВЕНЬ 5 (GLOFAS): получает данные расхода воды GloFAS для одной точки.

    Endpoint: https://flood-api.open-meteo.com/v1/flood
    Без API-ключа. Бесплатно. Время ответа ~300 мс.

    Args:
        lat: широта (например, 53.775 для Белёва)
        lon: долгота (например, 36.125 для Белёва)
        past_days: дней истории (default: 7)
        forecast_days: дней прогноза (default: 16)

    Returns:
        {
          "time": ["2026-03-22", ..., "2026-04-13"],   # ISO даты (24 элемента)
          "discharge": [204.1, 185.3, ...],             # river_discharge м³/с
          "discharge_mean": [190.0, ...],               # river_discharge_mean м³/с
          "discharge_max": [220.0, ...],                # river_discharge_max м³/с
          "lat": float, "lon": float,
          "status": "ok"
        }
        или None при ошибке.
    """
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = [
        ("latitude",      str(lat)),
        ("longitude",     str(lon)),
        ("daily",         "river_discharge"),
        ("daily",         "river_discharge_mean"),
        ("daily",         "river_discharge_max"),
        ("forecast_days", str(forecast_days)),
        ("past_days",     str(past_days)),
    ]

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        times          = daily.get("time", [])
        discharge      = daily.get("river_discharge", [])
        discharge_mean = daily.get("river_discharge_mean", [])
        discharge_max  = daily.get("river_discharge_max", [])

        if not times or not discharge:
            logger.warning("[GloFAS] Пустой ответ для lat=%s lon=%s", lat, lon)
            return None

        return {
            "time":           times,
            "discharge":      [round(v, 1) if v is not None else None for v in discharge],
            "discharge_mean": [round(v, 1) if v is not None else None for v in discharge_mean],
            "discharge_max":  [round(v, 1) if v is not None else None for v in discharge_max],
            "lat":    lat,
            "lon":    lon,
            "status": "ok",
        }

    except Exception as exc:
        logger.warning("[GloFAS] Ошибка для lat=%s lon=%s: %s", lat, lon, exc)
        return None


def _compute_glofas_analytics(raw: dict, wave_to_serpuhov: tuple) -> dict:
    """
    Вычисляет аналитику по данным одной GloFAS-станции.

    Args:
        raw: результат fetch_glofas_station()
        wave_to_serpuhov: (min_days, max_days) время добегания до Серпухова

    Returns:
        {
          "current_discharge": float,   # последний историч. расход
          "peak_discharge": float,      # пик в прогнозном периоде
          "peak_date": str,             # дата пика "YYYY-MM-DD"
          "trend_arrow": str,           # "↑↑" / "↑" / "→" / "↓" / "↓↓"
          "flood_ratio": float,         # current / mean (аномальность)
          "wave_arrival_serpukhov": {"earliest": str, "latest": str}
        }
    """
    times     = raw.get("time", [])
    discharge = raw.get("discharge", [])
    d_mean    = raw.get("discharge_mean", [])

    today_str = date_cls.today().isoformat()

    # Разбиваем на историю и прогноз
    history_vals  = []
    history_times = []
    forecast_vals  = []
    forecast_times = []

    for t, q in zip(times, discharge):
        if q is None:
            continue
        if t <= today_str:
            history_vals.append(q)
            history_times.append(t)
        else:
            forecast_vals.append(q)
            forecast_times.append(t)

    # Текущий расход = последнее историческое значение
    current_discharge = history_vals[-1] if history_vals else None

    # Пик в прогнозе
    peak_discharge = None
    peak_date = None
    if forecast_vals:
        valid_forecast = [(q, t) for q, t in zip(forecast_vals, forecast_times) if q is not None]
        if valid_forecast:
            max_pair = max(valid_forecast, key=lambda x: x[0])
            peak_discharge = max_pair[0]
            peak_date = max_pair[1]
    elif history_vals:
        # Нет прогноза — пик из истории
        valid_history = [(q, t) for q, t in zip(history_vals, history_times) if q is not None]
        if valid_history:
            max_pair = max(valid_history, key=lambda x: x[0])
            peak_discharge = max_pair[0]
            peak_date = max_pair[1]

    # Тренд (за последние 3 исторических дня)
    trend_arrow = "→"
    if len(history_vals) >= 3:
        delta = history_vals[-1] - history_vals[-3]
        pct_change = delta / max(abs(history_vals[-3]), 1) * 100
        if pct_change >= 30:
            trend_arrow = "↑↑"
        elif pct_change >= 10:
            trend_arrow = "↑"
        elif pct_change <= -30:
            trend_arrow = "↓↓"
        elif pct_change <= -10:
            trend_arrow = "↓"
        else:
            trend_arrow = "→"

    # Flood ratio = current / median (среднее всего массива mean)
    flood_ratio = None
    if current_discharge and d_mean:
        valid_mean = [v for v in d_mean if v is not None and v > 0]
        if valid_mean:
            median_q = sum(valid_mean) / len(valid_mean)
            flood_ratio = round(current_discharge / median_q, 2)

    # Arrival в Серпухов
    wave_arrival = None
    if peak_date:
        try:
            peak_dt = date_cls.fromisoformat(peak_date)
            earliest = peak_dt + timedelta(days=int(wave_to_serpuhov[0]))
            latest   = peak_dt + timedelta(days=int(wave_to_serpuhov[1]) + 1)
            wave_arrival = {
                "earliest": earliest.isoformat(),
                "latest":   latest.isoformat(),
            }
        except Exception:
            pass

    return {
        "current_discharge":      current_discharge,
        "peak_discharge":         peak_discharge,
        "peak_date":              peak_date,
        "trend_arrow":            trend_arrow,
        "flood_ratio":            flood_ratio,
        "wave_arrival_serpukhov": wave_arrival,
    }


def fetch_all_glofas_upstream() -> dict:
    """
    УРОВЕНЬ 5 (GLOFAS): опрашивает все 7 станций параллельно.
    Возвращает полный словарь с данными по каждой станции + сводку.

    Returns:
        {
          "orel": {
            "name": "Орёл", "river": "р. Ока",
            "lat": 52.925, "lon": 36.025,
            "time": [...], "discharge": [...], "discharge_mean": [...],
            "discharge_max": [...],
            "current_discharge": 55.0,        # последний исторический день
            "peak_discharge": 95.0,           # максимум в прогнозе
            "peak_date": "2026-04-01",         # дата пика в прогнозе
            "trend_arrow": "↑",               # тренд за 3 дня
            "flood_ratio": 2.3,               # current / mean
            "wave_arrival_serpukhov": {       # расчётный приход волны в Серпухов
                "earliest": "2026-04-06",
                "latest": "2026-04-08",
            },
            "source_status": "ok" | "cached" | "unavailable",
          },
          "mtsensk": {...},
          "belev": {...},
          "kaluga": {...},
          "aleksin": {...},
          "tarusa": {...},
          "kozelsk": {...},
          "_fetch_time": str,  # ISO timestamp
          "_status": "ok" | "partial" | "unavailable",
        }
    """
    today_str = _now_utc_iso()
    results: dict = {"_fetch_time": today_str}
    ok_count = 0

    # Параллельный опрос всех 7 станций
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futures = {
            slug: ex.submit(
                fetch_glofas_station,
                cfg["lat"], cfg["lon"],
            )
            for slug, cfg in GLOFAS_STATIONS.items()
        }

    for slug, cfg in GLOFAS_STATIONS.items():
        try:
            raw = futures[slug].result()
        except Exception as exc:
            logger.warning("[GloFAS] Исключение для станции %s: %s", slug, exc)
            raw = None

        station_data = {
            "name":  cfg["name"],
            "river": cfg["river"],
            "lat":   cfg["lat"],
            "lon":   cfg["lon"],
        }

        if raw is None:
            station_data.update({
                "time":             [],
                "discharge":        [],
                "discharge_mean":   [],
                "discharge_max":    [],
                "current_discharge": None,
                "peak_discharge":   None,
                "peak_date":        None,
                "trend_arrow":      "?",
                "flood_ratio":      None,
                "wave_arrival_serpukhov": None,
                "source_status":    "unavailable",
            })
        else:
            ok_count += 1
            # Вычисляем аналитику
            analyt = _compute_glofas_analytics(raw, cfg["wave_to_serpuhov"])
            station_data.update({
                "time":             raw["time"],
                "discharge":        raw["discharge"],
                "discharge_mean":   raw["discharge_mean"],
                "discharge_max":    raw["discharge_max"],
                "current_discharge": analyt["current_discharge"],
                "peak_discharge":   analyt["peak_discharge"],
                "peak_date":        analyt["peak_date"],
                "trend_arrow":      analyt["trend_arrow"],
                "flood_ratio":      analyt["flood_ratio"],
                "wave_arrival_serpukhov": analyt["wave_arrival_serpukhov"],
                "source_status":    "ok",
            })

        results[slug] = station_data

    if ok_count == 0:
        # Пробуем кеш
        cached = _load_cache(GLOFAS_CACHE)
        if cached:
            cached["_status"] = "cached"
            logger.info("[GloFAS] Все станции недоступны — используем кеш")
            return cached
        results["_status"] = "unavailable"
        logger.warning("[GloFAS] Все станции недоступны, кеш также отсутствует")
    elif ok_count < len(GLOFAS_STATIONS):
        results["_status"] = "partial"
        logger.info("[GloFAS] Частично доступен: %d/%d станций", ok_count, len(GLOFAS_STATIONS))
    else:
        results["_status"] = "ok"
        logger.info("[GloFAS] OK — все %d станций", ok_count)

    _save_cache(GLOFAS_CACHE, results)
    return results


def calculate_wave_arrival(glofas_data: dict) -> dict:
    """
    Вычисляет сводный прогноз прихода волны в Серпухов по всем станциям.

    Args:
        glofas_data: результат fetch_all_glofas_upstream()

    Returns:
        {
          "orel":    {"peak_date": str, "arrival_earliest": str, "arrival_latest": str, "discharge": float},
          "belev":   {...},
          ...
          "serpukhov_arrival": {    # наиболее вероятный приход в Серпухов
            "earliest": str, "latest": str,
            "based_on": str,       # название ключевой станции
          }
        }
    """
    result = {}
    arrivals = []

    for slug, cfg in GLOFAS_STATIONS.items():
        station = glofas_data.get(slug, {})
        if station.get("source_status") != "ok":
            continue

        peak_date = station.get("peak_date")
        wave      = station.get("wave_arrival_serpukhov")

        if peak_date and wave:
            result[slug] = {
                "peak_date":        peak_date,
                "arrival_earliest": wave["earliest"],
                "arrival_latest":   wave["latest"],
                "discharge":        station.get("current_discharge"),
                "peak_discharge":   station.get("peak_discharge"),
                "name":             station.get("name"),
            }
            arrivals.append((slug, wave["earliest"], wave["latest"],
                             station.get("peak_discharge") or 0))

    # Выбираем ключевую станцию
    # Приоритет: Белёв > Таруса > Алексин > Калуга > Мценск > Орёл > Козельск
    PRIORITY = ["belev", "tarusa", "aleksin", "kaluga", "mtsensk", "orel", "kozelsk"]
    best_slug = None
    for s in PRIORITY:
        if s in result:
            best_slug = s
            break

    if best_slug and best_slug in result:
        result["serpukhov_arrival"] = {
            "earliest": result[best_slug]["arrival_earliest"],
            "latest":   result[best_slug]["arrival_latest"],
            "based_on": GLOFAS_STATIONS[best_slug]["name"],
        }
    elif arrivals:
        # Fallback: самый ранний приход
        arrivals.sort(key=lambda x: x[1])
        result["serpukhov_arrival"] = {
            "earliest": arrivals[0][1],
            "latest":   arrivals[-1][2],
            "based_on": "нескольких станций",
        }

    return result


def calculate_flood_ratio(station_data: dict) -> float | None:
    """
    Вычисляет индекс аномальности расхода: Q_current / Q_median.

    Значения:
    < 1.0  — ниже нормы
    1–2    — норма/умеренный
    2–3    — повышенный
    3–5    — высокий (паводок)
    > 5    — экстремальный

    Args:
        station_data: один элемент из glofas_data (с полями discharge, discharge_mean)

    Returns:
        float | None
    """
    return station_data.get("flood_ratio")


def _svg_sparkline(values: list, width: int = 80, height: int = 24,
                   color: str = "#3b82f6") -> str:
    """
    Генерирует inline SVG sparkline из списка значений GloFAS (7-дневная история).

    Args:
        values: список float (7 значений, может содержать None)
        width:  ширина SVG в px
        height: высота SVG в px
        color:  цвет линии

    Returns:
        HTML-строка с <svg>...</svg>, или "" если данных недостаточно
    """
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return ""

    mn = min(valid)
    mx = max(valid)
    rng = mx - mn or 1.0

    pts = []
    n = len(valid)
    for i, v in enumerate(valid):
        x = i / (n - 1) * width
        y = height - (v - mn) / rng * (height - 4) - 2
        pts.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(pts)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# МАСТЕР-ФУНКЦИЯ: fetch_all_data()
# ══════════════════════════════════════════════════════════════════════════════

def fetch_all_data() -> dict:
    """
    Мастер-функция: запускает все 5 источников параллельно, объединяет результаты.

    Порядок: serpuhov.ru → КИМ API → ЦУГМС → Open-Meteo → GloFAS (параллельно).
    При падении любого источника — используется кеш или помечается как "unavailable".
    Сбои одного источника не влияют на остальные.

    v3.0: добавлен 5-й источник GloFAS, 5 workers.

    Возвращает:
        {
          "serpuhov": {level_m, level_cm, daily_change_cm, abs_level_m_bs, ...},
          "kim": {kashira: {...}, kaluga: {...}, ryazan: {...}, _api_status, ...},
          "cugms": {review_number, serpuhov_change_cm, forecast_text, ...},
          "weather": {days: [...], snow_depth_cm, flood_index, ...},
          "glofas": {                           # NEW v3.0
            "orel": {...}, "mtsensk": {...}, "belev": {...},
            "kaluga": {...}, "aleksin": {...}, "tarusa": {...},
            "kozelsk": {...},
            "_fetch_time": str, "_status": "ok"|"partial"|"unavailable",
          },
          "fetch_time": str,           # ISO timestamp UTC
          "sources_ok": list[str],     # источники, ответившие свежими данными или из кеша
          "sources_failed": list[str], # источники, полностью недоступные
        }
    """
    logger.info("=" * 60)
    logger.info("fetch_all_data() — запуск 5 источников параллельно")
    logger.info("=" * 60)

    # Запускаем все 5 источников параллельно (5 workers)
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        f_serp   = executor.submit(fetch_serpuhov_level)
        f_kim    = executor.submit(fetch_kim_stations)
        f_cugms  = executor.submit(fetch_cugms_review)
        f_wext   = executor.submit(fetch_weather_extended)
        f_glofas = executor.submit(fetch_all_glofas_upstream)

    # Получаем результаты (futures уже завершены после выхода из контекстного менеджера)
    serp   = f_serp.result()
    kim    = f_kim.result()
    cugms  = f_cugms.result()
    wext   = f_wext.result()
    glofas = f_glofas.result()

    sources_ok: list[str]     = []
    sources_failed: list[str] = []

    # Классифицируем статусы источников
    for name, src, stat_key in [
        ("serpuhov.ru", serp,   "source_status"),
        ("kim",         kim,    "_api_status"),
        ("cugms",       cugms,  "source_status"),
        ("weather",     wext,   "source_status"),
        ("glofas",      glofas, "_status"),
    ]:
        status = (src or {}).get(stat_key, "unavailable") if src else "unavailable"
        if src and status in ("ok", "partial"):
            sources_ok.append(name)
        elif src and status == "cached":
            sources_ok.append(f"{name}(кеш)")
        else:
            sources_failed.append(name)

    logger.info("Источники OK: %s", sources_ok)
    if sources_failed:
        logger.warning("Источники FAILED: %s", sources_failed)

    return {
        "serpuhov":       serp,
        "kim":            kim,
        "cugms":          cugms,
        "weather":        wext,
        "glofas":         glofas,        # NEW v3.0
        "fetch_time":     _now_utc_iso(),
        "sources_ok":     sources_ok,
        "sources_failed": sources_failed,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ТОЧКА ВХОДА — ТЕСТ
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pprint

    logging.getLogger().setLevel(logging.DEBUG)
    print("\n" + "=" * 60)
    print("fetch_module.py v3.0 — тест всех источников")
    print("=" * 60)

    data = fetch_all_data()

    print("\n[ИТОГО]")
    print(f"  Время запроса: {data['fetch_time']}")
    print(f"  Источники OK:  {data['sources_ok']}")
    print(f"  Источники ❌:  {data['sources_failed']}")

    print("\n[SERPUHOV.RU]")
    s = data.get("serpuhov") or {}
    if s.get("level_m") is not None:
        print(f"  Уровень: {s['level_m']:.2f} м ({s['level_cm']:.0f} см)")
        print(f"  Δ сутки: {s['daily_change_m']:+.2f} м ({s['daily_change_cm']:+.0f} см)")
        print(f"  Абс. уровень: {s['abs_level_m_bs']:.3f} м БС")
        print(f"  НЯ={s['nya_m_bs']} м БС | ОЯ={s['oya_m_bs']} м БС")
        print(f"  Состояние: {s['water_status']}")
        print(f"  Статус: {s['source_status']} (кеш: {s['cache_age_h']} ч)")
    else:
        print(f"  Статус: {s.get('source_status', 'unavailable')}")

    print("\n[КИМ API]")
    k = data.get("kim") or {}
    print(f"  Статус API: {k.get('_api_status')}")
    for station in ["kashira", "kaluga", "ryazan", "kolomna"]:
        st = k.get(station)
        if st and st.get("level_cm") is not None:
            print(f"  {station}: {st['level_cm']} см ({st['date']})")
        else:
            print(f"  {station}: нет данных ({(st or {}).get('status', '?')})")

    print("\n[ЦУГМС]")
    c = data.get("cugms") or {}
    print(f"  Обзор №{c.get('review_number')} от {c.get('review_date')}")
    print(f"  Серпухов Δ: {c.get('serpuhov_change_cm')} см/сут")
    print(f"  Кашира Δ:   {c.get('kashira_change_cm')} см/сут")
    print(f"  Лёд: {c.get('ice_status')}")
    print(f"  Прогноз: {str(c.get('forecast_text', ''))[:120]}...")
    print(f"  Интенсивность: {c.get('forecast_intensity_mps')}")
    print(f"  Опасные явления: {c.get('dangerous_expected')}")
    print(f"  URL: {c.get('source_url')}")

    print("\n[ПОГОДА]")
    w = data.get("weather") or {}
    if w:
        print(f"  Снег: {w.get('snow_depth_cm'):.0f} см")
        print(f"  Индекс паводка: {w.get('flood_index')} — {w.get('flood_label')}")
        print(f"  {w.get('flood_summary')}")
        for line in w.get("commentary", []):
            print(f"  • {line}")
    else:
        print("  Погода недоступна")

    print("\n[GLOFAS — 7 СТАНЦИЙ]")
    g = data.get("glofas") or {}
    print(f"  Статус: {g.get('_status')}")
    for slug, cfg in GLOFAS_STATIONS.items():
        st = g.get(slug, {})
        q    = st.get("current_discharge")
        peak = st.get("peak_discharge")
        pd   = st.get("peak_date")
        tr   = st.get("trend_arrow", "?")
        fr   = st.get("flood_ratio")
        wav  = st.get("wave_arrival_serpukhov")
        status = st.get("source_status", "unavailable")
        if status == "ok" and q is not None:
            wave_str = ""
            if wav:
                wave_str = f", волна→Серп: {wav['earliest'][:10]}…{wav['latest'][:10]}"
            print(
                f"  {cfg['name']:20s}: Q={q:.0f} м³/с {tr}, "
                f"пик={peak:.0f} м³/с ({pd}), ratio={fr}{wave_str}"
            )
        else:
            print(f"  {cfg['name']:20s}: {status}")

    print("\n[ПРОГНОЗ ПРИХОДА ВОЛНЫ В СЕРПУХОВ]")
    wave_arrivals = calculate_wave_arrival(g)
    sa = wave_arrivals.get("serpukhov_arrival")
    if sa:
        print(f"  Ориентир по {sa['based_on']}: {sa['earliest'][:10]} — {sa['latest'][:10]}")
    else:
        print("  Данных для прогноза недостаточно")

    print("\n[SVG SPARKLINE — тест]")
    test_vals = [100.0, 120.0, 150.0, 180.0, 170.0, 160.0, 155.0]
    svg = _svg_sparkline(test_vals, width=80, height=24, color="#3b82f6")
    print(f"  SVG ({len(svg)} chars): {svg[:80]}...")

    print("\n" + "=" * 60)
