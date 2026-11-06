# Ежедневная сводка по кофейне для управляющих (только чтение, фудтрак не включён).
# Запуск: python3 daily_report.py [ГГГГ-ММ-ДД; по умолчанию вчера] [--telegram]
#         python3 daily_report.py --now [--at ЧЧ:ММ]   промежуточный отчёт на сейчас
#         python3 daily_report.py --abc                ABC-анализ кухни и десертов за 30 дней
# С --telegram текст размечен для parse_mode=HTML (справочный блок курсивом).
# Печатает готовый текст сообщения (подходит для Telegram).
import weather
import re
import getpass, hashlib, html, json, os, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

BASE = "https://gussi-penza.iiko.it/resto/api"
LOGIN = "Kris"
FREE_PRICE = "Свободная цена"
# Разделы меню iiko -> категории топа. Модификаторы и «Конструктор» (хлеб, намазки, добавки) в топ не идут.
SKIP_PARENTS = {"Модификаторы"}
SKIP_SECOND = {"Конструктор"}
SKIP_GROUPS = {"Чтобы стало вкуснее"}
DRINK_SECOND = {"Напитки", "Пиво, сидр"}
DESSERT_SECOND = {"Десерты"}
CATEGORIES = [("drinks", "🥤 Напитки"), ("desserts", "🍰 Десерты"), ("food", "🍳 Еда")]
# Добавки к напитку: модификаторы, привязанные к напитку, и отдельные позиции из «Чтобы стало вкуснее»
ADDON_GROUPS = {"Чтобы стало вкуснее"}
ADDON_DISHES = {"Доп шот"}
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]


def get(url, data=None):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)


def olap(key, rows_by, aggs, start, end):
    body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                       "groupByRowFields": rows_by, "aggregateFields": aggs,
                       "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                      "from": start.isoformat(), "to": end.isoformat(),
                                                      "includeLow": "true", "includeHigh": "false"}}}).encode()
    return json.loads(get(BASE + "/v2/reports/olap?key=" + key, body)).get("data", [])


def rub(x):
    return "{:,.0f}".format(x).replace(",", " ") + " ₽"


def pct(a, b):
    if not b:
        return ""
    p = round((a / b - 1) * 100)
    return ("%+d%%" % p).replace("-", "−") if p else "±0%"


def chk_word(n):
    if n % 10 == 1 and n % 100 != 11:
        return "чек"
    return "чека" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "чеков"


def times(n):
    return "раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "раз"


def category(r):
    if r.get("DishGroup.TopParent") in SKIP_PARENTS or r.get("DishGroup.SecondParent") in SKIP_SECOND \
            or r.get("DishGroup") in SKIP_GROUPS or r.get("DishName") == FREE_PRICE:
        return None
    if r.get("DishGroup.SecondParent") in DRINK_SECOND:
        return "drinks"
    if r.get("DishGroup.SecondParent") in DESSERT_SECOND:
        return "desserts"
    return "food"


def addon_kind(name, group):
    """Вид добавки по модификатору или None, если это обычный выбор (коровье молоко, без сиропа, сахар, корица)."""
    n, g = name.lower(), (group or "").lower()
    if "без " in n:
        return None
    if "сироп" in n or "сироп" in g:
        return "сироп"
    if "молоко" in n or "альтернативн" in g:
        return None if "коровье" in n else "альт. молоко"
    if "маршмеллоу" in n or "шоколад" in n or "сливки" in n or "шот" in n:
        return "другое"
    return None


# Напитки, к которым могут быть добавки (сироп, альтернативное молоко и т. д.): считаются в показателе «Напитки с добавками»
ADDON_DRINK_PREFIXES = ("капучино", "латте", "флэт уайт", "американо", "раф", "бамбл", "айс латте", "айс капучино",
                        "какао", "матча зеленая", "матча зелёная", "матча голубая")


# Сезонные напитки идут с уже включённым сиропом, поэтому в расчёт добавок не входят
SEASONAL_GROUPS = {"Осенние напитки", "Зимние напитки", "Весенние напитки", "Летние напитки"}


def is_addon_drink(name, group=None):
    return group not in SEASONAL_GROUPS and (name or "").strip().lower().startswith(ADDON_DRINK_PREFIXES)


