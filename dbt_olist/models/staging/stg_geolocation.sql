-- dedupe (source is ~26% full-row duplicates) and drop points outside
-- Brazil's bounding box (42 known bad rows) -- same rules applied in the
-- Postgres staging_schema.sql geolocation_clean view
select distinct
    geolocation_zip_code_prefix,
    geolocation_lat,
    geolocation_lng,
    geolocation_city,
    geolocation_state
from {{ source('raw', 'geolocation_raw') }}
where geolocation_lat between -33.75 and 5.27
  and geolocation_lng between -73.99 and -34.79
