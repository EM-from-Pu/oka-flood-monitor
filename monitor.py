#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# okamonitor.py v4.2 — 26.03.2026
# Полная версия: 7 постов, KIM T0-T10, analytics, heartbeat, digest, alert,
# волновой прогноз, сравнение 2024, HTML-отчёт, CSV-история, group_draft
# fetch_module.py — единственное место парсинга fishingsib.ru

import os, re, json, csv, requests
from datetime import datetime, timedelta, timezone
from fetch_module import fetch_level as fish_fetch, STATIONS

# ─── CONFIG ───────────────────────────────────────────────────────────────────
TG_TOKEN  = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN = os.environ.get("TG_CHAT_ID",   "49747475")
CHAT_GROUP = os.environ.get("TG_GROUP_ID",  "-5234360275")
OWM_KEY    = os.environ.get("WEATHER_API_KEY", "")
SERP_LAT, SERP_LON = 54.834050, 37.742901

# KIM-пороги Серпухов
CRITICAL_LEVEL = 945   # Дом под угрозой
PEAK_2024      = 920   # Уровень 2024
PODTOP_LEVEL   = 800   # Критический (дачи затапливает)
POYMA_LEVEL    = 645   # Опасный (пойма)
NORM_LEVEL     = 500   # Выше нормы

KIM_THRESHOLDS = [500, 645, 800, 920, 945, 965]
KIM_EMOJI  = {500:"🟡", 645:"🟠", 800:"🔴", 920:"🆘", 945:"💀", 965:"⚫"}
KIM_LABEL  = {
    500: "L1 выше нормы",
    645: "L2 опасный (пойма)",
    800: "L3 критический (дачи)",
    920: "L4 уровень 2024",
    945: "L5 ДОМ ПОД УГРОЗОЙ",
    965: "L6 подвал залит",
}

# ─── PATHS ────────────────────────────────────────────────────────────────────
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

# ─── HISTORY SCHEMA ───────────────────────────────────────────────────────────
HISTORY_COLS = [
    "datetime",
    "orel","belev","kaluga","shukina","serpukhov","kashira","kolomna",
    "delta_serp_24h","delta_serp_48h","delta_orel_24h","delta_kaluga_24h",
    "temp","humidity","wind_ms","wind_dir","clouds","precip_mm",
    "alert_level","forecast_days_to_945","forecast_days_to_peak",
    "scenario_base_peak","scenario_base_date","notes",
]

SLUG_NAMES = {
    "orel":"Орёл","belev":"Белев","kaluga":"Калуга","shukina":"Щукина/Алексин",
    "serpukhov":"Серпухов","kashira":"Кашира","kolomna":"Коломна",
}
SLUG_LAG = {s["slug"].replace("oka-","").replace("serpuhov","serpukhov"): s["lag_h"] for s in STATIONS}
# fix oka-shukina → shukina
SLUG_LAG["shukina"] = 24

STATION_KEYS = ["orel","belev","kaluga","shukina","serpukhov","kashira","kolomna"]

# ─── FETCH ALL LEVELS ─────────────────────────────────────────────────────────
def fetch_all_levels():
    print(f"[OkaMonitor v4.2] Парсим уровни воды ({len(STATIONS)} постов fishingsib)...")
    levels = {}
    for st in STATIONS:
        slug_key = st["slug"].replace("oka-","").replace("serpuhov","serpukhov")
        url = f"https://allrivers.info/gauge/{st['slug']}"
        val = fish_fetch(url, st["name"])
        levels[slug_key] = val
        # printed by fetch_module
    print(f"  Уровни: {levels}")
    return levels

# ─── FETCH WEATHER (OpenWeatherMap или Open-Meteo fallback) ───────────────────
def fetch_weather():
    print("Парсим погоду (Серпухов)...")
    if OWM_KEY:
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat":SERP_LAT,"lon":SERP_LON,"appid":OWM_KEY,"units":"metric","lang":"ru"},
                timeout=12
            )
            if r.status_code == 200:
                d = r.json()
                return dict(
                    temp     = round(d["main"]["temp"], 1),
                    humidity = d["main"]["humidity"],
                    wind_ms  = round(d["wind"]["speed"], 1),
                    wind_dir = d["wind"].get("deg", 0),
                    clouds   = d["clouds"]["all"],
                    precip_mm= round(d.get("rain",{}).get("1h",0)+d.get("snow",{}).get("1h",0),1),
                    weather  = d["weather"][0]["description"],
                )
        except Exception as e:
            print(f"  OWM err: {e}")
    # Open-Meteo fallback (без ключа)
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": SERP_LAT,"longitude": SERP_LON,
                "current_weather": True,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snow_depth_max,wind_speed_10m_max",
                "hourly": "relative_humidity_2m,precipitation,snowfall",
                "forecast_days": 2,
                "timezone": "Europe/Moscow",
            },
            timeout=12
        )
        if r.status_code == 200:
            d = r.json()
            cw = d.get("current_weather", {})
            daily = d.get("daily", {})
            hourly = d.get("hourly", {})
            return dict(
                temp      = cw.get("temperature"),
                humidity  = (hourly.get("relative_humidity_2m") or [None])[0],
                wind_ms   = cw.get("windspeed"),
                wind_dir  = cw.get("winddirection",0),
                clouds    = None,
                precip_mm = (daily.get("precipitation_sum") or [None])[0],
                snow_depth= (daily.get("snow_depth_max") or [None])[0],
                weather   = "данные Open-Meteo",
                temp_max  = (daily.get("temperature_2m_max") or [None])[0],
                temp_min  = (daily.get("temperature_2m_min") or [None])[0],
                wind_max  = (daily.get("wind_speed_10m_max") or [None])[0],
            )
    except Exception as e:
        print(f"  OpenMeteo err: {e}")
    return {}