# Напитки, к которым ждём десерт: любой кофе, какао, чай и матча, в том числе сезонные
NO_DESSERT_GROUPS = {"Фреш/коктейли", "Напитки бутылированные", "Пиво, сидр"}
SEASONAL_DESSERT_PREFIXES = ("капучино", "латте", "раф", "какао", "айс", "эспрессо", "американо", "флэт", "матча")


def is_dessert_drink(name, group):
    n = (name or "").strip().lower()
    if group in NO_DESSERT_GROUPS or group in ADDON_GROUPS or n.startswith("доп шот"):
        return False
    if group in SEASONAL_GROUPS:
        return n.startswith(SEASONAL_DESSERT_PREFIXES) or "чай" in n
    return True


def check_stats(lines):
    """По строкам чеков: (чеков с напитком, из них с десертом, напитков, напитков с добавкой, {вид: кол-во})."""
    by_id = {r["ItemSaleEvent.Id"]: r for r in lines}
    orders = {}
    for r in lines:
        o = orders.setdefault(r["UniqOrderId.Id"], {"drinks": 0, "core": 0, "dd": 0, "dq": 0, "dessert": False, "loose": {}})
        qty = r["DishAmountInt"] or 0
        if qty <= 0:
            continue
        if r.get("SoldWithItem.Id"):
            parent = by_id.get(r["SoldWithItem.Id"])
            kind = addon_kind(r["DishName"], r.get("DishGroup"))
            if parent and kind and is_addon_drink(parent["DishName"], parent.get("DishGroup")):
                o.setdefault("with", {}).setdefault(parent["ItemSaleEvent.Id"], (parent["DishAmountInt"], kind))
            continue
        if r.get("DishGroup") in ADDON_GROUPS or r["DishName"] in ADDON_DISHES:
            kind = addon_kind(r["DishName"], r.get("DishGroup")) or "другое"
            o["loose"][kind] = o["loose"].get(kind, 0) + qty
            continue
        c = category(r)
        if c == "drinks":
            o["drinks"] += qty
            if is_addon_drink(r["DishName"], r.get("DishGroup")):
                o["core"] += qty
            if is_dessert_drink(r["DishName"], r.get("DishGroup")):
                o["dd"] += qty
        elif c == "desserts":
            o["dessert"] = True
            o["dq"] += qty
    with_drink = with_dessert = drinks = filled = 0
    kinds = {}
    for o in orders.values():
        if not o["drinks"]:
            continue
        with_drink += o["dd"]
        with_dessert += o["dq"] if o["dd"] else 0
        drinks += o["core"]
        n = 0
        for qty, kind in o.get("with", {}).values():
            kinds[kind] = kinds.get(kind, 0) + qty
            n += qty
        # отдельно пробитые добавки считаем по одной на напиток, но не больше, чем напитков в чеке
        for kind, qty in o["loose"].items():
            add = min(qty, o["core"] - n)
            if add > 0:
                kinds[kind] = kinds.get(kind, 0) + add
                n += add
        filled += min(n, o["core"])
    return with_drink, with_dessert, drinks, filled, kinds


LINE_FIELDS = ["UniqOrderId.Id", "ItemSaleEvent.Id", "SoldWithItem.Id", "DishName",
               "DishGroup.TopParent", "DishGroup.SecondParent", "DishGroup"]


def attendance_starts(base, key, day):
    """Время входа сотрудников в систему (явки) за день, список строк ISO. При ошибке пустой список."""
    try:
        xml = get("%s/employees/attendance/?key=%s&from=%s&to=%s" % (base, key, day.isoformat(), (day + timedelta(days=1)).isoformat()))
        return re.findall(r"<dateFrom>([^<]+)</dateFrom>", xml)
    except Exception:
        return []


