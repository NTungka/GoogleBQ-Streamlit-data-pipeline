"""
Load the 9 Olist CSVs into the Cloud SQL for PostgreSQL staging schema
(see staging_schema.sql), using the Cloud SQL Python Connector -- IAM
authenticated, encrypted, no Authorized Networks / IP allowlisting needed.

One-time setup (do this before running this script):
  1. pip install "cloud-sql-python-connector[pg8000]" sqlalchemy python-dotenv pandas
  2. gcloud auth application-default login
     (grants this script your IAM identity; requires "Cloud SQL Client" role
     on your user/service account)
  3. Apply staging_schema.sql to the instance once, e.g. via Cloud Shell or
     local gcloud:
         gcloud sql connect INSTANCE_NAME --user=postgres --database=DB_NAME < staging_schema.sql
     (psql handles multi-statement DDL correctly; this script does not
     re-implement DDL parsing)
  4. cp .env.example .env   and fill in INSTANCE_CONNECTION_NAME / DB_USER / DB_PASS / DB_NAME

Usage:
    python load_to_cloudsql.py
"""

import os
from pathlib import Path

import pandas as pd
import sqlalchemy
from dotenv import load_dotenv
from google.cloud.sql.connector import Connector

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

INSTANCE_CONNECTION_NAME = os.environ["INSTANCE_CONNECTION_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_NAME = os.environ["DB_NAME"]

# Load order matters: parent tables (referenced by FK) must load before
# child tables that reference them.
TABLE_LOAD_ORDER = [
    ("category_translation", "product_category_name_translation.csv", "category_translation"),
    ("customers", "olist_customers_dataset.csv", "customers"),
    ("sellers", "olist_sellers_dataset.csv", "sellers"),
    ("products", "olist_products_dataset.csv", "products"),
    ("geolocation", "olist_geolocation_dataset.csv", "geolocation_raw"),
    ("orders", "olist_orders_dataset.csv", "orders"),
    ("order_items", "olist_order_items_dataset.csv", "order_items"),
    ("order_payments", "olist_order_payments_dataset.csv", "order_payments"),
    ("order_reviews", "olist_order_reviews_dataset.csv", "order_reviews"),
]

DATE_COLUMNS = {
    "orders": [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ],
    "order_items": ["shipping_limit_date"],
    "order_reviews": ["review_creation_date", "review_answer_timestamp"],
}

# Columns that are nullable integers in Postgres but load as float64 in
# pandas due to NaNs -- cast to pandas' nullable Int64 so NaN -> NULL
# instead of e.g. 40.0 being written where 40 is expected.
NULLABLE_INT_COLUMNS = {
    "products": ["product_name_lenght", "product_description_lenght", "product_photos_qty"],
}


def build_engine(connector: Connector) -> sqlalchemy.engine.Engine:
    def getconn():
        return connector.connect(
            INSTANCE_CONNECTION_NAME,
            "pg8000",
            user=DB_USER,
            password=DB_PASS,
            db=DB_NAME,
        )

    return sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn)


def load_table(engine: sqlalchemy.engine.Engine, name: str, csv_file: str, target_table: str) -> None:
    print(f"Loading {csv_file} -> staging.{target_table} ...")
    df = pd.read_csv(DATA_DIR / csv_file)

    for col in DATE_COLUMNS.get(name, []):
        df[col] = pd.to_datetime(df[col], errors="coerce")

    for col in NULLABLE_INT_COLUMNS.get(name, []):
        df[col] = df[col].astype("Int64")

    df.to_sql(
        target_table,
        engine,
        schema="staging",
        if_exists="append",
        index=False,
        method="multi",
        chunksize=5000,
    )
    print(f"  -> {len(df)} rows loaded")


def main() -> None:
    connector = Connector()
    try:
        engine = build_engine(connector)
        for name, csv_file, target_table in TABLE_LOAD_ORDER:
            load_table(engine, name, csv_file, target_table)
        print("\nAll tables loaded successfully.")
    finally:
        connector.close()


if __name__ == "__main__":
    main()
