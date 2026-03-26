# okamonitor.py v4.3 — 26.03.2026
# Fixes: B1 B2 B3 B4 + warning-сигнал приближения
import re, json, os, time, datetime, requests
from fetch_module import fetch_level, fetch_snow_cover, STATIONS

VERSION = "4.3"
MODE    = os.environ.get("OKA_MODE", "full")

TG_TOKEN       = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN     = int(os.environ.get("TG_CHAT_ID",    "49747475"))
CHAT_MY_GROUP  = int(os.environ.get("TG_GROUP_ID",   "-5234360275"))
CHAT_NEIGHBORS = int(os.environ.get("TG_NEIGHBORS_ID", "-1001672586477"))
SEND_TG        = bool(TG_TOKEN)

HISTORY_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history.json")
WARNING_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "warning_sent.json")

# KIM-пороги для Серпухова
KIM = [300, 500, 645, 800, 920, 945, 965]
KIM_EMOJI = {300:"🟡", 500:"🟠", 645:"🔴", 800:"🆘", 920:"💀", 945:"⚫", 965:"⛔"}
KIM_LABEL = {
    300: "T0 Внимание — приближение",
    500: "T1 Опасный уровень",
    645: "T2 Критический",
    800: "T3 Очень опасный",
    920: "T4 Уровень 2024",
    945: "T5 ДОМ ПОД УГРОЗОЙ",
    965: "T6 Подвал затоплен",
}
WARN_THRESHOLDS = [300, 400, 450]  # сигналы приближения
ALERT_THRESHOLDS = [500, 645, 800, 920, 945, 965]  # полные алерты

KEY_BY_SLUG = {
    "oka-orel":     "orel",
    "oka-belev":    "belev",
    "oka-kaluga":   "kaluga",
    "oka-shukina":  "shukina",
    "oka-serpuhov": "serpukhov",
    "oka-kashira":  "kashira",
    "oka-kolomna":  "kolomna",
}

# ─── TG ──────────────────────────────────────────────────────────────────────
def tg_send(chat_id, text, silent=False):
    if not SEND_TG:
        tag = f"[TG-skip {chat_id}]"
        print(f"{tag} {text[:120].replace(chr(10),' ')}")
        return True
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_notification": silent},
            timeout=15,
        )
        print(f"  TG→{chat_id}: {r.status_code}")
        if r.status_code == 400:
            err = r.json().get("description","")
            print(f"  TG error: {err}")
        return r.status_code == 200
    except Exception as e:
        print(f"  TG err {chat_id}: {e}")
        return False

def tg_send_all(text, include_neighbors=False, silent=False):
    tg_send(CHAT_ADMIN, text, silent)
    tg_send(CHAT_MY_GROUP, text, silent)
    if include_neighbors:
        tg_send(CHAT_NEIGHBORS, text, silent)

# ─── ДАННЫЕ ──────────────────────────────────────────────────────────────────
def fetch_all_levels():
    print(f"[OkaMonitor v{VERSION}] Парсим уровни воды ({len(STATIONS)} постов fishingsib)...")
    levels = {}
    for s in STATIONS:
        url = "https://allrivers.info/gauge/" + s["slug"]
        key = KEY_BY_SLUG.get(s["slug"], s["slug"])
        val = fetch_level(url, s["name"])
        levels[key] = val
        print(f"  {s['name']}: {val} см")
    print(f"  Уровни: {levels}")
    return levels

def load_history():
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return []

def save_history(history, levels):
    now = datetime.datetime.now()
    date_key = now.strftime("%Y-%m-%d")
    entry = {"ts": now.strftime("%Y-%m-%d %H:%M"), "date": date_key, "levels": levels}
    history = [h for h in history if h.get("date") != date_key][-29:]
    history.append(entry)
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  history save err:", e)
    return history

