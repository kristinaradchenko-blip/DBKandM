# Telegram-бот со сводкой по кофейне (только чтение из iiko).
# Переменные окружения: TELEGRAM_BOT_TOKEN, IIKO_PASSWORD; TELEGRAM_CHAT_IDS (через запятую) нужны для утренней рассылки.
# Команды сейчас доступны всем, кто нашёл бота. Позже можно ограничить: TELEGRAM_RESTRICT=1 (тогда отвечает только чатам из TELEGRAM_CHAT_IDS).
#   python3 telegram_bot.py --send            отправить сводку за вчера всем из TELEGRAM_CHAT_IDS и выйти (для расписания 08:30)
#   python3 telegram_bot.py --send-truck     сводка по фудтраку за вчера (расписание 09:00)
#   добавьте --today к --send или --send-truck, чтобы отправить итоги сегодняшнего дня (вечерняя рассылка 22:30)
#   python3 telegram_bot.py --send-now       отправить промежуточный отчёт «на сейчас» (для расписания 13:00)
#   python3 telegram_bot.py --send --dry-run  то же, но только напечатать (работает и с --send-now)
#   python3 telegram_bot.py --run-all         бот + рассылки по расписанию в одном процессе (запуск с рабочего стола)
#   python3 telegram_bot.py                   работать постоянно и отвечать на команды (нужен сервер, который не выключается)
# Команды: /now (/today) — промежуточный отчёт, /yesterday (/y), /day ГГГГ-ММ-ДД, /id (покажет номер чата, отвечает всем, остальное только своим).
import json, os, sys, threading, time, urllib.parse, urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import morning
import daily_report
import foodtruck_report

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
RESTRICT = os.environ.get("TELEGRAM_RESTRICT") == "1"
ALLOWED = {c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()}
try:  # получатели рассылок из файла (по одному номеру чата в строке), в дополнение к переменной окружения
    ALLOWED |= {l.strip() for l in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "recipients.txt")) if l.strip().isdigit()}
except OSError:
    pass
API = "https://api.telegram.org/bot%s/" % TOKEN


def call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(API + method, data=data), timeout=70) as r:
        return json.loads(r.read().decode())


COMMANDS = [{"command": "cafe_morning", "description": "Кафе_Утро"},
            {"command": "cafe_day", "description": "Кафе_День"},
            {"command": "cafe_itogi", "description": "Кафе_Итоги"},
            {"command": "cafe_date", "description": "Кафе_Дата (пример: /cafe_date 8.10)"},
            {"command": "cafe_abc", "description": "Кафе_АБС"},
            {"command": "truck_morning", "description": "Трак_Утро"},
            {"command": "truck_day", "description": "Трак_День"},
            {"command": "truck_itogi", "description": "Трак_Итоги"},
            {"command": "truck_date", "description": "Трак_Дата (пример: /truck_date 8.10)"},
            {"command": "id", "description": "Номер этого чата"}]


def setup_menu():
    """Список команд в меню бота и кнопка «Меню» рядом с полем ввода."""
    cmds = json.dumps(COMMANDS, ensure_ascii=False)
    for scope in (None, {"type": "all_private_chats"}, {"type": "all_group_chats"}):
        extra = {"scope": json.dumps(scope)} if scope else {}
        call("setMyCommands", commands=cmds, **extra)
    call("setChatMenuButton", menu_button=json.dumps({"type": "commands"}))


def remove_buttons(chat_id):
    """Убрать кнопки под полем ввода, если они остались от прошлой версии бота."""
    call("sendMessage", chat_id=chat_id, text="Кнопки под полем ввода убраны, команды остались в меню.",
         reply_markup=json.dumps({"remove_keyboard": True}))


def send(chat_id, text, html=True):
    params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    if html:
        params["parse_mode"] = "HTML"
    return call("sendMessage", **params)


def report_for(day):
    return daily_report.build(day, daily_report.load(day), "html")


