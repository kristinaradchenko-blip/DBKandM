import getpass, hashlib, json, sys, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

HOSTS = ["gussi-penza.iiko.it", "gussi-penza-fud-trak.iiko.it", "gussi-penza-co.iiko.it"]
LOGIN = "Kris"


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def check(host, pass_hash, day, nextday):
    base = "https://" + host + "/resto/api"
    key = None
    try:
        key = get(base + "/auth?" + urllib.parse.urlencode({"login": LOGIN, "pass": pass_hash})).strip()
        print("  вход: OK")
        try:
            root = ET.fromstring(get(base + "/corporation/departments?key=" + key))
            deps = [(e.findtext("name"), e.findtext("type")) for e in root.iter() if e.tag.endswith("corporateItemDto")]
            print("  подразделения:", deps[:15] or get(base + "/corporation/departments?key=" + key)[:300])
        except Exception as e:
            print("  подразделения: ошибка", e)
        try:
            prods = json.loads(get(base + "/v2/entities/products/list?key=" + key))
            print("  продуктов в номенклатуре:", len(prods), "; примеры:", [p.get("name") for p in prods[:3]])
        except Exception as e:
            print("  номенклатура: ошибка", e)
        try:
            cols = json.loads(get(base + "/v2/reports/olap/columns?reportType=SALES&key=" + key))
            print("  полей в OLAP продаж:", len(cols), "; первые:", list(cols)[:40])
        except Exception as e:
            print("  поля OLAP: ошибка", e)
        try:
            body = json.dumps({"reportType": "SALES", "buildSummary": "false",
                               "groupByRowFields": ["Department", "DishName"],
                               "aggregateFields": ["DishDiscountSumInt", "ProductCostBase.ProductCost", "UniqOrderId.OrdersCount"],
                               "filters": {"OpenDate.Typed": {"filterType": "DateRange", "periodType": "CUSTOM",
                                                              "from": day, "to": nextday,
                                                              "includeLow": "true", "includeHigh": "false"}}}).encode()
            rows = json.loads(get(base + "/v2/reports/olap?key=" + key, body)).get("data", [])
            print("  продажи за", day, ": строк", len(rows))
            for r in rows[:10]:
                print("   ", r)
        except Exception as e:
            print("  OLAP продаж: ошибка", e)
    except Exception as e:
        print("  вход: ошибка", e)
    finally:
        if key:
            try:
                get(base + "/logout?key=" + key)
                print("  выход: OK")
            except Exception as e:
                print("  выход: ошибка", e)


def main():
    pwd = getpass.getpass("Пароль Kris (на экране не виден): ")
    pass_hash = hashlib.sha1(pwd.encode()).hexdigest()
    day = (date.today() - timedelta(days=1)).isoformat()
    nextday = date.today().isoformat()
    for h in HOSTS:
        print("\n=== " + h)
        check(h, pass_hash, day, nextday)


main()
