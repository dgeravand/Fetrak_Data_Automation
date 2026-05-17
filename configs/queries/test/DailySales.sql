-- Example SQL query for Daily Sales Report
-- Replace with your own query

SELECT
    date,
    region,
    product_name,
    SUM(quantity)    AS total_quantity,
    SUM(revenue)     AS total_revenue,
    AVG(unit_price)  AS avg_unit_price
FROM sales
WHERE date >= CURRENT_DATE - INTERVAL 7 DAY
GROUP BY date, region, product_name
ORDER BY date DESC, total_revenue DESC
LIMIT 1000