def report_now():
    now = daily_report.datetime.now(daily_report.MSK)
    return daily_report.build_now(now, daily_report.load_now(now.date()), "html")


def report_abc():
    return daily_report.build_abc(daily_report.load_abc(), "html")


def report_truck(day=None):
    day = day or date.today() - timedelta(days=1)
    return foodtruck_report.build(day, foodtruck_report.load(day), "html")


def report_truck_now():
    now = daily_report.datetime.now(daily_report.MSK)
    return foodtruck_report.build_now(now, foodtruck_report.load_now(now.date()), "html")


def send_daily(dry=False, now_report=False, truck=False, today=False, morning_kind=None, truck_now=False):
    day = date.today() if today else date.today() - timedelta(days=1)  # --today: итоги сегодняшнего дня (вечерняя рассылка)
    text = (report_morning(morning_kind) if morning_kind else report_truck_now() if truck_now else report_truck(day) if truck
            else report_now() if now_report else report_for(day))
    if dry:
        print(text)
        return
    if not ALLOWED:
        sys.exit("TELEGRAM_CHAT_IDS пуст: некому слать утреннюю сводку")
    for chat in sorted(ALLOWED):
        send(chat, text)
    print("отправлено в чатов:", len(ALLOWED))


def parse_day(text):
    """Дата из «8.10», «08.10.2026» или «2026-10-08»; без года берём текущий. None, если не разобрали."""
    t = text.strip().replace("/", ".")
    try:
        if "-" in t:
            return date.fromisoformat(t)
        p = [int(x) for x in t.split(".") if x]
        year = p[2] if len(p) > 2 else date.today().year
        return date(year + 2000 if year < 100 else year, p[1], p[0])
    except Exception:
        return None


def report_morning(kind):
    now = daily_report.datetime.now(daily_report.MSK)
    return morning.build(kind, now, morning.load(kind, now.date()), "html")


def handle(msg):
    chat = str(msg["chat"]["id"])
    parts = (msg.get("text") or "").strip().split()
    if not parts:
        return
    cmd = parts[0].split("@")[0].lower()
    if cmd in ("/id", "/start"):
        send(chat, "Номер этого чата: <code>%s</code>" % chat)
        return
    if RESTRICT and chat not in ALLOWED:
        send(chat, "Нет доступа. Отправьте номер чата владельцу бота.", html=False)
        return
    try:
        dated = ("/cafe_date", "/truck_date", "/day", "/truck")  # без даты в команде отчёт не считается
        slow = dated + ("/yesterday", "/y", "/cafe_day", "/now", "/today", "/truck_day", "/truck_now", "/cafe_itogi", "/truck_itogi", "/itogi",
                        "/cafe_abc", "/abc")
        if cmd in slow and (cmd not in dated or len(parts) > 1):  # эти отчёты считаются минутами
            send(chat, "⏳ Собираю отчёт, это может занять несколько минут.", html=False)
        arg = parts[1] if len(parts) > 1 else None
        if cmd in ("/yesterday", "/y"):
            day = date.today() - timedelta(days=1)
        elif cmd in ("/cafe_morning", "/truck_morning"):
            send(chat, report_morning("cafe" if cmd.startswith("/cafe") else "truck"))
            return
        elif cmd in ("/cafe_day", "/now", "/today"):
            send(chat, report_now())
            return
        elif cmd == "/truck_day" or cmd == "/truck_now":
            send(chat, report_truck_now())
            return
        elif cmd in ("/cafe_itogi", "/truck_itogi", "/itogi"):
            if cmd != "/truck_itogi":
                send(chat, report_for(date.today()))
            if cmd != "/cafe_itogi":
                send(chat, report_truck(date.today()))
            return
        elif cmd in ("/cafe_date", "/truck_date", "/day", "/truck"):
            day = parse_day(arg) if arg else None
            if not day:
                send(chat, "Напишите дату после команды, например: %s 8.10" % cmd, html=False)
                return
            if cmd != "/truck_date" and cmd != "/truck":
                send(chat, report_for(day))
            if cmd != "/cafe_date":
                send(chat, report_truck(day))
            return
        elif cmd in ("/cafe_abc", "/abc"):
            send(chat, report_abc())
            return
        else:
            send(chat, "Команды смотрите в меню бота: Кафе_ и Трак_ (утро, день, итоги дня, сводка за дату), Кафе_АБС.", html=False)
            return
        send(chat, report_for(day))
    except Exception as e:
        send(chat, "Не получилось собрать сводку: %s" % e, html=False)


