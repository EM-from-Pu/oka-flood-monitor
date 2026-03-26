#!/usr/bin/env python3
# =============================================================================
# OkaFloodMonitor v4.3  —  27.03.2026
# WEATHER EXTENDED BLOCK FULLY INTEGRATED
# Базируется на v4.2 (GOLDEN) + расширенный блок погоды из ТЗ (file:3)
#
# ИЗМЕНЕНИЯ vs v4.2:
#   + fetch_weather_extended()  — Open-Meteo, 8 дней (4 факт + 4 прогноз)
#   + compute_weather_flood_index() — паводковый индекс 0-4
#   + generate_weather_commentary() — 6 векторов анализа
#   + weather_ext_html()  — HTML-блок (Зоны A/B/D из ТЗ)
#   + WEATHER_EXT_CSS     — CSS для блока
#   + generate_html() теперь принимает wext=None и вставляет wext_html
#   + format_digest() добавлена строка паводкового индекса погоды
#   + HISTORY_COLS расширены: snow_depth_cm, flood_weather_index
#   + API FIX: snow_depth_max вместо snow_depth (Open-Meteo v1 API)
#
# NO-GO соблюдены:
#   - не трогаем fetch_module.py, fetchlevel, STATIONS
#   - не используем re.sub/assert на строки кода
#   - не переписываем computeanalytics, не ломаем KIM-пороги
#   - patch применён напрямую, не через строковые замены
# =============================================================================

import os, json, csv, requests
from datetime import datetime, timedelta, timezone

# ─── CONFIG ────────────────────────────────────────────────────────────────────
TG_TOKEN    = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN  = os.environ.get("TG_CHAT_ID", "49747475")
CHAT_GROUP  = os.environ.get("TG_GROUP_ID", "-5234360275")
OWM_KEY     = os.environ.get("WEATHER_API_KEY", "")
SERP_LAT, SERP_LON = 54.834050, 37.742901

CRITICAL_LEVEL = 945
PEAK_2024      = 920
PODTOP_LEVEL   = 800
POYMA_LEVEL    = 645
NORM_LEVEL     = 500
KIM_THRESHOLDS = (500, 645, 800, 920, 945, 965)
KIM_EMOJI  = {500:"🟢",645:"🟡",800:"🟠",920:"🔴",945:"🆘",965:"⛔"}
KIM_LABEL  = {500:"L1 норма",645:"L2 пойма",800:"L3 подтоп",
              920:"L4 пик2024",945:"L5 критич",965:"L6 макс"}

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(BASE_DIR, "data")
DOCS_DIR    = os.path.join(BASE_DIR, "docs")
HISTORY_FILE= os.path.join(DATA_DIR, "history.csv")
REF_2024    = os.path.join(DATA_DIR, "2024ref.json")
DATA_JSON   = os.path.join(DOCS_DIR, "data.json")
INDEX_HTML  = os.path.join(DOCS_DIR, "index.html")
GROUP_DRAFT = os.path.join(DOCS_DIR, "groupdraft.txt")
STATUS_FILE = os.path.join(DOCS_DIR, "status.txt")
ALERTS_FILE = os.path.join(DATA_DIR, "alertssent.json")

# История расширена двумя новыми колонками
HISTORY_COLS = (
    "datetime,orel,belev,kaluga,shukina,serpukhov,kashira,kolomna,"
    "delta_serp_24h,delta_serp_48h,delta_orel_24h,delta_kaluga_24h,"
    "temp,humidity,wind_ms,wind_dir,clouds,precip_mm,"
    "alert_level,forecast_days_to_945,forecast_days_to_peak,"
    "scenario_base_peak,scenario_base_date,notes,"
    "snow_depth_cm,flood_weather_index"
).split(",")

SLUG_NAMES = {
    "orel":"Орёл","belev":"Белёв","kaluga":"Калуга","shukina":"Щукино",
    "serpukhov":"Серпухов","kashira":"Кашира","kolomna":"Коломна"
}
# lag_h берётся из STATIONS через fetch_module; здесь fallback
SLUG_LAG = {"orel":96,"belev":72,"kaluga":48,"shukina":24,"serpukhov":0,"kashira":-12,"kolomna":-24}
STATION_KEYS = ["orel","belev","kaluga","shukina","serpukhov","kashira","kolomna"]

def printf(fmt, *a):
    print(fmt % a if a else fmt)

# ─── FETCH LEVELS (через fetch_module.py) ──────────────────────────────────────
def fetch_all_levels():
    try:
        from fetch_module import fetch_level as fishfetch, STATIONS
    except ImportError:
        printf("WARNING: fetch_module not found, using stub")
        return {k: None for k in STATION_KEYS}

    printf("OkaMonitor v4.3 | %d станций fishingsib…", len(STATIONS))
    levels = {}
    for st in STATIONS:
        slug_key = st["slug"].replace("oka-","").replace("serpuhov","serpukhov")
        url = f"https://allrivers.info/gauge/{st['slug']}"
        val = fishfetch(url, st["name"])
        levels[slug_key] = val
        printf("  %s → %s", st["name"], val)
    printf("levels: %s", levels)
    return levels

# ─── FETCH WEATHER (OWM → Open-Meteo fallback, старый простой блок) ────────────
def fetch_weather():
    printf("fetch_weather…")
    if OWM_KEY:
        try:
            r = requests.get("https://api.openweathermap.org/data/2.5/weather",
                params={"lat":SERP_LAT,"lon":SERP_LON,"appid":OWM_KEY,"units":"metric","lang":"ru"},
                timeout=12)
            if r.status_code == 200:
                d = r.json()
                return dict(
                    temp=round(d["main"]["temp"],1),
                    humidity=d["main"]["humidity"],
                    wind_ms=round(d["wind"]["speed"],1),
                    wind_dir=d["wind"].get("deg",0),
                    clouds=d["clouds"]["all"],
                    precip_mm=round(d.get("rain",{}).get("1h",0)+d.get("snow",{}).get("1h",0),1),
                    weather=d["weather"][0]["description"],
                )
        except Exception as e:
            printf("OWM err: %s", e)
    # Open-Meteo fallback
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=[
            ("latitude",SERP_LAT),("longitude",SERP_LON),
            ("current_weather","true"),
            ("daily","temperature_2m_max"),("daily","temperature_2m_min"),
            ("daily","precipitation_sum"),("daily","snow_depth_max"),
            ("daily","wind_speed_10m_max"),
            ("hourly","relative_humidity_2m"),
            ("forecast_days",2),("timezone","Europe/Moscow"),
        ], timeout=12)
        if r.status_code == 200:
            d = r.json()
            cw    = d.get("current_weather", {})
            daily = d.get("daily", {})
            hourly= d.get("hourly", {})
            return dict(
                temp=cw.get("temperature"),
                humidity=(hourly.get("relative_humidity_2m") or [None])[0],
                wind_ms=cw.get("windspeed"),
                wind_dir=cw.get("winddirection",0),
                clouds=None,
                precip_mm=(daily.get("precipitation_sum") or [None])[0],
                snow_depth=(daily.get("snow_depth_max") or [None])[0],
                weather="Open-Meteo",
                temp_max=(daily.get("temperature_2m_max") or [None])[0],
                temp_min=(daily.get("temperature_2m_min") or [None])[0],
                wind_max=(daily.get("wind_speed_10m_max") or [None])[0],
            )
    except Exception as e:
        printf("OpenMeteo err: %s", e)
    return {}

