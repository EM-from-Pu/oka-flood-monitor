#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# oka_monitor.py v3.0 — Полный мониторинг Оки
import os, json, csv, requests
from datetime import datetime, timedelta, timezone

TG_TOKEN   = os.environ.get("TG_TOKEN", "")
CHAT_ADMIN = os.environ.get("TG_CHAT_ID", "49747475")
CHAT_GROUP = os.environ.get("TG_GROUP_ID", "-5234360275")
OWM_KEY    = os.environ.get("WEATHER_API_KEY", "")

SERPUKHOV_LAT, SERPUKHOV_LON = 54.834050, 37.742901
CRITICAL_LEVEL = 945
PEAK_2024      = 920
POYMA_LEVEL    = 645
PODTOP_LEVEL   = 800

HISTORY_FILE = "docs/history.csv"
DATA_JSON    = "docs/data.json"
INDEX_HTML   = "docs/index.html"
GROUP_DRAFT  = "docs/group_draft.txt"
STATUS_FILE  = "docs/status.txt"
ALERTS_FILE  = "docs/alerts_sent.json"

GAUGES = {
    "orel":      "https://allrivers.info/gauge/oka-orel",
    "aleksin":   "https://allrivers.info/gauge/oka-shukina",
    "kaluga":    "https://allrivers.info/gauge/oka-kaluga",
    "serpukhov": "https://allrivers.info/gauge/oka-serpuhov",
    "kashira":   "https://allrivers.info/gauge/oka-kashira",
}

HISTORY_COLS = [
    "datetime","orel","aleksin","kaluga","serpukhov","kashira",
    "delta_serp_24h","delta_serp_48h","delta_orel_24h","delta_kaluga_24h",
    "temp","humidity","wind_ms","wind_dir","clouds","precip_mm",
    "alert_level","forecast_days_to_945","forecast_days_to_peak",
    "scenario_base_peak","scenario_base_date","notes"
]

def fetch_level(url):
    try:
        import re
        h = {"User-Agent": "Mozilla/5.0 OkaFloodMonitor/3.0"}
        r = requests.get(url + "/waterlevel/", headers=h, timeout=15)
        r.raise_for_status()
        for p in [r'"water_level"\s*:\s*(\d+)', r'(\d{3,4})\s*см']:
            m = re.search(p, r.text, re.IGNORECASE)
            if m:
                v = int(m.group(1))
                if 50 < v < 1500: return v
        return None
    except Exception as e:
        print(f"[fetch_level] {url}: {e}"); return None

def fetch_all_levels():
    levels = {}
    for name, url in GAUGES.items():
        levels[name] = fetch_level(url)
        print(f"  {name}: {levels[name]}")
    return levels

def fetch_weather():
    if not OWM_KEY: return {}
    try:
        url = (f"https://api.openweathermap.org/data/2.5/weather"
               f"?lat={SERPUKHOV_LAT}&lon={SERPUKHOV_LON}"
               f"&appid={OWM_KEY}&units=metric&lang=ru")
        d = requests.get(url, timeout=10).json()
        return {
            "temp":      round(d["main"]["temp"], 1),
            "humidity":  d["main"]["humidity"],
            "wind_ms":   round(d["wind"]["speed"], 1),
            "wind_dir":  d["wind"].get("deg", 0),
            "clouds":    d["clouds"]["all"],
            "precip_mm": round(d.get("rain",{}).get("1h",0)+d.get("snow",{}).get("1h",0),1),
            "weather":   d["weather"][0]["description"],
        }
    except Exception as e:
        print(f"[fetch_weather] {e}"); return {}

