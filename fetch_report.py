#!/usr/bin/env python3
"""
fetch_report.py — v1.0 | 26.03.2026
Watchdog: обнаруживает новый PDF-отчёт в docs/reports/,
делает git push и шлёт уведомление в Telegram.
Запускается launchd в 10:15 каждый день.
"""
import os, re, subprocess, datetime, json, requests
from pathlib import Path

# ─── НАСТРОЙКИ ───────────────────────────────────────────────────────────────
REPO_DIR    = Path("/Users/admin/Downloads/oka_v3")
REPORTS_DIR = REPO_DIR / "docs" / "reports"
DOCS_DIR    = REPO_DIR / "docs"

TG_TOKEN       = os.environ.get("TG_TOKEN", "8715561124:AAFxyNB3j1BgNa1vtAbqPEw7ATMaBLovPbo")
CHAT_ADMIN     = int(os.environ.get("CHAT_ADMIN", "49747475"))
CHAT_GROUP     = int(os.environ.get("TG_GROUP_ID", "-5234360275"))
CHAT_NEIGHBORS = int(os.environ.get("TG_NEIGHBORS_ID", "-1001672586477"))

BASE_URL = "https://em-from-pu.github.io/oka-flood-monitor"
STATE_FILE = REPO_DIR / "data" / "last_report_sent.txt"
# ─────────────────────────────────────────────────────────────────────────────

def tg_send(chat_id, text):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15
        )
        print(f"  TG→{chat_id}: {r.status_code}")
    except Exception as e:
        print(f"  TG err: {e}")

def find_todays_report():
    """Ищет PDF с сегодняшней датой в docs/reports/"""
    today = datetime.date.today()
    patterns = [
        f"*{today.strftime('%d.%m.%Y')}*.pdf",
        f"*{today.strftime('%Y-%m-%d')}*.pdf",
        f"*{today.strftime('%d_%m_%Y')}*.pdf",
    ]
    for pattern in patterns:
        found = list(REPORTS_DIR.glob(pattern))
        if found:
            return found[0]
    return None

def already_sent(pdf_path):
    """Проверяем, не отправляли ли уже уведомление об этом файле"""
    if not STATE_FILE.exists():
        return False
    return STATE_FILE.read_text().strip() == str(pdf_path.name)

def mark_sent(pdf_path):
    STATE_FILE.write_text(pdf_path.name)

def update_reports_index():
    """Обновляет docs/reports_index.json для сайта"""
    reports = sorted(REPORTS_DIR.glob("*.pdf"), reverse=True)
    items = []
    for f in reports:
        m = re.search(r'(\d{2})\.(\d{2})\.(\d{4})', f.name)
        if m:
            label = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
            iso   = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        else:
            label, iso = f.stem, "0000-00-00"
        items.append({"date": iso, "label": label, "file": f"reports/{f.name}"})
    idx = DOCS_DIR / "reports_index.json"
    idx.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    print(f"  reports_index.json обновлён: {len(items)} записей")

def git_push(pdf_path):
    try:
        subprocess.run(["git", "add", str(pdf_path),
                        str(DOCS_DIR / "reports_index.json")],
                       cwd=REPO_DIR, check=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"report {datetime.date.today()}"],
            cwd=REPO_DIR, capture_output=True, text=True
        )
        if "nothing to commit" in result.stdout:
            print("  git: нечего коммитить (уже закоммичено)")
        else:
            subprocess.run(["git", "push", "origin", "main"],
                           cwd=REPO_DIR, check=True)
            print("  git push ✅")
    except subprocess.CalledProcessError as e:
        print(f"  git err: {e}")

def notify_tg(pdf_path):
    date_str = datetime.date.today().strftime("%d.%m.%Y")
    url = f"{BASE_URL}/reports/{pdf_path.name}"
    text = (
        f"📋 <b>Аналитический отчёт — {date_str}</b>\n"
        f"🌊 Паводок на Оке | Ежедневный мониторинг\n\n"
        f"🔗 <a href='{url}'>Открыть PDF-отчёт</a>\n"
        f"📊 Данные онлайн: {BASE_URL}"
    )
    tg_send(CHAT_ADMIN, text)
    tg_send(CHAT_GROUP, text)
    tg_send(CHAT_NEIGHBORS, text)

def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[fetch_report v1.0] {now}")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    pdf = find_todays_report()
    if not pdf:
        print(f"  Отчёт за сегодня не найден в {REPORTS_DIR}")
        return

    print(f"  Найден: {pdf.name}")

    if already_sent(pdf):
        print("  Уже отправляли — пропускаем")
        return

    update_reports_index()
    git_push(pdf)
    notify_tg(pdf)
    mark_sent(pdf)
    print("  Готово ✅")

if __name__ == "__main__":
    main()