# ─── FETCH WEATHER EXTENDED (новый расширенный блок) ──────────────────────────
def fetch_weather_extended():
    """
    Open-Meteo: 4 прошлых дня + сегодня + 3 дня вперёд.
    Ключевой фикс: snow_depth_max вместо snow_depth (API v1 не поддерживает snow_depth как daily).
    snow_depth_max возвращается в метрах → *100 = см.
    """
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast", params=[
            ("latitude",  SERP_LAT),
            ("longitude", SERP_LON),
            ("daily", "temperature_2m_max"),
            ("daily", "temperature_2m_min"),
            ("daily", "precipitation_sum"),
            ("daily", "rain_sum"),
            ("daily", "snowfall_sum"),
            ("daily", "snow_depth_max"),        # ← FIX: snow_depth_max не snow_depth
            ("daily", "wind_speed_10m_max"),
            ("daily", "weather_code"),
            ("past_days",     4),
            ("forecast_days", 4),
            ("timezone", "Europe/Moscow"),
            ("wind_speed_unit", "ms"),
        ], timeout=12)
        r.raise_for_status()
        d = r.json()
        daily = d.get("daily", {})
        dates = daily.get("time", [])
        today = datetime.now().date().isoformat()

        days = []
        for i, date in enumerate(dates):
            days.append({
                "date":         date,
                "is_forecast":  date > today,
                "tmax":         daily["temperature_2m_max"][i],
                "tmin":         daily["temperature_2m_min"][i],
                "precip":       daily["precipitation_sum"][i] or 0,
                "rain_sum":     daily["rain_sum"][i] or 0,
                "snowfall_cm":  daily["snowfall_sum"][i] or 0,
                "snow_depth_cm":round((daily["snow_depth_max"][i] or 0) * 100, 1),
                "wind_ms":      daily["wind_speed_10m_max"][i],
                "weather_code": daily["weather_code"][i],
            })

        past_days_list = [d for d in days if not d["is_forecast"]]
        snow_depth_cm  = past_days_list[-1]["snow_depth_cm"] if past_days_list else 0

        flood_level, flood_label, flood_color, flood_summary = compute_weather_flood_index(days, snow_depth_cm)
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

# ─── 6 ВЕКТОРОВ ПОГОДНОГО АНАЛИЗА ─────────────────────────────────────────────
def _analyze_ros(days, snow_depth_cm):
    for i, day in enumerate(days[4:], 1):
        rain = day.get("rain_sum", 0) or 0
        tmax = day.get("tmax", 0) or 0
        if rain >= 5 and tmax > 0 and snow_depth_cm > 3:
            return [f"⚠️ ОПАСНО: через {i} дн. дождь ({rain:.0f}мм) при +{tmax:.0f}°C на снег "
                    f"({snow_depth_cm:.0f}см) — Rain-on-Snow, максимальный риск!"]
        elif rain >= 2 and tmax > 0 and snow_depth_cm > 1:
            return [f"🟡 Через {i} дн. ожидается дождь ({rain:.0f}мм) при плюсе — доп. нагрузка на реку."]
    return []

def _analyze_snow_depth(days):
    depths = [d["snow_depth_cm"] for d in days[:4] if d.get("snow_depth_cm") is not None]
    if not depths:
        return ["❓ Данные о снежном покрове недоступны."]
    c = depths[-1]
    delta = c - depths[0] if len(depths) > 1 else 0
    if c < 1:   return ["✅ Снежный покров исчез — талые воды уже не добавятся."]
    if c < 5:   return [f"🔵 Снежный покров минимальный ({c:.0f} см) — растает за 1–2 дня тепла."]
    if c < 15:  return [f"❄️ Снежный покров: {c:.0f} см (Δ4 дня: {delta:+.0f} см)."]
    return [f"⚠️ Значительный снежный покров: {c:.0f} см — серьёзный вклад в паводок при потеплении и дожде."]

def _analyze_frost_nights(days):
    fp = sum(1 for d in days[:4] if (d.get("tmin") or 0) < 0)
    ff = sum(1 for d in days[4:] if (d.get("tmin") or 0) < 0)
    if ff >= 2: return [f"❄️ Прогноз: {ff} ночи с морозом — таяние замедлится, рост уровня притормозит."]
    if ff == 1: return ["❄️ Одна ночь с морозом в прогнозе — кратковременное замедление таяния."]
    if fp >= 2: return [f"🌡 Последние ночи с морозом ({fp}/4), прогноз — потепление: таяние ускорится."]
    return ["🌡 Ночных заморозков нет и не ожидается — снег тает и ночью."]

def _analyze_tmin_trend(days):
    tmins = [d["tmin"] for d in days[:4] if d.get("tmin") is not None]
    if len(tmins) < 2: return []
    tr = tmins[-1] - tmins[0]
    avg = sum(tmins) / len(tmins)
    if tr >= 3:
        return [f"📈 Ночи теплеют (+{tr:.0f}°C за 4 дня){', пока с морозом — скоро через 0°C' if avg < 0 else ' — таяние ускоряется'}."]
    if tr <= -3: return [f"📉 Ночи холодают ({tr:.0f}°C за 4 дня) — интенсивность таяния снижается."]
    if avg < 0:  return ["🌡 Ночные температуры стабильно минусовые — таяние только днём."]
    return ["🌡 Ночные температуры стабильно выше нуля — снег тает круглосуточно."]

def _analyze_warm_days(days):
    sp = sum(1 for d in reversed(days[:4]) if (d.get("tmax") or 0) > 10)
    sf = 0
    for d in days[4:]:
        if (d.get("tmax") or 0) > 10: sf += 1
        else: break
    total = sp + sf
    if total >= 5: return [f"☀️ Длительное тепло: {total} дней подряд >+10°C — интенсивное снеготаяние, пик близко."]
    if sf >= 2:    return [f"☀️ Прогноз: {sf} тёплых дня (>+10°C) — снег будет таять активно."]
    return []

