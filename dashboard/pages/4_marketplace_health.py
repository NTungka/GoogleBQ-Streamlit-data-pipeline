import plotly.express as px
import streamlit as st

from common import filter_by_date_and_category, filter_by_date_and_state, load_order_items, load_orders

st.title("Marketplace Health")
st.subheader("See which sellers and categories are carrying the marketplace, and order-status health.")

orders_df = load_orders()
items_df = load_order_items()
f_orders = filter_by_date_and_state(orders_df)
f_items = filter_by_date_and_category(items_df)

active_sellers = f_items["seller_id"].nunique()
delivered_share = (f_orders["order_status"] == "delivered").mean() * 100 if len(f_orders) else 0
canceled_share = (f_orders["order_status"] == "canceled").mean() * 100 if len(f_orders) else 0

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("Active Sellers", f"{active_sellers:,}")
kpi2.metric("Orders Delivered", f"{delivered_share:.1f}%")
kpi3.metric("Orders Canceled", f"{canceled_share:.1f}%")

st.divider()

st.subheader("Top 15 Sellers by Revenue")
top_sellers = (
    f_items.groupby("seller_id")["total_item_value"]
    .sum()
    .sort_values(ascending=False)
    .head(15)
    .reset_index()
)
fig = px.bar(
    top_sellers, x="total_item_value", y="seller_id", orientation="h",
    labels={"total_item_value": "Revenue (R$)", "seller_id": "Seller"},
    template="plotly_white",
)
fig.update_layout(yaxis={"categoryorder": "total ascending"})
st.plotly_chart(fig, width="stretch")
st.caption("The sellers to brief and stock ahead of a demand spike.")

st.subheader("Orders by Status")
status_counts = f_orders["order_status"].value_counts().reset_index()
status_counts.columns = ["order_status", "orders"]
fig = px.bar(status_counts, x="order_status", y="orders", template="plotly_white")
st.plotly_chart(fig, width="stretch")
st.caption("Includes cancellations and unavailable orders alongside delivered ones.")

st.subheader("Active Sellers by State")
seller_state_counts = f_items.drop_duplicates("seller_id")["seller_state"].value_counts().reset_index()
seller_state_counts.columns = ["seller_state", "sellers"]
fig = px.bar(seller_state_counts, x="seller_state", y="sellers", template="plotly_white")
st.plotly_chart(fig, width="stretch")
st.caption("Where the seller base is concentrated -- relevant to regional fulfilment planning.")
