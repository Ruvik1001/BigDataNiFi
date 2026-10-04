import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ["METABASE_URL"].rstrip("/")
EMAIL = os.environ["METABASE_EMAIL"]
PASSWORD = os.environ["METABASE_PASSWORD"]
DASHBOARD = "Продажи pet store"

QUESTIONS = [
    {
        "name": "Выручка по категориям",
        "display": "bar",
        "query": """
            SELECT category_name, sum(revenue) AS revenue, sum(sales_cnt) AS sales_cnt
            FROM report_products
            GROUP BY category_name
            ORDER BY revenue DESC
        """,
        "viz": {"graph.dimensions": ["category_name"], "graph.metrics": ["revenue"]},
    },
    {
        "name": "Продажи по названию товара",
        "display": "bar",
        "query": """
            SELECT product_name, sum(sales_cnt) AS sales_cnt, sum(revenue) AS revenue
            FROM report_products
            GROUP BY product_name
            ORDER BY revenue DESC
        """,
        "viz": {"graph.dimensions": ["product_name"], "graph.metrics": ["revenue"]},
    },
    {
        "name": "Продажи по месяцам",
        "display": "line",
        "query": """
            SELECT month_num, month_name, revenue, orders_cnt, avg_check
            FROM report_time
            ORDER BY year_num, month_num
        """,
        "viz": {"graph.dimensions": ["month_name"], "graph.metrics": ["revenue"]},
    },
    {
        "name": "Клиенты по странам",
        "display": "bar",
        "query": """
            SELECT country_name, count(*) AS customers
            FROM report_customers
            GROUP BY country_name
            ORDER BY customers DESC
            LIMIT 10
        """,
        "viz": {"graph.dimensions": ["country_name"], "graph.metrics": ["customers"]},
    },
    {
        "name": "Топ-10 клиентов",
        "display": "table",
        "query": """
            SELECT first_name, last_name, email, country_name, total_sum, orders_cnt, avg_check
            FROM report_customers
            ORDER BY total_sum DESC
            LIMIT 10
        """,
        "viz": {},
    },
    {
        "name": "Топ-5 магазинов",
        "display": "table",
        "query": """
            SELECT store_name, city_name, country_name, revenue, orders_cnt, avg_check
            FROM report_stores
            ORDER BY revenue DESC
            LIMIT 5
        """,
        "viz": {},
    },
    {
        "name": "Топ-5 поставщиков",
        "display": "table",
        "query": """
            SELECT supplier_name, country_name, revenue, avg_price, sales_cnt
            FROM report_suppliers
            ORDER BY revenue DESC
            LIMIT 5
        """,
        "viz": {},
    },
    {
        "name": "Рейтинг и отзывы",
        "display": "table",
        "query": """
            SELECT product_name, category_name, brand_name, rating, reviews, sales_cnt, revenue
            FROM report_quality
            ORDER BY rating DESC, reviews DESC
            LIMIT 10
        """,
        "viz": {},
    },
]


def call(method, path, payload=None, token=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Metabase-Session"] = token
    req = urllib.request.Request(URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code} {body[:2500]}") from exc


def wait_metabase():
    deadline = time.time() + 600
    while time.time() < deadline:
        try:
            health = call("GET", "/api/health")
            if health.get("status") == "ok":
                print("metabase отвечает")
                return
        except Exception as exc:
            print("жду metabase:", type(exc).__name__)
        time.sleep(5)
    raise SystemExit("metabase не поднялся")


def session():
    props = call("GET", "/api/session/properties")
    if not props.get("has-user-setup"):
        call(
            "POST",
            "/api/setup",
            {
                "token": props.get("setup-token"),
                "user": {
                    "email": EMAIL,
                    "password": PASSWORD,
                    "first_name": "Виктор",
                    "last_name": "Руднев",
                    "site_name": "Pet store",
                },
                "prefs": {
                    "site_name": "Pet store",
                    "allow_tracking": False,
                },
            },
        )
        print("учётная запись создана")
    logged = call("POST", "/api/session", {"username": EMAIL, "password": PASSWORD})
    return logged["id"]


def database_id(token):
    listing = call("GET", "/api/database", token=token)
    rows = listing if isinstance(listing, list) else listing.get("data") or listing.get("databases") or []
    for row in rows:
        if row.get("name") == "pet_store":
            return row["id"]
    created = call(
        "POST",
        "/api/database",
        {
            "name": "pet_store",
            "engine": "postgres",
            "details": {
                "host": os.environ["POSTGRES_HOST"],
                "port": int(os.environ["POSTGRES_INTERNAL_PORT"]),
                "dbname": os.environ["POSTGRES_DB"],
                "user": os.environ["POSTGRES_USER"],
                "password": os.environ["POSTGRES_PASSWORD"],
                "ssl": False,
            },
        },
        token=token,
    )
    print("база подключена")
    return created["id"]


def find_dashboard(token):
    items = call("GET", "/api/collection/root/items?models=dashboard", token=token)
    for item in items.get("data") or []:
        if item.get("name") == DASHBOARD:
            return item["id"]
    return None


def card_ids(token, db_id):
    items = call("GET", "/api/collection/root/items?models=card", token=token)
    have = {item["name"]: item["id"] for item in items.get("data") or []}
    ids = []
    for question in QUESTIONS:
        if question["name"] in have:
            ids.append(have[question["name"]])
            continue
        card = call(
            "POST",
            "/api/card",
            {
                "name": question["name"],
                "display": question["display"],
                "visualization_settings": question["viz"],
                "dataset_query": {
                    "type": "native",
                    "native": {"query": question["query"]},
                    "database": db_id,
                },
            },
            token=token,
        )
        ids.append(card["id"])
        print(question["name"])
    return ids


def main():
    wait_metabase()
    token = session()
    dash_id = find_dashboard(token)
    if dash_id:
        current = call("GET", f"/api/dashboard/{dash_id}", token=token)
        if current.get("dashcards"):
            print("дашборд уже есть")
            return
    else:
        created = call("POST", "/api/dashboard", {"name": DASHBOARD}, token=token)
        dash_id = created["id"]
    db_id = database_id(token)
    dashcards = []
    for index, card_id in enumerate(card_ids(token, db_id)):
        dashcards.append(
            {
                "id": -(index + 1),
                "card_id": card_id,
                "row": (index // 2) * 5,
                "col": (index % 2) * 9,
                "size_x": 9,
                "size_y": 5,
                "parameter_mappings": [],
                "visualization_settings": {},
            }
        )
    call("PUT", f"/api/dashboard/{dash_id}", {"dashcards": dashcards}, token=token)
    print("дашборд собран")


if __name__ == "__main__":
    main()
