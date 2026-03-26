import re, sys

with open(sys.argv[1], 'r') as f:
    src = f.read()

# Находим старую функцию fetch_level и заменяем целиком
old = re.search(r'def fetch_level\(.*?\n(?=def |\nSTATIONS|^[A-Z])', src, re.DOTALL)
if not old:
    print("ERROR: fetch_level not found")
    sys.exit(1)

NEW_FUNC = '''def fetch_level(url, name):
    """Парсим уровень воды через JSON API allrivers.info"""
    import json as _json
    slug = url.rstrip("/").split("/gauge/")[-1]
    api_urls = [
        f"https://allrivers.info/gauge/{slug}/waterlevel.json",
        f"https://allrivers.info/api/waterlevel/{slug}/",
        f"https://allrivers.info/gauge/{slug}/waterlevel/",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Referer": "https://allrivers.info/",
    }
    # Попытка 1: JSON API
    try:
        r = requests.get(api_urls[0], headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            # Формат: [{"date":...,"level":NNN}, ...] или {"level":NNN}
            if isinstance(data, list) and data:
                val = data[-1].get("level") or data[-1].get("value") or data[-1].get("waterlevel")
                if val is not None:
                    print(f"  {name}: {val} (JSON API)")
                    return int(float(val))
            elif isinstance(data, dict):
                val = data.get("level") or data.get("value") or data.get("waterlevel")
                if val is not None:
                    print(f"  {name}: {val} (JSON dict)")
                    return int(float(val))
    except Exception as e:
        pass
    # Попытка 2: HTML парсинг с расширенными заголовками
    try:
        import time as _time
        _time.sleep(1)
        r = requests.get(api_urls[2], headers=headers, timeout=20)
        if r.status_code == 200:
            html = r.text
            # Паттерны для поиска уровня в HTML
            patterns = [
                r'"waterlevel"\s*:\s*(-?\\d+(?:\\.\\d+)?)',
                r'"level"\s*:\s*(-?\\d+(?:\\.\\d+)?)',
                r'waterlevel["\']\\s*:\\s*(-?\\d+)',
                r'<span[^>]*class="[^"]*level[^"]*"[^>]*>\\s*(-?\\d+)',
                r'уровень[^\\d]{0,30}(-?\\d{2,4})\\s*см',
                r'(-?\\d{2,4})\\s*(?:см|cm)',
            ]
            for p in patterns:
                m = re.search(p, html, re.IGNORECASE)
                if m:
                    val = int(float(m.group(1)))
                    if -200 < val < 2000:
                        print(f"  {name}: {val} (HTML regex)")
                        return val
    except Exception as e:
        print(f"[fetch_level] {name}: HTML error: {e}")
    # Попытка 3: snt-bugorok.ru как fallback только для Серпухова
    if "serpuhov" in slug or "serpukhov" in slug:
        try:
            r = requests.get(
                "https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-serpukhov-segodnya",
                headers=headers, timeout=15)
            if r.status_code == 200:
                m = re.search(r'(-?\\d{2,4})\\s*(?:см|cm|<)', r.text, re.IGNORECASE)
                if m:
                    val = int(float(m.group(1)))
                    if 50 < val < 2000:
                        print(f"  {name}: {val} (bugorok fallback)")
                        return val
        except Exception as e:
            pass
    print(f"  {name}: None (all methods failed)")
    return None

'''

src = src[:old.start()] + NEW_FUNC + src[old.end():]

with open(sys.argv[1], 'w') as f:
    f.write(src)
print("OK: fetch_level replaced")
