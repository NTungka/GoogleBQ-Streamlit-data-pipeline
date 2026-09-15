"""
Olist marketplace dashboard -- queries the star schema marts
(`star_schema_olist.*`) directly via the BigQuery client.

Layout and caching pattern (st.cache_resource for the client, st.cache_data
for query results, KPI cards, sidebar filters, tabbed sections) follow
rohit-module2-project/dashboard/app.py. The queries themselves are new,
not copied -- that project's schema (fct_sales, fct_order_summary,
dim_geography) doesn't exist here. This schema keeps orders/items/
payments/reviews as separate fact tables at their own grain (see
README.md's "Star schema" section), so the tabs below are built around
this project's own stated business case instead: delivery performance,
customer satisfaction segmented by seller/category/delay, and marketplace/
seller health (see README.md's "Business case" section).
"""

import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery

PROJECT_ID = "project-858e450f-408c-4bd2-941"
DATASET_ID = "star_schema_olist"


@st.cache_resource
def get_bigquery_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


client = get_bigquery_client()


def _query(sql: str) -> pd.DataFrame:
    return client.query(sql).to_dataframe()


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


orders_df = load_orders()
items_df = load_order_items()
payments_df = load_payments()
reviews_df = load_reviews()

st.set_page_config(layout="wide", page_title="Olist E-Commerce Dashboard")
st.title("Olist Marketplace Dashboard")

# --- Sidebar filters ---
st.sidebar.header("Filters")

min_date = orders_df["order_purchase_date"].min().date()
max_date = orders_df["order_purchase_date"].max().date()
date_range = st.sidebar.date_input(
    "Order date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
)
if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

all_categories = sorted(items_df["product_category_name_english"].dropna().unique())
selected_categories = st.sidebar.multiselect(
    "Product categories", options=all_categories, default=all_categories
)

all_states = sorted(orders_df["customer_state"].dropna().unique())
selected_states = st.sidebar.multiselect(
    "Customer states", options=all_states, default=all_states
)


def _in_range(df: pd.DataFrame) -> pd.Series:
    d = df["order_purchase_date"].dt.date
    return (d >= start_date) & (d <= end_date)


f_orders = orders_df[_in_range(orders_df) & orders_df["customer_state"].isin(selected_states)]
f_items = items_df[
    _in_range(items_df) & items_df["product_category_name_english"].isin(selected_categories)
]
f_payments = payments_df[_in_range(payments_df)]
f_reviews = reviews_df[
    _in_range(reviews_df) & reviews_df["product_category_name_english"].isin(selected_categories)
]

# --- KPI cards ---
st.markdown(
    """
    <style>
    .kpi-card { background-color: #f8f9fa; border: 1px solid #e9ecef;
                padding: 15px; border-radius: 8px; text-align: center; }
    </style>
    """,
    unsafe_allow_html=True,
)

total_revenue = f_payments["payment_value"].sum()
total_orders = f_orders["order_id"].nunique()
total_customers = f_orders["customer_id"].nunique()
avg_order_value = total_revenue / total_orders if total_orders else 0
late_rate = f_orders["is_late_delivery"].mean() * 100 if len(f_orders) else 0
avg_review = f_reviews["review_score"].mean() if len(f_reviews) else float("nan")

cols = st.columns(6)
kpi_values = [
    ("Total Revenue", f"R$ {total_revenue:,.2f}"),
    ("Total Orders", f"{total_orders:,}"),
    ("Total Customers", f"{total_customers:,}"),
    ("Avg. Order Value", f"R$ {avg_order_value:,.2f}"),
    ("Late Delivery Rate", f"{late_rate:.1f}%"),
    ("Avg. Review Score", f"{avg_review:.2f}" if pd.notna(avg_review) else "n/a"),
]
for col, (label, value) in zip(cols, kpi_values):
    with col:
        st.markdown('<div class="kpi-card">', unsafe_allow_html=True)
        st.metric(label, value)
        st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")

tab_sales, tab_delivery, tab_satisfaction, tab_marketplace = st.tabs(
    ["Sales Overview", "Delivery Performance", "Customer Satisfaction", "Marketplace Health"]
)