def _analyze_precipitation(days):
    fr = sum(d.get("rain_sum", 0) or 0 for d in days[4:])
    pr = sum(d.get("rain_sum", 0) or 0 for d in days[:4])
    if fr >= 20: return [f"🌧 Прогноз осадков 4 дня: {fr:.0f} мм — значительно, доп. нагрузка на водосбор."]
    if fr >= 8:  return [f"🌧 Ожидается {fr:.0f} мм осадков — умеренно."]
    if pr >= 15: return [f"🌧 За последние 4 дня выпало {pr:.0f} мм — почва насыщена, сток повышен."]
    return []

def compute_weather_flood_index(days, snow_depth_cm):
    score = 0
    score += sum(1 for d in days[4:] if (d.get("tmin") or -5) >= 0) * 2
    score += sum(1 for d in days[4:] if (d.get("tmax") or 0) >= 10) * 1
    score += min(sum(d.get("rain_sum",0) or 0 for d in days[4:]) / 5, 4)
    if   snow_depth_cm > 20: score += 2
    elif snow_depth_cm > 5:  score += 1
    if any((d.get("rain_sum",0) or 0) >= 5 and (d.get("tmax") or 0) > 0 and snow_depth_cm > 3
           for d in days[4:]):
        score += 3
    if   score >= 10: return 4,"КРИТИЧЕСКИЙ","#8e0000","Все факторы против нас: тепло, дождь, снег. Максимально быстрый рост уровня."
    elif score >= 7:  return 3,"ВЫСОКИЙ",    "#c0392b","Активное таяние, ночи тёплые, осадки. Уровень будет расти значительно."
    elif score >= 4:  return 2,"УМЕРЕННЫЙ",  "#e67e22","Таяние идёт, есть сдерживающие факторы. Умеренный рост уровня."
    elif score >= 2:  return 1,"НИЗКИЙ",     "#f39c12","Ночные заморозки сдерживают таяние. Уровень растёт медленно."
    else:             return 0,"СТАБИЛЬНЫЙ", "#27ae60","Погода не способствует значительному росту уровня."

def generate_weather_commentary(days, snow_depth_cm):
    c = []
    c += _analyze_ros(days, snow_depth_cm)
    c += _analyze_snow_depth(days)
    c += _analyze_frost_nights(days)
    c += _analyze_tmin_trend(days)
    c += _analyze_warm_days(days)
    c += _analyze_precipitation(days)
    return c[:4]

# ─── CSS РАСШИРЕННОГО БЛОКА ПОГОДЫ ─────────────────────────────────────────────
WEATHER_EXT_CSS = """
.weather-ext-block{background:#161b22;border-radius:12px;padding:16px;margin:12px 0}
.weather-flood-index{border:2px solid;border-radius:10px;padding:14px 18px;margin-bottom:16px;background:rgba(255,255,255,.03)}
.wfi-label{font-size:.85em;color:#95a5a6;display:block}
.wfi-value{font-size:1.6em;font-weight:900;display:block;margin:4px 0}
.wfi-summary{margin:0;color:#bdc3c7;font-size:.95em}
.weather-table{width:100%;border-collapse:collapse;font-size:.88em}
.weather-table th,.weather-table td{padding:6px 8px;text-align:center;border-bottom:1px solid #30363d;white-space:nowrap}
.weather-table td:first-child{text-align:left;color:#95a5a6;min-width:90px}
td.frost{background:rgba(192,57,43,.25);color:#ff6b6b;font-weight:bold}
td.zero-temp{background:rgba(243,156,18,.20);color:#f39c12}
td.warm-night{background:rgba(39,174,96,.20);color:#27ae60}
td.hot{color:#e74c3c;font-weight:bold}
td.fc,th.fc{background:rgba(52,152,219,.08);border-left:1px dashed #3498db}
th.fc-first{border-left:2px solid #3498db}
.weather-commentary{margin-top:14px}
.weather-commentary h3{font-size:1em;margin-bottom:8px;color:#79c0ff}
.weather-commentary ul{list-style:none;padding:0;margin:0}
.weather-commentary li{padding:5px 0;border-bottom:1px solid #30363d;font-size:.9em;color:#bdc3c7}
"""

def weather_ext_html(wext):
    """HTML расширенного блока погоды (Зоны A + B + D из ТЗ)."""
    if not wext:
        return ""
    days        = wext.get("days", [])
    flood_color = wext.get("flood_color", "#7f8c8d")
    flood_label = wext.get("flood_label", "—")
    flood_sum   = wext.get("flood_summary", "")
    commentary  = wext.get("commentary", [])
    snow_cm     = wext.get("snow_depth_cm", 0)

    # Зона A — паводковый индекс
    zone_a = (
        f'<div class="weather-flood-index" style="border-color:{flood_color}">'
        f'<span class="wfi-label">Паводковый индекс погоды ❄{snow_cm:.0f} см снега</span>'
        f'<span class="wfi-value" style="color:{flood_color}">{flood_label}</span>'
        f'<p class="wfi-summary">{flood_sum}</p>'
        f'</div>'
    )

    # Зона B — таблица 8 дней
    fc_start = next((i for i, d in enumerate(days) if d["is_forecast"]), len(days))

    def hcls(i):
        if i < fc_start: return ""
        return "fc-first" if i == fc_start else "fc"

    def tmax_cls(day):
        b = "fc" if day["is_forecast"] else ""
        h = " hot" if (day.get("tmax") or 0) >= 10 else ""
        return (b + h).strip()

    def tmin_cls(day):
        v = day.get("tmin")
        base = "frost" if (v or 0) < 0 else "zero-temp" if v == 0 else "warm-night"
        fc = " fc" if day["is_forecast"] else ""
        return base + fc

    def fmt_t(v):
        if v is None: return "—"
        return f"+{round(v)}" if v > 0 else str(round(v))

    ths  = "".join(f'<th class="{hcls(i)}">{d["date"][5:]}{"▸" if d["is_forecast"] else ""}</th>' for i,d in enumerate(days))
    r_tmax  = "".join(f'<td class="{tmax_cls(d)}">{fmt_t(d.get("tmax"))}</td>' for d in days)
    r_tmin  = "".join(f'<td class="{tmin_cls(d)}">{fmt_t(d.get("tmin"))}</td>' for d in days)
    r_prec  = "".join(f'<td class="{"fc" if d["is_forecast"] else ""}">{d.get("precip",0) or "—"}</td>' for d in days)
    r_snow  = "".join(
        f'<td class="{"fc" if d["is_forecast"] else ""}">{"—" if d["is_forecast"] else (str(d["snow_depth_cm"]) if d["snow_depth_cm"] > 0 else "0")}</td>'
        for d in days
    )
    r_wind  = "".join(f'<td class="{"fc" if d["is_forecast"] else ""}">{round(d["wind_ms"]) if d.get("wind_ms") is not None else "—"}</td>' for d in days)

    zone_b = (
        '<div style="overflow-x:auto"><table class="weather-table">'
        f'<thead><tr><th></th>{ths}</tr></thead>'
        '<tbody>'
        f'<tr><td>Tmax °C</td>{r_tmax}</tr>'
        f'<tr><td>Tmin °C</td>{r_tmin}</tr>'
        f'<tr><td>Осадки мм</td>{r_prec}</tr>'
        f'<tr><td>❄ Покров см</td>{r_snow}</tr>'
        f'<tr><td>Ветер м/с</td>{r_wind}</tr>'
        '</tbody></table></div>'
    )

    # Зона D — автокомментарии
    li_s   = "".join(f"<li>{c}</li>" for c in commentary)
    zone_d = (
        '<div class="weather-commentary">'
        '<h3>📊 Паводковый анализ погоды</h3>'
        f'<ul>{li_s}</ul>'
        '</div>'
    )

    return (
        '<div class="weather-ext-block">'
        '<h3>🌡 Погода — динамика и прогноз (8 дней)</h3>'
        f'{zone_a}{zone_b}{zone_d}'
        '</div>'
    )

