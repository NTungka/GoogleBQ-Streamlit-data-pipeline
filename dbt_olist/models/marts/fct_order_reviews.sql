-- grain: one row per (review_id, order_id)
select
    review_id,
    order_id,
    review_score,
    review_comment_title,
    review_comment_message,
    review_creation_date,
    review_answer_timestamp,
    timestamp_diff(review_answer_timestamp, review_creation_date, hour) as hours_to_answer
from {{ ref('stg_order_reviews') }}
