#!/usr/bin/env python3
"""fetch_2024.py — скачивает архив уровней 2024 года с allrivers.info"""
import json, time, re, os
import urllib.request

STATIONS_2024 = [
    {"key": "orel",      "slug": "oka-orel"},
    {"key": "belev",     "slug": "oka-belev"},
    {"key": "kaluga",    "slug": "oka-kaluga"},
    {"key": "shukina",   "slug": "oka-shukina"},
    {"key": "serpukhov", "slug": "oka-serpuhov"},
    {"key": "kashira",   "slug": "oka-kashira"},
    {"key": "kolomna",   "slug": "oka-kolomna"},
]

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ref_2024.json")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 OkaMonitor/1.0"}

def fetch_archive(slug):
    url = f"https://allrivers.info/gauge/{slug}/waterlevel/"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # ищем JSON-массив с историческими данными в <script>
        m = re.search(r'var\s+chartData\s*=\s*(\[.*?\]);', html, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            # фильтруем 2024
            y2024 = [d for d in data if str(d.get("date","")).startswith("2024")]
            print(f"  {slug}: {len(y2024)} записей 2024")
            return y2024
        # запасной вариант — ищем другой паттерн
        m2 = re.search(r'"series":\s*\[.*?"data":\s*(\[.*?\])', html, re.DOTALL)
        if m2:
            data = json.loads(m2.group(1))
            print(f"  {slug}: {len(data)} записей (raw)")
            return data
        print(f"  {slug}: данные не найдены в HTML")
        return []
    except Exception as e:
        print(f"  {slug}: ошибка — {e}")
        return []

result = {}
for st in STATIONS_2024:
    print(f"Загружаем {st['key']} ({st['slug']})...")
    result[st["key"]] = fetch_archive(st["slug"])
    time.sleep(1.5)  # вежливая пауза

with open(OUT, "w") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in result.values())
print(f"\nГотово! Сохранено {total} записей → {OUT}")