def _load(day):
    pwd = os.environ.get("IIKO_PASSWORD") or getpass.getpass("Пароль Kris (на экране не виден): ")
    key = get(BASE + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": hashlib.sha1(pwd.encode()).hexdigest()})).strip()
    try:
        nxt = day + timedelta(days=1)
        return {
            # 4 прошлых таких же дня недели + сам день, по часам
            "hours": olap(key, ["OpenDate.Typed", "HourOpen"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], day - timedelta(days=28), nxt),
            "daily": olap(key, ["OpenDate.Typed"], ["DishDiscountSumInt", "DishSumInt", "DiscountSum", "UniqOrderId.OrdersCount"], day - timedelta(days=28), nxt),
            "dishes": olap(key, ["DishGroup.TopParent", "DishGroup.SecondParent", "DishGroup", "DishName"], ["DishDiscountSumInt", "DishAmountInt"], day, nxt),
            "disc": olap(key, ["UniqOrderId.Id", "OrderDiscount.Type"], ["DiscountSum", "DishSumInt"], day, nxt),
            "lines": olap(key, LINE_FIELDS, ["DishAmountInt"], day, nxt),
            "lines_prev": olap(key, LINE_FIELDS, ["DishAmountInt"], day - timedelta(days=7), day - timedelta(days=6)),
            "free30": olap(key, ["OpenDate.Typed", "DishName"], ["DishAmountInt"], day - timedelta(days=30), day),
            "opens": attendance_starts(BASE, key, day),
        }
    finally:
        get(BASE + "/logout?key=" + key)


def load(day):
    data = _load(day)
    try:
        import insights  # отложенный импорт: insights сам использует этот модуль
        data["insights"] = insights.build(day, insights.load(day, weeks=1))  # итоги сравниваем с прошлой неделей, как и шапку отчёта
    except Exception:
        data["insights"] = []  # выводы необязательны: отчёт уходит и без них
    return data


def first_open(starts, day):
    """Самое раннее время входа в систему за день в виде ЧЧ:ММ или None."""
    times = [t for t in starts if t.startswith(day.isoformat())]
    return min(times)[11:16] if times else None


def build(day, d, fmt="plain"):
    week_ago = day - timedelta(days=7)
    same_days = [(day - timedelta(days=7 * i)).isoformat() for i in range(1, 5)]
    daily = {r["OpenDate.Typed"]: r for r in d["daily"]}
    hours = {}
    for r in d["hours"]:
        hours.setdefault(r["OpenDate.Typed"], {})[int(r["HourOpen"])] = r
    t, p = daily.get(day.isoformat(), {}), daily.get(week_ago.isoformat(), {})
    rev, chk = t.get("DishDiscountSumInt", 0), t.get("UniqOrderId.OrdersCount", 0)
    prev, pchk = p.get("DishDiscountSumInt", 0), p.get("UniqOrderId.OrdersCount", 0)
    avg, pavg = (rev / chk if chk else 0), (prev / pchk if pchk else 0)

    lines = ["☕ Кафе · %s, %s, %d %s" % ("Итоги дня" if day == date.today() else "Сводка за дату", WEEKDAYS[day.weekday()], day.day, MONTHS[day.month - 1]), ""]
    lines += ["Выручка: %s (%s к прошлой неделе)" % (rub(rev), pct(rev, prev)),
              "Чеков: %d (%s)" % (chk, pct(chk, pchk)),
              "Средний чек: %s (%s)" % (rub(avg), pct(avg, pavg))]
    start = first_open(d.get("opens", []), day)
    if start:
        lines.append("Начало работы: %s (вход в систему)" % start)
    lines.append("")

    # Часы пик: лучшие 3 часа подряд
    h = hours.get(day.isoformat(), {})
    if h:
        best = max(range(min(h), max(h) - 1), key=lambda s: sum(h.get(s + i, {}).get("DishDiscountSumInt", 0) for i in range(3)), default=min(h))
        peak = sum(h.get(best + i, {}).get("DishDiscountSumInt", 0) for i in range(3))
        lines.append("⏰ Пик: %02d:00–%02d:00, %d%% выручки" % (best, best + 3, round(peak / rev * 100) if rev else 0))

    # Что берут вместе с напитком
    wd, wds, dr, fl, kinds = check_stats(d["lines"])
    pwd_, pwds, pdr, pfl, _ = check_stats(d["lines_prev"])
    if wd:
        def share(a, b):
            return round(a / b * 100) if b else 0
        kinds_txt = ", ".join("%s %d" % (k, v) for k, v in sorted(kinds.items(), key=lambda kv: -kv[1]))
        lines += ["", "🧾 В чеках",
                  "• Десертов к напиткам (кофе, какао, чай, матча): %d к %d (%d%%, неделю назад %d%%)" % (wds, wd, share(wds, wd), share(pwds, pwd_)),
                  "• Кофе, какао и матча с добавками: %d из %d (%d%%, неделю назад %d%%)%s" % (fl, dr, share(fl, dr), share(pfl, pdr), ": " + kinds_txt if kinds_txt else "")]

    # Скидки: общая сумма и разбивка по видам
    full, disc = t.get("DishSumInt", 0), t.get("DiscountSum", 0)
    pfull, pdisc = p.get("DishSumInt", 0), p.get("DiscountSum", 0)
    if full:
        lines += ["", "🏷 Скидки: %s (%d%% от суммы чеков, неделю назад %d%%)"
                  % (rub(disc), round(disc / full * 100), round(pdisc / pfull * 100) if pfull else 0)]
        # Чеки со скидкой, сгруппированные по размеру скидки в чеке (округляем до 10%)
        buckets = {}
        for r in d["disc"]:
            if (r["DiscountSum"] or 0) > 0 and r["DishSumInt"]:
                pc = max(10, int(r["DiscountSum"] / r["DishSumInt"] * 10 + 0.5) * 10)
                b_ = buckets.setdefault(pc, {"n": 0, "sum": 0, "types": {}})
                b_["n"] += 1
                b_["sum"] += r["DiscountSum"]
                name = r["OrderDiscount.Type"] or "без названия"
                b_["types"][name] = b_["types"].get(name, 0) + 1
        for pc in sorted(buckets):
            b_ = buckets[pc]
            top_types = ", ".join(k for k, _ in sorted(b_["types"].items(), key=lambda kv: -kv[1])[:2])
            lines.append("• %d%% — %d %s · %s (%s)" % (pc, b_["n"], chk_word(b_["n"]), rub(b_["sum"]), top_types))

    notes = []
    # 1. Касса молчала в часы, когда обычно идут чеки
    usual_last = sorted(max(hours[s]) for s in same_days if s in hours)
    if h and usual_last and max(h) < usual_last[len(usual_last) // 2] - 1:
        cut = max(h) + 1
        ev = [sum(r["UniqOrderId.OrdersCount"] for hr, r in hours[s].items() if hr >= cut) for s in same_days if s in hours]
        ev_rev = [sum(r["DishDiscountSumInt"] for hr, r in hours[s].items() if hr >= cut) for s in same_days if s in hours]
        before = sum(r["DishDiscountSumInt"] for hr, r in hours.get(week_ago.isoformat(), {}).items() if hr < cut)
        notes.append("После %02d:00 ни одного чека. Обычно в эти часы %d–%d чеков, около %s. "
                     "Закрылись раньше или касса не передала данные? До %02d:00 день шёл %s к прошлой неделе."
                     % (cut, min(ev), max(ev), rub(round(sum(ev_rev) / len(ev_rev), -3)), cut, pct(rev, before)))
    # 2. Выручка сильно отличается от обычной для этого дня недели
    elif prev and abs(rev / prev - 1) >= 0.15:
        notes.append("Выручка %s к прошлой неделе. Стоит понять причину: погода, событие, смена." % pct(rev, prev))
    # 3. Много продаж по «Свободной цене»
    free = sum(r["DishAmountInt"] for r in d["dishes"] if r["DishName"] == FREE_PRICE)
    free_sum = sum(r["DishDiscountSumInt"] for r in d["dishes"] if r["DishName"] == FREE_PRICE)
    hist = [r["DishAmountInt"] for r in d["free30"] if r["DishName"] == FREE_PRICE]
    usual_max = max(hist) if hist else 0
    if free >= 10 and free > usual_max:
        notes.append("«Свободная цена» пробита %d %s на %s, обычно до %d %s в день. Проверьте, что продавали."
                     % (free, times(free), rub(free_sum), usual_max, times(usual_max)))
    # 4. Скидки выше обычного и скидки 100%
    usual = [daily[x]["DiscountSum"] / daily[x]["DishSumInt"] for x in same_days if x in daily and daily[x].get("DishSumInt")]
    usual_share = sum(usual) / len(usual) if usual else 0
    if full and disc / full >= max(0.15, usual_share + 0.05):
        notes.append("Скидки %d%% от суммы чеков, обычно около %d%%." % (round(disc / full * 100), round(usual_share * 100)))
    free_orders = [r for r in d["disc"] if r["DishSumInt"] and ((r["DiscountSum"] or 0) / r["DishSumInt"] >= 0.98 or "100%" in (r["OrderDiscount.Type"] or ""))]
    if free_orders:
        notes.append("Есть чеки со скидкой 100%%: %d %s на %s. Проверьте, кто и зачем их провёл."
                     % (len(free_orders), chk_word(len(free_orders)), rub(sum(r["DiscountSum"] for r in free_orders))))

    notes += d.get("insights", [])
    if notes:
        lines += ["", "⚠️ Обратите внимание:"] + ["• " + n for n in notes]
    split = len(lines)
    # Топ-3 в каждой категории; одно блюдо может лежать в нескольких группах, поэтому суммируем по названию
    by_cat = {}
    for r in d["dishes"]:
        c = category(r)
        if c and r["DishDiscountSumInt"]:
            agg = by_cat.setdefault(c, {}).setdefault(r["DishName"], [0, 0])
            agg[0] += r["DishAmountInt"]
            agg[1] += r["DishDiscountSumInt"]
    for c, title in CATEGORIES:
        items = sorted(by_cat.get(c, {}).items(), key=lambda kv: -kv[1][1])
        if not items:
            continue
        total = sum(v[1] for _, v in items)
        lines += ["", "%s · %s (%d%% выручки)" % (title, rub(total), round(total / rev * 100) if rev else 0)]
        for i, (name, (qty, s_)) in enumerate(items[:3], 1):
            lines.append("%d. %s — %d шт · %s" % (i, name, qty, rub(s_)))

    main, top = lines[:split], lines[split:]
    if top and not top[0]:
        top = top[1:]
    if not top:
        return "\n".join(main)
    head = "Что продавали (справочно)"
    if fmt == "html":  # Telegram, parse_mode=HTML: заголовок жирным, справочный блок курсивом
        out = [html.escape(l) for l in main] + ["", "────────────", "<b>%s</b>" % head] + \
              [("<i>%s</i>" % html.escape(l)) if l else "" for l in top]
    else:
        out = main + ["", "────────────", head] + top
    return "\n".join(out)


MSK = timezone(timedelta(hours=3))  # Пенза живёт по московскому времени


def _load_now(today):
    pwd = os.environ.get("IIKO_PASSWORD") or getpass.getpass("Пароль Kris (на экране не виден): ")
    key = get(BASE + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": hashlib.sha1(pwd.encode()).hexdigest()})).strip()
    try:
        nxt = today + timedelta(days=1)
        line_fields = LINE_FIELDS + ["HourOpen"]
        return {
            "hours": olap(key, ["OpenDate.Typed", "HourOpen"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], today - timedelta(days=28), nxt),
            "lines": olap(key, line_fields, ["DishAmountInt"], today, nxt),
            "lines_prev": olap(key, line_fields, ["DishAmountInt"], today - timedelta(days=7), today - timedelta(days=6)),
            "opens": attendance_starts(BASE, key, today),
        }
    finally:
        get(BASE + "/logout?key=" + key)


def load_now(today, zones=True):
    """zones=True: добавить данные для блока «На что обратить внимание»."""
    data = _load_now(today)
    if not zones:
        return data
    try:
        import insights
        data["ins_raw"] = insights.load(today)
    except Exception:
        data["ins_raw"] = None  # зоны внимания необязательны
    return data


def build_now(now, d, fmt="plain"):
    """Промежуточный отчёт: итоги за полные часы с открытия и что сделать до конца дня."""
    today, H = now.date(), now.hour
    hours = {}
    for r in d["hours"]:
        hours.setdefault(r["OpenDate.Typed"], {})[int(r["HourOpen"])] = r

    def part(day, upto, field):
        return sum(r[field] for h, r in hours.get(day.isoformat(), {}).items() if h < upto)

    prior = [today - timedelta(days=7 * i) for i in range(1, 5) if hours.get((today - timedelta(days=7 * i)).isoformat())]
    head = "⏱ Кафе · День, сейчас %02d:%02d, %s" % (now.hour, now.minute, WEEKDAYS[today.weekday()])
    if H < 9 or not prior:
        out = [head, "", "Пока рано: за первые часы данных мало. Попробуйте после 10:00."]
        return "\n".join(html.escape(l) for l in out) if fmt == "html" else "\n".join(out)

    R, C = "DishDiscountSumInt", "UniqOrderId.OrdersCount"
    rev, chk = part(today, H, R), part(today, H, C)
    avg_rev = sum(part(x, H, R) for x in prior) / len(prior)
    avg_chk = sum(part(x, H, C) for x in prior) / len(prior)
    avg_avg = avg_rev / avg_chk if avg_chk else 0
    mine_avg = rev / chk if chk else 0
    shares = [part(x, H, R) / sum(r[R] for r in hours[x.isoformat()].values()) for x in prior if sum(r[R] for r in hours[x.isoformat()].values())]
    totals = [sum(r[R] for r in hours[x.isoformat()].values()) for x in prior]
    share = sum(shares) / len(shares) if shares else 0
    forecast = rev / share if share else 0
    usual_total = sum(totals) / len(totals) if totals else 0

    def pc(a, b):
        return (pct(a, b) + " к обычному") if b else ""

    start = first_open(d.get("opens", []), today)
    since = "С %s" % start if start and int(start[:2]) < H else "С открытия"
    lines = [head, "", "%s до %02d:00 (полные часы)" % (since, H),
             "Выручка: %s (%s: %s)" % (rub(rev), pct(rev, avg_rev), rub(avg_rev)) if avg_rev else "Выручка: %s" % rub(rev),
             "Чеков: %d (%s: %d)" % (chk, pct(chk, avg_chk), round(avg_chk)) if avg_chk else "Чеков: %d" % chk,
             "Средний чек: %s (%s: %s)" % (rub(mine_avg), pct(mine_avg, avg_avg), rub(avg_avg)) if avg_avg else "Средний чек: %s" % rub(mine_avg)]
    wx = weather.today_weather(now)
    if forecast and share < FORECAST_MIN_SHARE:
        lines += ["", "📈 Прогноз на день пока не считаем: к этому часу обычно набирается около %d%% дневной выручки, оценка вышла бы случайной. Появится ближе к полудню." % round(share * 100)]
        forecast = 0
    if forecast:
        base = forecast
        if wx and wx["factor"] < 1:
            forecast = rev + (forecast - rev) * wx["factor"]  # поправка только на оставшуюся часть дня
        lines += ["", "📈 Прогноз на день: около %s (обычно %s)" % (rub(round(forecast, -2)), rub(round(usual_total, -2)))]
        if wx and wx["factor"] < 1:
            lines.append("С поправкой на погоду %s (без неё около %s)" % (pct(forecast, base).replace("к ", ""), rub(round(base, -2))))
    if wx:
        lines.append(wx["line"])

    # Напиток + десерт и добавки, как в утренней сводке, но только по полным часам
    def upto(rows):
        return [r for r in rows if int(r["HourOpen"]) < H]
    wd, wds, dr, fl, _ = check_stats(upto(d["lines"]))
    pwd_, pwds, pdr, pfl, _ = check_stats(upto(d["lines_prev"]))
    share_ = lambda a, b: round(a / b * 100) if b else 0
    if wd:
        lines += ["", "🧾 В чеках",
                  "• Десертов к напиткам (кофе, какао, чай, матча): %d к %d (%d%%, неделю назад к этому часу %d%%)" % (wds, wd, share_(wds, wd), share_(pwds, pwd_)),
                  "• Кофе, какао и матча с добавками: %d из %d (%d%%, неделю назад %d%%)" % (fl, dr, share_(fl, dr), share_(pfl, pdr))]

    # Рекомендации по правилам
    tips = []
    pace = rev / avg_rev - 1 if avg_rev else 0
    chk_pace = chk / avg_chk - 1 if avg_chk else 0
    avg_pace = mine_avg / avg_avg - 1 if avg_avg else 0
    early = share < FORECAST_MIN_SHARE  # рано: утренних продаж слишком мало, чтобы судить о темпе дня
    if early:
        pass
    elif pace <= -0.10:
        if chk_pace <= -0.10 and avg_pace > -0.05:
            tips.append("Гостей меньше обычного. Напомните о себе: сторис или рассылка с предложением на обед, блюдо дня на входе.")
        elif avg_pace <= -0.10 and chk_pace > -0.05:
            tips.append("Гости идут, но чеки меньше обычного. Предлагайте к кофе десерт и добавки: сироп, альтернативное молоко.")
        else:
            tips.append("И гостей, и сумма чека меньше обычного. Усильте предложение на кассе (десерт, добавки) и напомните о себе в соцсетях.")
    elif pace >= 0.10:
        tips.append("День идёт выше обычного. Проверьте остатки ходовых блюд и десертов, чтобы к вечеру ничего не закончилось.")
    if wd and share_(wds, wd) + 5 <= share_(pwds, pwd_):
        tips.append("Десерт берут реже, чем неделю назад (%d%% против %d%%). Пусть бариста предлагает десерт при заказе кофе." % (share_(wds, wd), share_(pwds, pwd_)))
    if dr and share_(fl, dr) + 4 <= share_(pfl, pdr):
        tips.append("Добавки к напиткам берут реже, чем неделю назад (%d%% против %d%%). Предлагайте сироп и альтернативное молоко." % (share_(fl, dr), share_(pfl, pdr)))
    hourly = {h: sum(hours[x.isoformat()].get(h, {}).get(R, 0) for x in prior) / len(prior) for h in range(H, 22)}
    wins = [(hourly[h] + hourly.get(h + 1, 0), h) for h in range(H, 21)]
    if wins and max(wins)[0] > 0:
        val, st = max(wins)
        tips.append("Впереди самые сильные часы: %02d:00–%02d:00, обычно около %s. Проверьте, что смена на месте, витрина полная, десерты выставлены." % (st, st + 2, rub(round(val, -2))))
    evening = sum(sum(r[R] for h, r in hours[x.isoformat()].items() if h >= 18) for x in prior) / len(prior)
    if H < 18 and evening >= 10000:
        tips.append("После 18:00 в этот день недели обычно ещё около %s. Не закрывайтесь раньше." % rub(round(evening, -3)))
    zones = []
    if d.get("ins_raw"):
        try:
            import insights
            zones = insights.build(today, d["ins_raw"], H=H, tips=True)
        except Exception:
            zones = []
    if zones:
        lines += ["", "👀 На что обратить внимание"] + ["• " + z for z in zones]
    wtip = weather.drink_tip(wx)
    if wtip:
        tips.insert(0, wtip)
    if not tips:
        tips.append("Идём по обычному графику, особых действий не нужно.")
    lines += ["", "💡 Что сделать до конца дня"] + ["• " + t for t in tips[:4]]
    text = "\n".join(lines)
    return html.escape(text) if fmt == "html" else text


FORECAST_MIN_SHARE = 0.20  # прогноз на день показываем, когда к этому часу обычно набрано не меньше 20% выручки
ABC_DAYS = 30
ABC_TOP, ABC_WEAK = 5, 3
ABC_PROMO, ABC_PROMO_MIN_QTY = 3, 15  # сколько позиций «продвигать» и минимум продаж за период
SEASONAL_FOOD_GROUPS = {"Летнее меню", "Весеннее меню", "Зимние блюда", "Сезонные блюда", "14 февраля"}


def load_abc(today=None):
    today = today or date.today()
    start, end = today - timedelta(days=ABC_DAYS), today
    pwd = os.environ.get("IIKO_PASSWORD") or getpass.getpass("Пароль Kris (на экране не виден): ")
    key = get(BASE + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": hashlib.sha1(pwd.encode()).hexdigest()})).strip()
    try:
        rows = olap(key, ["OpenDate.Typed", "DishGroup.TopParent", "DishGroup.SecondParent", "DishGroup", "DishName"],
                    ["DishDiscountSumInt", "DishAmountInt", "ProductCostBase.ProductCost"], start, end)
    finally:
        get(BASE + "/logout?key=" + key)
    return {"rows": rows, "start": start, "end": end}


def build_abc(d, fmt="plain"):
    """ABC-анализ кухни и десертов по выручке за 30 дней: лидеры и кандидаты на вывод из меню."""
    start, end = d["start"], d["end"]
    new_after = (start + timedelta(days=7)).isoformat()  # позиции, которых не было в первую неделю, считаем новинками
    agg = {}
    for r in d["rows"]:
        c = category(r)
        if c == "food" and r["DishName"].strip().startswith("Павлова"):
            c = "desserts"  # Павлова лежит в сезонной группе меню, но по сути десерт
        if c not in ("food", "desserts") or not r["DishDiscountSumInt"]:
            continue
        sec = "desserts" if c == "desserts" else "seasonal" if r["DishGroup"] in SEASONAL_FOOD_GROUPS else "food"
        a = agg.setdefault((sec, r["DishName"].strip()), {"rev": 0, "qty": 0, "first": "9", "grp": r["DishGroup"], "cost": 0})
        a["rev"] += r["DishDiscountSumInt"]
        a["qty"] += r["DishAmountInt"]
        a["cost"] += r.get("ProductCostBase.ProductCost") or 0
        a["first"] = min(a["first"], r["OpenDate.Typed"])
    lines = ["📊 Кафе · АБС-анализ меню · %d %s – %d %s" % (start.day, MONTHS[start.month - 1], (end - timedelta(days=1)).day, MONTHS[(end - timedelta(days=1)).month - 1]),
             "A — позиции, дающие первые 80% выручки раздела, B — следующие 15%, C — последние 5%."]
    for cat, title in (("food", "🍳 Кухня · постоянное меню"), ("seasonal", "🍂 Кухня · сезонное меню"), ("desserts", "🍰 Десерты")):
        items = sorted(((n, v) for (c, n), v in agg.items() if c == cat), key=lambda kv: -kv[1]["rev"])
        total = sum(v["rev"] for _, v in items)
        if not items:
            continue
        cum, counts = 0, {"A": 0, "B": 0, "C": 0}
        for n, v in items:
            cum += v["rev"]
            v["cls"] = "A" if cum / total <= 0.8 or counts["A"] == 0 else "B" if cum / total <= 0.95 else "C"
            counts[v["cls"]] += 1
            v["share"] = v["rev"] / total * 100
        lines += ["", "%s · %d позиций, %s" % (title, len(items), rub(total)),
                  "A: %d · B: %d · C: %d" % (counts["A"], counts["B"], counts["C"]), "", "Что продаётся лучше всего"]
        for i, (n, v) in enumerate(items[:ABC_TOP], 1):
            lines.append("%d. %s — %d шт · %s (%.0f%%)" % (i, n, v["qty"], rub(v["rev"]), v["share"]))
        # кандидат на вывод: класс C, меньше 1% выручки раздела, не новинка; до трёх самых слабых
        weak = [(n, v) for n, v in reversed(items) if v["first"] < new_after and v["cls"] == "C" and v["share"] < 1][:ABC_WEAK]
        lines += ["", "Что берут хуже всего, кандидаты на вывод из меню"]
        if not weak:
            lines.append("Таких нет")
        for i, (n, v) in enumerate(weak, 1):
            grp = ", " + v["grp"] if cat == "seasonal" else ""
            lines.append("%d. %s — %d шт · %s (%.1f%%)%s" % (i, n, v["qty"], rub(v["rev"]), v["share"], grp))
        # что продвигать: не класс A (есть куда расти), маржа выше средней по разделу, спрос стабильный
        costed = [(n, v) for n, v in items if v["cost"] > 0]
        if costed:
            avg = 1 - sum(v["cost"] for _, v in costed) / sum(v["rev"] for _, v in costed)
            promo = [(n, v, 1 - v["cost"] / v["rev"]) for n, v in costed
                     if v["cls"] != "A" and v["first"] < new_after and v["qty"] >= ABC_PROMO_MIN_QTY and 1 - v["cost"] / v["rev"] > avg]
            promo.sort(key=lambda t: -(t[1]["rev"] - t[1]["cost"]) / t[1]["qty"])
            lines += ["", "Что продвигать официантам (маржа выше средней %.0f%%, продаётся не в лидерах)" % (avg * 100)]
            if not promo:
                lines.append("Таких нет")
            for i, (n, v, m) in enumerate(promo[:ABC_PROMO], 1):
                lines.append("%d. %s — маржа %.0f%%, %s с порции · продано %d шт" % (i, n, m * 100, rub((v["rev"] - v["cost"]) / v["qty"]), v["qty"]))
    lines += ["", "В кандидаты попадают позиции класса C с долей меньше 1% выручки раздела, но не больше трёх. Новинки, которых не было в первую неделю периода, не показаны: у них мало времени на продажи. Маржа считается как выручка минус себестоимость блюда из iiko."]
    text = "\n".join(lines)
    return html.escape(text) if fmt == "html" else text


def main():
    if "--abc" in sys.argv:  # ABC-анализ кухни и десертов за 30 дней
        print(build_abc(load_abc(), "html" if "--telegram" in sys.argv else "plain"))
        return
    if "--now" in sys.argv:  # промежуточный отчёт; --at ЧЧ:ММ для проверки на другое время
        now = datetime.now(MSK)
        if "--at" in sys.argv:
            hh, mm = sys.argv[sys.argv.index("--at") + 1].split(":")
            now = now.replace(hour=int(hh), minute=int(mm))
        print(build_now(now, load_now(now.date()), "html" if "--telegram" in sys.argv else "plain"))
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    day = date.fromisoformat(args[0]) if args else date.today() - timedelta(days=1)
    print(build(day, load(day), "html" if "--telegram" in sys.argv else "plain"))


if __name__ == "__main__":
    main()
