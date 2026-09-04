-- grain: one row per order. Payments and reviews are kept as separate fact
-- tables (an order can have several of each) to avoid fanning this out.
with orders as (
    select * from {{ ref('stg_orders') }}
),

item_counts as (
    select
        order_id,
        count(*) as item_count
    from {{ ref('stg_order_items') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.order_status,
    o.order_purchase_timestamp,
    date(o.order_purchase_timestamp) as order_purchase_date,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    coalesce(ic.item_count, 0) as item_count,

    -- known real anomalies, modeled once here rather than duplicated as
    -- separate dbt tests (see staging/_staging__models.yml note)
    o.order_delivered_customer_date is not null
        and o.order_delivered_customer_date > o.order_estimated_delivery_date
        as is_late_delivery,

    o.order_delivered_carrier_date is not null
        and o.order_approved_at is not null
        and o.order_delivered_carrier_date < o.order_approved_at
        as is_carrier_before_approved,

    o.order_status = 'delivered' and o.order_delivered_customer_date is null
        as is_delivered_missing_date,

    coalesce(ic.item_count, 0) = 0
        as has_no_line_items

from orders o
left join item_counts ic on o.order_id = ic.order_id
