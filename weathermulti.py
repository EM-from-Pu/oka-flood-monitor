"""
weather_multi.py — Мульти-точечный прогноз осадков для бассейна Оки.
Запрашивает Open-Meteo для 6 ключевых точек и формирует матрицу осадков + аналитику.
Не зависит от fetch_module.py.

v1.0 — 31.03.2026
"""

import time
import requests
from datetime import datetime, timezone, timedelta

# ─── Ключевые точки бассейна Оки ───────────────────────────────────────────
WEATHER_POINTS = [
    {"slug": "orel",      "name": "Орёл",      "lat": 52.97, "lon": 36.07, "role": "верховья — исток Оки"},
    {"slug": "tula",      "name": "Тула",       "lat": 54.19, "lon": 37.62, "role": "приток Упа, водосбор"},
    {"slug": "kaluga",    "name": "Калуга",     "lat": 54.53, "lon": 36.28, "role": "приток Угра, средний бассейн"},
    {"slug": "belev",     "name": "Белёв",      "lat": 53.81, "lon": 36.13, "role": "верхняя Ока"},
    {"slug": "serpuhov",  "name": "Серпухов",   "lat": 54.92, "lon": 37.41, "role": "основная точка наблюдения"},
    {"slug": "pushchino", "name": "Пущино",     "lat": 54.83, "lon": 37.62, "role": "район Жерновки"},
]

# ─── Пороги аналитики ──────────────────────────────────────────────────────
PRECIP_THRESHOLDS = {
    "light":    (0.1, 2.0),   # слабый дождь
    "moderate": (2.0, 8.0),   # умеренный
    "heavy":    (8.0, 20.0),  # сильный
    "extreme":  (20.0, 999),  # ливень
}

TEMP_THAW_THRESHOLD = 3.0   # °C — активное таяние при Tmax > 3


def fetch_multi_weather(timeout: int = 20) -> dict:
    """
    Запрашивает Open-Meteo для всех точек.
    Возвращает:
    {
        "points": [
            {
                "slug": "orel", "name": "Орёл", "role": "...",
                "days": [
                    {"date": "2026-03-31", "precip_mm": 0.9, "tmax": 9, "tmin": 3, "snow_cm": 0, "weather": "дождь"},
                    ...
                ],
                "total_precip_3d": 1.0,
                "total_precip_7d": 6.5,
                "max_daily_precip": 5.2,
                "max_daily_date": "2026-04-02",
            },
            ...
        ],
        "analysis": {
            "basin_total_3d_mm": 15.0,
            "basin_max_point": "Серпухов",
            "basin_max_3d": 6.0,
            "rain_on_snow_risk": True,
            "rain_on_snow_where": "Орёл",
            "alert_level": "high",  # none / low / moderate / high / critical
            "alert_text": "...",
            "summary": "..."
        },
        "fetch_time": "2026-03-31T12:00:00",
        "status": "ok"  # ok / partial / error
    }
    """
    result = {
        "points": [],
        "analysis": {},
        "fetch_time": datetime.now(timezone.utc).isoformat()[:19],
        "status": "ok"
    }
    
    ok_count = 0
    
    for pt in WEATHER_POINTS:
        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={pt['lat']}&longitude={pt['lon']}"
                f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,snowfall_sum,weathercode"
                f"&timezone=Europe/Moscow&forecast_days=8"
            )
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            time.sleep(1)
            data = resp.json()
            
            daily = data.get("daily", {})
            dates = daily.get("time", [])
            tmax_arr = daily.get("temperature_2m_max", [])
            tmin_arr = daily.get("temperature_2m_min", [])
            precip_arr = daily.get("precipitation_sum", [])
            snow_arr = daily.get("snowfall_sum", [])
            snow_depth_arr = daily.get("snowfall_sum", [])  # snow_depth недоступна в daily, используем snowfall_sum
            wcode_arr = daily.get("weathercode", [])
            
            days = []
            for i, d in enumerate(dates):
                precip = precip_arr[i] if i < len(precip_arr) and precip_arr[i] is not None else 0
                tmax = tmax_arr[i] if i < len(tmax_arr) else None
                tmin = tmin_arr[i] if i < len(tmin_arr) else None
                snow_d = snow_depth_arr[i] if i < len(snow_depth_arr) and snow_depth_arr[i] is not None else 0
                wc = wcode_arr[i] if i < len(wcode_arr) else 0
                
                # Weather code → text
                weather_text = _wcode_to_text(wc)
                
                days.append({
                    "date": d,
                    "precip_mm": round(precip, 1),
                    "tmax": round(tmax, 1) if tmax is not None else None,
                    "tmin": round(tmin, 1) if tmin is not None else None,
                    "snow_cm": round(snow_d * 100, 1) if snow_d else 0,
                    "weather": weather_text,
                })
            
            total_3d = sum(day["precip_mm"] for day in days[:3])
            total_7d = sum(day["precip_mm"] for day in days[:7])
            max_daily = max((day["precip_mm"] for day in days), default=0)
            max_daily_date = ""
            for day in days:
                if day["precip_mm"] == max_daily and max_daily > 0:
                    max_daily_date = day["date"]
                    break
            
            result["points"].append({
                "slug": pt["slug"],
                "name": pt["name"],
                "role": pt["role"],
                "days": days,
                "total_precip_3d": round(total_3d, 1),
                "total_precip_7d": round(total_7d, 1),
                "max_daily_precip": round(max_daily, 1),
                "max_daily_date": max_daily_date,
            })
            ok_count += 1
            
        except Exception as e:
            result["points"].append({
                "slug": pt["slug"],
                "name": pt["name"],
                "role": pt["role"],
                "days": [],
                "total_precip_3d": 0,
                "total_precip_7d": 0,
                "max_daily_precip": 0,
                "max_daily_date": "",
                "error": str(e),
            })
    
    if ok_count == 0:
        result["status"] = "error"
    elif ok_count < len(WEATHER_POINTS):
        result["status"] = "partial"
    
    # ─── Аналитика ──────────────────────────────────────────────────────
    result["analysis"] = _analyze_basin_weather(result["points"])
    
    return result


