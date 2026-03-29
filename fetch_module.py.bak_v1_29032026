import re, requests, os

_H = {"User-Agent": "Mozilla/5.0 (compatible; OkaMonitor/3.0)"}

STATIONS = [
    {"name": "Орёл",           "slug": "oka-orel",     "fish": "orel/yhWo8bhntMxogJp7",         "lag_h": 96},
    {"name": "Белев",          "slug": "oka-belev",    "fish": "belev/Cmb6SN4xu3Tosu9k",        "lag_h": 72},
    {"name": "Калуга",         "slug": "oka-kaluga",   "fish": "kaluga/uDT4nYcJiH3fT4wB",       "lag_h": 48},
    {"name": "Щукина/Алексин", "slug": "oka-shukina",  "fish": "shchukina/72BPEWHZX5spRFTV",    "lag_h": 24},
    {"name": "Серпухов",       "slug": "oka-serpuhov", "fish": "serpuhov/bQniajySN3daftjV",      "lag_h": 0},
    {"name": "Кашира",         "slug": "oka-kashira",  "fish": "kashira/LcwHYZCR2iqvgViW",      "lag_h": -12},
    {"name": "Коломна",        "slug": "oka-kolomna",  "fish": "kolomna/JKcyzRFgSafZRdAX",      "lag_h": -24},
]

def _fishingsib(fish_slug):
    try:
        r = requests.get(
            "https://www.fishingsib.ru/waterinfo/gauging-station/" + fish_slug + "/",
            headers=_H, timeout=20)
        if r.status_code != 200:
            return None
        m = re.search(r'data-current="(-?\d+)"', r.text)
        if m:
            val = int(m.group(1))
            if -500 < val < 2000:
                return val
    except Exception as e:
        print("  fishingsib err:", e)
    return None

def fetch_level(url, name):
    slug = url.rstrip("/").split("/gauge/")[-1]
    st = next((s for s in STATIONS if s["slug"] == slug), None)
    if st and st["fish"]:
        val = _fishingsib(st["fish"])
        if val is not None:
            pass  # B4 fixed: print убран, monitor.py выводит сам
            return val
    print("  " + name + ": None")
    return None

def fetch_snow_cover():
    regions = {
        "Орловская обл": (52.97, 36.07),
        "Тульская обл":  (54.19, 37.62),
        "Калужская обл": (54.51, 36.26),
    }
    result = {}
    key = os.environ.get("WEATHER_API_KEY", "")
    if not key:
        return result
    for rname, (lat, lon) in regions.items():
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"lat": lat, "lon": lon, "appid": key, "units": "metric", "lang": "ru"},
                timeout=10)
            if r.status_code == 200:
                d = r.json()
                result[rname] = {
                    "snow_mm": (d.get("snow") or {}).get("1h", 0) or (d.get("snow") or {}).get("3h", 0),
                    "rain_mm": (d.get("rain") or {}).get("1h", 0) or (d.get("rain") or {}).get("3h", 0),
                    "temp":    (d.get("main") or {}).get("temp"),
                    "desc":    ((d.get("weather") or [{}])[0]).get("description", ""),
                }
        except Exception:
            pass
    return result

if __name__ == "__main__":
    print("=== Тест всех постов ===")
    for s in STATIONS:
        fetch_level("https://allrivers.info/gauge/" + s["slug"], s["name"])
