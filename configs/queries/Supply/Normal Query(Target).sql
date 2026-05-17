-- Daily Summary Report
-- Replace TARGET_DATE with your desired date

SELECT
    report_date,
    metric_name,
    metric_value,
    category,
    region
FROM summary_metrics
WHERE report_date = '{TARGET_DATE}'
ORDER BY metric_name, region