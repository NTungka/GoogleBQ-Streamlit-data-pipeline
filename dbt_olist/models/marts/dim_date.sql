-- covers the full observed order-date range (2016-09-04 to 2018-10-17)
-- with headroom on both sides
with spine as (
    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2016-01-01' as date)",
        end_date="cast('2019-01-01' as date)"
    ) }}
)

select
    date_day,
    extract(year from date_day) as year,
    extract(month from date_day) as month,
    extract(day from date_day) as day,
    extract(dayofweek from date_day) as day_of_week,       -- 1=Sunday .. 7=Saturday
    format_date('%A', date_day) as day_name,
    format_date('%B', date_day) as month_name,
    extract(dayofweek from date_day) in (1, 7) as is_weekend
from spine
