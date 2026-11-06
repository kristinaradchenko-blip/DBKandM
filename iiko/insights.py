# Автоматические выводы для блока «Обратите внимание» (итоги дня) и «На что обратить внимание» («на сейчас»):
# что необычного по сравнению со средним по четырём прошлым таким же дням недели. Показываем только заметное.
# Проверка: python3 insights.py [ГГГГ-ММ-ДД]
import hashlib, os, sys, urllib.parse
from datetime import date, timedelta

import daily_report as d

CAT = {"food": "кухня", "desserts": "десерты", "drinks": "напитки"}
BIG, SMALL = 2000, 500          # границы «крупного» и «мелкого» чека, ₽
MIN_HOUR = 4000                 # провальный час: минус столько и не менее 35% к обычному
WEEKS = 4


def _pull(key, x):
    nxt = x + timedelta(days=1)
    return {"checks": d.olap(key, ["UniqOrderId.Id", "HourOpen"], ["DishDiscountSumInt"], x, nxt),
            "dishes": d.olap(key, ["DishGroup.TopParent", "DishGroup.SecondParent", "DishGroup", "DishName", "HourOpen"], ["DishDiscountSumInt", "DishAmountInt"], x, nxt),
            "hours": d.olap(key, ["HourOpen"], ["DishDiscountSumInt"], x, nxt),
            "disc": d.olap(key, ["UniqOrderId.Id", "OrderDiscount.Type", "HourOpen"], ["DiscountSum", "DishSumInt"], x, nxt)}


def load(day, weeks=WEEKS):
    """Данные за день и за прошлые такие же дни недели (те, где были продажи), склеенные вместе: o['prev'], o['k'] = сколько дней."""
    key = d.get(d.BASE + "/auth?" + urllib.parse.urlencode({"login": d.LOGIN, "pass": hashlib.sha1(os.environ["IIKO_PASSWORD"].encode()).hexdigest()})).strip()
    try:
        cur = _pull(key, day)
        prev, k = {n: [] for n in cur}, 0
        for i in range(1, weeks + 1):
            p = _pull(key, day - timedelta(days=7 * i))
            if sum(r["DishDiscountSumInt"] for r in p["hours"]) > 0:
                k += 1
                for n in prev:
                    prev[n] += p[n]
    finally:
        d.get(d.BASE + "/logout?key=" + key)
    return {"cur": cur, "prev": prev, "k": k}


def kt(x):
    return ("%.1f" % (abs(x) / 1000)).replace(".", ",") + " тыс. ₽"


def sign(x):
    return ("+" if x >= 0 else "−") + kt(x)


