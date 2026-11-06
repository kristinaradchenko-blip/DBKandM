# Средний чек по официантам/сотрудникам из iikoServer (только чтение).
# Запуск: python3 waiters_avg_check.py [дней_назад; по умолчанию 0 = только сегодня]
import csv, getpass, hashlib, json, os, sys, time, urllib.parse, urllib.request
from datetime import date, timedelta

HOSTS = ["https://gussi-penza.iiko.it/resto/api", "https://gussi-penza-fud-trak.iiko.it/resto/api"]
HOST = HOSTS[0]
LOGIN = "Kris"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 0
CANDIDATES = ["Cashier", "AuthUser", "Cashier.Name", "AuthUser.Name", "SessionID.Cashier"]


def get(url, data=None):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2)


def olap(key, field, start, end):
    body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                       "groupByRowFields": ["Department", field],
                       "aggregateFields": ["DishDiscountSumInt", "UniqOrderId.OrdersCount"],
                       "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                      "from": start, "to": end,
                                                      "includeLow": "true", "includeHigh": "false"}}}).encode()
    return json.loads(get(HOST + "/v2/reports/olap?key=" + key, body)).get("data", [])


def run_host(host, h, start, end):
    global HOST
    HOST = host
    key = None
    out_all = []
    try:
        key = get(HOST + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": h})).strip()
        cols = json.loads(get(HOST + "/v2/reports/olap/columns?reportType=SALES&key=" + key))
        fields = [f for f in CANDIDATES if f in cols]
        print(host.split("//")[1].split("/")[0], "- поля сотрудников:", fields or "не найдены")
        for field in fields[:3]:
            for r in olap(key, field, start, end):
                orders = r.get("UniqOrderId.OrdersCount") or 0
                total = r.get("DishDiscountSumInt") or 0
                if orders:
                    out_all.append((field, r.get("Department"), r.get(field) or "(не указан)", orders, round(total), round(total / orders)))
    finally:
        if key:
            try:
                get(HOST + "/logout?key=" + key)
            except Exception as e:
                print("Выход: ошибка", e)
    return out_all


def main():
    pwd = getpass.getpass("Пароль Kris (на экране не виден): ")
    h = hashlib.sha1(pwd.encode()).hexdigest()
    end = (date.today() + timedelta(days=1)).isoformat()
    start = (date.today() - timedelta(days=DAYS)).isoformat()
    print("Период: с %s по сегодня включительно\n" % start)
    rows = []
    for host in HOSTS:
        try:
            rows += run_host(host, h, start, end)
        except Exception as e:
            print(host, "- ошибка:", e)
    for field in sorted(set(r[0] for r in rows)):
        out = sorted([r[1:] for r in rows if r[0] == field], key=lambda x: (x[0] or "", -x[4]))
        print("\n=== Разрез по полю:", field)
        print("%-22s %-28s %8s %12s %10s" % ("Заведение", "Сотрудник", "Чеков", "Выручка", "Ср.чек"))
        for d, n, o, t, a in out:
            print("%-22s %-28s %8d %12d %10d" % (d, n, o, t, a))
        path = os.path.expanduser("~/Desktop/iiko_avg_check_%s.csv" % field.replace(".", "_"))
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Заведение", "Сотрудник", "Чеков", "Выручка", "Средний чек"])
            w.writerows(out)
        print("Сохранено в файл:", path)
    print("\nГотово, из iiko вышли.")


main()
