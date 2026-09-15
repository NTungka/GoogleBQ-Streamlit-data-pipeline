"""
Shared schema + merge-key config for the GCS -> BigQuery `raw` dataset load.

One entry per Olist CSV. Column names and BigQuery types mirror
src/staging_schema.sql (the Postgres staging schema) exactly -- same
names, same "product_name_lenght" typo and all -- so the dbt staging
models under dbt_olist/models/staging/, and everything built on top of
them (including the fct_orders anomaly monitors), need zero changes: they
still read `raw.<table>` with the same columns and types they always have.
"""

from dataclasses import dataclass

from google.cloud import bigquery


@dataclass(frozen=True)
class TableConfig:
    table: str                  # target table in the `raw` dataset
    schema: list                # list[bigquery.SchemaField]
    key_columns: list           # MERGE ON columns
    match_on_full_row: bool = False  # geolocation_raw: no natural key


def _f(name: str, type_: str, mode: str = "REQUIRED") -> bigquery.SchemaField:
    return bigquery.SchemaField(name, type_, mode=mode)


TABLE_CONFIG: dict[str, TableConfig] = {
    "product_category_name_translation.csv": TableConfig(
        table="category_translation",
        schema=[
            _f("product_category_name", "STRING"),
            _f("product_category_name_english", "STRING"),
        ],
        key_columns=["product_category_name"],
    ),
    "olist_customers_dataset.csv": TableConfig(
        table="customers",
        schema=[
            _f("customer_id", "STRING"),
            _f("customer_unique_id", "STRING"),
            _f("customer_zip_code_prefix", "INT64"),
            _f("customer_city", "STRING"),
            _f("customer_state", "STRING"),
        ],
        key_columns=["customer_id"],
    ),
    "olist_sellers_dataset.csv": TableConfig(
        table="sellers",
        schema=[
            _f("seller_id", "STRING"),
            _f("seller_zip_code_prefix", "INT64"),
            _f("seller_city", "STRING"),
            _f("seller_state", "STRING"),
        ],
        key_columns=["seller_id"],
    ),
    "olist_products_dataset.csv": TableConfig(
        table="products",
        schema=[
            _f("product_id", "STRING"),
            _f("product_category_name", "STRING", mode="NULLABLE"),
            _f("product_name_lenght", "INT64", mode="NULLABLE"),
            _f("product_description_lenght", "INT64", mode="NULLABLE"),
            _f("product_photos_qty", "INT64", mode="NULLABLE"),
            _f("product_weight_g", "NUMERIC", mode="NULLABLE"),
            _f("product_length_cm", "NUMERIC", mode="NULLABLE"),
            _f("product_height_cm", "NUMERIC", mode="NULLABLE"),
            _f("product_width_cm", "NUMERIC", mode="NULLABLE"),
        ],
        key_columns=["product_id"],
    ),
    "olist_geolocation_dataset.csv": TableConfig(
        table="geolocation_raw",
        # lat/lng as FLOAT64, not NUMERIC: BigQuery's NUMERIC defaults to a
        # 9-digit decimal scale (unlike Postgres's arbitrary-precision
        # NUMERIC), and real values here have up to ~14 decimal digits,
        # which BigQuery's CSV loader rejects outright as invalid. FLOAT64
        # also matches how the star schema already types customer_lat/
        # seller_lat -- coordinates don't need exact decimal arithmetic
        # the way price/freight_value do.
        schema=[
            _f("geolocation_zip_code_prefix", "INT64"),
            _f("geolocation_lat", "FLOAT64"),
            _f("geolocation_lng", "FLOAT64"),
            _f("geolocation_city", "STRING"),
            _f("geolocation_state", "STRING"),
        ],
        # No natural key -- ~26% of rows are legitimate full-row duplicates
        # (repeated zip/lat/lng samples), same as the Postgres staging
        # table. Match on the full row instead, insert-only: re-running the
        # load never re-inserts a row already present, but never touches
        # or drops the real duplicates either.
        key_columns=[
            "geolocation_zip_code_prefix",
            "geolocation_lat",
            "geolocation_lng",
            "geolocation_city",
            "geolocation_state",
        ],
        match_on_full_row=True,
    ),
    "olist_orders_dataset.csv": TableConfig(
        table="orders",
        schema=[
            _f("order_id", "STRING"),
            _f("customer_id", "STRING"),
            _f("order_status", "STRING"),
            _f("order_purchase_timestamp", "TIMESTAMP"),
            _f("order_approved_at", "TIMESTAMP", mode="NULLABLE"),
            _f("order_delivered_carrier_date", "TIMESTAMP", mode="NULLABLE"),
            _f("order_delivered_customer_date", "TIMESTAMP", mode="NULLABLE"),
            _f("order_estimated_delivery_date", "TIMESTAMP"),
        ],
        key_columns=["order_id"],
    ),
    "olist_order_items_dataset.csv": TableConfig(
        table="order_items",
        schema=[
            _f("order_id", "STRING"),
            _f("order_item_id", "INT64"),
            _f("product_id", "STRING"),
            _f("seller_id", "STRING"),
            _f("shipping_limit_date", "TIMESTAMP"),
            _f("price", "NUMERIC"),
            _f("freight_value", "NUMERIC"),
        ],
        key_columns=["order_id", "order_item_id"],
    ),
    "olist_order_payments_dataset.csv": TableConfig(
        table="order_payments",
        schema=[
            _f("order_id", "STRING"),
            _f("payment_sequential", "INT64"),
            _f("payment_type", "STRING"),
            _f("payment_installments", "INT64"),
            _f("payment_value", "NUMERIC"),
        ],
        key_columns=["order_id", "payment_sequential"],
    ),
    "olist_order_reviews_dataset.csv": TableConfig(
        table="order_reviews",
        schema=[
            _f("review_id", "STRING"),
            _f("order_id", "STRING"),
            _f("review_score", "INT64"),
            _f("review_comment_title", "STRING", mode="NULLABLE"),
            _f("review_comment_message", "STRING", mode="NULLABLE"),
            _f("review_creation_date", "TIMESTAMP"),
            _f("review_answer_timestamp", "TIMESTAMP"),
        ],
        key_columns=["review_id", "order_id"],
    ),
}