# --- Sales Overview ---
with tab_sales:
    st.subheader("Sales Overview")

    revenue_trend = (
        f_payments.groupby(f_payments["order_purchase_date"].dt.to_period("M").dt.to_timestamp())[
            "payment_value"
        ]
        .sum()
        .reset_index()
    )
    fig = px.line(
        revenue_trend,
        x="order_purchase_date",
        y="payment_value",
        title="Monthly Revenue (payments collected)",
        labels={"order_purchase_date": "Month", "payment_value": "Revenue (R$)"},
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

    top_categories = (
        f_items.groupby("product_category_name_english")["total_item_value"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    )
    fig = px.bar(
        top_categories,
        x="total_item_value",
        y="product_category_name_english",
        orientation="h",
        title="Top 15 Categories by Revenue",
        labels={"total_item_value": "Revenue (R$)", "product_category_name_english": "Category"},
        template="plotly_white",
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, width="stretch")

# --- Delivery Performance (business case pillar 1) ---
with tab_delivery:
    st.subheader("Delivery Performance")
    st.caption(
        "The anomaly-monitor flags computed once on fct_orders (see README.md's "
        "dbt design notes) -- this tab is only possible because this schema keeps "
        "them, unlike a schema that only stores raw timestamps."
    )

    monthly_flags = (
        f_orders.assign(month=f_orders["order_purchase_date"].dt.to_period("M").dt.to_timestamp())
        .groupby("month")[["is_late_delivery", "is_carrier_before_approved", "is_delivered_missing_date"]]
        .mean()
        .mul(100)
        .reset_index()
        .melt(id_vars="month", var_name="flag", value_name="rate_pct")
    )
    fig = px.line(
        monthly_flags,
        x="month",
        y="rate_pct",
        color="flag",
        title="Monthly Anomaly Rates",
        labels={"month": "Month", "rate_pct": "Rate (%)", "flag": "Flag"},
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

    flag_counts = pd.DataFrame(
        {
            "flag": [
                "is_late_delivery",
                "is_carrier_before_approved",
                "is_delivered_missing_date",
                "has_no_line_items",
            ],
            "orders": [
                int(f_orders["is_late_delivery"].sum()),
                int(f_orders["is_carrier_before_approved"].sum()),
                int(f_orders["is_delivered_missing_date"].sum()),
                int(f_orders["has_no_line_items"].sum()),
            ],
        }
    )
    fig = px.bar(
        flag_counts,
        x="flag",
        y="orders",
        title="Orders Flagged, by Anomaly Type (selected range)",
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

# --- Customer Satisfaction (business case pillar 2) ---
with tab_satisfaction:
    st.subheader("Customer Satisfaction")

    col1, col2 = st.columns(2)
    with col1:
        fig = px.histogram(
            f_reviews,
            x="review_score",
            nbins=5,
            title="Review Score Distribution",
            template="plotly_white",
        )
        st.plotly_chart(fig, width="stretch")

    with col2:
        by_delay = (
            f_reviews.groupby("is_late_delivery")["review_score"].mean().reset_index()
        )
        by_delay["is_late_delivery"] = by_delay["is_late_delivery"].map(
            {True: "Late", False: "On time"}
        )
        fig = px.bar(
            by_delay,
            x="is_late_delivery",
            y="review_score",
            title="Avg. Review Score: Late vs. On-Time Delivery",
            labels={"is_late_delivery": "Delivery", "review_score": "Avg. Review Score"},
            template="plotly_white",
        )
        st.plotly_chart(fig, width="stretch")

    by_category = (
        f_reviews.groupby("product_category_name_english")["review_score"]
        .mean()
        .sort_values()
        .head(15)
        .reset_index()
    )
    fig = px.bar(
        by_category,
        x="review_score",
        y="product_category_name_english",
        orientation="h",
        title="15 Lowest-Rated Categories (avg. review score)",
        labels={"review_score": "Avg. Review Score", "product_category_name_english": "Category"},
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

# --- Marketplace / Seller Health (business case pillar 3) ---
with tab_marketplace:
    st.subheader("Marketplace / Seller Health")

    top_sellers = (
        f_items.groupby("seller_id")["total_item_value"]
        .sum()
        .sort_values(ascending=False)
        .head(15)
        .reset_index()
    )
    fig = px.bar(
        top_sellers,
        x="total_item_value",
        y="seller_id",
        orientation="h",
        title="Top 15 Sellers by Revenue",
        labels={"total_item_value": "Revenue (R$)", "seller_id": "Seller"},
        template="plotly_white",
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, width="stretch")

    status_counts = f_orders["order_status"].value_counts().reset_index()
    status_counts.columns = ["order_status", "orders"]
    fig = px.bar(
        status_counts,
        x="order_status",
        y="orders",
        title="Orders by Status (incl. cancellations)",
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

    seller_state_counts = f_items.drop_duplicates("seller_id")["seller_state"].value_counts().reset_index()
    seller_state_counts.columns = ["seller_state", "sellers"]
    fig = px.bar(
        seller_state_counts,
        x="seller_state",
        y="sellers",
        title="Active Sellers by State",
        template="plotly_white",
    )
    st.plotly_chart(fig, width="stretch")

st.sidebar.markdown("---")
st.sidebar.info("Data from the `star_schema_olist` marts, built with dbt. Dashboard: Streamlit.")
