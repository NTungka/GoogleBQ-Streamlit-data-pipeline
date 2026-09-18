"""
Shared BigQuery access, cached queries, and cross-page filter state for the
multi-page dashboard. Imported by app.py (the entry point, which renders
the sidebar filters once per run) and by every page in pages/.

Layout conventions here -- the persona-framed sidebar ("As an Olist
marketplace operator, I would like to know...", one page per question),
title+subheader+KPI-row+divider opening every page, st.caption() takeaways
under each chart -- are consistent across every page via this shared
module. Filters are rendered once in app.py (the script st.navigation
re-runs on every page switch) and shared across pages via
st.session_state, persisted with widget `key=`s so each page reads the
same selections rather than re-rendering its own filter widgets.

Query logic and dbt/olist-data-platform provenance notes are unchanged from
the single-file app.py this replaced -- see git history for that version.
"""

import pandas as pd
import streamlit as st
from google.cloud import bigquery

PROJECT_ID = "project-858e450f-408c-4bd2-941"
DATASET_ID = "star_schema_olist"


@st.cache_resource
def get_bigquery_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


def _query(sql: str) -> pd.DataFrame:
    return get_bigquery_client().query(sql).to_dataframe()


@st.cache_data(ttl=3600)
def load_orders() -> pd.DataFrame:
    """Order grain: status, delivery-anomaly flags, and the customer's state."""
    sql = f"""
        SELECT
            o.order_id,
            o.order_purchase_date,
            o.order_status,
            o.is_late_delivery,
            o.is_carrier_before_approved,
            o.is_delivered_missing_date,
            o.has_no_line_items,
            c.customer_id,
            c.customer_state
        FROM `{PROJECT_ID}.{DATASET_ID}.fct_orders` o
        JOIN `{PROJECT_ID}.{DATASET_ID}.dim_customers` c
          ON o.customer_id = c.customer_id
    """
    df = _query(sql)
    df["order_purchase_date"] = pd.to_datetime(df["order_purchase_date"])
    return df


@st.cache_data(ttl=3600)
def load_order_items() -> pd.DataFrame:
    """Item grain: revenue by category/seller, joined back to order date.

    dim_sellers is a Type 2 SCD (composite key seller_id + valid_from) --
    filtering to ds.is_current keeps this a one-row-per-seller join instead
    of fanning out across a seller's historical location rows.
    """
    sql = f"""
        SELECT
            oi.order_id,
            o.order_purchase_date,
            oi.total_item_value,
            dp.product_category_name_english,
            ds.seller_id,
            ds.seller_state
        FROM `{PROJECT_ID}.{DATASET_ID}.fct_order_items` oi
        JOIN `{PROJECT_ID}.{DATASET_ID}.fct_orders` o USING (order_id)
        LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.dim_products` dp
          ON oi.product_id = dp.product_id
        JOIN `{PROJECT_ID}.{DATASET_ID}.dim_sellers` ds
          ON oi.seller_id = ds.seller_id AND ds.is_current
    """
    df = _query(sql)
    df["order_purchase_date"] = pd.to_datetime(df["order_purchase_date"])
    return df


@st.cache_data(ttl=3600)
def load_payments() -> pd.DataFrame:
    """Payment grain: revenue actually collected, by date and method."""
    sql = f"""
        SELECT
            o.order_purchase_date,
            p.payment_type,
            p.payment_value
        FROM `{PROJECT_ID}.{DATASET_ID}.fct_order_payments` p
        JOIN `{PROJECT_ID}.{DATASET_ID}.fct_orders` o USING (order_id)
    """
    df = _query(sql)
    df["order_purchase_date"] = pd.to_datetime(df["order_purchase_date"])
    return df


@st.cache_data(ttl=3600)
def load_reviews() -> pd.DataFrame:
    """Review grain, joined to delivery lateness, category, and seller --
    the exact "segment by seller, category, and delivery delay" cut the
    business case calls out. An order with several items/categories
    attributes its one review to each of them, a standard approximation
    for order-level (not item-level) review data."""
    sql = f"""
        SELECT
            r.review_id,
            r.review_score,
            o.order_purchase_date,
            o.is_late_delivery,
            dp.product_category_name_english,
            ds.seller_id
        FROM `{PROJECT_ID}.{DATASET_ID}.fct_order_reviews` r
        JOIN `{PROJECT_ID}.{DATASET_ID}.fct_orders` o USING (order_id)
        JOIN `{PROJECT_ID}.{DATASET_ID}.fct_order_items` oi USING (order_id)
        LEFT JOIN `{PROJECT_ID}.{DATASET_ID}.dim_products` dp
          ON oi.product_id = dp.product_id
        JOIN `{PROJECT_ID}.{DATASET_ID}.dim_sellers` ds
          ON oi.seller_id = ds.seller_id AND ds.is_current
    """
    df = _query(sql)
    df["order_purchase_date"] = pd.to_datetime(df["order_purchase_date"])
    return df


@st.cache_data(ttl=3600)
def load_delivery_legs() -> pd.DataFrame:
    """Per-state delivery-day breakdown: seller handling (approved -> carrier)
    vs carrier transit (carrier -> customer) -- ported from
    olist-data-platform's delivery_performance_by_state mart, recomputed
    here since this schema keeps raw timestamps on fct_orders rather than
    pre-materializing day-diff measures."""
    sql = f"""
        SELECT
            c.customer_state,
            COUNT(*) AS delivered_orders,
            AVG(DATE_DIFF(DATE(o.order_delivered_customer_date), o.order_purchase_date, DAY)) AS avg_delivery_days,
            AVG(CASE WHEN o.is_late_delivery THEN 1.0 ELSE 0.0 END) AS late_rate,
            AVG(DATE_DIFF(DATE(o.order_delivered_carrier_date), DATE(o.order_approved_at), DAY)) AS avg_seller_handling_days,
            AVG(DATE_DIFF(DATE(o.order_delivered_customer_date), DATE(o.order_delivered_carrier_date), DAY)) AS avg_carrier_transit_days
        FROM `{PROJECT_ID}.{DATASET_ID}.fct_orders` o
        JOIN `{PROJECT_ID}.{DATASET_ID}.dim_customers` c ON o.customer_id = c.customer_id
        WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
        GROUP BY c.customer_state
    """
    return _query(sql)


