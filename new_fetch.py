import re, sys

src = open(sys.argv[1]).read()

NEW_FETCH = """
def fetch_level(url, name):
    slug = url.rstrip('/').split('/gauge/')[-1]
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; OkaMonitor/3.0)',
        'Referer': 'https://allrivers.info/',
    }
    # --- Источник 1: KIM API (официальный) ---
    try:
        kim = requests.get(
            'https://ris.kim-online.ru/api.php?demand=water_levels',
            headers=headers, timeout=15)
        if kim.status_code == 200:
            data = kim.json()
            # Ищем наш пост по slug/названию
            slug_map = {
                'oka-serpuhov': ['серпухов', 'serpukhov', 'serpuhov'],
                'oka-kaluga':   ['калуга', 'kaluga'],
                'oka-kashira':  ['кашира', 'kashira'],
                'oka-orel':     ['орел', 'орёл', 'orel'],
                'oka-shukina':  ['щукино', 'щукина', 'shukina', 'алексин', 'aleksin'],
            }
            keywords = slug_map.get(slug, [slug.replace('oka-','')])
            items = data if isinstance(data, list) else data.get('items', data.get('data', []))
            for item in items:
                name_field = str(item.get('name','') + item.get('title','') + item.get('post','')).lower()
                if any(k in name_field for k in keywords):
                    val = item.get('level') or item.get('value') or item.get('waterlevel')
                    if val is not None:
                        print(f"  {name}: {val} (KIM API)")
                        return int(float(val))
    except Exception as e:
        print(f"  {name}: KIM API error: {e}")
    # --- Источник 2: regions.ru парсинг для Серпухова ---
    if 'serpuh' in slug:
        try:
            r = requests.get(
                'https://serp.mk.ru/social/',
                headers=headers, timeout=15)
            # fallback: willmap.me
            r2 = requests.get(
                'https://willmap.me/uroven-vody-oka-g-serpuhov',
                headers=headers, timeout=15)
            for resp in [r2, r]:
                if resp.status_code == 200:
                    m = re.search(r'(\d{2,4})\s*(?:cm|см|</)', resp.text[:3000])
                    if m:
                        val = int(m.group(1))
                        if 50 < val < 1500:
                            print(f"  {name}: {val} (willmap/mk fallback)")
                            return val
        except Exception as e:
            print(f"  {name}: fallback error: {e}")
    # --- Источник 3: fishingsib.ru - отдаёт данные без JS ---
    fishmap = {
        'oka-serpuhov': 'serpuhov/bQniajySN3daftjV',
        'oka-kaluga':   'kaluzhskaya-oblast',
        'oka-orel':     'orel',
        'oka-kashira':  'kashira',
        'oka-shukina':  'aleksin',
    }
    if slug in fishmap:
        try:
            r = requests.get(
                f'https://www.fishingsib.ru/waterinfo/gauging-station/{fishmap[slug]}/',
                headers=headers, timeout=15)
            if r.status_code == 200:
                m = re.search(r'class="[^"]*level[^"]*"[^>]*>\\s*(-?\\d+)', r.text)
                if not m:
                    m = re.search(r'(-?\\d{2,4})\\s*(?:см|cm)', r.text[:2000])
                if m:
                    val = int(m.group(1))
                    if -300 < val < 1500:
                        print(f"  {name}: {val} (fishingsib)")
                        return val
        except Exception as e:
            print(f"  {name}: fishingsib error: {e}")
    print(f"  {name}: None (all methods failed)")
    return None


def fetch_snow_cover():
    \"\"\"Снеговой покров по регионам бассейна Оки\"\"\"
    regions = {
        'Орловская обл': (52.97, 36.07),
        'Тульская обл':  (54.19, 37.62),
        'Калужская обл': (54.51, 36.26),
    }
    result = {}
    WEATHER_API_KEY = os.environ.get('WEATHER_API_KEY','')
    if not WEATHER_API_KEY:
        return result
    for rname, (lat, lon) in regions.items():
        try:
            r = requests.get(
                f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}&units=metric&lang=ru',
                timeout=10)
            if r.status_code == 200:
                d = r.json()
                snow = d.get('snow', {}).get('1h', 0) or d.get('snow', {}).get('3h', 0)
                rain = d.get('rain', {}).get('1h', 0) or d.get('rain', {}).get('3h', 0)
                temp = d.get('main', {}).get('temp')
                desc = d.get('weather', [{}])[0].get('description', '')
                result[rname] = {'snow_mm': snow, 'rain_mm': rain, 'temp': temp, 'desc': desc}
        except Exception:
            pass
    return result

"""

# Заменяем старую fetch_level
old_match = re.search(r'\ndef fetch_level\(', src)
if not old_match:
    print("ERROR: fetch_level not found")
    sys.exit(1)

# Найдём конец функции - следующий def на том же уровне
rest = src[old_match.start():]
next_def = re.search(r'\n(?:def |class )', rest[1:])
if next_def:
    end_pos = old_match.start() + 1 + next_def.start()
else:
    end_pos = len(src)

new_src = src[:old_match.start()] + NEW_FETCH + src[end_pos:]
open(sys.argv[1], 'w').write(new_src)
print("OK: fetch_level + fetch_snow_cover injected")