# Расписание рассылок (время Пензы): (час, минута, название, аргументы для send_daily)
SCHEDULE = [(8, 0, "Кафе_Утро", {"morning_kind": "cafe"}),
            (8, 1, "Трак_Утро", {"morning_kind": "truck"}),
            (11, 30, "Кафе_День", {"now_report": True}),
            (11, 31, "Трак_День", {"truck_now": True}),
            (15, 0, "Кафе_День", {"now_report": True}),
            (15, 1, "Трак_День", {"truck_now": True}),
            (22, 15, "Кафе_Итоги", {"today": True}),
            (22, 16, "Трак_Итоги", {"truck": True, "today": True})]
LATE_MINUTES = 30  # опоздавший запуск (Mac спал) догоняем не позже чем через столько минут, старые отчёты не шлём


def due_jobs(now, done):
    """Задания, которым пора запуститься: время наступило, опоздание не больше LATE_MINUTES, сегодня ещё не слали."""
    out = []
    for h, m, name, kw in SCHEDULE:
        key = (now.date(), h, m)
        late = (now - now.replace(hour=h, minute=m, second=0, microsecond=0)).total_seconds() / 60
        if key not in done and 0 <= late <= LATE_MINUTES:
            out.append((key, name, kw))
    return out


def run_job(name, kw):
    try:
        print(time.strftime("%H:%M:%S"), "рассылка:", name, flush=True)
        send_daily(**kw)
    except BaseException as e:  # SystemExit из send_daily тоже ловим, чтобы не остановить расписание
        print("ошибка рассылки %s: %s" % (name, e), flush=True)


def scheduler():
    done = set()
    while True:
        now = daily_report.datetime.now(daily_report.MSK)
        for key, name, kw in due_jobs(now, done):
            done.add(key)
            threading.Thread(target=run_job, args=(name, kw), daemon=True).start()  # отчёт «День» считается минуты, не блокируем остальные
        time.sleep(20)


def poll():
    try:
        setup_menu()
    except Exception as e:
        print("не удалось обновить меню:", e)
    offset = 0
    while True:
        try:
            for upd in call("getUpdates", offset=offset, timeout=50).get("result", []):
                offset = upd["update_id"] + 1
                if "message" in upd:  # отчёты считаются минутами: каждую команду в своём потоке, чтобы бот не замолкал
                    threading.Thread(target=handle, args=(upd["message"],), daemon=True).start()
        except Exception as e:
            print("ошибка опроса:", e)
            time.sleep(5)


if __name__ == "__main__":
    if "--run-all" in sys.argv:
        print("Бот и расписание запущены. Окно не закрывайте.", flush=True)
        threading.Thread(target=scheduler, daemon=True).start()
        poll()
    elif "--setup-menu" in sys.argv:
        setup_menu()
        print("меню команд обновлено")
    elif any(f in sys.argv for f in ("--send", "--send-now", "--send-truck", "--send-truck-now", "--send-morning", "--send-truck-morning")):
        send_daily("--dry-run" in sys.argv, now_report="--send-now" in sys.argv, truck="--send-truck" in sys.argv, today="--today" in sys.argv,
                   morning_kind="cafe" if "--send-morning" in sys.argv else "truck" if "--send-truck-morning" in sys.argv else None,
                   truck_now="--send-truck-now" in sys.argv)
    else:
        poll()