def wind_dir_str(deg):
    return ["С","СВ","В","ЮВ","Ю","ЮЗ","З","СЗ"][int((deg+22.5)/45)%8]

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    with open(HISTORY_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_history(rows):
    os.makedirs("docs", exist_ok=True)
    with open(HISTORY_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLS, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def get_past_level(history, station, hours_ago):
    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=hours_ago)
    best, best_diff = None, timedelta(days=999)
    for row in history:
        try:
            dt = datetime.fromisoformat(row["datetime"])
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            diff = abs(dt - target)
            if diff < best_diff:
                best_diff = diff
                v = row.get(station,"")
                best = int(v) if v and v != "" else None
        except: pass
    return best if best_diff < timedelta(hours=6) else None

def compute_analytics(levels, history, weather):
    s  = levels.get("serpukhov")
    o  = levels.get("orel")
    k  = levels.get("kaluga")
    ka = levels.get("kashira")

    s24 = get_past_level(history,"serpukhov",24)
    s48 = get_past_level(history,"serpukhov",48)
    o24 = get_past_level(history,"orel",24)
    k24 = get_past_level(history,"kaluga",24)

    ds24 = (s-s24) if s and s24 else None
    ds48 = ((s-s48)/2) if s and s48 else None
    do24 = (o-o24) if o and o24 else None
    dk24 = (k-k24) if k and k24 else None

    # Прогноз до 945
    days_to_945 = date_to_945 = None
    if s and ds24 and ds24 > 0:
        days_to_945 = round((CRITICAL_LEVEL-s)/ds24, 1)
        date_to_945 = (datetime.now()+timedelta(days=days_to_945)).strftime("%d.%m")
    elif s and s >= CRITICAL_LEVEL:
        days_to_945 = 0

    # Прогноз пика
    orel_declining   = (do24 is not None and do24 < -5)
    kaluga_declining = (dk24 is not None and dk24 < -5)
    serp_slowing     = (ds24 is not None and ds48 is not None and ds24<ds48 and ds24>0)

    pb_days = pb_level = pb_date = None
    po_level = po_date = pp_level = pp_date = None

    if s:
        if orel_declining and kaluga_declining:
            extra = abs(dk24)/max(ds24 or 1,1) if dk24 and ds24 else 3
            pb_days = round(min(max(extra,1),6),1)
        elif orel_declining:
            pb_days = 4.0
        elif serp_slowing and s > 600:
            ratio = (ds24/ds48) if ds48 else 1
            pb_days = round(min(1/(1-ratio+0.01) if ratio<1 else 5, 10),1)

        if pb_days is not None:
            pb_level = round(s + (ds24 or 0)*pb_days)
            pb_date  = (datetime.now()+timedelta(days=pb_days)).strftime("%d.%m")
            if ds24:
                opt_days  = pb_days*0.7
                pess_days = pb_days*1.5
                po_level  = round(s+(ds24*0.5)*opt_days)
                po_date   = (datetime.now()+timedelta(days=opt_days)).strftime("%d.%m")
                pp_level  = round(s+(ds24*1.2)*pess_days)
                pp_date   = (datetime.now()+timedelta(days=pess_days)).strftime("%d.%m")

    # Уровень тревоги
    if s is None: al = "UNKNOWN"
    elif s >= CRITICAL_LEVEL: al = "CRITICAL"
    elif s >= PEAK_2024: al = "RED"
    elif s >= PODTOP_LEVEL: al = "ORANGE"
    elif s >= POYMA_LEVEL: al = "YELLOW"
    else: al = "GREEN"

    # Инсайты (if-то)
    insights = []
    if ds24 is not None:
        if ds24>=40: insights.append(f"🚨 ЭКСТРЕННЫЙ ТЕМП: +{ds24} см/сут у Серпухова!")
        elif ds24>=20: insights.append(f"⚡️ Высокий темп роста: +{ds24} см/сут у Серпухова")
        elif ds24>0: insights.append(f"📈 Серпухов растёт: +{ds24} см/сут")
        elif ds24<-10: insights.append(f"📉 Серпухов снижается: {ds24} см/сут — пик пройден?")
        elif abs(ds24)<=3: insights.append("➡️ Серпухов стабилен")
    if do24 is not None and ds24 is not None:
        if do24>=30 and ds24<15:
            insights.append(f"🔔 Орёл: +{do24} см/сут — волна придёт через ~3-4 суток")
        if do24<-5 and ds24>0:
            insights.append(f"⏳ Орёл разворачивается — у нас пик близко")
    if dk24 is not None and ds24 is not None:
        if dk24>=20 and ds24<10:
            insights.append(f"⏰ Калуга: +{dk24} см/сут — рост у нас через ~48-72 ч")
        if dk24<-5 and ds24>0:
            insights.append(f"📊 Калуга снижается — у нас пик через 1-3 дня")
    if ds24 is not None and ds48 is not None:
        if ds24>ds48*1.3 and ds24>5:
            insights.append(f"📈 Темп ускоряется: +{round(ds48)}→+{round(ds24)} см/сут")
        if ds24<ds48*0.7 and ds48>5:
            insights.append(f"📉 Темп замедляется: +{round(ds48)}→+{round(ds24)} см/сут")
    if s and ka and ka<s-50:
        insights.append(f"⚠️ Кашира ({ka} см) << Серпухов ({s} см) — сток замедлен")
    if s and s>800:
        diff = PEAK_2024-s
        if diff>0: insights.append(f"📊 До пика 2024 ({PEAK_2024} см): ещё {diff} см")
        else: insights.append(f"🔴 Превышен уровень пика 2024 на {abs(diff)} см!")
    t = weather.get("temp")
    if t is not None:
        pr = weather.get("precip_mm",0)
        if t>10 and pr>5: insights.append(f"🌧️ Тепло +{t}°C + осадки {pr} мм — ускорение таяния!")
        elif t>8: insights.append(f"☀️ Тепло +{t}°C — активное снеготаяние")
        elif t<0: insights.append(f"❄️ Морозы {t}°C — снеготаяние приостановлено")

    return dict(
        ds24=ds24, ds48=ds48, do24=do24, dk24=dk24,
        days_to_945=days_to_945, date_to_945=date_to_945,
        peak_base_days=pb_days, peak_base_level=pb_level,
        peak_base_date=pb_date,
        peak_opt_level=po_level, peak_opt_date=po_date,
        peak_pess_level=pp_level, peak_pess_date=pp_date,
        alert_level=al, insights=insights,
        orel_declining=orel_declining,
        kaluga_declining=kaluga_declining,
        serp_slowing=serp_slowing,
    )

def tg_send(chat_id, text, parse_mode="HTML"):
    if not TG_TOKEN: print(f"[TG] skip: {text[:60]}"); return
    try:
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id":chat_id,"text":text,"parse_mode":parse_mode,
                  "disable_web_page_preview":True}, timeout=15)
        r.raise_for_status()
    except Exception as e: print(f"[TG] Error: {e}")

def fmt_delta(d):
    if d is None: return "н/д"
    return f"{'+'if d>0 else ''}{round(d)} см"

def trend_icon(d):
    if d is None: return "➡️"
    if d>=20: return "🔺🔺"
    if d>=5:  return "📈"
    if d<=-10: return "📉"
    if d<=-2: return "🔻"
    return "➡️"