def _analyze_basin_weather(points: list) -> dict:
    """Формирует аналитику по всем точкам бассейна."""
    
    analysis = {
        "basin_total_3d_mm": 0,
        "basin_max_point": "",
        "basin_max_3d": 0,
        "rain_on_snow_risk": False,
        "rain_on_snow_where": "",
        "alert_level": "none",
        "alert_text": "",
        "summary": "",
    }
    
    max_3d = 0
    max_3d_name = ""
    total_basin_3d = 0
    rain_on_snow_points = []
    heavy_rain_points = []
    
    for pt in points:
        total_basin_3d += pt["total_precip_3d"]
        
        if pt["total_precip_3d"] > max_3d:
            max_3d = pt["total_precip_3d"]
            max_3d_name = pt["name"]
        
        # Rain-on-Snow detection
        for day in pt.get("days", [])[:5]:
            if day["precip_mm"] > 1.0 and day["snow_cm"] > 0 and day.get("tmax", 0) and day["tmax"] > 0:
                rain_on_snow_points.append((pt["name"], day["date"], day["precip_mm"], day["snow_cm"]))
                break
        
        # Heavy rain detection
        if pt["max_daily_precip"] >= 8.0:
            heavy_rain_points.append((pt["name"], pt["max_daily_date"], pt["max_daily_precip"]))
    
    analysis["basin_total_3d_mm"] = round(total_basin_3d, 1)
    analysis["basin_max_point"] = max_3d_name
    analysis["basin_max_3d"] = round(max_3d, 1)
    
    # Rain-on-Snow
    if rain_on_snow_points:
        analysis["rain_on_snow_risk"] = True
        analysis["rain_on_snow_where"] = ", ".join(set(p[0] for p in rain_on_snow_points))
    
    # Alert level
    if rain_on_snow_points and total_basin_3d > 15:
        analysis["alert_level"] = "critical"
    elif rain_on_snow_points or total_basin_3d > 20:
        analysis["alert_level"] = "high"
    elif heavy_rain_points or total_basin_3d > 10:
        analysis["alert_level"] = "moderate"
    elif total_basin_3d > 3:
        analysis["alert_level"] = "low"
    else:
        analysis["alert_level"] = "none"
    
    # Summary text
    parts = []
    if total_basin_3d > 0:
        parts.append(f"Суммарные осадки по бассейну за 3 дня: {total_basin_3d:.0f} мм")
    if max_3d_name:
        parts.append(f"Максимум: {max_3d_name} ({max_3d:.0f} мм за 3 дня)")
    if heavy_rain_points:
        for name, date, mm in heavy_rain_points:
            parts.append(f"⚠️ Сильный дождь: {name} — {mm:.0f} мм ({date})")
    if rain_on_snow_points:
        for name, date, mm, snow in rain_on_snow_points:
            parts.append(f"🔴 Rain-on-Snow: {name} — дождь {mm:.0f} мм на снег {snow:.0f} см ({date})")
    
    analysis["summary"] = ". ".join(parts) if parts else "Осадки минимальные по всему бассейну."
    
    # Alert text for TG/notifications
    alert_labels = {
        "none": "Осадки не влияют на паводок",
        "low": "Незначительные осадки — слабое влияние",
        "moderate": "Умеренные осадки — возможно ускорение подъёма",
        "high": "Значительные осадки — ускорение подъёма уровня",
        "critical": "КРИТИЧНО: дождь на снег — максимальное ускорение паводка",
    }
    analysis["alert_text"] = alert_labels.get(analysis["alert_level"], "")
    
    return analysis