def build(day, o, H=None, tips=False):
    """Зоны внимания. H: учитывать только полные часы до H (для «на сейчас»), None: весь день.
    tips=True: к каждой зоне добавить «что делать» (для «на сейчас»)."""
    k = o.get("k") or 0
    if not k:
        return []
    last = k == 1                                    # сравнение с одной прошлой неделей или со средним за несколько
    w_cmp = "чем неделю назад" if last else "обычного"   # «больше/меньше …»
    w_to = "к прошлой неделе" if last else "к обычному"
    w_usual = "неделю назад" if last else "обычно около"
    up = lambda rows: [r for r in rows if H is None or int(r["HourOpen"]) < H]
    cur = {n: up(v) for n, v in o["cur"].items()}
    prev = {n: up(v) for n, v in o["prev"].items()}
    notes = []

    def add(text, tip):
        notes.append(text + (" Что делать: " + tip if tips and tip else ""))

    cs = [c["DishDiscountSumInt"] for c in cur["checks"] if c["DishDiscountSumInt"] > 0]
    ps = [c["DishDiscountSumInt"] for c in prev["checks"] if c["DishDiscountSumInt"] > 0]
    if not cs or not ps:
        return []
    rev, prv = sum(cs), sum(ps) / k                      # prv, p_all и далее: среднее за один прошлый день
    n_all, p_all = len(cur["checks"]), len(prev["checks"]) / k  # как в отчёте: считаем и нулевые чеки
    n_pct, a_pct = n_all / p_all - 1, (rev / n_all) / (prv / p_all) - 1

    # 1. расхождение чеков и среднего чека
    cats = {}
    for lab, part in (("cur", cur), ("prev", prev)):
        for r in part["dishes"]:
            c = d.category(r)
            if c:
                cats.setdefault(c, {"cur": 0, "prev": 0})[lab] += r["DishDiscountSumInt"] / (1 if lab == "cur" else k)
    deltas = sorted(((v["cur"] - v["prev"], c) for c, v in cats.items()), key=lambda t: t[0])
    if n_pct >= 0.10 and a_pct <= -0.10:
        worst, best = deltas[0], deltas[-1]
        head = "Чеков больше %s, а средний чек ниже" % w_cmp
        if worst[0] < 0:
            head += ": просадка в категории «%s» (%s %s)" % (CAT[worst[1]], sign(worst[0]), w_to)
            if best[0] > 0:
                head += ", «%s» выросла (%s)" % (CAT[best[1]], sign(best[0]))
        add(head + ".", "гостей хватает, надо поднять чек: к кофе предлагайте десерт, в обед горячее; назовите конкретное блюдо вместо «что-нибудь ещё?».")
    elif n_pct <= -0.10 and a_pct >= 0.10:
        add("Чеков меньше %s, зато средний чек выше: идёт меньше гостей, но они берут больше." % w_cmp, "напомните о себе: сторис или рассылка с блюдом дня, чтобы вернуть поток.")

    # 2. крупные и мелкие чеки
    big_c, big_p = sum(1 for x in cs if x >= BIG), sum(1 for x in ps if x >= BIG) / k
    small_c, small_p = sum(1 for x in cs if x < SMALL), sum(1 for x in ps if x < SMALL) / k
    if abs(big_c - big_p) >= 3 and abs(big_c - big_p) / max(big_p, 1) >= 0.15:
        gain = sum(x for x in cs if x >= BIG) - sum(x for x in ps if x >= BIG) / k
        add("Крупных чеков (от %d ₽) %s: %d (%s %d), это %s выручки." % (BIG, "меньше" if big_c < big_p else "больше", big_c, w_usual, round(big_p), sign(gain)),
            "компаниям и парам предлагайте горячее и десерт на стол, а не только напитки." if big_c < big_p else "")
    if abs(small_c - small_p) >= 5 and abs(small_c - small_p) / max(small_p, 1) >= 0.20:
        add("Мелких чеков (до %d ₽) %s: %d (%s %d)." % (SMALL, "больше" if small_c > small_p else "меньше", small_c, w_usual, round(small_p)),
            "к одиночному кофе предлагайте десерт или выпечку." if small_c > small_p else "")

    # 3. акции (скидки на 100% и общий уровень скидок проверяет основной отчёт)
    kinds = {}
    for lab, part in (("cur", cur), ("prev", prev)):
        for r in part["disc"]:
            if r["DiscountSum"] and r["OrderDiscount.Type"] and "персонала" not in r["OrderDiscount.Type"].lower():
                kinds.setdefault(r["OrderDiscount.Type"], {"cur": 0, "prev": 0})[lab] += 1 / (1 if lab == "cur" else k)
    for name, v in kinds.items():
        if v["cur"] >= 5 and v["cur"] >= 2 * max(v["prev"], 1) and "100%" not in name:
            add("Акцию «%s» применили в %d чеках (%s %d)." % (name, v["cur"], w_usual, round(v["prev"])),
                "следите, чтобы к акционному напитку предлагали десерт: иначе акция съедает чек.")

    # 4. слабый час
    hc, hp = {}, {}
    for r in cur["hours"]:
        hc[int(r["HourOpen"])] = r["DishDiscountSumInt"]
    for r in prev["hours"]:
        hp[int(r["HourOpen"])] = hp.get(int(r["HourOpen"]), 0) + r["DishDiscountSumInt"] / k
    # в «на сейчас» интересны только последние два часа: на более ранние уже не повлиять
    bad = sorted(((hc.get(h, 0) - hp[h], h) for h in hp if hp[h] - hc.get(h, 0) >= MIN_HOUR and hc.get(h, 0) <= hp[h] * 0.65
                  and (not tips or H is None or h >= H - 2)), key=lambda t: t[0])
    if bad:
        add("Самые слабые часы " + w_to + ": " + ", ".join("%02d:00 (%s)" % (h, sign(v)) for v, h in bad[:2]) + ".",
            "проверьте, что витрина полная и десерты выставлены; в тихие часы предложите гостям блюдо дня.")
    return notes


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today() - timedelta(days=1)
    for n in build(day, load(day)):
        print("• " + n)