# ─── HISTORY I/O ───────────────────────────────────────────────────────────────
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
    now    = datetime.now(timezone.utc)
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
                v = row.get(station,"")
                best = int(float(v)) if v and v != "—" else None
        except Exception:
            pass
    return best if best_diff < timedelta(hours=6) else None

# ─── ALERTS DEDUP ──────────────────────────────────────────────────────────────
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
    with open(ALERTS_FILE,"w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def should_send_alert(alerts, key, cooldown_h=6):
    ts = alerts.get(key)
    if not ts: return True
    return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > cooldown_h * 3600

# ─── 2024 REFERENCE ────────────────────────────────────────────────────────────
def load_2024_ref():
    if not os.path.exists(REF_2024): return {}
    try:
        with open(REF_2024) as f: return json.load(f)
    except Exception: return {}

def get_2024_value(ref, doy):
    return ref.get(str(doy)) or ref.get(f"{doy:03d}")

# ─── COMPUTE ANALYTICS ─────────────────────────────────────────────────────────
def compute_analytics(levels, history, weather):
    s  = levels.get("serpukhov"); o  = levels.get("orel")
    b  = levels.get("belev");     k  = levels.get("kaluga")
    ka = levels.get("kashira");   sh = levels.get("shukina")

    s24 = get_past_level(history,"serpukhov",24); s48 = get_past_level(history,"serpukhov",48)
    o24 = get_past_level(history,"orel",24);      k24 = get_past_level(history,"kaluga",24)

    ds24 = (s-s24)     if s is not None and s24 is not None else None
    ds48 = (s-s48)/2   if s is not None and s48 is not None else None
    do24 = (o-o24)     if o is not None and o24 is not None else None
    dk24 = (k-k24)     if k is not None and k24 is not None else None

    wave_msg = None
    if o is not None and do24 is not None:
        wave_msg = f"🌊 Орёл {o} {'↑' if do24>0 else '↓'}{round(do24)} → волна в Серпухов ~96ч"

    pb_days=pb_level=pb_date=None; po_level=po_date=None; pp_level=pp_date=None
    orel_decl  = do24 is not None and do24 < -5
    kaluga_decl= dk24 is not None and dk24 < -5
    serp_slow  = ds24 is not None and ds48 is not None and ds24 < ds48 and ds24 > 0

    if s is not None:
        if orel_decl and kaluga_decl:
            extra  = abs(dk24) / max(ds24 or 1, 1) if dk24 and ds24 else 3
            pb_days = round(min(max(extra,1),6),1)
        elif orel_decl: pb_days = 4.0
        elif serp_slow and s > 600:
            ratio = ds24/ds48 if ds48 else 1
            pb_days = round(min(1/(1-ratio+0.01) if ratio<1 else 5, 10), 1)
        if pb_days is not None:
            pb_level = round(s+(ds24 or 0)*pb_days)
            pb_date  = (datetime.now()+timedelta(days=pb_days)).strftime("%d.%m")
            po_level = round(s+(ds24 or 0)*0.5*pb_days*0.7)
            po_date  = (datetime.now()+timedelta(days=pb_days*0.7)).strftime("%d.%m")
            pp_level = round(s+(ds24 or 0)*1.2*pb_days*1.5)
            pp_date  = (datetime.now()+timedelta(days=pb_days*1.5)).strftime("%d.%m")

    days_to_945=date_to_945=None
    if s is not None and ds24 and ds24>0:
        days_to_945 = round((CRITICAL_LEVEL-s)/ds24,1)
        date_to_945 = (datetime.now()+timedelta(days=days_to_945)).strftime("%d.%m")
    elif s is not None and s>=CRITICAL_LEVEL:
        days_to_945 = 0

    danger_pct = 0
    if s is not None:
        base_pct  = min(s/CRITICAL_LEVEL*100,100)
        speed_pct = min(abs(ds24 or 0)/50*20,20) if ds24 and ds24>0 else 0
        danger_pct = round(min(base_pct+speed_pct,100),1)

    alert_level = "GREEN"
    if s is not None:
        if   s>=CRITICAL_LEVEL:   alert_level="CRITICAL"
        elif s>=PEAK_2024:         alert_level="RED"
        elif s>=PODTOP_LEVEL:      alert_level="ORANGE"
        elif s>=POYMA_LEVEL:       alert_level="YELLOW"
        elif ds24 and ds24>=40:    alert_level="RED"
        elif ds24 and ds24>=20:    alert_level="YELLOW"
    elif s is None:
        alert_level="UNKNOWN"

    insights = []
    t  = weather.get("temp") or weather.get("temp_max")
    pr = weather.get("precip_mm",0) or 0
    if t is not None and t>10 and pr>5: insights.append(f"🌧 Тепло +{t}°C + дождь {pr}мм — ускоренное таяние!")
    elif t is not None and t>8:          insights.append(f"☀️ Активное дневное таяние (+{t}°C)")
    elif t is not None and t<0:          insights.append(f"❄️ Мороз {t}°C — таяние заморожено")
    if ds24 and ds24>=40:  insights.append(f"🚨 Сверхбыстрый рост: +{round(ds24)} см/сут!")
    elif ds24 and ds24>=20: insights.append(f"⚡ Быстрый рост: +{round(ds24)} см/сут")
    if orel_decl and kaluga_decl: insights.append("📉 Орёл и Калуга падают — пик волны приближается к Серпухову")
    if wave_msg: insights.append(wave_msg)

    ref      = load_2024_ref()
    doy      = datetime.now().timetuple().tm_yday
    s2024    = get_2024_value(ref, doy)
    vs2024   = (s - int(s2024)) if s is not None and s2024 is not None else None

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

# ─── FORMAT HELPERS ────────────────────────────────────────────────────────────
def fmt_delta(d):
    if d is None: return ""
    return f"+{round(d)}" if d > 0 else str(round(d))

def trend(d):
    if d is None: return ""
    if d > 20: return "🔺"
    if d > 5:  return "↑"
    if d < -10: return "↓↓"
    if d < -2:  return "↓"
    return "→"

def dist(s, target, ds24):
    if s is None: return ""
    if s >= target: return "✅"
    rem = target - s
    if ds24 and ds24 > 0:
        days = round(rem / ds24, 1)
        dt   = (datetime.now()+timedelta(days=days)).strftime("%d.%m")
        return f"{rem}см → {days}дн. ({dt})"
    return f"{rem}см"

def wind_dir_str(deg):
    dirs = ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"]
    return dirs[int(deg/45+0.5) % 8]

ALERT_EMOJI = {"GREEN":"🟢","YELLOW":"🟡","ORANGE":"🟠","RED":"🔴","CRITICAL":"🆘","UNKNOWN":"⚪"}
ALERT_COLOR = {"GREEN":"#27ae60","YELLOW":"#f39c12","ORANGE":"#e67e22",
               "RED":"#c0392b","CRITICAL":"#8e0000","UNKNOWN":"#7f8c8d"}

# ─── FORMAT HEARTBEAT ──────────────────────────────────────────────────────────
def format_heartbeat(levels, analytics, weather):
    now  = datetime.now().strftime("%d.%m.%Y %H:%M")
    al   = analytics
    em   = ALERT_EMOJI.get(al.get("alert_level"),"⚪")
    ds24 = al.get("ds24")
    lines = [f"<b>HEARTBEAT {now}</b>", f"{em} {al.get('danger_pct',0):.0f}%", ""]
    for key in STATION_KEYS:
        v  = levels.get(key)
        nm = SLUG_NAMES.get(key, key)
        lag= SLUG_LAG.get(key, 0)
        lags = f"+{lag}ч" if lag > 0 else (f"{lag}ч" if lag < 0 else "")
        vs = f"{v}" if v is not None else "—"
        d24 = al.get("ds24") if key=="serpukhov" else al.get("do24") if key=="orel" else al.get("dk24") if key=="kaluga" else None
        mark = " ◀" if key=="serpukhov" else ""
        lines.append(f"{nm}{lags}: {vs} {trend(d24)}{fmt_delta(d24)}{mark}")
    if ds24 and ds24>0 and al.get("days_to_945"):
        lines.append(f"До 945: {dist(levels.get('serpukhov'),CRITICAL_LEVEL,ds24)}")
    if al.get("wave_msg"): lines.append(al["wave_msg"])
    t = weather.get("temp"); pr = weather.get("precip_mm",0) or 0; wm = weather.get("wind_ms")
    if t is not None: lines.append(f"🌡{t}°C | 💧{pr}мм | 💨{wm}м/с")
    lines.append("https://em-from-pu.github.io/oka-flood-monitor")
    return "\n".join(lines)

# ─── FORMAT DIGEST ─────────────────────────────────────────────────────────────
def format_digest(levels, analytics, weather, history, wext=None):
    now = datetime.now().strftime("%d.%m.%Y")
    al  = analytics; s=levels.get("serpukhov"); o=levels.get("orel"); b=levels.get("belev")
    k=levels.get("kaluga"); sh=levels.get("shukina"); ka=levels.get("kashira"); ko=levels.get("kolomna")
    ds24=al.get("ds24"); ds48=al.get("ds48"); do24=al.get("do24"); dk24=al.get("dk24")
    pb=al.get("peak_base_level"); pbd=al.get("peak_base_date"); pbdays=al.get("peak_base_days")
    po=al.get("peak_opt_level"); pod=al.get("peak_opt_date")
    pp=al.get("peak_pess_level"); ppd=al.get("peak_pess_date")
    vs2024=al.get("vs_2024"); s2024=al.get("serp_2024")
    em=ALERT_EMOJI.get(al.get("alert_level"),"⚪")
    dpct=al.get("danger_pct",0)

    fcast = ""
    if s is not None and s>=CRITICAL_LEVEL: fcast = f"🆘 Серпухов {s} — КРИТИЧЕСКИЙ УРОВЕНЬ!\n"
    elif al.get("days_to_945") and ds24 and ds24>0: fcast = f"До 945: {dist(s,CRITICAL_LEVEL,ds24)}\n"

    peak_b = ""
    if pb and pbd:
        peak_b = (f"\n🔺 Оптим.: {po or '?'} ({pod or '?'})"
                  f"\n🔸 Базов.: {pb} ({pbd}, ~{pbdays}дн.)"
                  f"\n🔻 Пессим.: {pp or '?'} ({ppd or '?'})")

    wave_t = f"\n{al['wave_msg']}" if al.get("wave_msg") else ""
    vs_t   = f"\nVS 2024: {s2024}→{s} ({'+'  if (vs2024 or 0)>=0 else ''}{vs2024})" if vs2024 is not None and s2024 is not None else ""

    ins_t  = "\n".join(f"• {i}" for i in al.get("insights",[])[:5])

    t=weather.get("temp"); pr=weather.get("precip_mm",0) or 0; wm=weather.get("wind_ms")
    wd=wind_dir_str(weather.get("wind_dir",0)); hm=weather.get("humidity")
    snowd=weather.get("snow_depth"); tmax=weather.get("temp_max"); tmin=weather.get("temp_min")
    wline=""
    if t is not None:
        wline = f"\n🌡{t}°C (min{tmin}/max{tmax}) | 💧{pr}мм | 💨{wm}м/с {wd} | 💦{hm}%"
        if snowd is not None: wline += f" | ❄{snowd}м снега"

    # Паводковый индекс погоды из wext
    wfl = ""
    if wext:
        wfl  = f"\n\n🌡 Паводковый индекс погоды: <b>{wext.get('flood_label','—')}</b>"
        wfl += f"\n{wext.get('flood_summary','')}"
        if wext.get("commentary"):
            wfl += "\n" + "\n".join(f"  {c}" for c in wext["commentary"][:2])

    return (
        f"<b>📊 Паводок Ока 2026</b>  {now}  {em} {dpct:.0f}%\n\n"
        f"🏔 Орёл (96ч): {o or '—'} {trend(do24)}{fmt_delta(do24)}\n"
        f"  Белёв (72ч): {b or '—'}\n"
        f"  Калуга (48ч): {k or '—'} {trend(dk24)}{fmt_delta(dk24)}\n"
        f"  Щукино (24ч): {sh or '—'}\n"
        f"<b>⭐ Серпухов: {s or '—'}</b> {trend(ds24)}{fmt_delta(ds24)} (48ч:{fmt_delta(ds48)}) {dpct:.0f}%\n"
        f"  Кашира (-12ч): {ka or '—'}\n"
        f"  Коломна (-24ч): {ko or '—'}\n\n"
        f"🎯 500: {dist(s,NORM_LEVEL,ds24)}\n"
        f"🎯 645: {dist(s,POYMA_LEVEL,ds24)}\n"
        f"🎯 800: {dist(s,PODTOP_LEVEL,ds24)}\n"
        f"🎯 920: {dist(s,PEAK_2024,ds24)}\n"
        f"🎯 945: {dist(s,CRITICAL_LEVEL,ds24)}\n\n"
        f"{fcast}{peak_b}{wave_t}{vs_t}"
        f"{wline}{wfl}\n\n"
        f"{ins_t}\n"
        "https://em-from-pu.github.io/oka-flood-monitor | fishingsib.ru"
    )

# ─── FORMAT GROUP DRAFT ─────────────────────────────────────────────────────────
def format_group_draft(levels, analytics):
    now  = datetime.now().strftime("%d.%m.%Y %H:%M")
    al   = analytics; s=levels.get("serpukhov","?"); o=levels.get("orel","?")
    k=levels.get("kaluga","?"); sh=levels.get("shukina","?"); ka=levels.get("kashira","?")
    ds24=al.get("ds24"); pb=al.get("peak_base_level"); pbd=al.get("peak_base_date")
    status=ALERT_EMOJI.get(al.get("alert_level"),"⚪")
    sign="+" if ds24 and ds24>0 else ""
    delta_txt=f"{sign}{round(ds24)}" if ds24 is not None else ""
    dist_txt=dist(s if isinstance(s,int) else None,CRITICAL_LEVEL,ds24)
    txt=(f"📊 Паводок Ока 2026 | {now}\nДанные 4 раза в сутки (08/12/17/20)\n\n"
         f"🔺 Орёл (3–4 сут.): {o}\n  Калуга (1–2 сут.): {k}\n  Щукино (~1 сут.): {sh}\n"
         f"<b>⭐ Серпухов: {s} {delta_txt} см/сут</b>\n  Кашира: {ka}\n\n"
         f"Пик 2024: 920 см | Критический: 945 см\nДо критического: {dist_txt}\n")
    if pb and pbd: txt += f"\nПрогноз пика: ~{pb} см ({pbd})"
    txt += f"\n\n{status}\nhttps://fishingsib.ru | ~60 гидропостов"
    return txt

# ─── KIM TRIGGERS ──────────────────────────────────────────────────────────────
def check_kim_triggers(levels, analytics, alerts):
    s=levels.get("serpukhov"); ds24=analytics.get("ds24")
    triggered=[]
    for thr in KIM_THRESHOLDS:
        key=f"KIM_{thr}"
        if s is not None and s>=thr and should_send_alert(alerts,key,cooldown_h=12):
            triggered.append((key,
                f"<b>🚨 ALERT: Серпухов {s}</b> ≥ {thr}\n"
                f"{KIM_EMOJI[thr]} {KIM_LABEL[thr]}\n"
                f"Δ24ч={fmt_delta(ds24)} | Опасность {analytics.get('danger_pct',0):.0f}%\n"
                f"До 945: {dist(s,CRITICAL_LEVEL,ds24)}"))
    if ds24 and ds24>=20:
        key="RATE_FAST"
        if should_send_alert(alerts,key,cooldown_h=6):
            triggered.append((key,f"⚡ <b>Быстрый рост</b> +{round(ds24)} см/сут | Серпухов {s}"))
    if ds24 and ds24>=40:
        key="RATE_STORM"
        if should_send_alert(alerts,key,cooldown_h=4):
            triggered.append((key,f"🆘 <b>ЭКСТРЕМАЛЬНЫЙ рост</b> +{round(ds24)} см/сут! | Серпухов {s}"))
    return triggered

# ─── TG SEND ───────────────────────────────────────────────────────────────────
def tg_send(chat_id, text, parse_mode="HTML"):
    if not TG_TOKEN:
        print(f"TG-skip {chat_id}: {text[:120].replace(chr(10),' ')}")
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":chat_id,"text":text,"parse_mode":parse_mode,"disable_web_page_preview":True},
            timeout=15)
        printf("TG→%s: %d", chat_id, r.status_code)
    except Exception as e:
        printf("TG err: %s", e)

