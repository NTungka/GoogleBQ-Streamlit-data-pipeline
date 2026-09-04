-- one row per zip prefix: many exact lat/lng samples share a prefix even
-- after dedup in stg_geolocation, so this rolls up to the grain that
-- customers/sellers actually join on (zip_code_prefix)
select
    geolocation_zip_code_prefix as zip_code_prefix,
    avg(geolocation_lat) as lat,
    avg(geolocation_lng) as lng,
    any_value(geolocation_city) as city,
    any_value(geolocation_state) as state
from {{ ref('stg_geolocation') }}
group by geolocation_zip_code_prefix