def format_digest(levels, analytics, weather, history):
    now = datetime.now().strftime("%d.%m.%Y")
    s=levels.get("serpukhov","н/д"); o=levels.get("orel","н/д")
    k=levels.get("kaluga","н/д"); ka=levels.get("kashira","н/д")
    al=analytics
    ds24=al.get("ds24"); ds48=al.get("ds48"); do24=al.get("do24"); dk24=al.get("dk24")
    alert_map={"GREEN":"💚 Норма","YELLOW":"🟡 Внимание","ORANGE":"🟠 Подготовка!",
               "RED":"🔴 ТРЕВОГА!","CRITICAL":"🚨 КРИТИЧЕСКИЙ!","UNKNOWN":"❓"}
    alert_txt=alert_map.get(al.get("alert_level","UNKNOWN"),"❓")
    days_945=al.get("days_to_945"); date_945=al.get("date_to_945")
    pb=al.get("peak_base_level"); pbd=al.get("peak_base_date")
    pb_days=al.get("peak_base_days")
    po=al.get("peak_opt_level"); pod=al.get("peak_opt_date")
    pp=al.get("peak_pess_level"); ppd=al.get("peak_pess_date")

    if isinstance(s,int) and s>=CRITICAL_LEVEL:
        forecast_block="🚨 ВОДА НА УРОВНЕ ПОРОГОВ ДОМОВ!\n"
    elif days_945 is not None and ds24 and ds24>0:
        forecast_block=f"⏱ До порога домов (945 см): <b>~{days_945} сут</b> (~{date_945})\n"
    else:
        forecast_block="📏 Рост остановился / данных мало\n"

    peak_block=""
    if pb and pbd:
        peak_block=(f"🏔 Прогноз пика: ~<b>{pb} см</b> через ~{pb_days} сут (~{pbd})\n"
                    f"   🟢 {po} см (~{pod}) | 🟡 {pb} см (~{pbd}) | 🔴 {pp} см (~{ppd})\n")
    else:
        peak_block="🏔 Прогноз пика: данных пока мало\n"

    def dist(target):
        if isinstance(s,int) and s<target and ds24 and ds24>0:
            return f"+{target-s} см (~{round((target-s)/ds24,1)} сут)"
        elif isinstance(s,int) and s>=target: return "✅ ДОСТИГНУТ"
        return "н/д"

    w_line=""
    if weather:
        t=weather.get("temp","?"); pr=weather.get("precip_mm",0)
        wm=weather.get("wind_ms","?"); wd=wind_dir_str(weather.get("wind_dir",0))
        w_line=f"\n🌡 Погода: {t}°C, осадки {pr} мм, ветер {wm} м/с {wd}"

    ins_txt="".join(f"  {i}\n" for i in al.get("insights",[])[:5]) or "  Накапливаем данные...\n"

    return (f"🌊 <b>ОКА ПАВОДОК 2026 — ДАЙДЖЕСТ</b>\n"
            f"📅 {now} | 08:00 МСК\n\n"
            f"━━━ УРОВНИ ВОДЫ ━━━━━━━━━━━━━━━━━━\n"
            f"📍 ОРЁЛ (верховье, −3-4 сут)\n   {o} см | Δ24ч: {fmt_delta(do24)} {trend_icon(do24)}\n\n"
            f"📍 КАЛУГА (−48-72 ч)\n   {k} см | Δ24ч: {fmt_delta(dk24)} {trend_icon(dk24)}\n\n"
            f"📍 <b>СЕРПУХОВ 🎯 (наш пост)</b>\n"
            f"   <b>{s} см</b> | Δ24ч: <b>{fmt_delta(ds24)}</b> {trend_icon(ds24)}\n"
            f"   Δ48ч (ср): {fmt_delta(ds48)}\n\n"
            f"📍 КАШИРА (ниже нас)\n   {ka} см{w_line}\n\n"
            f"━━━ ПРОГНОЗ ━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{forecast_block}{peak_block}\n"
            f"━━━ ДО КРИТИЧЕСКИХ ОТМЕТОК ━━━━━━━\n"
            f"🟡 645 см (пойма): {dist(645)}\n"
            f"🟠 800 см (подтопление): {dist(800)}\n"
            f"🔴 920 см (пик 2024): {dist(PEAK_2024)}\n"
            f"🚨 945 см (ПОРОГ ДОМОВ): {dist(CRITICAL_LEVEL)}\n\n"
            f"━━━ АНАЛИТИКА ━━━━━━━━━━━━━━━━━━━\n{ins_txt}\n"
            f"━━━ СТАТУС ━━━━━━━━━━━━━━━━━━━━━━\n   {alert_txt}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <a href='https://em-from-pu.github.io/oka-flood-monitor/'>Полная аналитика онлайн</a>\n"
            f"📡 allrivers.info | ⏱ Следующий замер: 18:00 МСК")

