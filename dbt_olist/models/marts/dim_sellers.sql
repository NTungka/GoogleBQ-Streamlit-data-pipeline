-- Type 2 SCD: one row per (seller_id, valid_from) -- multiple rows per
-- seller_id if their location has changed. Join to fct_order_items on
-- seller_id AND shipping_limit_date BETWEEN valid_from AND
-- COALESCE(valid_to, timestamp('9999-12-31')) for point-in-time-accurate
-- seller location, not just current location.
select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state,
    dbt_valid_from as valid_from,
    dbt_valid_to as valid_to,
    dbt_valid_to is null as is_current
from {{ ref('sellers_snapshot') }}
