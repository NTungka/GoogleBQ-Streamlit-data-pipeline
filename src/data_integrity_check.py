import pandas as pd
import numpy as np
import os
from pathlib import Path

DATA_DIR = str(Path(__file__).resolve().parent.parent / "data")

files = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

dfs = {}
print("=" * 80)
print("LOADING FILES")
print("=" * 80)
for name, fname in files.items():
    path = os.path.join(DATA_DIR, fname)
    df = pd.read_csv(path)
    dfs[name] = df
    print(f"{name:22s} shape={df.shape}")

print()
print("=" * 80)
print("SCHEMA / DTYPES")
print("=" * 80)
for name, df in dfs.items():
    print(f"\n--- {name} ---")
    print(df.dtypes.to_string())

print()
print("=" * 80)
print("NULL VALUE COUNTS (columns with any nulls)")
print("=" * 80)
for name, df in dfs.items():
    nulls = df.isnull().sum()
    nulls = nulls[nulls > 0]
    if len(nulls) > 0:
        pct = (nulls / len(df) * 100).round(2)
        summary = pd.DataFrame({"null_count": nulls, "pct": pct})
        print(f"\n--- {name} ({len(df)} rows) ---")
        print(summary.to_string())
    else:
        print(f"\n--- {name} --- no nulls")

print()
print("=" * 80)
print("DUPLICATE ROWS (full row duplicates)")
print("=" * 80)
for name, df in dfs.items():
    dupes = df.duplicated().sum()
    print(f"{name:22s} full-row duplicates: {dupes}")

print()
print("=" * 80)
print("PRIMARY KEY UNIQUENESS CHECKS")
print("=" * 80)
pk_checks = {
    "customers": "customer_id",
    "orders": "order_id",
    "products": "product_id",
    "sellers": "seller_id",
    "category_translation": "product_category_name",
}
for name, key in pk_checks.items():
    df = dfs[name]
    n_total = len(df)
    n_unique = df[key].nunique()
    print(f"{name:22s} key={key:25s} total={n_total:8d} unique={n_unique:8d} dup_keys={n_total - n_unique}")

# order_items composite key
oi = dfs["order_items"]
comp_dupe = oi.duplicated(subset=["order_id", "order_item_id"]).sum()
print(f"{'order_items':22s} key=(order_id,order_item_id)      dup_keys={comp_dupe}")

# order_reviews - review_id may repeat across orders
orv = dfs["order_reviews"]
print(f"{'order_reviews':22s} key=review_id                    total={len(orv)} unique={orv['review_id'].nunique()} unique_order_id={orv['order_id'].nunique()}")

print()
print("=" * 80)
print("REFERENTIAL INTEGRITY CHECKS (orphans = FK values not found in parent PK)")
print("=" * 80)

def check_fk(child_name, child_df, fk_col, parent_name, parent_df, pk_col):
    child_keys = set(child_df[fk_col].dropna().unique())
    parent_keys = set(parent_df[pk_col].dropna().unique())
    orphans = child_keys - parent_keys
    print(f"{child_name}.{fk_col} -> {parent_name}.{pk_col}: {len(orphans)} orphan values "
          f"({len(orphans)/max(len(child_keys),1)*100:.3f}% of distinct FK values)")
    return orphans

check_fk("orders", dfs["orders"], "customer_id", "customers", dfs["customers"], "customer_id")
check_fk("order_items", dfs["order_items"], "order_id", "orders", dfs["orders"], "order_id")
check_fk("order_items", dfs["order_items"], "product_id", "products", dfs["products"], "product_id")
check_fk("order_items", dfs["order_items"], "seller_id", "sellers", dfs["sellers"], "seller_id")
check_fk("order_payments", dfs["order_payments"], "order_id", "orders", dfs["orders"], "order_id")
check_fk("order_reviews", dfs["order_reviews"], "order_id", "orders", dfs["orders"], "order_id")
check_fk("products", dfs["products"], "product_category_name", "category_translation", dfs["category_translation"], "product_category_name")

# reverse: orders with no items / no payments / no reviews
orders_ids = set(dfs["orders"]["order_id"])
oi_ids = set(dfs["order_items"]["order_id"])
op_ids = set(dfs["order_payments"]["order_id"])
orv_ids = set(dfs["order_reviews"]["order_id"])
print(f"\norders with NO order_items: {len(orders_ids - oi_ids)}")
print(f"orders with NO order_payments: {len(orders_ids - op_ids)}")
print(f"orders with NO order_reviews: {len(orders_ids - orv_ids)}")

print()
print("=" * 80)
print("ORDER STATUS DISTRIBUTION")
print("=" * 80)
print(dfs["orders"]["order_status"].value_counts().to_string())