@st.cache_data(ttl=3600)
def load_customer_segments() -> pd.DataFrame:
    """RFM-style segmentation per customer_unique_id -- ported from
    olist-data-platform's customer_metrics mart (same quartile thresholds
    and gold/silver/repeat/lapsed/standard rule), recomputed here at query
    time via BigQuery window functions rather than a pre-built mart, since
    this schema doesn't have one."""
    sql = f"""
        WITH delivered AS (
            SELECT o.order_id, c.customer_unique_id, o.order_purchase_date
            FROM `{PROJECT_ID}.{DATASET_ID}.fct_orders` o
            JOIN `{PROJECT_ID}.{DATASET_ID}.dim_customers` c ON o.customer_id = c.customer_id
            WHERE o.order_status NOT IN ('canceled', 'unavailable')
        ),
        order_value AS (
            SELECT order_id, SUM(total_item_value) AS order_total_value
            FROM `{PROJECT_ID}.{DATASET_ID}.fct_order_items`
            GROUP BY order_id
        ),
        per_customer AS (
            SELECT
                d.customer_unique_id,
                COUNT(DISTINCT d.order_id) AS order_count,
                SUM(ov.order_total_value) AS lifetime_value,
                MAX(d.order_purchase_date) AS last_purchase_date
            FROM delivered d
            LEFT JOIN order_value ov ON d.order_id = ov.order_id
            GROUP BY d.customer_unique_id
        ),
        dataset_end AS (SELECT MAX(last_purchase_date) AS max_date FROM per_customer),
        scored AS (
            SELECT
                pc.*,
                NTILE(4) OVER (ORDER BY DATE_DIFF(de.max_date, pc.last_purchase_date, DAY) DESC) AS r_score,
                NTILE(4) OVER (ORDER BY pc.order_count) AS f_score,
                NTILE(4) OVER (ORDER BY pc.lifetime_value) AS m_score
            FROM per_customer pc CROSS JOIN dataset_end de
        )
        SELECT
            *,
            CASE
                WHEN m_score = 4 AND r_score >= 3 THEN 'gold'
                WHEN m_score >= 3 AND r_score >= 2 THEN 'silver'
                WHEN order_count > 1 THEN 'repeat'
                WHEN r_score = 1 THEN 'lapsed'
                ELSE 'standard'
            END AS customer_segment
        FROM scored
    """
    return _query(sql)


# --- Shared sidebar filters ---------------------------------------------
#
# Rendered once by app.py on every run (app.py is the script st.navigation
# re-executes on each page switch), using fixed widget `key=`s so Streamlit
# stores the current selections in st.session_state -- readable from any
# page without re-rendering the widgets there. filter_orders_like() below
# is how each page applies them to its own (independently cached) query.

FILTER_KEYS = ("date_range", "selected_categories", "selected_states")


def render_sidebar_filters() -> None:
    st.sidebar.header("Filters")

    orders_df = load_orders()
    items_df = load_order_items()

    min_date = orders_df["order_purchase_date"].min().date()
    max_date = orders_df["order_purchase_date"].max().date()
    st.sidebar.date_input(
        "Order date range",
        value=st.session_state.get("date_range", (min_date, max_date)),
        min_value=min_date,
        max_value=max_date,
        key="date_range",
    )

    all_categories = sorted(items_df["product_category_name_english"].dropna().unique())
    st.sidebar.multiselect(
        "Product categories",
        options=all_categories,
        default=st.session_state.get("selected_categories", all_categories),
        key="selected_categories",
    )

    all_states = sorted(orders_df["customer_state"].dropna().unique())
    st.sidebar.multiselect(
        "Customer states",
        options=all_states,
        default=st.session_state.get("selected_states", all_states),
        key="selected_states",
    )

    st.sidebar.markdown("---")
    st.sidebar.info("Data from the `star_schema_olist` marts, built with dbt. Dashboard: Streamlit.")


def _date_range() -> tuple:
    date_range = st.session_state.get("date_range")
    if date_range and len(date_range) == 2:
        return date_range
    orders_df = load_orders()
    return orders_df["order_purchase_date"].min().date(), orders_df["order_purchase_date"].max().date()


def filter_by_date(df: pd.DataFrame, date_col: str = "order_purchase_date") -> pd.DataFrame:
    start_date, end_date = _date_range()
    d = df[date_col].dt.date
    return df[(d >= start_date) & (d <= end_date)]


def filter_by_date_and_state(df: pd.DataFrame, state_col: str = "customer_state") -> pd.DataFrame:
    df = filter_by_date(df)
    selected_states = st.session_state.get("selected_states")
    if selected_states:
        df = df[df[state_col].isin(selected_states)]
    return df


def filter_by_date_and_category(df: pd.DataFrame, category_col: str = "product_category_name_english") -> pd.DataFrame:
    df = filter_by_date(df)
    selected_categories = st.session_state.get("selected_categories")
    if selected_categories:
        df = df[df[category_col].isin(selected_categories)]
    return df
