-- Daily Target Report
-- Simple daily aggregate for a target date

SELECT
    report_date,
    metric_name,
    sum(value)       AS total_value,
    avg(value)       AS avg_value,
    min(value)       AS min_value,
    max(value)       AS max_value,
    count(*)         AS record_count
FROM daily_metrics
WHERE report_date = '{TARGET_DATE}'
GROUP BY report_date, metric_name
ORDER BY metric_name