print()
print("=" * 80)
print("DATE LOGIC CHECKS (orders table)")
print("=" * 80)
orders = dfs["orders"].copy()
date_cols = [c for c in orders.columns if "date" in c or "timestamp" in c]
for c in date_cols:
    orders[c] = pd.to_datetime(orders[c], errors="coerce")

print(f"Date columns: {date_cols}")
print(f"\nDate range (order_purchase_timestamp): {orders['order_purchase_timestamp'].min()} to {orders['order_purchase_timestamp'].max()}")

# logic: delivered_customer_date should be >= purchase timestamp
bad_delivery = orders[
    orders["order_delivered_customer_date"].notna() &
    (orders["order_delivered_customer_date"] < orders["order_purchase_timestamp"])
]
print(f"\nRows where delivered_customer_date < purchase_timestamp: {len(bad_delivery)}")

bad_approval = orders[
    orders["order_approved_at"].notna() &
    (orders["order_approved_at"] < orders["order_purchase_timestamp"])
]
print(f"Rows where order_approved_at < purchase_timestamp: {len(bad_approval)}")

bad_carrier = orders[
    orders["order_delivered_carrier_date"].notna() &
    orders["order_approved_at"].notna() &
    (orders["order_delivered_carrier_date"] < orders["order_approved_at"])
]
print(f"Rows where delivered_carrier_date < approved_at: {len(bad_carrier)}")

# delivered status but missing delivered_customer_date
delivered_missing_date = orders[
    (orders["order_status"] == "delivered") &
    orders["order_delivered_customer_date"].isna()
]
print(f"\nOrders with status='delivered' but missing delivered_customer_date: {len(delivered_missing_date)}")

print()
print("=" * 80)
print("NUMERIC SANITY CHECKS")
print("=" * 80)
oi = dfs["order_items"]
print(f"order_items.price: min={oi['price'].min()}, max={oi['price'].max()}, negative_or_zero={ (oi['price']<=0).sum() }")
print(f"order_items.freight_value: min={oi['freight_value'].min()}, max={oi['freight_value'].max()}, negative={ (oi['freight_value']<0).sum() }")

op = dfs["order_payments"]
print(f"order_payments.payment_value: min={op['payment_value'].min()}, max={op['payment_value'].max()}, negative_or_zero={ (op['payment_value']<=0).sum() }")
print(f"order_payments.payment_installments: min={op['payment_installments'].min()}, max={op['payment_installments'].max()}, zero_installments={ (op['payment_installments']==0).sum() }")
print(f"order_payments.payment_type values: {op['payment_type'].unique().tolist()}")

orv = dfs["order_reviews"]
print(f"order_reviews.review_score range: {orv['review_score'].min()} - {orv['review_score'].max()}")
print(f"order_reviews.review_score value counts:\n{orv['review_score'].value_counts().sort_index().to_string()}")

prod = dfs["products"]
weight_zero = (prod["product_weight_g"] == 0).sum()
print(f"\nproducts.product_weight_g == 0: {weight_zero}")
dims_zero = ((prod["product_length_cm"]==0)|(prod["product_height_cm"]==0)|(prod["product_width_cm"]==0)).sum()
print(f"products with a zero dimension: {dims_zero}")

geo = dfs["geolocation"]
print(f"\ngeolocation lat range: {geo['geolocation_lat'].min()} to {geo['geolocation_lat'].max()}")
print(f"geolocation lng range: {geo['geolocation_lng'].min()} to {geo['geolocation_lng'].max()}")
# Brazil bounding box approx lat: -33.75 to 5.27, lng: -73.99 to -34.79
out_of_bbox = geo[(geo["geolocation_lat"] > 5.27) | (geo["geolocation_lat"] < -33.75) |
                   (geo["geolocation_lng"] > -34.79) | (geo["geolocation_lng"] < -73.99)]
print(f"geolocation points outside Brazil bounding box: {len(out_of_bbox)} ({len(out_of_bbox)/len(geo)*100:.3f}%)")

geo_dupes = geo.duplicated().sum()
print(f"geolocation full-row duplicates: {geo_dupes}")

print()
print("=" * 80)
print("ZIP CODE PREFIX CROSS-CHECK (customers/sellers vs geolocation)")
print("=" * 80)
cust_zips = set(dfs["customers"]["customer_zip_code_prefix"].unique())
seller_zips = set(dfs["sellers"]["seller_zip_code_prefix"].unique())
geo_zips = set(geo["geolocation_zip_code_prefix"].unique())
print(f"customer zip prefixes not in geolocation: {len(cust_zips - geo_zips)} / {len(cust_zips)}")
print(f"seller zip prefixes not in geolocation: {len(seller_zips - geo_zips)} / {len(seller_zips)}")

print()
print("=" * 80)
print("DONE")
print("=" * 80)