def format_group_draft(levels, analytics):
    now=datetime.now().strftime("%d.%m.%Y")
    s=levels.get("serpukhov","?"); o=levels.get("orel","?")
    k=levels.get("kaluga","?"); ka=levels.get("kashira","?")
    al=analytics; ds24=al.get("ds24")
    days_945=al.get("days_to_945"); date_945=al.get("date_to_945")
    pb_level=al.get("peak_base_level"); pb_date=al.get("peak_base_date")
    alert_map={"GREEN":"💚 Наблюдаем","YELLOW":"🟡 Готовимся",
               "ORANGE":"🟠 Действуем!","RED":"🔴 СРОЧНЫЕ МЕРЫ!",
               "CRITICAL":"🚨 ВОДА ИДЁТ К ДОМАМ!","UNKNOWN":"📡 Сбор данных"}
    status=alert_map.get(al.get("alert_level","UNKNOWN"),"📡")
    sign="+" if ds24 and ds24>0 else ""
    delta_txt=f"{sign}{round(ds24)} см/сут" if ds24 else "стабильно"
    f_txt=""
    if days_945 and isinstance(days_945,float) and days_945<30 and ds24 and ds24>0:
        f_txt+=f"\n⏰ До порога домов: ~{days_945} сут (~{date_945})"
    if pb_level and pb_date:
        f_txt+=f"\n🏔 Прогноз пика: ~{pb_level} см (~{pb_date})"
    return (f"🌊 ПАВОДОК 2026 | ДАЧИ | {now}, утро\n\n"
            f"📊 УРОВНИ ОКИ (08:00 МСК):\n"
            f"• Орёл (3-4 дня до нас): {o} см\n"
            f"• Калуга (1-2 дня до нас): {k} см\n"
            f"• Серпухов (наш пост): {s} см [{delta_txt}]\n"
            f"• Кашира (ниже нас): {ka} см\n"
            f"\n📏 ОРИЕНТИР 2024: пик 920 см (в 20 см от порогов){f_txt}\n"
            f"\n📌 СТАТУС: {status}\n"
            f"\n🔗 em-from-pu.github.io/oka-flood-monitor/\nДанные: allrivers.info | МЧС МО")

def generate_html(levels, analytics, weather, history):
    s=levels.get("serpukhov"); o=levels.get("orel")
    k=levels.get("kaluga"); a=levels.get("aleksin"); ka=levels.get("kashira")
    al=analytics; now_str=datetime.now().strftime("%d.%m.%Y %H:%M МСК")
    ds24=al.get("ds24"); days_945=al.get("days_to_945"); date_945=al.get("date_to_945")
    pb_level=al.get("peak_base_level"); pb_date=al.get("peak_base_date")
    pb_days=al.get("peak_base_days")
    po_level=al.get("peak_opt_level"); po_date=al.get("peak_opt_date")
    pp_level=al.get("peak_pess_level"); pp_date=al.get("peak_pess_date")
    color_map={"GREEN":("#27ae60","💚 Норма"),"YELLOW":("#f39c12","🟡 Внимание"),
               "ORANGE":("#e67e22","🟠 Подготовка!"),"RED":("#c0392b","🔴 ТРЕВОГА!"),
               "CRITICAL":("#8e0000","🚨 КРИТИЧЕСКИЙ!"),"UNKNOWN":("#7f8c8d","❓")}
    alert_level=al.get("alert_level","UNKNOWN")
    alert_color,alert_txt=color_map.get(alert_level,("#7f8c8d","❓"))
    pct=min(round((s/CRITICAL_LEVEL*100),1) if s else 0, 100)

    # Hero forecast block
    if s and s>=CRITICAL_LEVEL:
        hero=('<div class="hero-forecast critical">'
              '<span class="hero-label">🚨 ВОДА НА УРОВНЕ ПОРОГОВ ДОМОВ!</span></div>')
    elif days_945 is not None and ds24 and ds24>0:
        hero=(f'<div class="hero-forecast">'
              f'<span class="hero-label">⏱ ДО ПОРОГА ДОМОВ (945 см):</span><br>'
              f'<span class="hero-days">{days_945} сут</span>'
              f'<span class="hero-date">примерно {date_945}</span></div>')
    else:
        days_left = CRITICAL_LEVEL-(s or 0)
        hero=(f'<div class="hero-forecast green">'
              f'<span class="hero-label">📏 До порога домов:</span><br>'
              f'<span class="hero-days" style="font-size:2.5em">{days_left} см</span>'
              f'<span class="hero-date">рост остановлен / спад</span></div>')

    # Scenarios
    scen=""
    if pb_level:
        scen=(f'<div class="scenarios"><h3>🏔 Прогноз пика паводка</h3>'
              f'<div class="scenario-cards">'
              f'<div class="sc-card green"><div class="sc-title">🟢 Оптимистичный</div>'
              f'<div class="sc-level">{po_level or "?"} см</div>'
              f'<div class="sc-date">~{po_date or "?"}</div></div>'
              f'<div class="sc-card yellow"><div class="sc-title">🟡 Базовый</div>'
              f'<div class="sc-level">{pb_level} см</div>'
              f'<div class="sc-date">~{pb_date}</div></div>'
              f'<div class="sc-card red"><div class="sc-title">🔴 Пессимистичный</div>'
              f'<div class="sc-level">{pp_level or "?"} см</div>'
              f'<div class="sc-date">~{pp_date or "?"}</div></div>'
              f'</div><p class="scenario-note">* Базовый: при текущем темпе. '
              f'Оптимистичный: темп снизится. Пессимистичный: усиление таяния.</p></div>')
    else:
        scen='<div class="scenarios"><p>🏔 Прогноз пика: накапливаем данные (нужно ≥2 дня)</p></div>'

    # Погода
    w_html=""
    if weather:
        t=weather.get("temp","?"); h=weather.get("humidity","?")
        wm=weather.get("wind_ms","?"); wd=wind_dir_str(weather.get("wind_dir",0))
        pr=weather.get("precip_mm",0); cl=weather.get("clouds","?")
        desc=weather.get("weather","")
        w_html=(f'<div class="weather-block"><h3>🌡 Погода (Серпухов/Пущино)</h3>'
                f'<div class="weather-grid">'
                f'<div>🌡 {t}°C — {desc}</div><div>💧 Осадки: {pr} мм</div>'
                f'<div>💨 Ветер: {wm} м/с {wd}</div><div>☁️ Облачность: {cl}%</div>'
                f'<div>💦 Влажность: {h}%</div></div></div>')

    # Инсайты
    ins_html="".join(f"<li>{i}</li>" for i in al.get("insights",[]))
    ins_html=ins_html or "<li>Накапливаем данные для аналитики...</li>"

    # Ориентиры
    def ms_dist(target):
        if s and s>=target: return "✅ ДОСТИГНУТ"
        return f"+{target-(s or 0)} см"

    def lvl_card(name, val, delta, note, main=False):
        d_str=""
        if delta is not None:
            sign="+" if delta>0 else ""
            d_str=f'<div class="gauge-delta">{sign}{round(delta)} см/сут</div>'
        cls="gauge-card main" if main else "gauge-card"
        return (f'<div class="{cls}"><div class="gauge-name">{name}</div>'
                f'<div class="gauge-level">{val or "н/д"} <span>см</span></div>'
                f'{d_str}<div class="gauge-note">{note}</div></div>')

    gauges_html=(
        lvl_card("📍 ОРЁЛ", o, al.get("do24"), "верховье, −3-4 дня")+
        lvl_card("📍 АЛЕКСИН", a, None, "−24-36 ч до нас")+
        lvl_card("📍 КАЛУГА", k, al.get("dk24"), "−48-72 ч до нас")+
        lvl_card("🎯 СЕРПУХОВ", s, al.get("ds24"), "НАША ТОЧКА", main=True)+
        lvl_card("📍 КАШИРА", ka, None, "ниже по течению")
    )

    # Таблица истории
    trows=""
    for row in sorted(history, key=lambda x:x.get("datetime",""), reverse=True)[:30]:
        def c(key):
            v=row.get(key,"")
            if not v: return "—"
            try:
                f=float(v)
                return (f"{f:+.0f}" if "delta" in key else str(round(f)))
            except: return str(v)
        cl_map={"GREEN":"row-green","YELLOW":"row-yellow","ORANGE":"row-orange",
                "RED":"row-red","CRITICAL":"row-critical"}
        rcls=cl_map.get(row.get("alert_level",""),"")
        trows+=(f'<tr class="{rcls}"><td>{row.get("datetime","")[:16]}</td>'
                f'<td>{c("orel")}</td><td>{c("aleksin")}</td><td>{c("kaluga")}</td>'
                f'<td><b>{c("serpukhov")}</b></td><td>{c("delta_serp_24h")}</td>'
                f'<td>{c("delta_serp_48h")}</td><td>{c("kashira")}</td>'
                f'<td>{c("temp")}</td><td>{c("precip_mm")}</td>'
                f'<td>{row.get("alert_level","")}</td>'
                f'<td>{row.get("notes","")[:60]}</td></tr>')

    return f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🌊 Ока Паводок 2026</title>