def build_merge_sql(project: str, raw_dataset: str, stage_dataset: str, config: TableConfig) -> str:
    """Upsert the staging table into the persistent raw table: insert new
    rows, update rows that already exist, never truncate or delete."""
    all_columns = [f.name for f in config.schema]
    on_clause = " AND ".join(f"T.{c} = S.{c}" for c in config.key_columns)
    insert_clause = (
        f"INSERT ({', '.join(all_columns)}) "
        f"VALUES ({', '.join('S.' + c for c in all_columns)})"
    )

    if config.match_on_full_row:
        # Every column is part of the key -- an exact match means the row
        # is already present, so there's nothing left to update.
        return (
            f"MERGE `{project}.{raw_dataset}.{config.table}` T\n"
            f"USING `{project}.{stage_dataset}.{config.table}` S\n"
            f"ON {on_clause}\n"
            f"WHEN NOT MATCHED THEN\n"
            f"  {insert_clause}"
        )

    non_key_columns = [c for c in all_columns if c not in config.key_columns]
    update_clause = ", ".join(f"{c} = S.{c}" for c in non_key_columns)
    return (
        f"MERGE `{project}.{raw_dataset}.{config.table}` T\n"
        f"USING `{project}.{stage_dataset}.{config.table}` S\n"
        f"ON {on_clause}\n"
        f"WHEN MATCHED THEN\n"
        f"  UPDATE SET {update_clause}\n"
        f"WHEN NOT MATCHED THEN\n"
        f"  {insert_clause}"
    )
