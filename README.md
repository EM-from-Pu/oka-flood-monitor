# 🌊 Ока Паводок 2026 — Мониторинг v3.0

**Страница:** https://em-from-pu.github.io/oka-flood-monitor/

## Что делает

- Парсит 5 постов: Орёл → Алексин → Калуга → Серпухов → Кашира
- Погода (OpenWeatherMap API)
- 12 аналитических if-то правил
- **Прогноз: N дней до порога домов (945 см) — крупно на странице**
- **Прогноз пика паводка — 3 сценария**
- TG-дайджест 08:00 и 18:00 МСК
- Черновик поста для группы соседей
- Мега-таблица с историей + погодой

## Secrets (Settings → Secrets → Actions)

| Секрет | Значение |
|--------|---------|
| `TG_TOKEN` | токен @OkaFlood2026_EM_bot |
| `TG_CHAT_ID` | `49747475` |
| `TG_GROUP_ID` | `-5234360275` |
| `WEATHER_API_KEY` | ключ с openweathermap.org (бесплатно) |

## Получить WEATHER_API_KEY (бесплатно)

1. https://openweathermap.org/api → Register
2. My API Keys → скопировать Default key
3. GitHub → Settings → Secrets → Actions → New → `WEATHER_API_KEY`
4. Ключ активируется через ~10 мин