def _wcode_to_text(code) -> str:
    """WMO weather code → русский текст."""
    if code is None:
        return "—"
    code = int(code)
    WMO = {
        0: "ясно", 1: "малооблачно", 2: "облачно", 3: "пасмурно",
        45: "туман", 48: "туман (изморозь)",
        51: "морось", 53: "морось (ум.)", 55: "морось (сильн.)",
        56: "морось (лёд)", 57: "морось (лёд, сильн.)",
        61: "дождь", 63: "дождь (ум.)", 65: "ливень",
        66: "лёд. дождь", 67: "лёд. дождь (сильн.)",
        71: "снег", 73: "снег (ум.)", 75: "снегопад",
        77: "крупа",
        80: "ливень (сл.)", 81: "ливень", 82: "ливень (сильн.)",
        85: "снег с дождём", 86: "снег с дождём (сильн.)",
        95: "гроза", 96: "гроза с градом", 99: "гроза с градом (сильн.)",
    }
    return WMO.get(code, f"код {code}")


def generate_precip_matrix_html(weather_data: dict) -> str:
    """
    Генерирует HTML-блок матрицы осадков по бассейну.
    Responsive: горизонтальный скролл на мобилках.
    """
    if not weather_data or weather_data.get("status") == "error":
        return ""
    
    points = weather_data.get("points", [])
    analysis = weather_data.get("analysis", {})
    
    if not points:
        return ""
    
    # Collect all dates (from first point that has data)
    dates = []
    for pt in points:
        if pt.get("days"):
            dates = [d["date"] for d in pt["days"]]
            break
    
    if not dates:
        return ""
    
    # Alert color
    alert_colors = {
        "none": "#10b981",
        "low": "#10b981", 
        "moderate": "#f59e0b",
        "high": "#f97316",
        "critical": "#ef4444",
    }
    alert_color = alert_colors.get(analysis.get("alert_level", "none"), "#64748b")
    
    # Date headers
    today = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d")
    
    def _fmt_date(d):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            dn = day_names[dt.weekday()]
            return f"{dn} {dt.day:02d}.{dt.month:02d}"
        except:
            return d[:10]
    
    def _precip_color(mm):
        if mm >= 10: return "#ef4444"
        if mm >= 5: return "#f97316"
        if mm >= 2: return "#f59e0b"
        if mm >= 0.5: return "#3b82f6"
        return "#94a3b8"
    
    def _precip_bg(mm):
        if mm >= 10: return "rgba(239,68,68,0.1)"
        if mm >= 5: return "rgba(249,115,22,0.1)"
        if mm >= 2: return "rgba(245,158,11,0.08)"
        return "transparent"
    
    # Build HTML
    html = f"""
<div style="margin:16px 0 8px;">
  <h4 style="margin:0 0 8px; font-size:0.95rem; color:var(--text-primary);">
    🌧️ Осадки по бассейну Оки (прогноз Open-Meteo)
  </h4>
  <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px; padding:8px 12px; border-radius:8px; background:{alert_color}10; border-left:3px solid {alert_color};">
    <span style="font-size:0.85rem; color:{alert_color}; font-weight:600;">{analysis.get('alert_text', '')}</span>
  </div>
  <div class="table-wrap">
    <table style="width:100%; border-collapse:collapse; font-size:0.78rem; min-width:600px;">
      <thead>
        <tr style="background:#f8fafc;">
          <th style="padding:6px 10px; text-align:left; border-bottom:2px solid var(--border); font-weight:600; color:var(--text-dim); min-width:100px;">Район</th>
"""
    
    for d in dates:
        is_today = (d == today)
        bg = "background:#eff6ff;" if is_today else ""
        html += f'          <th style="padding:6px 8px; text-align:center; border-bottom:2px solid var(--border); font-size:0.72rem; {bg}">{_fmt_date(d)}</th>\n'
    
    html += '          <th style="padding:6px 8px; text-align:center; border-bottom:2px solid var(--border); font-weight:700; color:var(--text-primary);">Σ 3д</th>\n'
    html += '        </tr>\n      </thead>\n      <tbody>\n'
    
    for pt in points:
        html += f'        <tr>\n'
        html += f'          <td style="padding:6px 10px; border-bottom:1px solid var(--border); font-weight:500;">'
        html += f'{pt["name"]}<br><span style="font-size:0.68rem; color:var(--text-dim);">{pt.get("role", "")}</span></td>\n'
        
        days_map = {d["date"]: d for d in pt.get("days", [])}
        
        for d in dates:
            day = days_map.get(d, {})
            mm = day.get("precip_mm", 0)
            weather = day.get("weather", "—")
            is_today = (d == today)
            bg = f"background:{_precip_bg(mm)};" if mm >= 0.5 else ""
            if is_today:
                bg = "background:#eff6ff;"
            
            cell = f"{mm:.1f}" if mm > 0 else "—"
            color = _precip_color(mm)
            
            html += f'          <td style="padding:6px 8px; text-align:center; border-bottom:1px solid var(--border); {bg}">'
            html += f'<span style="color:{color}; font-weight:{600 if mm >= 2 else 400};">{cell}</span>'
            if weather and weather != "—" and mm > 0:
                html += f'<br><span style="font-size:0.65rem; color:var(--text-dim);">{weather}</span>'
            html += '</td>\n'
        
        # Sum 3 days
        total_3d = pt.get("total_precip_3d", 0)
        html += f'          <td style="padding:6px 8px; text-align:center; border-bottom:1px solid var(--border); font-weight:700; color:{_precip_color(total_3d)};">{total_3d:.0f}</td>\n'
        html += '        </tr>\n'
    
    html += '      </tbody>\n    </table>\n  </div>\n'
    
    # Analysis summary
    summary = analysis.get("summary", "")
    if summary:
        html += f'  <div style="font-size:0.82rem; color:var(--text-secondary); margin:10px 0 4px; line-height:1.5;">{summary}</div>\n'
    
    html += '  <div style="font-size:0.72rem; color:var(--text-dim); margin-top:4px;">Источник: Open-Meteo API. Данные по координатам каждого района.</div>\n'
    html += '</div>\n'
    
    return html


# ─── Тест ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching multi-point weather...")
    data = fetch_multi_weather()
    print(f"Status: {data['status']}")
    print(f"Points: {len(data['points'])}")
    for pt in data["points"]:
        print(f"  {pt['name']}: 3d={pt['total_precip_3d']}mm, max={pt['max_daily_precip']}mm ({pt['max_daily_date']})")
    print(f"\nAnalysis:")
    for k, v in data["analysis"].items():
        print(f"  {k}: {v}")
