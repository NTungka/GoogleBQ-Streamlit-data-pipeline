import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from common import filter_by_date_and_state, load_delivery_legs, load_orders

st.title("Delivery Performance")
st.subheader("See where deliveries are slow or late, and which leg of the journey drives it.")

orders_df = load_orders()
delivery_legs_df = load_delivery_legs()
f_orders = filter_by_date_and_state(orders_df)

late_rate = f_orders["is_late_delivery"].mean() * 100 if len(f_orders) else 0
flagged_orders = int(f_orders["is_late_delivery"].sum())
avg_state_delivery_days = delivery_legs_df["avg_delivery_days"].mean()

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("Late Delivery Rate", f"{late_rate:.1f}%")
kpi2.metric("Orders Delivered Late", f"{flagged_orders:,}")
kpi3.metric("Avg. Delivery Days (state avg.)", f"{avg_state_delivery_days:.1f}")

st.divider()

st.subheader("Monthly Anomaly Rates")
st.caption(
    "The anomaly-monitor flags computed once on fct_orders (see README.md's dbt design "
    "notes) -- this page is only possible because this schema keeps them, unlike a schema "
    "that only stores raw timestamps."
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
    monthly_flags, x="month", y="rate_pct", color="flag",
    labels={"month": "Month", "rate_pct": "Rate (%)", "flag": "Flag"},
    template="plotly_white",
)
st.plotly_chart(fig, width="stretch")
st.caption("Late delivery, carrier-before-approved, and missing-delivery-date rates, by month.")

st.subheader("Orders Flagged by Anomaly Type")
flag_counts = (
    f_orders[["is_late_delivery", "is_carrier_before_approved", "is_delivered_missing_date", "has_no_line_items"]]
    .sum()
    .astype(int)
    .rename_axis("flag")
    .reset_index(name="orders")
)
fig = px.bar(flag_counts, x="flag", y="orders", template="plotly_white")
st.plotly_chart(fig, width="stretch")
st.caption("Raw counts behind the rates above, for the selected date range and states.")

st.subheader("Average Delivery Days by State: Seller Handling vs Carrier Transit")
st.caption(
    "Ported from olist-data-platform's delivery-readiness analysis (its #1 finding: seller "
    "handling is flat everywhere, the regional gap is entirely carrier transit). Reads a "
    "pre-aggregated per-state mart, so it isn't filtered by date/state like the charts above."
)
legs = delivery_legs_df.sort_values("avg_delivery_days", ascending=False)
fig = go.Figure()
fig.add_bar(name="Seller handling", x=legs["customer_state"], y=legs["avg_seller_handling_days"])
fig.add_bar(name="Carrier transit", x=legs["customer_state"], y=legs["avg_carrier_transit_days"])
fig.update_layout(barmode="stack", xaxis_title="Customer state", yaxis_title="Days", template="plotly_white")
st.plotly_chart(fig, width="stretch")

st.subheader("States: Slower Is Also Later")
fig = px.scatter(
    legs, x="avg_delivery_days", y="late_rate", text="customer_state",
    labels={"avg_delivery_days": "Avg. delivery days", "late_rate": "Late deliveries (rate)"},
    template="plotly_white",
)
fig.update_traces(textposition="top center")
fig.update_yaxes(tickformat=".0%")
st.plotly_chart(fig, width="stretch")
st.caption("States further to the right (slower) also tend to sit higher (later) -- distance and lateness move together.")

st.subheader("Order Volume vs Late-Delivery Rate by Month")
monthly_volume = (
    orders_df.assign(month=orders_df["order_purchase_date"].dt.to_period("M").dt.to_timestamp())
    .groupby("month")
    .agg(orders=("order_id", "count"), late_rate=("is_late_delivery", "mean"))
    .reset_index()
)
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_bar(x=monthly_volume["month"], y=monthly_volume["orders"], name="Orders", opacity=0.4)
fig.add_trace(
    go.Scatter(x=monthly_volume["month"], y=monthly_volume["late_rate"], name="Late rate", mode="lines+markers"),
    secondary_y=True,
)
fig.update_layout(template="plotly_white")
fig.update_yaxes(title_text="Orders", secondary_y=False)
fig.update_yaxes(title_text="Late rate", tickformat=".0%", secondary_y=True)
st.plotly_chart(fig, width="stretch")
st.caption(
    "Uses the full (unfiltered by sidebar) order history, to show the true capacity effect: "
    "the late rate tends to spike alongside order volume, not just distance."
)
