-- lat/lng denormalized in from stg_geolocation (rolled up to zip-prefix
-- grain) rather than kept as a separate dim_geolocation table -- keeps
-- this a single-join dimension for the dashboard, at the cost of
-- duplicating coordinates across customers sharing a zip prefix.
with geo as (
    select
        geolocation_zip_code_prefix as zip_code_prefix,
        avg(geolocation_lat) as lat,
        avg(geolocation_lng) as lng
    from {{ ref('stg_geolocation') }}
    group by geolocation_zip_code_prefix
)

select
    c.customer_id,
    c.customer_unique_id,
    c.customer_zip_code_prefix,
    c.customer_city,
    c.customer_state,
    geo.lat as customer_lat,
    geo.lng as customer_lng
from {{ ref('stg_customers') }} as c
left join geo on geo.zip_code_prefix = c.customer_zip_code_prefix