# ─── GENERATE HTML ─────────────────────────────────────────────────────────────
def generate_html(levels, analytics, weather, history, wext=None):
    s=levels.get("serpukhov"); o=levels.get("orel"); b=levels.get("belev")
    k=levels.get("kaluga"); sh=levels.get("shukina"); ka=levels.get("kashira"); ko=levels.get("kolomna")
    al=analytics; now_str=datetime.now().strftime("%d.%m.%Y %H:%M")
    ds24=al.get("ds24"); pb_level=al.get("peak_base_level"); pb_date=al.get("peak_base_date")
    pb_days=al.get("peak_base_days"); po_level=al.get("peak_opt_level"); po_date=al.get("peak_opt_date")
    pp_level=al.get("peak_pess_level"); pp_date=al.get("peak_pess_date")
    danger_pct=al.get("danger_pct",0); vs2024=al.get("vs_2024"); s2024=al.get("serp_2024")
    alert_level=al.get("alert_level","UNKNOWN")
    alert_color=ALERT_COLOR.get(alert_level,"#7f8c8d")
    alert_em=ALERT_EMOJI.get(alert_level,"⚪")

    def lvl_card(name, val, delta, note, main=False):
        dstr=""
        if delta is not None:
            dstr=f'<div class="gauge-delta">{"+" if delta>0 else ""}{round(delta)}</div>'
        cls="gauge-card main" if main else "gauge-card"
        vh=str(val) if val is not None else '<span class="na">—</span>'
        return (f'<div class="{cls}"><div class="gauge-name">{name}</div>'
                f'<div class="gauge-level">{vh}</div>{dstr}'
                f'<div class="gauge-note">{note}</div></div>')

    gauges_html=(
        lvl_card("Орёл",     o, al.get("do24"),"96ч до Серп.")+
        lvl_card("Белёв",    b, None,"72ч")+
        lvl_card("Калуга",   k, al.get("dk24"),"48ч")+
        lvl_card("Щукино",   sh, None,"24ч")+
        lvl_card("Серпухов", s, ds24,"★ ключевой",main=True)+
        lvl_card("Кашира",   ka, None,"-12ч")+
        lvl_card("Коломна",  ko, None,"-24ч")
    )

    def ms_dist(target):
        if s is None: return ""
        if s>=target: return "✅"
        rem=target-s
        if ds24 and ds24>0:
            d=round(rem/ds24,1)
            dt=(datetime.now()+timedelta(days=d)).strftime("%d.%m")
            return f"{rem}см → {d}дн.({dt})"
        return f"{rem}см"

    thresh_rows="".join(
        f'<tr><td>{KIM_EMOJI[t]} {t}</td><td>{KIM_LABEL[t]}</td><td>{ms_dist(t)}</td></tr>'
        for t in KIM_THRESHOLDS)

    if pb_level:
        scen=(f'<div class="scenario-cards">'
              f'<div class="sc-card green"><div class="sc-title">🟢 Оптим.</div>'
              f'<div class="sc-level">{po_level or "?"}</div><div class="sc-date">{po_date or "?"}</div></div>'
              f'<div class="sc-card yellow"><div class="sc-title">🔸 Базов.</div>'
              f'<div class="sc-level">{pb_level}</div><div class="sc-date">{pb_date} (~{pb_days}дн.)</div></div>'
              f'<div class="sc-card red"><div class="sc-title">🔴 Пессим.</div>'
              f'<div class="sc-level">{pp_level or "?"}</div><div class="sc-date">{pp_date or "?"}</div></div>'
              f'</div>')
    else:
        scen='<div class="scenario-cards"><p>Прогноз пика строится по накопленной истории…</p></div>'

    t=weather.get("temp"); hm=weather.get("humidity"); wm=weather.get("wind_ms")
    wd=wind_dir_str(weather.get("wind_dir",0)); pr=weather.get("precip_mm",0) or 0
    tmax=weather.get("temp_max"); tmin=weather.get("temp_min"); snowd=weather.get("snow_depth")
    desc=weather.get("weather","")
    w_html=""
    if t is not None:
        w_html=(f'<div class="weather-block"><h3>🌡 Погода сейчас</h3>'
                f'<div class="weather-grid">'
                f'<div>{t}°C {desc}</div><div>min{tmin}/max{tmax}</div>'
                f'<div>💧{pr}мм</div><div>💨{wm}м/с {wd}</div><div>💦{hm}%</div>'
                f'{"<div>❄"+str(snowd)+" м</div>" if snowd else "<div></div>"}'
                f'</div></div>')

    wave_html=""
    if al.get("wave_msg"):
        wave_html=f'<div class="wave-block">{al["wave_msg"]}</div>'

    vs24_html=""
    if vs2024 is not None and s2024 is not None:
        sign="+" if vs2024>=0 else ""
        vs24_html=f'<div class="vs2024">VS 2024: {s2024} → сейчас {s} ({sign}{vs2024})</div>'

    # ← РАСШИРЕННЫЙ БЛОК ПОГОДЫ
    wext_html = weather_ext_html(wext)

    ins_html="".join(f"<li>{i}</li>" for i in al.get("insights",[])) or "<li>—</li>"
    pct=min(round(s/CRITICAL_LEVEL*100,1) if s else 0,100)

    t_rows=[]
    for row in sorted(history, key=lambda x:x.get("datetime",""), reverse=True)[:30]:
        def cv(key):
            v=row.get(key,"")
            if not v: return ""
            try:
                f=float(v); return str(round(f))
            except: return str(v)
        cl_map={"GREEN":"row-green","YELLOW":"row-yellow","ORANGE":"row-orange",
                "RED":"row-red","CRITICAL":"row-critical"}
        rcls=cl_map.get(row.get("alert_level",""),"")
        t_rows.append(
            f'<tr class="{rcls}"><td>{row.get("datetime","")[:16]}</td>'
            f'<td>{cv("orel")}</td><td>{cv("belev")}</td><td>{cv("kaluga")}</td>'
            f'<td>{cv("shukina")}</td><td><b>{cv("serpukhov")}</b></td>'
            f'<td>{cv("kashira")}</td><td>{cv("kolomna")}</td>'
            f'<td>{cv("delta_serp_24h")}</td><td>{cv("temp")}</td><td>{cv("precip_mm")}</td></tr>')
    t_rows_html="".join(t_rows) or "<tr><td colspan='11'>—</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ОКА Паводок 2026</title>
