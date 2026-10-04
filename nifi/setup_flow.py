import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = os.environ["NIFI_API_URL"].rstrip("/")
USER = os.environ.get("NIFI_USER", "")
PASSWORD = os.environ.get("NIFI_PASSWORD", "")
CLIENT = str(uuid.uuid4())

JDBC = "jdbc:postgresql://{host}:{port}/{db}".format(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ["POSTGRES_INTERNAL_PORT"],
    db=os.environ["POSTGRES_DB"],
)
DRIVER = "/opt/nifi/nifi-current/lib/postgresql-42.7.4.jar"


def call(method, path, payload=None, token=None, form=None):
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    last = None
    for _ in range(8):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode()
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            last = f"{method} {path} -> {exc.code} {body[:2500]}"
            if exc.code not in (409, 500, 503):
                raise RuntimeError(last) from exc
            time.sleep(3)
            # Request нельзя отправить второй раз с тем же объектом после чтения? можно, data уже задан
            req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    raise RuntimeError(last or "nifi api")


def wait_nifi():
    deadline = time.time() + 480
    while time.time() < deadline:
        try:
            urllib.request.urlopen(API + "/nifi-api/access/config", timeout=5)
            print("nifi отвечает")
            return
        except Exception as exc:
            print("жду nifi:", type(exc).__name__)
            time.sleep(5)
    raise SystemExit("nifi не поднялся")


def login():
    # На HTTP NiFi не выдаёт токен. Если корень открывается без него, так и ходим.
    try:
        call("GET", "/nifi-api/flow/process-groups/root")
        print("nifi без логина")
        return None
    except RuntimeError as exc:
        print("без токена не пускает:", exc)
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            token = call(
                "POST",
                "/nifi-api/access/token",
                form={"username": USER, "password": PASSWORD},
            )
            if isinstance(token, str) and len(token) > 20:
                return token
        except RuntimeError as exc:
            print("логин:", exc)
        time.sleep(5)
    raise SystemExit("не пускает в nifi")


def rev(entity):
    return {"clientId": CLIENT, "version": entity["revision"]["version"]}


def find_prop(descriptors, display):
    for key, desc in descriptors.items():
        if desc.get("displayName") == display or key == display:
            return key, desc
    names = sorted(d.get("displayName") for d in descriptors.values())
    raise KeyError(f"нет свойства {display}, есть: {names}")


def allowable(desc, wanted):
    values = desc.get("allowableValues") or []
    if not values:
        return wanted
    options = []
    for item in values:
        value = item.get("allowableValue", item) if isinstance(item, dict) else item
        if isinstance(value, dict):
            options.append(value)
        else:
            options.append({"value": value, "displayName": str(value)})
    for value in options:
        if wanted in (value.get("value"), value.get("displayName")):
            return value.get("value")
    low = str(wanted).lower()
    for value in options:
        if low in (str(value.get("value", "")).lower(), str(value.get("displayName", "")).lower()):
            return value.get("value")
    raise KeyError(f"{wanted} не из {options}")


def create_service(token, group_id, type_name, name):
    return call(
        "POST",
        f"/nifi-api/process-groups/{group_id}/controller-services",
        payload={
            "revision": {"clientId": CLIENT, "version": 0},
            "component": {"type": type_name, "name": name},
        },
        token=token,
    )


def update_service(token, entity, properties):
    service_id = entity["component"]["id"]
    current = call("GET", f"/nifi-api/controller-services/{service_id}", token=token)
    mapped = {}
    for display, wanted in properties.items():
        key, desc = find_prop(current["component"]["descriptors"], display)
        mapped[key] = allowable(desc, wanted) if desc.get("allowableValues") else wanted
    return call(
        "PUT",
        f"/nifi-api/controller-services/{service_id}",
        payload={
            "revision": rev(current),
            "component": {
                "id": service_id,
                "name": current["component"]["name"],
                "properties": mapped,
            },
        },
        token=token,
    )


