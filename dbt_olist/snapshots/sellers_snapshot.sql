{% snapshot sellers_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='seller_id',
        strategy='check',
        check_cols=['seller_zip_code_prefix', 'seller_city', 'seller_state'],
    )
}}

select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state
from {{ source('raw', 'sellers') }}

{% endsnapshot %}