def load_warning_state():
    try:
        if os.path.exists(WARNING_FILE):
            with open(WARNING_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_warning_state(state):
    try:
        os.makedirs(os.path.dirname(WARNING_FILE), exist_ok=True)
        with open(WARNING_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("  warning state err:", e)

# ─── ВЫЧИСЛЕНИЯ ──────────────────────────────────────────────────────────────
def get_deltas(history, key):
    vals = [(h["date"], h["levels"].get(key)) for h in history if h["levels"].get(key) is not None]
    d24 = vals[-1][1] - vals[-2][1] if len(vals) >= 2 else None
    d48 = vals[-1][1] - vals[-3][1] if len(vals) >= 3 else None
    return d24, d48

def trend_arrow(d):
    if d is None: return "→"
    if d > 3:  return "↑"
    if d < -3: return "↓"
    return "→"

def danger_pct(level):
    """% от порога T1=500 (опасного уровня). Не может быть отрицательным."""
    if level is None: return None
    return round(max(0.0, min(100.0, level / 500.0 * 100.0)), 1)

def kim_label_current(level):
    if level is None: return "н/д", 0
    active = [k for k in KIM if level >= k]
    if not active: return "Норма", 0
    cur = max(active)
    return KIM_LABEL[cur], cur

def days_to(level, delta24, target):
    if level is None or delta24 is None or delta24 <= 0: return None
    remaining = target - level
    if remaining <= 0: return 0
    return round(remaining / delta24, 1)

def fmt_level(v, key, history):
    d24, _ = get_deltas(history, key)
    arrow  = trend_arrow(d24)
    d24s   = (f"+{d24}" if d24 and d24 > 0 else str(d24)) if d24 is not None else "н/д"
    vs     = f"{v} см" if v is not None else "н/д"
    return f"{vs} {arrow} ({d24s}/сут)"

# ─── ПОГОДА ──────────────────────────────────────────────────────────────────
def fetch_weather():
    print("Парсим погоду (Серпухов)...")
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": 54.834050, "longitude": 37.742901,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,snow_depth_max",
                "current_weather": True,
                "timezone": "Europe/Moscow", "forecast_days": 3,
            }, timeout=15)
        if r.status_code == 200:
            d = r.json()
            daily = d.get("daily", {})
            ds = (daily.get("temperature_2m_max") or [None])[0]
            dn = (daily.get("temperature_2m_min") or [None])[0]
            precip = (daily.get("precipitation_sum") or [None])[0]
            snow   = (daily.get("snow_depth_max") or [None])[0]
            alert  = "WARM" if (ds is not None and ds >= 10) else "GREEN"
            print(f"  alert={alert}, ds24={ds}")
            return {"alert": alert, "temp_day": ds, "temp_night": dn,
                    "precip": precip, "snow": snow}
    except Exception as e:
        print("  weather err:", e)
    return {"alert": "UNKNOWN", "temp_day": None, "temp_night": None,
            "precip": None, "snow": None}

# ─── ФОРМАТИРОВАНИЕ ──────────────────────────────────────────────────────────
def build_heartbeat(levels, history, weather):
    now   = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    serp  = levels.get("serpukhov")
    label, code = kim_label_current(serp)
    emoji = KIM_EMOJI.get(code, "🟢") if code else "🟢"
    dpct  = danger_pct(serp)
    dpct_s = f"{dpct}%" if dpct is not None else "н/д"

    lines = [f"🕐 <b>HEARTBEAT {now} МСК</b>",
             f"Статус: {emoji} {label} | Опасность: {dpct_s}", ""]
    for s in STATIONS:
        key  = KEY_BY_SLUG.get(s["slug"], s["slug"])
        lag  = s["lag_h"]
        lag_s = f"−{abs(lag)}ч" if lag < 0 else (f"+{lag}ч" if lag > 0 else "0")
        lines.append(f"  {s['name']} [{lag_s}]: {fmt_level(levels.get(key), key, history)}")
    if weather.get("temp_day") is not None:
        lines.append(f"\n🌡 Серпухов: {weather['temp_day']}°/{weather['temp_night']}° | "
                     f"осадки: {weather.get('precip',0)} мм")
    return "\n".join(lines)

def build_digest_neighbors(levels, history, weather):
    """Краткий дайджест для соседей — без heartbeat-шума."""
    now  = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    serp = levels.get("serpukhov")
    label, code = kim_label_current(serp)
    emoji = KIM_EMOJI.get(code, "🟢") if code else "🟢"
    dpct  = danger_pct(serp)
    dpct_s = f"{dpct}%" if dpct is not None else "н/д"
    serp_d24, serp_d48 = get_deltas(history, "serpukhov")

    lines = [
        f"🌊 <b>ОКА ПАВОДОК 2026 — ДАЙДЖЕСТ</b>",
        f"📅 {now} МСК | {emoji} Опасность: {dpct_s}",
        "",
        "━━━ УРОВНИ ВОДЫ ━━━━━━━━━━━━━━━━",
    ]
    for s in STATIONS:
        key  = KEY_BY_SLUG.get(s["slug"], s["slug"])
        v    = levels.get(key)
        d24, d48 = get_deltas(history, key)
        arrow = trend_arrow(d24)
        d24s  = (f"+{d24}" if d24 and d24>0 else str(d24)) if d24 is not None else "н/д"
        vs    = f"{v} см" if v is not None else "н/д"
        lines.append(f"📍 {s['name']} (лаг {s['lag_h']}ч): {vs} {arrow} | Δ24ч: {d24s}")

    lines.append("")
    lines.append("━━━ СЕРПУХОВ — ДО ПОРОГОВ ━━━━━━━━")
    if serp is not None:
        for thr in ALERT_THRESHOLDS:
            if serp < thr:
                d = days_to(serp, serp_d24, thr)
                d_s = f"~{d} дн" if d else "н/д (уровень падает)"
                lines.append(f"  {KIM_EMOJI.get(thr,'')} {thr} см ({KIM_LABEL[thr]}): "
                              f"ещё {thr-serp} см ({d_s})")
    else:
        lines.append("  Данные недоступны")

    lines.append("")
    if weather.get("temp_day") is not None:
        lines.append("━━━ ПОГОДА (Серпухов) ━━━━━━━━━━━━")
        lines.append(f"  🌡 {weather['temp_day']}°/{weather['temp_night']}° | "
                     f"💧 {weather.get('precip',0)} мм")
        if weather.get("snow") is not None:
            lines.append(f"  ❄️ Снег: {weather['snow']} м")

    lines.append("")
    lines.append("📊 Данные: fishingsib.ru | open-meteo.com")
    lines.append("🌐 https://em-from-pu.github.io/oka-flood-monitor")
    return "\n".join(lines)

