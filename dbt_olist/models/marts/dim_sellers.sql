-- Type 2 SCD: one row per (seller_id, valid_from) -- multiple rows per
-- seller_id if their location has changed. Join to fct_order_items on
-- seller_id AND shipping_limit_date BETWEEN valid_from AND
-- COALESCE(valid_to, timestamp('9999-12-31')) for point-in-time-accurate
-- seller location, not just current location.
--
-- lat/lng denormalized in from stg_geolocation (rolled up to zip-prefix
-- grain) rather than kept as a separate dim_geolocation table. Joined on
-- each snapshot row's own seller_zip_code_prefix, so a seller's historical
-- rows keep the coordinates for whatever zip was active during that
-- period -- consistent with the point-in-time join this dimension is
-- built for.
with geo as (
    select
        geolocation_zip_code_prefix as zip_code_prefix,
        avg(geolocation_lat) as lat,
        avg(geolocation_lng) as lng
    from {{ ref('stg_geolocation') }}
    group by geolocation_zip_code_prefix
)

select
    s.seller_id,
    s.seller_zip_code_prefix,
    s.seller_city,
    s.seller_state,
    geo.lat as seller_lat,
    geo.lng as seller_lng,
    s.dbt_valid_from as valid_from,
    s.dbt_valid_to as valid_to,
    s.dbt_valid_to is null as is_current
from {{ ref('sellers_snapshot') }} as s
left join geo on geo.zip_code_prefix = s.seller_zip_code_prefix
