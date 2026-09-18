import pandas as pd
import plotly.express as px
import streamlit as st

from common import filter_by_date, filter_by_date_and_category, load_order_items, load_payments

st.title("Sales Overview")
st.subheader("See when demand is strongest and which categories drive revenue.")

payments_df = load_payments()
items_df = load_order_items()
f_payments = filter_by_date(payments_df)
f_items = filter_by_date_and_category(items_df)

total_revenue = f_payments["payment_value"].sum()
total_orders = f_items["order_id"].nunique()
avg_order_value = total_revenue / total_orders if total_orders else 0

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("Total Revenue", f"R$ {total_revenue:,.2f}")
kpi2.metric("Orders", f"{total_orders:,}")
kpi3.metric("Avg. Order Value", f"R$ {avg_order_value:,.2f}")

st.divider()

st.subheader("Monthly Revenue")
revenue_trend = (
    f_payments.groupby(f_payments["order_purchase_date"].dt.to_period("M").dt.to_timestamp())["payment_value"]
    .sum()
    .reset_index()
)
fig = px.line(
    revenue_trend,
    x="order_purchase_date",
    y="payment_value",
    labels={"order_purchase_date": "Month", "payment_value": "Revenue (R$)"},
    template="plotly_white",
    markers=True,
)
# Black Friday 2017 marker -- olist-data-platform's #1 finding, confirmed on
# our own data too (Nov 2017 peak R$1,179,144 vs their reported R$1.17m).
black_friday = pd.Timestamp("2017-11-01")
if revenue_trend["order_purchase_date"].min() <= black_friday <= revenue_trend["order_purchase_date"].max():
    fig.add_vline(x=black_friday, line_dash="dash", line_color="grey")
    fig.add_annotation(
        x=black_friday, y=revenue_trend["payment_value"].max(),
        text="Black Friday<br>Nov 2017", showarrow=False, yshift=20,
    )
st.plotly_chart(fig, width="stretch")
st.caption("Revenue trend by month, with the Black Friday 2017 spike marked where it falls in range.")

st.subheader("Top Categories by Revenue")
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
    labels={"total_item_value": "Revenue (R$)", "product_category_name_english": "Category"},
    template="plotly_white",
)
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, width="stretch")
st.caption("The 15 highest-revenue product categories in the selected date range and category filter.")