def enable_service(token, entity):
    service_id = entity["component"]["id"]
    current = call("GET", f"/nifi-api/controller-services/{service_id}", token=token)
    call(
        "PUT",
        f"/nifi-api/controller-services/{service_id}/run-status",
        payload={
            "revision": rev(current),
            "state": "ENABLED",
            "disconnectedNodeAcknowledged": False,
        },
        token=token,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        current = call("GET", f"/nifi-api/controller-services/{service_id}", token=token)
        state = current["component"]["state"]
        errors = current["component"].get("validationErrors") or []
        if state == "ENABLED":
            print(current["component"]["name"], "включён")
            return current
        if errors and state == "DISABLED":
            raise RuntimeError(f"{current['component']['name']}: {errors}")
        time.sleep(2)
    raise RuntimeError(entity["component"]["name"] + " не включился")


def create_processor(token, group_id, type_name, name, x):
    return call(
        "POST",
        f"/nifi-api/process-groups/{group_id}/processors",
        payload={
            "revision": {"clientId": CLIENT, "version": 0},
            "component": {
                "type": type_name,
                "name": name,
                "position": {"x": x, "y": 80},
            },
        },
        token=token,
    )


def update_processor(token, entity, properties, terminate):
    proc_id = entity["component"]["id"]
    current = call("GET", f"/nifi-api/processors/{proc_id}", token=token)
    mapped = {}
    for display, wanted in properties.items():
        key, desc = find_prop(current["component"]["config"]["descriptors"], display)
        mapped[key] = allowable(desc, wanted) if desc.get("allowableValues") else wanted
    rels = [rel["name"] for rel in current["component"].get("relationships") or []]
    updated = call(
        "PUT",
        f"/nifi-api/processors/{proc_id}",
        payload={
            "revision": rev(current),
            "component": {
                "id": proc_id,
                "name": current["component"]["name"],
                "config": {
                    "properties": mapped,
                    "autoTerminatedRelationships": [name for name in rels if name in terminate],
                },
            },
        },
        token=token,
    )
    errors = updated["component"].get("validationErrors") or []
    if errors:
        print(updated["component"]["name"], "пока так:", errors)
    return updated


def connect(token, group_id, source_id, dest_id):
    call(
        "POST",
        f"/nifi-api/process-groups/{group_id}/connections",
        payload={
            "revision": {"clientId": CLIENT, "version": 0},
            "component": {
                "source": {"id": source_id, "groupId": group_id, "type": "PROCESSOR"},
                "destination": {"id": dest_id, "groupId": group_id, "type": "PROCESSOR"},
                "selectedRelationships": ["success"],
                "flowFileExpiration": "0 sec",
                "backPressureObjectThreshold": 10000,
                "backPressureDataSizeThreshold": "1 GB",
                "prioritizers": [],
                "bends": [],
            },
        },
        token=token,
    )


def terminate_unconnected(token, entity, names):
    proc_id = entity["component"]["id"]
    current = call("GET", f"/nifi-api/processors/{proc_id}", token=token)
    rels = [rel["name"] for rel in current["component"].get("relationships") or []]
    return call(
        "PUT",
        f"/nifi-api/processors/{proc_id}",
        payload={
            "revision": rev(current),
            "component": {
                "id": proc_id,
                "name": current["component"]["name"],
                "config": {"autoTerminatedRelationships": [name for name in rels if name in names]},
            },
        },
        token=token,
    )


def start_processor(token, entity):
    proc_id = entity["component"]["id"]
    current = call("GET", f"/nifi-api/processors/{proc_id}", token=token)
    errors = current["component"].get("validationErrors") or []
    if errors:
        raise RuntimeError(f"{current['component']['name']} невалиден: {errors}")
    call(
        "PUT",
        f"/nifi-api/processors/{proc_id}/run-status",
        payload={
            "revision": rev(current),
            "state": "RUNNING",
            "disconnectedNodeAcknowledged": False,
        },
        token=token,
    )
    print(current["component"]["name"], "запущен")


def main():
    wait_nifi()
    token = login()
    root = call("GET", "/nifi-api/flow/process-groups/root", token=token)
    group_id = root["processGroupFlow"]["id"]
    processors = root["processGroupFlow"]["flow"]["processors"]
    by_name = {p["component"]["name"]: p for p in processors}
    if "Read mock_sales" in by_name and "Insert sales" in by_name:
        consume = terminate_unconnected(token, by_name["Read mock_sales"], {"failure"})
        put = terminate_unconnected(token, by_name["Insert sales"], {"success", "failure", "retry"})
        start_processor(token, put)
        start_processor(token, consume)
        print("поток запущен")
        return

    dbcp = create_service(token, group_id, "org.apache.nifi.dbcp.DBCPConnectionPool", "Postgres")
    dbcp = update_service(
        token,
        dbcp,
        {
            "Database Connection URL": JDBC,
            "Database Driver Class Name": "org.postgresql.Driver",
            "Database Driver Location(s)": DRIVER,
            "Database User": os.environ["POSTGRES_USER"],
            "Password": os.environ["POSTGRES_PASSWORD"],
        },
    )
    reader = create_service(token, group_id, "org.apache.nifi.json.JsonTreeReader", "JSON")
    reader = update_service(token, reader, {"Schema Access Strategy": "Infer Schema"})
    dbcp = enable_service(token, dbcp)
    reader = enable_service(token, reader)

    consume = create_processor(
        token,
        group_id,
        "org.apache.nifi.processors.kafka.pubsub.ConsumeKafka_2_6",
        "Read mock_sales",
        0,
    )
    consume = update_processor(
        token,
        consume,
        {
            "Kafka Brokers": os.environ["KAFKA_BOOTSTRAP"],
            "Topic Name(s)": os.environ["KAFKA_TOPIC"],
            "Group ID": os.environ["KAFKA_GROUP"],
            "Offset Reset": "earliest",
            "Honor Transactions": "false",
        },
        terminate={"failure"},
    )
    put = create_processor(
        token,
        group_id,
        "org.apache.nifi.processors.standard.PutDatabaseRecord",
        "Insert sales",
        520,
    )
    put = update_processor(
        token,
        put,
        {
            "Record Reader": reader["component"]["id"],
            "Database Connection Pooling Service": dbcp["component"]["id"],
            "Statement Type": "UPSERT",
            "Database Type": "PostgreSQL",
            "Schema Name": "public",
            "Table Name": "sales",
            "Update Keys": "source_file,source_row",
            "Translate Field Names": "false",
            "Unmatched Field Behavior": "Ignore Unmatched Fields",
            "Unmatched Column Behavior": "Ignore Unmatched Columns",
        },
        terminate={"success", "failure", "retry"},
    )
    connect(token, group_id, consume["component"]["id"], put["component"]["id"])
    start_processor(token, put)
    start_processor(token, consume)
    print("поток запущен")


if __name__ == "__main__":
    main()
