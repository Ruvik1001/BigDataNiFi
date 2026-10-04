-- Витрины поверх sales. Это представления: новая строка из потока сразу видна в отчёте.
-- Сумму чека не пересчитываю из цены и количества, в исходнике они не сходятся.

CREATE VIEW report_products AS
SELECT
    coalesce(btrim(product_name), '') AS product_name,
    coalesce(btrim(product_category), '') AS category_name,
    coalesce(btrim(product_brand), '') AS brand_name,
    sum(NULLIF(btrim(sale_total_price), '')::numeric) AS revenue,
    count(*) AS sales_cnt,
    sum(NULLIF(btrim(sale_quantity), '')::bigint) AS qty_sum,
    avg(NULLIF(btrim(product_rating), '')::numeric) AS rating,
    max(NULLIF(btrim(product_reviews), '')::int) AS reviews
FROM sales
GROUP BY 1, 2, 3;

CREATE VIEW report_customers AS
SELECT
    coalesce(btrim(customer_first_name), '') AS first_name,
    coalesce(btrim(customer_last_name), '') AS last_name,
    btrim(customer_email) AS email,
    coalesce(btrim(customer_country), '') AS country_name,
    sum(NULLIF(btrim(sale_total_price), '')::numeric) AS total_sum,
    count(*) AS orders_cnt,
    round(avg(NULLIF(btrim(sale_total_price), '')::numeric), 2) AS avg_check
FROM sales
WHERE btrim(coalesce(customer_email, '')) <> ''
GROUP BY 1, 2, 3, 4;

CREATE VIEW report_time AS
SELECT
    EXTRACT(YEAR FROM sale_dt)::int AS year_num,
    EXTRACT(MONTH FROM sale_dt)::int AS month_num,
    btrim(to_char(sale_dt, 'Month')) AS month_name,
    sum(amount) AS revenue,
    count(*) AS orders_cnt,
    round(avg(amount), 2) AS avg_check
FROM (
    SELECT
        to_date(btrim(sale_date), 'FMMM/FMDD/YYYY') AS sale_dt,
        NULLIF(btrim(sale_total_price), '')::numeric AS amount
    FROM sales
    WHERE btrim(coalesce(sale_date, '')) <> ''
) s
GROUP BY 1, 2, 3;

CREATE VIEW report_stores AS
SELECT
    coalesce(btrim(store_name), '') AS store_name,
    coalesce(btrim(store_city), '') AS city_name,
    coalesce(btrim(store_country), '') AS country_name,
    sum(NULLIF(btrim(sale_total_price), '')::numeric) AS revenue,
    count(*) AS orders_cnt,
    round(avg(NULLIF(btrim(sale_total_price), '')::numeric), 2) AS avg_check
FROM sales
GROUP BY 1, 2, 3;

CREATE VIEW report_suppliers AS
SELECT
    coalesce(btrim(supplier_name), '') AS supplier_name,
    coalesce(btrim(supplier_country), '') AS country_name,
    sum(NULLIF(btrim(sale_total_price), '')::numeric) AS revenue,
    round(avg(NULLIF(btrim(product_price), '')::numeric), 2) AS avg_price,
    count(*) AS sales_cnt
FROM sales
GROUP BY 1, 2;

CREATE VIEW report_quality AS
SELECT
    coalesce(btrim(product_name), '') AS product_name,
    coalesce(btrim(product_category), '') AS category_name,
    coalesce(btrim(product_brand), '') AS brand_name,
    round(avg(NULLIF(btrim(product_rating), '')::numeric), 2) AS rating,
    coalesce(max(NULLIF(btrim(product_reviews), '')::int), 0) AS reviews,
    count(*) AS sales_cnt,
    sum(NULLIF(btrim(sale_total_price), '')::numeric) AS revenue
FROM sales
GROUP BY 1, 2, 3;
