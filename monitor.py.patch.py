import re, sys

src = open(sys.argv[1]).read()

NEW_FETCH = r"""
FISHINGSIB_MAP = {
    'oka-orel':     'orel/yhWo8bhntMxogJp7',
    'oka-kaluga':   'kaluga/pAVqHdBwrNKcLmFE',
    'oka-shukina':  'shchukina/72BPEWHZX5spRFTV',
    'oka-serpuhov': 'serpuhov/bQniajySN3daftjV',
    'oka-kashira':  'kashira/LcwHYZCR2iqvgViW',
    'oka-belev':    'belev/KGxNzQmPtWsRvYjA',
}

def fetch_level_fishingsib(slug):
    """Парсим fishingsib.ru - статический HTML, без JS.
    Структура страницы: max / min / CURRENT (3-е число в блоке)"""
    fish_slug = FISHINGSIB_MAP.get(slug)
    if not fish_slug:
        return None
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; OkaMonitor/3.0)'}
    try:
        r = requests.get(
            f'https://www.fishingsib.ru/waterinfo/gauging-station/{fish_slug}/',
            headers=headers, timeout=20)
        if r.status_code != 200:
            return None
        # Ищем блок с тремя числами: max / min / current
        # Паттерн: три числа подряд с возможным знаком минус
        numbers = re.findall(r'(-?\d+)\n\n(-?\d+)\n\n(-?\d+)', r.text)
        if numbers:
            current = int(numbers[0][2])
            if -500 < current < 2000:
                return current
        # Fallback: ищем фразу "Уровень воды N см"
        m = re.search(r'Уровень воды (-?\d+) см', r.text)
        if m:
            return int(m.group(1))
    except Exception as e:
        print(f'    fishingsib error ({slug}): {e}')
    return None

def fetch_level(url, name):
    """Получаем уровень воды. Основной источник: fishingsib.ru"""
    slug = url.rstrip('/').split('/gauge/')[-1]
    # --- Источник 1: fishingsib.ru (статический HTML, без JS) ---
    val = fetch_level_fishingsib(slug)
    if val is not None:
        print(f'  {name}: {val} (fishingsib)')
        return val
    # --- Источник 2: snt-bugorok.ru (только для Серпухова и Калуги) ---
    bugorok_map = {
        'oka-serpuhov': 'https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-serpukhov-segodnya',
        'oka-kaluga':   'https://www.snt-bugorok.ru/level/uroven-vody-v-oke-u-g-kaluga-segodnya',
        'oka-kashira':  'https://www.snt-bugorok.ru/level/uroven-vody-v-reke-oka-u-g-kashira-segodnya',
        'oka-orel':     'https://www.snt-bugorok.ru/level/uroven-vody-v-oke-g-orel-segodnya',
    }
    if slug in bugorok_map:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (compatible; OkaMonitor/3.0)'}
            r = requests.get(bugorok_map[slug], headers=headers, timeout=15)
            if r.status_code == 200:
                m = re.search(r'(-?\d{2,4})\s*(?:см|cm)', r.text[:5000])
                if m:
                    v = int(m.group(1))
                    if -500 < v < 2000:
                        print(f'  {name}: {v} (bugorok)')
                        return v
        except Exception as e:
            print(f'  {name}: bugorok error: {e}')
    print(f'  {name}: None (all methods failed)')
    return None


def fetch_snow_cover():
    """Снеговой покров по регионам бассейна Оки через OpenWeatherMap"""
    regions = {
        'Орловская обл': (52.97, 36.07),
        'Тульская обл':  (54.19, 37.62),
        'Калужская обл': (54.51, 36.26),
    }
    result = {}
    key = os.environ.get('WEATHER_API_KEY', '')
    if not key:
        return result
    for rname, (lat, lon) in regions.items():
        try:
            r = requests.get(
                f'https://api.openweathermap.org/data/2.5/weather'
                f'?lat={lat}&lon={lon}&appid={key}&units=metric&lang=ru',
                timeout=10)
            if r.status_code == 200:
                d = r.json()
                snow = (d.get('snow') or {}).get('1h', 0) or (d.get('snow') or {}).get('3h', 0)
                rain = (d.get('rain') or {}).get('1h', 0) or (d.get('rain') or {}).get('3h', 0)
                temp = (d.get('main') or {}).get('temp')
                desc = (d.get('weather') or [{}])[0].get('description', '')
                result[rname] = {'snow_mm': snow, 'rain_mm': rain, 'temp': temp, 'desc': desc}
        except Exception:
            pass
    return result

"""

old_match = re.search(r'\ndef fetch_level\(', src)
if not old_match:
    print("ERROR: fetch_level not found"); sys.exit(1)

rest = src[old_match.start():]
next_def = re.search(r'\n(?:def |class )', rest[1:])
end_pos = (old_match.start() + 1 + next_def.start()) if next_def else len(src)

# Удаляем старые FISHINGSIB_MAP и fetch_level_fishingsib если уже есть
clean_src = re.sub(r'\nFISHINGSIB_MAP\s*=.*?(?=\ndef |\nclass |\Z)', '', src[:old_match.start()], flags=re.DOTALL)
clean_src = re.sub(r'\ndef fetch_level_fishingsib\(.*?(?=\ndef |\nclass |\Z)', '', clean_src, flags=re.DOTALL)
clean_src = re.sub(r'\ndef fetch_snow_cover\(.*?(?=\ndef |\nclass |\Z)', '', clean_src, flags=re.DOTALL)

new_src = clean_src + NEW_FETCH + src[end_pos:]
open(sys.argv[1], 'w').write(new_src)
print("OK: fetch_level + fetch_snow_cover + FISHINGSIB_MAP — all injected cleanly")
