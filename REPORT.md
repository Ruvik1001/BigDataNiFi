# Отчёт по лабораторной работе №5 (BigDataNiFi)

Работа выполнена студентом МАИ группы М8О-205СВ-25 Рудневым Виктором Владимировичем.

## Цель

Прогнать строки CSV через Kafka в виде JSON, NiFi в потоке сложить их в PostgreSQL без агрегации, посчитать 6 витрин SQL и показать их в Metabase.

## Шаги

1. `docker-compose.yml`: PostgreSQL 16, Kafka 3.8 (KRaft), NiFi 1.28.1, Metabase 0.49, producer.
2. `producer/send_to_kafka.py` читает 10 CSV и шлёт каждую строку отдельным JSON в топик `mock_sales`. В сообщение добавлены `source_file` и номер строки. CSV читается модулем `csv`, потому что в `product_description` есть переносы.
3. В образ NiFi добавлен JDBC-драйвер Postgres. Скрипт `nifi/setup_flow.py` собирает поток: ConsumeKafka читает топик с начала, PutDatabaseRecord пишет в таблицу `sales` (UPSERT по файлу и номеру строки).
4. При старте Postgres создаётся пустая `sales` и шесть представлений (`sql/02_reports.sql`). Агрегации в NiFi нет.
5. `metabase/setup_metabase.py` заводит пользователя, подключает Postgres и собирает дашборд «Продажи pet store».
6. Проверил число строк, лаг группы `nifi-sales` и те же срезы, что в прошлых работах.

## Обоснование

В Postgres лежит сырая продажа, одна строка сообщения. `id` из CSV не ключ: в каждом файле он снова с 1. Уникальны `source_file` и `source_row`, повторная отправка обновляет ту же строку, а не плодит копию.

Сумму чека не пересчитывал из цены и количества: в исходнике они не сходятся.

Витрины — представления, а не отдельные таблицы. Пока NiFi дописывает `sales`, отчёт сразу видит новые строки, второй джобы не нужно.

Зерно:

- `report_products` и `report_quality` — название, категория и бренд;
- `report_customers` — покупатель (email);
- `report_time` — год и месяц, дата в CSV вида `M/d/yyyy`;
- `report_stores` — магазин, город и страна;
- `report_suppliers` — имя и страна поставщика, средняя цена взята по `product_price`, не по чеку.

Покупатели и магазины в этом наборе почти не повторяются, поэтому топ-10 клиентов и топ-5 магазинов — это просто самые крупные чеки. Имеет смысл смотреть категории, название товара, страны и месяцы.

Корреляция рейтинга и числа продаж по витрине качества около 0.006: связи нет.

NiFi слушает HTTP. Токен он выдаёт только по HTTPS, поэтому холст открывается без пароля. Для лабораторной машины этого хватает.

## Конфигурация

Параметры в `.env`. В git его нет, есть `.env_example`.

```bash
copy .env_example .env
```

| Переменная | Зачем |
|------------|--------|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | доступ к Postgres |
| `POSTGRES_HOST`, `POSTGRES_INTERNAL_PORT` | адрес Postgres из NiFi и Metabase (`postgres` / `5432`) |
| `POSTGRES_PORT` | порт на хосте, в шаблоне `5436` |
| `KAFKA_BOOTSTRAP` | адрес брокера из контейнеров (`kafka:9094`) |
| `KAFKA_HOST_PORT` | порт брокера на хосте, в шаблоне `9095` |
| `KAFKA_TOPIC`, `KAFKA_GROUP` | топик `mock_sales` и группа `nifi-sales` |
| `KAFKA_NODE_ID`, `KAFKA_PROCESS_ROLES`, `KAFKA_LISTENERS`, `KAFKA_ADVERTISED_LISTENERS`, `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP`, `KAFKA_CONTROLLER_LISTENER_NAMES`, `KAFKA_INTER_BROKER_LISTENER_NAME`, `KAFKA_CONTROLLER_QUORUM_VOTERS`, `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR`, `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR`, `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR`, `KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS`, `KAFKA_NUM_PARTITIONS`, `KAFKA_CLUSTER_ID` | один брокер KRaft |
| `NIFI_WEB_HTTP_PORT` | порт UI внутри контейнера, `8080` |
| `NIFI_PORT` | тот же UI на хосте, в шаблоне `8083` |
| `NIFI_API_URL` | API для скрипта настройки (`http://nifi:8080`) |
| `NIFI_SENSITIVE_PROPS_KEY` | ключ, которым NiFi шифрует пароль Postgres в потоке |
| `METABASE_EMAIL`, `METABASE_PASSWORD` | вход в Metabase |
| `METABASE_PORT` | UI на хосте, в шаблоне `3001` |
| `METABASE_URL` | адрес для скрипта настройки (`http://metabase:3000`) |
| `DATA_DIR` | каталог CSV внутри producer |

В шаблоне пароли локальные: Postgres `postgres`/`postgres`, база `pet_store`. Metabase `student@mai.local` / `Metabase1`.

Запуск из каталога `BigDataNiFi`:

```bash
docker compose up -d --build
```

NiFi: http://localhost:8083/nifi . Metabase: http://localhost:3001 , дашборд «Продажи pet store».

Повторная отправка: `docker compose up -d --force-recreate producer`. Если холст пустой после пересоздания NiFi: `docker compose up -d --force-recreate nifi-setup`. Дашборд заново: `docker compose up -d --force-recreate metabase-setup`. С нуля: `docker compose down -v && docker compose up -d --build`.

## Результат

Producer отправил 10000 сообщений. Группа `nifi-sales`: current-offset 10000, log-end-offset 10000, лаг 0.

PostgreSQL, таблица `sales`: 10000 строк, 10 файлов, `source_row` от 1 до 1000.

| Представление | Строк |
|---------------|------:|
| report_products | 3233 |
| report_customers | 10000 |
| report_time | 12 |
| report_stores | 10000 |
| report_suppliers | 6295 |
| report_quality | 3233 |

Выручка по категории: Toy 868101.63 (3406), Cage 831117.94 (3327), Food 830632.55 (3267).

По названию товара: Bird Cage 3352 продажи / 847478.05, Dog Food 3339 / 848567.19, Cat Toy 3309 / 833806.88.

Покупатели: China 1738, Indonesia 1174, Russia 628, Philippines 555, Brazil 385.

Все продажи за 2021 год, выручка 2529852.12. Максимум заказов в августе (897) и октябре (892).

`corr(rating, sales_cnt)` по `report_quality` = 0.0058.
