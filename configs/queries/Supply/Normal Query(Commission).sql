-- Commission Summary Report
-- Aggregates commission metrics across a date range

SELECT
    report_date,
    category,
    SUM(amount)      AS total_amount,
    AVG(amount)      AS avg_amount,
    SUM(fee)         AS total_fee,
    COUNT(*)         AS record_count
FROM commission_records
WHERE report_date BETWEEN '{START_DATE}' AND '{END_DATE}'
GROUP BY report_date, category
ORDER BY report_date, category