import plotly.express as px
import streamlit as st

from common import load_customer_segments

st.title("Customer Segments")
st.subheader("See who the best customers are, and how much of the business they carry.")
st.caption(
    "RFM-style segmentation (recency/frequency/monetary quartiles), ported from "
    "olist-data-platform's customer_metrics mart. Not filtered by the sidebar -- this is a "
    "full customer-base segmentation, not a per-order or per-category slice."
)

segments_df = load_customer_segments()

seg_summary = (
    segments_df.groupby("customer_segment")
    .agg(
        customers=("customer_unique_id", "size"),
        revenue=("lifetime_value", "sum"),
        avg_ltv=("lifetime_value", "mean"),
        avg_orders=("order_count", "mean"),
    )
    .sort_values("revenue", ascending=False)
)
seg_summary["revenue_share"] = seg_summary["revenue"] / seg_summary["revenue"].sum()
seg_summary["customer_share"] = seg_summary["customers"] / seg_summary["customers"].sum()

total_customers = segments_df["customer_unique_id"].nunique()
repeat_rate = (segments_df["order_count"] > 1).mean()
gold = seg_summary.loc["gold"] if "gold" in seg_summary.index else None

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Total Customers", f"{total_customers:,}")
kpi2.metric("Repeat-Purchase Rate", f"{repeat_rate:.1%}")
if gold is not None:
    kpi3.metric("Gold Customers", f"{int(gold['customers']):,}")
    kpi4.metric("Gold Revenue Share", f"{gold['revenue_share']:.1%}")

st.divider()

with st.expander("What do the segments mean?"):
    st.markdown(
        "- **Gold:** top monetary quartile, recent purchasers -- the highest-value, "
        "still-active customers.\n"
        "- **Silver:** strong monetary quartile with reasonable recency.\n"
        "- **Repeat:** more than one order, but didn't score high enough on monetary/recency "
        "to land in gold or silver.\n"
        "- **Lapsed:** in the least-recent quartile -- haven't purchased in a long time.\n"
        "- **Standard:** everyone else -- one order, not particularly recent or high-value.\n\n"
        "Same quartile thresholds as olist-data-platform's customer_metrics mart."
    )

st.subheader("Revenue Share by Customer Segment")
fig = px.bar(
    seg_summary.reset_index(),
    x="customer_segment",
    y="revenue_share",
    labels={"customer_segment": "Segment", "revenue_share": "Share of revenue"},
    template="plotly_white",
)
fig.update_yaxes(tickformat=".0%")
st.plotly_chart(fig, width="stretch")
st.caption("Gold customers are a small share of the customer base but a disproportionate share of revenue.")

st.subheader("Segment Summary")
st.dataframe(
    seg_summary[["customers", "customer_share", "revenue_share", "avg_ltv", "avg_orders"]].style.format(
        {"customer_share": "{:.1%}", "revenue_share": "{:.1%}", "avg_ltv": "R$ {:.2f}", "avg_orders": "{:.2f}"}
    )
)