<style>
:root{{--green:#27ae60;--yellow:#f39c12;--orange:#e67e22;--red:#c0392b;--crit:#8e0000;
      --bg:#0f1923;--card:#1a2635;--text:#ecf0f1;--border:#2c3e50;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);font-family:'Segoe UI',sans-serif;padding:16px;max-width:1200px;margin:0 auto;}}
h1{{font-size:1.8em;margin-bottom:4px;}}h2{{font-size:1.3em;margin:20px 0 10px;border-bottom:1px solid var(--border);padding-bottom:6px;}}h3{{font-size:1.1em;margin:12px 0 8px;}}
.subtitle{{color:#95a5a6;font-size:0.9em;margin-bottom:16px;}}
.status-badge{{display:inline-block;padding:6px 18px;border-radius:20px;font-weight:bold;font-size:1.1em;margin:10px 0;background:{alert_color};color:white;}}
.hero-forecast{{background:linear-gradient(135deg,#1a2635,#243447);border:2px solid var(--orange);border-radius:12px;padding:28px;text-align:center;margin:16px 0;}}
.hero-forecast.critical{{border-color:var(--crit);background:#2d0000;}}
.hero-forecast.green{{border-color:var(--green);}}
.hero-label{{font-size:1em;color:#bdc3c7;display:block;margin-bottom:8px;}}
.hero-days{{font-size:3.5em;font-weight:900;color:var(--orange);display:block;line-height:1;}}
.hero-forecast.green .hero-days{{color:var(--green);}}
.hero-date{{font-size:1.4em;color:#ecf0f1;display:block;margin-top:4px;}}
.progress-wrap{{background:#1a2635;border-radius:8px;padding:14px;margin:12px 0;}}
.progress-label{{display:flex;justify-content:space-between;font-size:0.85em;color:#95a5a6;margin-bottom:6px;}}
.progress-bar{{height:24px;border-radius:6px;overflow:hidden;background:#0a1420;position:relative;}}
.progress-fill{{height:100%;border-radius:6px;background:linear-gradient(90deg,#27ae60,#f39c12,#e67e22,#c0392b);width:{pct}%;}}
.progress-pct{{position:absolute;right:8px;top:3px;font-size:0.85em;font-weight:bold;color:white;}}
.gauges-grid{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0;}}
.gauge-card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 18px;min-width:160px;flex:1;}}
.gauge-card.main{{border-color:var(--orange);background:#1f2f3e;}}
.gauge-name{{font-size:0.85em;color:#95a5a6;margin-bottom:4px;}}
.gauge-level{{font-size:2em;font-weight:bold;line-height:1;}}
.gauge-level span{{font-size:0.5em;color:#7f8c8d;}}
.gauge-delta{{font-size:0.95em;color:var(--orange);margin-top:4px;}}
.gauge-note{{font-size:0.75em;color:#7f8c8d;margin-top:6px;}}
.scenarios{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.scenario-cards{{display:flex;gap:12px;flex-wrap:wrap;margin:10px 0;}}
.sc-card{{flex:1;min-width:140px;border-radius:8px;padding:12px;text-align:center;}}
.sc-card.green{{background:#0d2b17;border:1px solid var(--green);}}
.sc-card.yellow{{background:#2b1f00;border:1px solid var(--yellow);}}
.sc-card.red{{background:#2b0000;border:1px solid var(--red);}}
.sc-title{{font-size:0.85em;margin-bottom:8px;}}
.sc-level{{font-size:1.8em;font-weight:bold;}}
.sc-date{{font-size:0.85em;color:#95a5a6;margin-top:4px;}}
.scenario-note{{font-size:0.75em;color:#7f8c8d;margin-top:8px;}}
.insights-block{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.insights-block ul{{list-style:none;}}
.insights-block li{{padding:5px 0;border-bottom:1px solid var(--border);}}
.insights-block li:last-child{{border:none;}}
.milestones{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.ms-row{{display:flex;align-items:center;padding:7px 0;border-bottom:1px solid var(--border);gap:12px;}}
.ms-row:last-child{{border:none;}}
.ms-level{{font-size:1.1em;font-weight:bold;min-width:80px;}}
.ms-desc{{flex:1;font-size:0.85em;color:#bdc3c7;}}
.ms-dist{{font-size:0.9em;color:var(--orange);text-align:right;min-width:120px;}}
.table-wrap{{overflow-x:auto;margin:12px 0;}}
table{{width:100%;border-collapse:collapse;font-size:0.82em;}}
th{{background:#1a2635;padding:8px 6px;text-align:center;border-bottom:2px solid var(--border);white-space:nowrap;}}
td{{padding:6px;text-align:center;border-bottom:1px solid var(--border);}}
tr.row-green td{{background:#0d2017;}}tr.row-yellow td{{background:#1f1600;}}
tr.row-orange td{{background:#1f1000;}}tr.row-red td{{background:#1f0000;}}
tr.row-critical td{{background:#2d0000;}}tr:hover td{{background:#243447;}}
.weather-block{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.weather-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-top:8px;}}
.weather-grid div{{background:#0f1923;border-radius:6px;padding:8px 12px;font-size:0.9em;}}
.legend{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;line-height:1.6;}}
.legend p{{margin:6px 0;font-size:0.9em;}}
.legend-levels{{margin:10px 0;}}
.ll{{padding:6px 10px;border-radius:6px;margin:4px 0;font-size:0.9em;}}
.ll.green{{background:#0d2017;}}.ll.yellow{{background:#1f1600;}}
.ll.orange{{background:#1f1000;}}.ll.red{{background:#1f0000;}}
.ll.critical{{background:#2d0000;}}
.compare-2024{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.table-2024{{width:100%;border-collapse:collapse;font-size:0.85em;margin-top:8px;}}
.table-2024 th{{background:#0f1923;padding:6px;}}
.table-2024 td{{padding:6px;border-bottom:1px solid var(--border);}}
.links-block{{background:var(--card);border-radius:10px;padding:16px;margin:12px 0;}}
.links-block ul{{list-style:none;}}.links-block li{{padding:4px 0;}}
.links-block a{{color:#3498db;text-decoration:none;}}
.footer{{text-align:center;color:#4a5568;font-size:0.8em;margin-top:24px;padding:16px;}}
@media(max-width:600px){{.gauge-level{{font-size:1.5em;}}.hero-days{{font-size:2.5em;}}}}
</style></head><body>
<h1>🌊 Ока Паводок 2026</h1>
<div class="subtitle">Автоматический мониторинг · Пущино / Серпухов</div>
<span class="status-badge">{alert_txt}</span>
{hero}
<div class="progress-wrap">
  <div class="progress-label">
    <span>Серпухов: {s or '?'} см → порог домов 945 см</span>
    <span>{pct}% от критического уровня</span>
  </div>
  <div class="progress-bar">
    <div class="progress-fill"></div>
    <span class="progress-pct">{pct}%</span>
  </div>
</div>
<h2>📡 Уровни воды прямо сейчас</h2>
<div class="gauges-grid">{gauges_html}</div>
{w_html}
{scen}
<div class="insights-block">
  <h3>🧠 Аналитика — что происходит</h3>
  <ul>{ins_html}</ul>
</div>
<h2>🎯 До критических отметок (Серпухов)</h2>
<div class="milestones">
  <div class="ms-row"><div class="ms-level" style="color:#f39c12">645 см</div>
    <div class="ms-desc">🟡 Вода на пойме — нижние луга залиты</div>
    <div class="ms-dist">{ms_dist(645)}</div></div>
  <div class="ms-row"><div class="ms-level" style="color:#e67e22">800 см</div>
    <div class="ms-desc">🟠 Подтопление — въезд на дачи затруднён</div>
    <div class="ms-dist">{ms_dist(800)}</div></div>
  <div class="ms-row"><div class="ms-level" style="color:#c0392b">920 см</div>
    <div class="ms-desc">🔴 Уровень пика 2024 — вода в 20 см от порогов</div>
    <div class="ms-dist">{ms_dist(920)}</div></div>
  <div class="ms-row"><div class="ms-level" style="color:#ff4444">945 см</div>
    <div class="ms-desc">🚨 ПОРОГ ДОМОВ — вода заходит в дома</div>
    <div class="ms-dist">{ms_dist(945)}</div></div>
</div>
<h2>📊 История уровней — полная таблица</h2>
<div class="table-wrap"><table>
  <thead><tr><th>Дата/Время</th><th>Орёл</th><th>Алексин</th><th>Калуга</th>
    <th>Серпухов</th><th>Δ24ч</th><th>Δ48ч(ср)</th><th>Кашира</th>
    <th>T°C</th><th>Осадки</th><th>Статус</th><th>Примечание</th></tr></thead>
  <tbody>{trows or '<tr><td colspan="12">Данные появятся после первого замера</td></tr>'}</tbody>
</table></div>
<div class="compare-2024">
  <h3>📅 Как было в 2024 (для сравнения)</h3>
  <table class="table-2024"><thead>
    <tr><th>Период</th><th>Серпухов</th><th>Событие</th></tr></thead>
  <tbody>
    <tr><td>Конец марта 2024</td><td>400-500 см</td><td>Начало роста</td></tr>
    <tr><td>1-5 апреля 2024</td><td>600-750 см</td><td>Активный рост, пойма залита</td></tr>
    <tr><td>7-10 апреля 2024</td><td>800-920 см</td><td>Подтопление дорог</td></tr>
    <tr><td>11 апреля 2024</td><td>~920 см</td><td>🔴 ПИК — 20 см от порогов!</td></tr>
    <tr><td>12-20 апреля 2024</td><td>920→700 см</td><td>Постепенный спад</td></tr>
  </tbody></table>
  <p style="margin-top:8px;font-size:0.85em;color:#bdc3c7;">
    В 2026 году снегозапас и температурный фон схожи с 2024. Следим внимательно!</p>
</div>
<div class="legend">
  <h3>📖 Как читать эту страницу</h3>
  <p>Мы отслеживаем уровень воды в Оке по цепочке постов от истоков к устью:
     <b>Орёл → Алексин → Калуга → Серпухов → Кашира</b>.</p>
  <p>Вода движется вниз по течению: что сейчас в Орле — придёт к нам через <b>3-4 суток</b>.
     Калуга — через <b>48-72 часа</b>. Это позволяет предупреждать паводок заранее.</p>
  <div class="legend-levels">
    <div class="ll green">💚 <b>0 – 644 см</b> — Норма. Дачи вне угрозы.</div>
    <div class="ll yellow">🟡 <b>645 – 799 см</b> — Вода на пойме. Нижние луга залиты.</div>
    <div class="ll orange">🟠 <b>800 – 919 см</b> — Подтопление. Въезд на дачи затруднён.</div>
    <div class="ll red">🔴 <b>920 – 944 см</b> — Уровень пика 2024. Вода в 20 см от порогов.</div>
    <div class="ll critical">🚨 <b>945+ см</b> — ПОРОГ ДОМОВ. Вода заходит в дома.</div>
  </div>
  <p><b>Прогноз "N дней"</b> — при текущем суточном темпе роста, через сколько вода достигнет
     отметки 945 см. Если темп = 0 или вода спадает — показываем остаток в сантиметрах.</p>
  <p><b>Прогноз пика</b> строится когда верхние посты (Орёл, Калуга) начинают снижаться —
     тогда волна уже прошла через них и движется к нам.</p>
</div>
<div class="links-block">
  <h3>🔗 Полезные ссылки</h3>
  <ul>
    <li><a href="https://allrivers.info/gauge/oka-serpuhov" target="_blank">allrivers.info — Серпухов</a></li>
    <li><a href="https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-serpukhov-segodnya" target="_blank">snt-bugorok.ru — Серпухов (дубль)</a></li>
    <li><a href="https://willmap.me/uroven-vody-oka-g-serpuhov" target="_blank">willmap.me — карта уровней</a></li>
    <li><a href="https://50.mchs.gov.ru/" target="_blank">МЧС Московской области</a></li>
    <li><a href="https://cugms.ru/" target="_blank">Центральное УГМС — обзоры паводка</a></li>
  </ul>
</div>
<div class="footer">
  Обновлено: {now_str} · GitHub Actions · allrivers.info<br>
  <a href="https://github.com/EM-from-Pu/oka-flood-monitor" style="color:#4a5568">GitHub репо</a>
</div>
</body></html>"""

def load_alerts_sent():
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE) as f: return json.load(f)
    return {}

def save_alerts_sent(data):
    with open(ALERTS_FILE,"w") as f: json.dump(data, f, indent=2)

def check_and_send_alerts(levels, analytics):
    s=levels.get("serpukhov"); ds=analytics.get("ds24")
    dk=analytics.get("dk24"); do=analytics.get("do24")
    if s is None: return
    sent=load_alerts_sent()
    now_h=datetime.now().strftime("%Y-%m-%d-%H")
    def already(k): return sent.get(k,"")==now_h
    def mark(k): sent[k]=now_h
    if s>500 and not already("T1"):
        tg_send(CHAT_ADMIN,f"💛 T1: Серпухов >500 см ({s}) — паводок начинается")
        tg_send(CHAT_GROUP,f"💛 Паводок 2026: уровень Оки у Серпухова превысил 500 см ({s} см)"); mark("T1")
    if ds and ds>=20 and not already("T2"):
        tg_send(CHAT_ADMIN,f"⚡️ T2: Серпухов растёт +{round(ds)} см/сут!"); mark("T2")
    if ds and ds>=40 and not already("T3"):
        tg_send(CHAT_ADMIN,f"🚨 T3 ЭКСТРЕННО: +{round(ds)} см/сут!")
        tg_send(CHAT_GROUP,f"🚨 ЭКСТРЕННО: Ока у Серпухова растёт +{round(ds)} см в сутки!"); mark("T3")
    if dk and dk>=30 and ds and ds<15 and not already("T4"):
        tg_send(CHAT_ADMIN,f"⏰ T4: Калуга +{round(dk)} см/сут — волна через ~48-72 ч!")
        tg_send(CHAT_GROUP,f"⏰ Волна идёт: Калуга +{round(dk)} см/сут, ждём через 48-72 ч"); mark("T4")
    for lvl,key,icon,desc in [(645,"T5","🟡","вода на пойме"),(800,"T6","🟠","подтопление"),
                               (920,"T7","🔴","уровень пика 2024"),(945,"T8","🚨","ПОРОГ ДОМОВ")]:
        if s>=lvl and not already(key):
            tg_send(CHAT_ADMIN,f"{icon} {key}: Серпухов достиг {lvl} см — {desc}!")
            tg_send(CHAT_GROUP,f"{icon} Уровень {lvl} см у Серпухова — {desc}! Сейчас: {s} см"); mark(key)
    if ds and ds<-10 and not already("T9"):
        tg_send(CHAT_ADMIN,f"📉 T9: Серпухов снижается {round(ds)} см/сут — пик пройден")
        tg_send(CHAT_GROUP,f"📉 Вода у Серпухова начала убывать ({round(ds)} см/сут). Пик пройден!"); mark("T9")
    save_alerts_sent(sent)

def main():
    mode=os.environ.get("MONITOR_MODE","full")
    print(f"[OkaMonitor v3.0] mode={mode}")
    print("Парсим уровни воды...")
    levels=fetch_all_levels()
    print("Парсим погоду...")
    weather=fetch_weather()
    history=load_history()
    analytics=compute_analytics(levels,history,weather)
    print(f"alert={analytics['alert_level']}, ds24={analytics['ds24']}, days_945={analytics['days_to_945']}")
    notes="; ".join(analytics.get("insights",[])[:2])
    now_iso=datetime.now(timezone.utc).isoformat()
    row={
        "datetime":now_iso,"orel":levels.get("orel",""),"aleksin":levels.get("aleksin",""),
        "kaluga":levels.get("kaluga",""),"serpukhov":levels.get("serpukhov",""),
        "kashira":levels.get("kashira",""),"delta_serp_24h":analytics.get("ds24",""),
        "delta_serp_48h":analytics.get("ds48",""),"delta_orel_24h":analytics.get("do24",""),
        "delta_kaluga_24h":analytics.get("dk24",""),"temp":weather.get("temp",""),
        "humidity":weather.get("humidity",""),"wind_ms":weather.get("wind_ms",""),
        "wind_dir":weather.get("wind_dir",""),"clouds":weather.get("clouds",""),
        "precip_mm":weather.get("precip_mm",""),"alert_level":analytics.get("alert_level",""),
        "forecast_days_to_945":analytics.get("days_to_945",""),
        "forecast_days_to_peak":analytics.get("peak_base_days",""),
        "scenario_base_peak":analytics.get("peak_base_level",""),
        "scenario_base_date":analytics.get("peak_base_date",""),"notes":notes,
    }
    history.append(row); save_history(history)
    os.makedirs("docs",exist_ok=True)
    html=generate_html(levels,analytics,weather,history)
    with open(INDEX_HTML,"w",encoding="utf-8") as f: f.write(html)
    data={"updated":now_iso,"levels":levels,
          "analytics":{k:analytics.get(k) for k in
                        ["ds24","ds48","alert_level","days_to_945","date_to_945",
                         "peak_base_level","peak_base_date","insights"]},
          "weather":weather}
    with open(DATA_JSON,"w",encoding="utf-8") as f: json.dump(data,f,ensure_ascii=False,indent=2)
    s=levels.get("serpukhov","?"); al=analytics.get("alert_level","?")
    with open(STATUS_FILE,"w",encoding="utf-8") as f:
        f.write(f"{al} | {datetime.now().strftime('%d.%m.%Y %H:%M MSK')} | S:{s}\n")
    draft=format_group_draft(levels,analytics)
    with open(GROUP_DRAFT,"w",encoding="utf-8") as f: f.write(draft)
    if mode in ("full","digest"):
        digest=format_digest(levels,analytics,weather,history)
        print("Отправляем дайджест...")
        tg_send(CHAT_ADMIN, digest)
        tg_send(CHAT_ADMIN, f"📋 ЧЕРНОВИК ДЛЯ ГРУППЫ (перешли вручную):\n\n{draft}")
    check_and_send_alerts(levels,analytics)
    print("✅ Готово!")

if __name__=="__main__":
    main()