<style>
body{{font-family:Segoe UI,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0}}
h1{{background:{alert_color};color:#fff;margin:0;padding:20px 24px;font-size:1.6em}}
h3{{color:#79c0ff;margin:12px 0 6px}}
.container{{max-width:1100px;margin:0 auto;padding:16px}}
.meta{{color:#8b949e;font-size:.85em;margin-bottom:16px}}
.gauges{{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}}
.gauge-card{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;min-width:120px;text-align:center}}
.gauge-card.main{{border:2px solid {alert_color};background:#1c2128}}
.gauge-name{{font-size:.8em;color:#8b949e;margin-bottom:4px}}
.gauge-level{{font-size:2em;font-weight:700;color:#e6edf3}}
.gauge-delta{{font-size:.9em;color:#3fb950;margin-top:2px}}
.gauge-note{{font-size:.75em;color:#6e7681;margin-top:4px}}
.na{{color:#6e7681;font-size:.7em}}
.danger-bar{{height:10px;background:#21262d;border-radius:5px;margin:12px 0}}
.danger-fill{{height:10px;border-radius:5px;background:linear-gradient(90deg,#3fb950,#d29922,#db6d28,#f85149);width:{pct}%}}
table{{width:100%;border-collapse:collapse;font-size:.82em}}
th{{background:#161b22;color:#8b949e;padding:6px 8px;text-align:left}}
td{{padding:5px 8px;border-bottom:1px solid #21262d}}
.row-green td{{background:#0d2016}}.row-yellow td{{background:#2a1d00}}
.row-orange td{{background:#2a1400}}.row-red td{{background:#2d0000}}.row-critical td{{background:#1a0000}}
.thresh-table td:first-child{{font-size:1.1em}}
.scenario-cards{{display:flex;gap:12px;flex-wrap:wrap;margin:8px 0}}
.sc-card{{background:#161b22;border-radius:8px;padding:12px;min-width:120px;text-align:center}}
.sc-card.green{{border-left:3px solid #3fb950}}.sc-card.yellow{{border-left:3px solid #d29922}}.sc-card.red{{border-left:3px solid #f85149}}
.sc-title{{font-size:.8em;color:#8b949e}}.sc-level{{font-size:1.6em;font-weight:700}}.sc-date{{font-size:.8em;color:#6e7681}}
.weather-block,.wave-block,.vs2024{{background:#161b22;border-radius:8px;padding:12px 16px;margin:12px 0}}
.weather-grid{{display:flex;flex-wrap:wrap;gap:12px 24px;font-size:.9em}}
.wave-block{{border-left:3px solid #388bfd;color:#79c0ff}}
.vs2024{{border-left:3px solid #d29922;color:#e3b341}}
a{{color:#388bfd}}
footer{{color:#6e7681;font-size:.8em;text-align:center;padding:20px}}
{WEATHER_EXT_CSS}
</style>
</head>
<body>
<h1>ОКА Паводок 2026 &nbsp;{alert_em}&nbsp;{s if s is not None else '—'}&nbsp; {danger_pct:.0f}%</h1>
<div class="container">
<p class="meta">{now_str} | fishingsib.ru</p>
<div class="danger-bar"><div class="danger-fill"></div></div>
<h3>7 гидропостов</h3>
<div class="gauges">{gauges_html}</div>
{wext_html}
{w_html}{wave_html}{vs24_html}
<h3>KIM-пороги</h3>
<table class="thresh-table">
<tr><th>Уровень</th><th>Статус</th><th>До порога</th></tr>{thresh_rows}</table>
<h3>Сценарии пика</h3>{scen}
<h3>Insights</h3><ul>{ins_html}</ul>
<p>Δ24ч Серп: {fmt_delta(ds24)} | Δ48ч: {fmt_delta(al.get('ds48'))} | Δ24ч Орёл: {fmt_delta(al.get('do24'))} | Δ24ч Калуга: {fmt_delta(al.get('dk24'))}</p>
{f'<p>До 945: {dist(s,CRITICAL_LEVEL,ds24)}</p>' if ds24 and ds24>0 else ''}
<h3>История (30 замеров)</h3>
<div style="overflow-x:auto"><table>
<tr><th>Время</th><th>Орёл</th><th>Белёв</th><th>Калуга</th><th>Щукино</th>
<th>Серпухов</th><th>Кашира</th><th>Коломна</th><th>Δ24ч</th><th>T°C</th><th>Осадки</th></tr>
{t_rows_html}</table></div>
<footer>OkaFloodMonitor v4.3 | 54.834050, 37.742901 |
<a href="https://fishingsib.ru">fishingsib.ru</a> |
<a href="https://em-from-pu.github.io/oka-flood-monitor">GitHub Pages</a>
</footer></div></body></html>"""

# ─── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DOCS_DIR, exist_ok=True)

    levels  = fetch_all_levels()
    weather = fetch_weather()
    wext    = fetch_weather_extended()        # ← НОВЫЙ БЛОК
    history = load_history()
    alerts  = load_alerts()

    analytics = compute_analytics(levels, history, weather)
    printf("alert=%s, ds24=%s, days945=%s, danger=%.1f%%",
           analytics.get("alert_level"), analytics.get("ds24"),
           analytics.get("days_to_945"), analytics.get("danger_pct",0))

    # История
    now_iso = datetime.now(timezone.utc).isoformat()
    row = {
        "datetime":now_iso,"orel":levels.get("orel",""),"belev":levels.get("belev",""),
        "kaluga":levels.get("kaluga",""),"shukina":levels.get("shukina",""),
        "serpukhov":levels.get("serpukhov",""),"kashira":levels.get("kashira",""),
        "kolomna":levels.get("kolomna",""),
        "delta_serp_24h":analytics.get("ds24",""),"delta_serp_48h":analytics.get("ds48",""),
        "delta_orel_24h":analytics.get("do24",""),"delta_kaluga_24h":analytics.get("dk24",""),
        "temp":weather.get("temp",""),"humidity":weather.get("humidity",""),
        "wind_ms":weather.get("wind_ms",""),"wind_dir":weather.get("wind_dir",""),
        "clouds":weather.get("clouds",""),"precip_mm":weather.get("precip_mm",""),
        "alert_level":analytics.get("alert_level",""),
        "forecast_days_to_945":analytics.get("days_to_945",""),
        "forecast_days_to_peak":analytics.get("peak_base_days",""),
        "scenario_base_peak":analytics.get("peak_base_level",""),
        "scenario_base_date":analytics.get("peak_base_date",""),
        "notes":"",
        "snow_depth_cm":  wext.get("snow_depth_cm","") if wext else "",
        "flood_weather_index": wext.get("flood_index","") if wext else "",
    }
    history.append(row)
    save_history(history)

    # Heartbeat
    heartbeat = format_heartbeat(levels, analytics, weather)
    print(heartbeat[:200]+"…")
    tg_send(CHAT_ADMIN, heartbeat)

    # Digest
    digest = format_digest(levels, analytics, weather, history, wext=wext)
    print(digest[:200]+"…")
    tg_send(CHAT_ADMIN, digest)

    # T4 → группа
    sv = levels.get("serpukhov")
    if sv is not None and sv >= POYMA_LEVEL or analytics.get("alert_level") in ("ORANGE","RED","CRITICAL"):
        printf("T4 → группа")
        tg_send(CHAT_GROUP, digest)

    # KIM
    triggered = check_kim_triggers(levels, analytics, alerts)
    for key,text in triggered:
        printf("KIM: %s", key)
        tg_send(CHAT_ADMIN, text)
        if any(str(t) in key for t in (645,800,920,945,965)):
            tg_send(CHAT_GROUP, text)
        alerts[key] = datetime.now().isoformat()
    if triggered:
        save_alerts(alerts)

    # Watchdog
    if sv is None:
        key="WATCHDOG_SERP"
        if should_send_alert(alerts,key,cooldown_h=6):
            tg_send(CHAT_ADMIN,"⚠️ <b>WATCHDOG</b>: нет данных Серпухова! Проверить fishingsib.ru")
            alerts[key]=datetime.now().isoformat()
            save_alerts(alerts)

    # HTML + JSON
    html = generate_html(levels, analytics, weather, history, wext=wext)
    with open(INDEX_HTML,"w",encoding="utf-8") as f: f.write(html)
    printf("HTML → %s", INDEX_HTML)

    data_out = {
        "updated":now_iso,"levels":levels,
        "analytics":{k:analytics.get(k) for k in (
            "ds24","ds48","alert_level","days_to_945","date_to_945",
            "peak_base_level","peak_base_date","danger_pct","wave_msg","insights")},
        "weather":weather,
        "weather_ext":{k:wext.get(k) for k in ("flood_index","flood_label","flood_summary","snow_depth_cm","commentary")} if wext else None,
    }
    with open(DATA_JSON,"w",encoding="utf-8") as f: json.dump(data_out,f,ensure_ascii=False,indent=2)
    printf("JSON → %s", DATA_JSON)

    with open(GROUP_DRAFT,"w",encoding="utf-8") as f: f.write(format_group_draft(levels,analytics))
    printf("Group draft → %s", GROUP_DRAFT)

    with open(STATUS_FILE,"w",encoding="utf-8") as f:
        f.write(f"{analytics.get('alert_level')}, {sv or '—'}, {now_iso}")
    printf("Status → %s", STATUS_FILE)

if __name__ == "__main__":
    main()
