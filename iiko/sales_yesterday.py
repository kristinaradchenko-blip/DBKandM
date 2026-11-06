# Продажи за вчера по обоим заведениям: итоги, блюда, группы, кассиры (только чтение).
# Результат пишется в ~/Documents/iiko_yesterday.json, чтобы Claude обновил отчёт.
import getpass, hashlib, json, os, time, urllib.parse, urllib.request
from datetime import date, timedelta

HOSTS = ["https://gussi-penza.iiko.it/resto/api", "https://gussi-penza-fud-trak.iiko.it/resto/api"]
LOGIN = "Kris"


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


def olap(base, key, rows_by, aggs, start, end):
    body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                       "groupByRowFields": rows_by, "aggregateFields": aggs,
                       "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                      "from": start, "to": end,
                                                      "includeLow": "true", "includeHigh": "false"}}}).encode()
    return json.loads(get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])


def main():
    pwd = os.environ.get("IIKO_PASSWORD") or getpass.getpass("Пароль Kris (на экране не виден): ")
    h = hashlib.sha1(pwd.encode()).hexdigest()
    day = (date.today() - timedelta(days=1)).isoformat()
    end = date.today().isoformat()
    out = {"day": day, "hosts": {}}
    for base in HOSTS:
        key = None
        host = base.split("//")[1].split("/")[0]
        try:
            key = get(base + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": h})).strip()
            out["hosts"][host] = {
                "totals": olap(base, key, ["Department"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount", "ProductCostBase.ProductCost"], day, end),
                "dishes": olap(base, key, ["Department", "DishGroup", "DishName"], ["DishDiscountSumInt", "DishAmountInt", "ProductCostBase.ProductCost"], day, end),
                "cashiers": olap(base, key, ["Department", "Cashier"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], day, end),
            }
            try:
                out["hosts"][host]["hours"] = olap(base, key, ["Department", "HourOpen"], ["DishDiscountSumInt", "UniqOrderId.OrdersCount"], day, end)
            except Exception:
                pass
            print(host, "- выгружено")
        except Exception as e:
            out["hosts"][host] = {"error": str(e)}
            print(host, "- ошибка:", e)
        finally:
            if key:
                try:
                    get(base + "/logout?key=" + key)
                except Exception:
                    pass
    path = os.path.expanduser("~/Documents/iiko_yesterday.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("Сохранено:", path, "\nГотово, из iiko вышли. Напишите Claude «готово».")


main()
