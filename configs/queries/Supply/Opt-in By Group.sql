-- Group Performance Report
-- Shows per-group summary metrics for a given date

SELECT
    report_date,
    group_name,
    group_size,
    total_value,
    avg_value,
    count_records
FROM group_performance
WHERE report_date = '{TARGET_DATE}'
ORDER BY group_name