def build_warning(level, threshold, d24, station="Серпухов"):
    """Сигнал приближения — ещё не алерт, но надо знать."""
    emoji  = KIM_EMOJI.get(threshold, "⚠️")
    label  = KIM_LABEL.get(threshold, "")
    days_s = f"~{days_to(level, d24, threshold)} дн" if d24 and d24 > 0 else "темп нарастания неизвестна"
    return (
        f"⚠️ <b>ВНИМАНИЕ: Приближение к порогу!</b>\n\n"
        f"📍 {station}: {level} см\n"
        f"Следующий порог: {emoji} {threshold} см ({label})\n"
        f"Осталось: {threshold - level} см\n"
        f"Прогноз: {days_s}\n\n"
        f"Данные обновляются каждый час."
    )

def build_alert(level, threshold, d24, station="Серпухов"):
    """Полный алерт при достижении порога."""
    emoji = KIM_EMOJI.get(threshold, "🚨")
    label = KIM_LABEL.get(threshold, "")
    now   = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    return (
        f"🚨 <b>АЛЕРТ! ПОРОГ ДОСТИГНУТ!</b>\n\n"
        f"📍 {station}: {level} см\n"
        f"Порог: {emoji} {threshold} см\n"
        f"Уровень: <b>{label}</b>\n"
        f"Время: {now} МСК\n\n"
        f"Скорость подъёма: "
        f"{(f'+{d24} см/сут' if d24 else 'н/д')}\n\n"
        f"🌐 https://em-from-pu.github.io/oka-flood-monitor"
    )

# ─── ЛОГИКА АЛЕРТОВ ──────────────────────────────────────────────────────────
def check_and_send_alerts(levels, history):
    serp  = levels.get("serpukhov")
    if serp is None:
        return
    d24, _ = get_deltas(history, "serpukhov")
    state   = load_warning_state()
    today   = datetime.datetime.now().strftime("%Y-%m-%d")

    # Сигналы приближения (только один раз в день на каждый порог)
    for thr in WARN_THRESHOLDS:
        key = f"warn_{thr}"
        last = state.get(key)
        # Шлём если: уровень в диапазоне [thr-50, thr) И сегодня ещё не слали
        if (thr - 50) <= serp < thr and last != today:
            msg = build_warning(serp, thr, d24)
            print(f"  ⚠️ Warning → {thr} см")
            tg_send_all(msg, include_neighbors=True)
            state[key] = today

    # Полные алерты при достижении порогов (один раз на каждый порог)
    for thr in ALERT_THRESHOLDS:
        key = f"alert_{thr}"
        last = state.get(key)
        if serp >= thr and last != today:
            msg = build_alert(serp, thr, d24)
            print(f"  🚨 Alert → {thr} см")
            tg_send_all(msg, include_neighbors=True)
            state[key] = today

    save_warning_state(state)

# ─── РАСПИСАНИЕ ──────────────────────────────────────────────────────────────
def is_digest_time():
    """Шлём дайджест соседям в 08:00 и 20:00 (±30 мин)."""
    h = datetime.datetime.now().hour
    m = datetime.datetime.now().minute
    return (h == 8 and m <= 30) or (h == 20 and m <= 30)

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    levels  = fetch_all_levels()
    weather = fetch_weather()
    history = load_history()
    history = save_history(history, levels)

    # 1. Heartbeat + полный дайджест → личка + моя группа (каждый час)
    heartbeat = build_heartbeat(levels, history, weather)
    print("Отправляем heartbeat...")
    tg_send(CHAT_ADMIN, heartbeat)
    tg_send(CHAT_MY_GROUP, heartbeat)

    # 2. Дайджест соседям → только в 08:00 и 20:00
    if is_digest_time():
        digest = build_digest_neighbors(levels, history, weather)
        print("Отправляем дайджест соседям (время 08/20)...")
        tg_send(CHAT_NEIGHBORS, digest)
    else:
        print(f"  Дайджест соседям: не время (час={datetime.datetime.now().hour})")

    # 3. Алерты и сигналы приближения → все группы при срабатывании
    check_and_send_alerts(levels, history)

if __name__ == "__main__":
    main()