# ─── SNOW COVER (OpenWeatherMap multi-region) ─────────────────────────────────
def fetch_snow_cover():
    if not OWM_KEY:
        return {}
    regions = {
        "Орёл":      (52.97, 36.07),
        "Калуга":    (54.51, 36.26),
        "Тула":      (54.19, 37.62),
        "Серпухов":  (SERP_LAT, SERP_LON),
    }
    result = {}
    for rname, (lat, lon) in regions.items():
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat":lat,"lon":lon,"appid":OWM_KEY,"units":"metric"},
                timeout=10
            )
            if r.status_code == 200:
                d = r.json()
                result[rname] = {
                    "snow_mm": d.get("snow",{}).get("1h",0) or d.get("snow",{}).get("3h",0),
                    "rain_mm": d.get("rain",{}).get("1h",0) or d.get("rain",{}).get("3h",0),
                    "temp":    d["main"]["temp"],
                    "desc":    d["weather"][0]["description"],
                }
        except Exception:
            pass
    return result

# ─── HISTORY I/O ──────────────────────────────────────────────────────────────
def load_history():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_history(rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def get_past_level(history, station, hours_ago):
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
                best = int(float(v)) if v and v != "" else None
        except Exception:
            pass
    return best if best_diff < timedelta(hours=6) else None

# ─── ALERTS DEDUP ─────────────────────────────────────────────────────────────
def load_alerts():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(ALERTS_FILE):
        try:
            with open(ALERTS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_alerts(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ALERTS_FILE, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def should_send_alert(alerts, key, cooldown_h=6):
    ts = alerts.get(key)
    if not ts:
        return True
    last = datetime.fromisoformat(ts)
    return (datetime.now() - last).total_seconds() > cooldown_h * 3600

# ─── LOAD 2024 REFERENCE ──────────────────────────────────────────────────────
def load_2024_ref():
    if not os.path.exists(REF_2024):
        return {}
    try:
        with open(REF_2024) as f:
            return json.load(f)
    except Exception:
        return {}

def get_2024_value(ref, day_of_year):
    return ref.get(str(day_of_year)) or ref.get(f"{day_of_year:03d}")

# ─── COMPUTE ANALYTICS ────────────────────────────────────────────────────────
def compute_analytics(levels, history, weather):
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    ka = levels.get("kashira")
    sh = levels.get("shukina")

    s24 = get_past_level(history, "serpukhov", 24)
    s48 = get_past_level(history, "serpukhov", 48)
    o24 = get_past_level(history, "orel",      24)
    k24 = get_past_level(history, "kaluga",    24)

    ds24 = (s - s24) if s is not None and s24 is not None else None
    ds48 = ((s - s48) / 2) if s is not None and s48 is not None else None
    do24 = (o - o24) if o is not None and o24 is not None else None
    dk24 = (k - k24) if k is not None and k24 is not None else None

    # Волновой прогноз: Орёл → Серпухов через 96ч
    wave_msg = None
    if o is not None and do24 is not None:
        direction = "поднимается" if do24 > 0 else "снижается"
        wave_msg = (
            f"Орёл сейчас {o} см ({'+' if do24>0 else ''}{round(do24)}/сут) — "
            f"волна ожидается в Серпухове через ~96ч"
        )

    # Прогноз пика (3 сценария)
    pb_days = pb_level = pb_date = None
    po_level = po_date = None
    pp_level = pp_date = None
    orel_declining  = do24 is not None and do24 < -5
    kaluga_declining = dk24 is not None and dk24 < -5
    serp_slowing = (ds24 is not None and ds48 is not None and
                    ds24 < ds48 and ds24 > 0)

    if s is not None:
        if orel_declining and kaluga_declining:
            extra = abs(dk24) / max(ds24 or 1, 1) if dk24 and ds24 else 3
            pb_days = round(min(max(extra, 1), 6), 1)
        elif orel_declining:
            pb_days = 4.0
        elif serp_slowing and s > 600:
            ratio = ds24 / ds48 if ds48 else 1
            pb_days = round(min(1 / (1 - ratio + 0.01) if ratio < 1 else 5, 10), 1)

        if pb_days is not None:
            pb_level = round(s + (ds24 or 0) * pb_days)
            pb_date  = (datetime.now() + timedelta(days=pb_days)).strftime("%d.%m")
            opt_days  = pb_days * 0.7
            pess_days = pb_days * 1.5
            po_level = round(s + (ds24 or 0) * 0.5 * opt_days)
            po_date  = (datetime.now() + timedelta(days=opt_days)).strftime("%d.%m")
            pp_level = round(s + (ds24 or 0) * 1.2 * pess_days)
            pp_date  = (datetime.now() + timedelta(days=pess_days)).strftime("%d.%m")

    # Дни до 945
    days_to_945 = date_to_945 = None
    if s is not None and ds24 and ds24 > 0:
        days_to_945 = round((CRITICAL_LEVEL - s) / ds24, 1)
        date_to_945 = (datetime.now() + timedelta(days=days_to_945)).strftime("%d.%m")
    elif s is not None and s >= CRITICAL_LEVEL:
        days_to_945 = 0

    # Индекс опасности 0–100%
    danger_pct = 0
    if s is not None:
        base_pct = min(s / CRITICAL_LEVEL * 100, 100)
        speed_pct = min(abs(ds24 or 0) / 50 * 20, 20) if ds24 and ds24 > 0 else 0
        danger_pct = round(min(max(base_pct + speed_pct, 0), 100), 1)

    # Alert level (KIM)
    alert_level = "GREEN"
    if s is not None:
        if s >= CRITICAL_LEVEL:    alert_level = "CRITICAL"
        elif s >= PEAK_2024:       alert_level = "RED"
        elif s >= PODTOP_LEVEL:    alert_level = "ORANGE"
        elif s >= POYMA_LEVEL:     alert_level = "YELLOW"
        elif ds24 and ds24 >= 40:  alert_level = "RED"
        elif ds24 and ds24 >= 20:  alert_level = "YELLOW"
    elif s is None:
        alert_level = "UNKNOWN"

    # Insights
    insights = []
    t = weather.get("temp") or weather.get("temp_max")
    pr = weather.get("precip_mm", 0) or 0
    if t is not None and t > 10 and pr > 5:
        insights.append(f"⚠️ Тепло ({t}°C) + дождь ({pr}мм) — риск резкого подъёма!")
    elif t is not None and t > 8:
        insights.append(f"🌡 Тепло ({t}°C) — активное таяние снега")
    elif t is not None and t < 0:
        insights.append(f"❄️ Мороз ({t}°C) — замедление паводка")
    if ds24 and ds24 >= 40:
        insights.append(f"🔥 Темп подъёма {round(ds24)}/сут — очень быстрый!")
    elif ds24 and ds24 >= 20:
        insights.append(f"⚡ Темп подъёма {round(ds24)}/сут — быстрый")
    if orel_declining and kaluga_declining:
        insights.append("📉 Орёл и Калуга снижаются — пик у Серпухова приближается")
    if wave_msg:
        insights.append(wave_msg)

    ref = load_2024_ref()
    day_of_year = datetime.now().timetuple().tm_yday
    serp_2024 = get_2024_value(ref, day_of_year)
    vs_2024 = None
    if s is not None and serp_2024 is not None:
        vs_2024 = s - serp_2024

    return dict(
        ds24=ds24, ds48=ds48, do24=do24, dk24=dk24,
        days_to_945=days_to_945, date_to_945=date_to_945,
        peak_base_days=pb_days, peak_base_level=pb_level, peak_base_date=pb_date,
        peak_opt_level=po_level, peak_opt_date=po_date,
        peak_pess_level=pp_level, peak_pess_date=pp_date,
        alert_level=alert_level, danger_pct=danger_pct,
        insights=insights, wave_msg=wave_msg,
        orel_declining=orel_declining, kaluga_declining=kaluga_declining,
        serp_slowing=serp_slowing,
        serp_2024=serp_2024, vs_2024=vs_2024,
    )

# ─── KIM TRIGGERED ALERTS ─────────────────────────────────────────────────────
def check_kim_triggers(levels, analytics, alerts):
    """Возвращает список (key, text) для новых алертов."""
    s  = levels.get("serpukhov")
    ds24 = analytics.get("ds24")
    triggered = []

    for thr in KIM_THRESHOLDS:
        key = f"KIM_{thr}"
        if s is not None and s >= thr and should_send_alert(alerts, key, cooldown_h=12):
            triggered.append((key,
                f"⚠️ <b>ALERT: Серпухов {s} см</b>\n"
                f"Пересечён порог {thr} см ({KIM_EMOJI[thr]} {KIM_LABEL[thr]})\n"
                f"Δ24ч: {_fmt_delta(ds24)} | Опасность: {analytics.get('danger_pct',0):.0f}%\n"
                f"До 945 см: {_dist(s, CRITICAL_LEVEL, ds24)}"
            ))

    if ds24 and ds24 >= 20:
        key = "RATE_FAST"
        if should_send_alert(alerts, key, cooldown_h=6):
            triggered.append((key,
                f"⚡ <b>Быстрый подъём</b>: +{round(ds24)} см/сут у Серпухова\n"
                f"Текущий уровень: {s} см"
            ))

    if ds24 and ds24 >= 40:
        key = "RATE_STORM"
        if should_send_alert(alerts, key, cooldown_h=4):
            triggered.append((key,
                f"🔥 <b>ШТОРМ-ТЕМП</b>: +{round(ds24)} см/сут у Серпухова!\n"
                f"Текущий уровень: {s} см"
            ))

    # watchdog: None > 6ч уже считает main()
    return triggered

# ─── TG SEND ──────────────────────────────────────────────────────────────────
def tg_send(chat_id, text, parse_mode="HTML"):
    if not TG_TOKEN:
        tag = f"[TG-skip {chat_id}]"
        preview = text[:120].replace("\n", " ")
        print(f"{tag} {preview}")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": parse_mode, "disable_web_page_preview": True},
            timeout=15
        )
        print(f"  TG→{chat_id}: {r.status_code}")
    except Exception as e:
        print(f"  TG err: {e}")

# ─── FORMAT HELPERS ───────────────────────────────────────────────────────────
def _fmt_delta(d):
    if d is None: return "н/д"
    return f"+{round(d)}" if d > 0 else str(round(d))

def _trend(d):
    if d is None: return "→"
    if d >= 20: return "🔥"
    if d >= 5:  return "↑"
    if d <= -10: return "↓"
    if d <= -2:  return "↘"
    return "→"

def _dist(s, target, ds24):
    if s is None: return "н/д"
    if s >= target: return "⚠️ ДОСТИГНУТ"
    remaining = target - s
    if ds24 and ds24 > 0:
        days = round(remaining / ds24, 1)
        date = (datetime.now() + timedelta(days=days)).strftime("%d.%m")
        return f"ещё {remaining} см (~{days} дн, {date})"
    return f"ещё {remaining} см"

def wind_dir_str(deg):
    dirs = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"]
    return dirs[int(deg / 45 + 0.5) % 8]

# ─── FORMAT HEARTBEAT ─────────────────────────────────────────────────────────
def format_heartbeat(levels, analytics, weather):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    al  = analytics
    alert_map = {
        "GREEN":"🟢 Норма","YELLOW":"🟡 Внимание","ORANGE":"🟠 Опасно!",
        "RED":"🔴 Критично!","CRITICAL":"💀 КРИТИЧЕСКИЙ!","UNKNOWN":"❓",
    }
    alert_txt = alert_map.get(al.get("alert_level","UNKNOWN"), "❓")
    ds24 = al.get("ds24")
    days_945 = al.get("days_to_945")

    lines = [
        f"🕐 <b>HEARTBEAT {now} МСК</b>",
        f"Статус: {alert_txt} | Опасность: {al.get('danger_pct',0):.0f}%",
        "",
    ]

    for key in STATION_KEYS:
        v   = levels.get(key)
        lag = SLUG_LAG.get(key, 0)
        lag_s = (f"+{lag}ч" if lag > 0 else (f"−{abs(lag)}ч" if lag < 0 else "0"))
        nm  = SLUG_NAMES.get(key, key)
        vs  = f"{v} см" if v is not None else "н/д"
        d24 = al.get("ds24") if key == "serpukhov" else (
              al.get("do24") if key == "orel" else (
              al.get("dk24") if key == "kaluga" else None))
        tr  = _trend(d24)
        d24s = _fmt_delta(d24) if d24 is not None else "н/д"
        marker = " ◀ ЦЕЛЬ" if key == "serpukhov" else ""
        lines.append(f"  {nm} [{lag_s}]: {vs} {tr} ({d24s}/сут){marker}")

    if ds24 and ds24 > 0 and days_945:
        lines.append(f"\n⏱ До 945 см: {_dist(levels.get('serpukhov'), CRITICAL_LEVEL, ds24)}")

    if al.get("wave_msg"):
        lines.append(f"🌊 {al['wave_msg']}")

    t = weather.get("temp")
    pr = weather.get("precip_mm", 0) or 0
    wm = weather.get("wind_ms")
    if t is not None:
        lines.append(f"\n🌡 {t}°C | 💧{pr}мм | 💨{wm}м/с")

    lines.append(f"\n🔗 em-from-pu.github.io/oka-flood-monitor")
    return "\n".join(lines)

# ─── FORMAT DIGEST ────────────────────────────────────────────────────────────
def format_digest(levels, analytics, weather, history):
    now = datetime.now().strftime("%d.%m.%Y")
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    sh = levels.get("shukina")
    ka = levels.get("kashira")
    ko = levels.get("kolomna")
    al = analytics
    ds24 = al.get("ds24")
    ds48 = al.get("ds48")
    do24 = al.get("do24")
    dk24 = al.get("dk24")
    days_945 = al.get("days_to_945")
    date_945 = al.get("date_to_945")
    pb = al.get("peak_base_level")
    pbd = al.get("peak_base_date")
    pb_days = al.get("peak_base_days")
    po = al.get("peak_opt_level")
    pod = al.get("peak_opt_date")
    pp = al.get("peak_pess_level")
    ppd = al.get("peak_pess_date")
    danger_pct = al.get("danger_pct", 0)
    vs_2024    = al.get("vs_2024")
    serp_2024  = al.get("serp_2024")

    alert_map = {
        "GREEN":"🟢","YELLOW":"🟡","ORANGE":"🟠",
        "RED":"🔴","CRITICAL":"💀","UNKNOWN":"❓",
    }
    em = alert_map.get(al.get("alert_level","UNKNOWN"), "❓")

    # Forecast block
    if s is not None and s >= CRITICAL_LEVEL:
        fcast = f"🆘 Уровень {s} см — ДОМ ПОД УГРОЗОЙ!"
    elif days_945 and ds24 and ds24 > 0:
        fcast = f"⏱ До 945 см: {_dist(s, CRITICAL_LEVEL, ds24)}"
    else:
        fcast = "Уровень в норме / данные недостаточны для прогноза"

    # Peak block
    if pb and pbd:
        peak_block = (
            f"\n━━━ ПРОГНОЗ ПИКА ━━━━━━━━━━━━━━━━━━\n"
            f"  🟢 Оптим.: ~{po or '?'} см ({pod or '?'})\n"
            f"  🟡 Базов.: ~{pb} см ({pbd}, ~{pb_days} дн)\n"
            f"  🔴 Пессим.: ~{pp or '?'} см ({ppd or '?'})"
        )
    else:
        peak_block = ""

    # Wave block
    wave_txt = f"\n🌊 {al['wave_msg']}" if al.get("wave_msg") else ""

    # vs 2024
    vs24_txt = ""
    if vs_2024 is not None and serp_2024 is not None:
        sign = "+" if vs_2024 >= 0 else ""
        vs24_txt = f"\n📊 vs 2024 (этот день): {serp_2024} см → сейчас {s} см ({sign}{vs_2024})"

    # Insights
    inst_txt = "\n".join(f"  ℹ️ {i}" for i in al.get("insights",[])[:5])

    # Weather
    t  = weather.get("temp")
    pr = weather.get("precip_mm", 0) or 0
    wm = weather.get("wind_ms")
    wd = wind_dir_str(weather.get("wind_dir", 0))
    hm = weather.get("humidity")
    snow_d = weather.get("snow_depth")
    t_max = weather.get("temp_max")
    t_min = weather.get("temp_min")
    w_line = ""
    if t is not None:
        w_line = (
            f"\n━━━ ПОГОДА (Серпухов) ━━━━━━━━━━━━━━━\n"
            f"  🌡 {t}°C (min:{t_min}° max:{t_max}°) | 💧{pr}мм\n"
            f"  💨 {wm}м/с {wd} | 💦{hm}%"
        )
        if snow_d is not None:
            w_line += f" | ❄️снег:{snow_d}м"

    return (
        f"🌊 <b>ОКА ПАВОДОК 2026 — ДАЙДЖЕСТ</b>\n"
        f"📅 {now} | {em} Опасность: {danger_pct:.0f}%\n"
        f"\n━━━ УРОВНИ ВОДЫ ━━━━━━━━━━━━━━━━━━\n"
        f"📍 Орёл      [+96ч]: {o if o is not None else 'н/д'} см {_trend(do24)} ({_fmt_delta(do24)}/сут)\n"
        f"📍 Белев     [+72ч]: {b if b is not None else 'н/д'} см →\n"
        f"📍 Калуга    [+48ч]: {k if k is not None else 'н/д'} см {_trend(dk24)} ({_fmt_delta(dk24)}/сут)\n"
        f"📍 Щукина    [+24ч]: {sh if sh is not None else 'н/д'} см →\n"
        f"📍 Серпухов  [цель]: <b>{s if s is not None else 'н/д'} см</b> {_trend(ds24)} ({_fmt_delta(ds24)}/сут)\n"
        f"         Δ48ч: {_fmt_delta(ds48)} | ⚠️{danger_pct:.0f}%\n"
        f"📍 Кашира   [−12ч]: {ka if ka is not None else 'н/д'} см →\n"
        f"📍 Коломна  [−24ч]: {ko if ko is not None else 'н/д'} см →\n"
        f"\n━━━ ПОРОГИ (Серпухов) ━━━━━━━━━━━━━━\n"
        f"  До 🟡 500 см: {_dist(s, NORM_LEVEL,    ds24)}\n"
        f"  До 🟠 645 см: {_dist(s, POYMA_LEVEL,   ds24)}\n"
        f"  До 🔴 800 см: {_dist(s, PODTOP_LEVEL,  ds24)}\n"
        f"  До 🆘 920 см: {_dist(s, PEAK_2024,     ds24)}\n"
        f"  До 💀 945 см: {_dist(s, CRITICAL_LEVEL,ds24)}\n"
        f"\n━━━ ПРОГНОЗ ━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {fcast}"
        f"{peak_block}"
        f"{wave_txt}"
        f"{vs24_txt}"
        f"{w_line}"
        + (f"\n\n━━━ АНАЛИТИКА ━━━━━━━━━━━━━━━━━━━━\n{inst_txt}" if inst_txt else "")
        + f"\n\n🔗 em-from-pu.github.io/oka-flood-monitor\nДанные: fishingsib.ru"
    )

# ─── FORMAT GROUP DRAFT ───────────────────────────────────────────────────────
def format_group_draft(levels, analytics):
    now = datetime.now().strftime("%d.%m.%Y")
    s  = levels.get("serpukhov", "?")
    o  = levels.get("orel",      "?")
    k  = levels.get("kaluga",    "?")
    sh = levels.get("shukina",   "?")
    ka = levels.get("kashira",   "?")
    al = analytics
    ds24 = al.get("ds24")
    days_945 = al.get("days_to_945")
    date_945 = al.get("date_to_945")
    pb = al.get("peak_base_level")
    pbd = al.get("peak_base_date")
    alert_map = {
        "GREEN":"💚 Наблюдаем","YELLOW":"🟡 Готовимся","ORANGE":"🟠 Действуем!",
        "RED":"🔴 Тревога!","CRITICAL":"🆘 КРИТИЧНО!","UNKNOWN":"❓",
    }
    status = alert_map.get(al.get("alert_level","UNKNOWN"), "❓")
    sign = "+" if ds24 and ds24 > 0 else ""
    delta_txt = f"{sign}{round(ds24)}" if ds24 is not None else "н/д"
    dist_txt = _dist(s if isinstance(s,int) else None, CRITICAL_LEVEL, ds24)

    txt = (
        f"🌊 ПАВОДОК 2026 | ДАЧИ | {now}, утро\n\n"
        f"📊 УРОВНИ ОКИ (данные на 08:00):\n"
        f"• Орёл (3-4 дня до нас):     {o} см\n"
        f"• Калуга (1-2 дня до нас):   {k} см\n"
        f"• Щукина/Алексин (1 день):   {sh} см\n"
        f"• Серпухов (наш пост):       {s} см [{delta_txt}/сут]\n"
        f"• Кашира (ниже нас):         {ka} см\n\n"
        f"📏 ОРИЕНТИР 2024: пик ~920 см у Серпухова\n"
        f"   (вода была в 20 см от порогов наших домов)\n\n"
        f"🎯 ДО КРИТИЧЕСКИХ ОТМЕТОК:\n"
        f"   До уровня 2024 (920 см): {_dist(s if isinstance(s,int) else None, PEAK_2024, ds24)}\n"
        f"   До порога домов (945 см): {dist_txt}\n"
    )
    if pb and pbd:
        txt += f"\n🔮 ПРОГНОЗ: пик ~{pb} см около {pbd}\n"
    txt += (
        f"\n📌 СТАТУС: {status}\n"
        f"Данные: fishingsib.ru | Следующее обновление: через 60 мин"
    )
    return txt

# ─── GENERATE HTML ────────────────────────────────────────────────────────────
def generate_html(levels, analytics, weather, history):
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    b  = levels.get("belev")
    k  = levels.get("kaluga")
    sh = levels.get("shukina")
    ka = levels.get("kashira")
    ko = levels.get("kolomna")
    al = analytics
    now_str  = datetime.now().strftime("%d.%m.%Y %H:%M")
    ds24     = al.get("ds24")
    days_945 = al.get("days_to_945")
    date_945 = al.get("date_to_945")
    pb_level = al.get("peak_base_level")
    pb_date  = al.get("peak_base_date")
    pb_days  = al.get("peak_base_days")
    po_level = al.get("peak_opt_level")
    po_date  = al.get("peak_opt_date")
    pp_level = al.get("peak_pess_level")
    pp_date  = al.get("peak_pess_date")
    danger_pct = al.get("danger_pct", 0)
    vs_2024    = al.get("vs_2024")
    serp_2024  = al.get("serp_2024")

    color_map = {
        "GREEN":  ("#27ae60","🟢"),
        "YELLOW": ("#f39c12","🟡"),
        "ORANGE": ("#e67e22","🟠"),
        "RED":    ("#c0392b","🔴"),
        "CRITICAL":("#8e0000","💀"),
        "UNKNOWN": ("#7f8c8d","❓"),
    }
    alert_level = al.get("alert_level","UNKNOWN")
    alert_color, alert_em = color_map.get(alert_level, ("#7f8c8d","❓"))

    # Gauge cards HTML
    def lvl_card(name, val, delta, note, main=False):
        d_str = ""
        if delta is not None:
            sign = "+" if delta > 0 else ""
            d_str = f'<div class="gauge-delta">{sign}{round(delta)}</div>'
        cls = "gauge-card main" if main else "gauge-card"
        val_html = str(val) if val is not None else '<span class="na">н/д</span>'
        return (
            f'<div class="{cls}">'
            f'<div class="gauge-name">{name}</div>'
            f'<div class="gauge-level">{val_html}</div>'
            f'{d_str}'
            f'<div class="gauge-note">{note}</div>'
            f'</div>'
        )

    gauges_html = (
        lvl_card("Орёл",    o,  al.get("do24"), "+96ч") +
        lvl_card("Белев",   b,  None,            "+72ч") +
        lvl_card("Калуга",  k,  al.get("dk24"), "+48ч") +
        lvl_card("Щукина",  sh, None,            "+24ч") +
        lvl_card("Серпухов",s,  ds24,            "цель", main=True) +
        lvl_card("Кашира",  ka, None,            "−12ч") +
        lvl_card("Коломна", ko, None,            "−24ч")
    )

    # Thresholds
    def ms_dist(target):
        if s is None: return ""
        if s >= target: return "⚠️ ДОСТИГНУТ"
        rem = target - s
        if ds24 and ds24 > 0:
            d = round(rem/ds24,1)
            dt = (datetime.now()+timedelta(days=d)).strftime("%d.%m")
            return f"ещё {rem} см (~{d} дн, {dt})"
        return f"ещё {rem} см"

    thresh_rows = "".join(
        f'<tr><td>{KIM_EMOJI[t]} {t} см</td><td>{KIM_LABEL[t]}</td><td>{ms_dist(t)}</td></tr>'
        for t in KIM_THRESHOLDS
    )

    # Scenario block
    if pb_level:
        scen = (
            f'<div class="scenario-cards">'
            f'<div class="sc-card green"><div class="sc-title">Оптим.</div>'
            f'<div class="sc-level">{po_level or "?"}</div>'
            f'<div class="sc-date">{po_date or "?"}</div></div>'
            f'<div class="sc-card yellow"><div class="sc-title">Базов.</div>'
            f'<div class="sc-level">{pb_level}</div>'
            f'<div class="sc-date">{pb_date} (~{pb_days}дн)</div></div>'
            f'<div class="sc-card red"><div class="sc-title">Пессим.</div>'
            f'<div class="sc-level">{pp_level or "?"}</div>'
            f'<div class="sc-date">{pp_date or "?"}</div></div>'
            f'</div>'
        )
    else:
        scen = '<div class="scenario-cards"><p>Данных пока недостаточно для прогноза пика</p></div>'

    # Weather block
    t   = weather.get("temp")
    hm  = weather.get("humidity")
    wm  = weather.get("wind_ms")
    wd  = wind_dir_str(weather.get("wind_dir",0))
    pr  = weather.get("precip_mm",0) or 0
    cl  = weather.get("clouds")
    desc= weather.get("weather","")
    t_max = weather.get("temp_max")
    t_min = weather.get("temp_min")
    snow_d = weather.get("snow_depth")
    w_html = ""
    if t is not None:
        w_html = (
            f'<div class="weather-block"><h3>🌡 Погода (Серпухов)</h3>'
            f'<div class="weather-grid">'
            f'<div>{t}°C — {desc}</div>'
            f'<div>min:{t_min}° / max:{t_max}°</div>'
            f'<div>💧 {pr}мм осадков</div>'
            f'<div>💨 {wm}м/с {wd}</div>'
            f'<div>💦 {hm}%</div>'
            + (f'<div>❄️ снег: {snow_d}м</div>' if snow_d else "")
            + f'</div></div>'
        )

    # Wave block
    wave_html = ""
    if al.get("wave_msg"):
        wave_html = f'<div class="wave-block">🌊 {al["wave_msg"]}</div>'

    # vs 2024
    vs24_html = ""
    if vs_2024 is not None and serp_2024 is not None:
        sign = "+" if vs_2024 >= 0 else ""
        vs24_html = (
            f'<div class="vs2024">📊 Сравнение с 2024 (этот день): '
            f'{serp_2024} см → сейчас {s} см ({sign}{vs_2024})</div>'
        )

    # History table
    t_rows = []
    for row in sorted(history, key=lambda x: x.get("datetime",""), reverse=True)[:30]:
        def cv(key):
            v = row.get(key,"")
            if not v: return "—"
            try:
                f = float(v)
                return str(round(f)) if "delta" not in key else str(round(f))
            except:
                return str(v)
        cl_map = {"GREEN":"row-green","YELLOW":"row-yellow","ORANGE":"row-orange",
                  "RED":"row-red","CRITICAL":"row-critical"}
        r_cls = cl_map.get(row.get("alert_level",""),"")
        t_rows.append(
            f'<tr class="{r_cls}">'
            f'<td>{row.get("datetime","")[:16]}</td>'
            f'<td>{cv("orel")}</td><td>{cv("belev")}</td><td>{cv("kaluga")}</td>'
            f'<td>{cv("shukina")}</td><td><b>{cv("serpukhov")}</b></td>'
            f'<td>{cv("kashira")}</td><td>{cv("kolomna")}</td>'
            f'<td>{cv("delta_serp_24h")}</td><td>{cv("temp")}</td>'
            f'<td>{cv("precip_mm")}</td></tr>'
        )
    t_rows_html = "\n".join(t_rows) if t_rows else '<tr><td colspan="11">История пуста</td></tr>'

    # Insights
    ins_html = "".join(f'<li>{i}</li>' for i in al.get("insights",[]))
    ins_html = ins_html or "<li>...</li>"

    pct = min(round(s / CRITICAL_LEVEL * 100, 1) if s else 0, 100)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ОКА ПАВОДОК 2026</title>
<style>
  body{{font-family:'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0}}
  h1{{background:{alert_color};color:#fff;margin:0;padding:20px 24px;font-size:1.6em}}
  h3{{color:#79c0ff;margin:12px 0 6px}}
  .container{{max-width:1100px;margin:0 auto;padding:16px}}
  .meta{{color:#8b949e;font-size:.85em;margin-bottom:16px}}
  .gauges{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
  .gauge-card{{background:#161b22;border:1px solid #30363d;border-radius:8px;
    padding:12px 16px;min-width:120px;text-align:center}}
  .gauge-card.main{{border:2px solid {alert_color};background:#1c2128}}
  .gauge-name{{font-size:.8em;color:#8b949e;margin-bottom:4px}}
  .gauge-level{{font-size:2em;font-weight:700;color:#e6edf3}}
  .gauge-delta{{font-size:.9em;color:#3fb950;margin-top:2px}}
  .gauge-note{{font-size:.75em;color:#6e7681;margin-top:4px}}
  .na{{color:#6e7681;font-size:.7em}}
  .danger-bar{{height:10px;background:#21262d;border-radius:5px;margin:12px 0}}
  .danger-fill{{height:10px;border-radius:5px;
    background:linear-gradient(90deg,#3fb950,#d29922,#db6d28,#f85149);
    width:{pct}%}}
  table{{width:100%;border-collapse:collapse;font-size:.82em}}
  th{{background:#161b22;color:#8b949e;padding:6px 8px;text-align:left}}
  td{{padding:5px 8px;border-bottom:1px solid #21262d}}
  .row-green td{{background:#0d2016}}
  .row-yellow td{{background:#2a1d00}}
  .row-orange td{{background:#2a1400}}
  .row-red td{{background:#2d0000}}
  .row-critical td{{background:#1a0000}}
  .thresh-table td:first-child{{font-size:1.1em}}
  .scenario-cards{{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0}}
  .sc-card{{background:#161b22;border-radius:8px;padding:12px;min-width:120px;text-align:center}}
  .sc-card.green{{border-left:3px solid #3fb950}}
  .sc-card.yellow{{border-left:3px solid #d29922}}
  .sc-card.red{{border-left:3px solid #f85149}}
  .sc-title{{font-size:.8em;color:#8b949e}}
  .sc-level{{font-size:1.6em;font-weight:700}}
  .sc-date{{font-size:.8em;color:#6e7681}}
  .weather-block,.wave-block,.vs2024{{background:#161b22;border-radius:8px;
    padding:12px 16px;margin:12px 0}}
  .weather-grid{{display:flex;flex-wrap:wrap;gap:12px 24px;font-size:.9em}}
  .wave-block{{border-left:3px solid #388bfd;color:#79c0ff}}
  .vs2024{{border-left:3px solid #d29922;color:#e3b341}}
  a{{color:#388bfd}}
  footer{{color:#6e7681;font-size:.8em;text-align:center;padding:20px}}
</style>
</head>
<body>
<h1>🌊 ОКА ПАВОДОК 2026 &nbsp;{alert_em}&nbsp; Серпухов: {s if s is not None else "н/д"} см &nbsp;|&nbsp; Опасность: {danger_pct:.0f}%</h1>
<div class="container">
<p class="meta">Обновлено: {now_str} МСК | Источник: fishingsib.ru</p>

<div class="danger-bar"><div class="danger-fill"></div></div>

<h3>📊 Уровни воды — 7 постов Оки</h3>
<div class="gauges">{gauges_html}</div>

{w_html}
{wave_html}
{vs24_html}

<h3>⚠️ Пороги КИМ (Серпухов)</h3>
<table class="thresh-table">
<tr><th>Порог</th><th>Значение</th><th>До порога</th></tr>
{thresh_rows}
</table>

<h3>🔮 Прогноз пика</h3>
{scen}

<h3>💡 Аналитика</h3>
<ul>{ins_html}</ul>
<p>Δ24ч Серпухов: {_fmt_delta(ds24)} см | Δ48ч: {_fmt_delta(al.get('ds48'))} см</p>
<p>Δ24ч Орёл: {_fmt_delta(al.get('do24'))} | Δ24ч Калуга: {_fmt_delta(al.get('dk24'))}</p>
{f'<p>До 945 см: {_dist(s, CRITICAL_LEVEL, ds24)}</p>' if ds24 and ds24 > 0 else ''}

<h3>📅 История замеров (последние 30)</h3>
<div style="overflow-x:auto">
<table>
<tr><th>Дата/время</th><th>Орёл</th><th>Белев</th><th>Калуга</th><th>Щукина</th>
<th>Серпухов</th><th>Кашира</th><th>Коломна</th><th>Δ/сут</th><th>T°</th><th>Осадки</th></tr>
{t_rows_html}
</table>
</div>

<footer>
  OkaFloodMonitor v4.2 | Дача: 54.834050, 37.742901 |
  <a href="https://fishingsib.ru">fishingsib.ru</a> |
  <a href="https://em-from-pu.github.io/oka-flood-monitor">Открыть в браузере</a>
</footer>
</div>
</body>
</html>"""

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    # 1. Данные
    levels  = fetch_all_levels()
    weather = fetch_weather()
    history = load_history()
    alerts  = load_alerts()

    # 2. Аналитика
    analytics = compute_analytics(levels, history, weather)
    print(f"  alert={analytics.get('alert_level')}, "
          f"ds24={analytics.get('ds24')}, days945={analytics.get('days_to_945')}, "
          f"danger={analytics.get('danger_pct',0):.0f}%")

    # 3. Сохраняем историю
    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "datetime": now_iso,
        "orel":     levels.get("orel",""), "belev": levels.get("belev",""),
        "kaluga":   levels.get("kaluga",""), "shukina": levels.get("shukina",""),
        "serpukhov":levels.get("serpukhov",""), "kashira": levels.get("kashira",""),
        "kolomna":  levels.get("kolomna",""),
        "delta_serp_24h":  analytics.get("ds24",""),
        "delta_serp_48h":  analytics.get("ds48",""),
        "delta_orel_24h":  analytics.get("do24",""),
        "delta_kaluga_24h":analytics.get("dk24",""),
        "temp":       weather.get("temp",""), "humidity": weather.get("humidity",""),
        "wind_ms":    weather.get("wind_ms",""), "wind_dir": weather.get("wind_dir",""),
        "clouds":     weather.get("clouds",""), "precip_mm": weather.get("precip_mm",""),
        "alert_level":analytics.get("alert_level",""),
        "forecast_days_to_945": analytics.get("days_to_945",""),
        "forecast_days_to_peak":analytics.get("peak_base_days",""),
        "scenario_base_peak":   analytics.get("peak_base_level",""),
        "scenario_base_date":   analytics.get("peak_base_date",""),
        "notes": "",
    }
    history.append(row)
    save_history(history)

    # 4. KIM алерты (dedup)
    triggered = check_kim_triggers(levels, analytics, alerts)
    for key, text in triggered:
        print(f"Отправляем KIM alert: {key}")
        tg_send(CHAT_ADMIN, text)
        s_val = levels.get("serpukhov")
        # в группу — только от T4 (645) и выше
        if any(str(t) in key for t in [645,800,920,945,965]):
            tg_send(CHAT_GROUP, text)
        alerts[key] = datetime.now().isoformat()
    if triggered:
        save_alerts(alerts)

    # Watchdog T10: данные Серпухова отсутствуют
    serp_val = levels.get("serpukhov")
    if serp_val is None:
        key = "WATCHDOG_SERP"
        if should_send_alert(alerts, key, cooldown_h=6):
            print("Отправляем watchdog alert...")
            tg_send(CHAT_ADMIN,
                "❌ <b>WATCHDOG</b>: Серпухов не отвечает!\n"
                "Данные с поста Серпухов недоступны.\n"
                "Проверьте fishingsib.ru и перезапустите скрипт."
            )
            alerts[key] = datetime.now().isoformat()
            save_alerts(alerts)

    # 5. Heartbeat
    heartbeat = format_heartbeat(levels, analytics, weather)
    print("Отправляем heartbeat...")
    tg_send(CHAT_ADMIN, heartbeat)

    # 6. Дайджест
    digest = format_digest(levels, analytics, weather, history)
    print("Отправляем дайджест...")
    tg_send(CHAT_ADMIN, digest)

    # 7. В группу — если уровень >= T4 (POYMA_LEVEL 645)
    if (serp_val is not None and serp_val >= POYMA_LEVEL) or \
       analytics.get("alert_level") in ("ORANGE","RED","CRITICAL"):
        print("🔴 Порог T4+ — дайджест идёт в группу!")
        tg_send(CHAT_GROUP, digest)

    # 8. HTML + JSON
    html = generate_html(levels, analytics, weather, history)
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML записан → {INDEX_HTML}")

    data_out = {
        "updated": now_iso,
        "levels": levels,
        "analytics": {k: analytics.get(k) for k in
                      ["ds24","ds48","alert_level","days_to_945","date_to_945",
                       "peak_base_level","peak_base_date","danger_pct","wave_msg","insights"]},
        "weather": weather,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)
    print(f"  JSON записан → {DATA_JSON}")

    # 9. Group draft
    group_draft = format_group_draft(levels, analytics)
    with open(GROUP_DRAFT, "w", encoding="utf-8") as f:
        f.write(group_draft)
    print(f"  Group draft → {GROUP_DRAFT}")

    # 10. Status file
    s_str = f"{serp_val} см" if serp_val is not None else "н/д"
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write(f"{analytics.get('alert_level','')} | {s_str} | {now_iso}")
    print(f"  Status → {STATUS_FILE}")

if __name__ == "__main__":
    main()
