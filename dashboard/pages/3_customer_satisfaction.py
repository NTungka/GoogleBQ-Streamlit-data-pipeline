import pandas as pd
import plotly.express as px
import streamlit as st

from common import filter_by_date_and_category, load_reviews

st.title("Customer Satisfaction")
st.subheader("See how delivery delays -- and which categories -- affect review scores.")

reviews_df = load_reviews()
f_reviews = filter_by_date_and_category(reviews_df)

avg_review = f_reviews["review_score"].mean() if len(f_reviews) else float("nan")
low_score_share = (f_reviews["review_score"] <= 2).mean() * 100 if len(f_reviews) else 0
late_gap = (
    f_reviews.groupby("is_late_delivery")["review_score"].mean()
    if len(f_reviews)
    else None
)
gap_value = (
    late_gap.get(False, float("nan")) - late_gap.get(True, float("nan"))
    if late_gap is not None and len(late_gap) == 2
    else float("nan")
)

kpi1, kpi2, kpi3 = st.columns(3)
kpi1.metric("Avg. Review Score", f"{avg_review:.2f}" if pd.notna(avg_review) else "n/a")
kpi2.metric("1-2 Star Reviews", f"{low_score_share:.1f}%")
kpi3.metric(
    "On-Time vs Late Review Gap",
    f"{gap_value:+.2f}" if pd.notna(gap_value) else "n/a",
    help="Average on-time review score minus average late-delivery review score.",
)

st.divider()

st.subheader("Review Score Distribution")
fig = px.histogram(f_reviews, x="review_score", nbins=5, template="plotly_white")
st.plotly_chart(fig, width="stretch")
st.caption("How review scores (1-5) are distributed across the selected date range and categories.")

st.subheader("Avg. Review Score: Late vs. On-Time Delivery")
by_delay = f_reviews.groupby("is_late_delivery")["review_score"].mean().reset_index()
by_delay["is_late_delivery"] = by_delay["is_late_delivery"].map({True: "Late", False: "On time"})
fig = px.bar(
    by_delay, x="is_late_delivery", y="review_score",
    labels={"is_late_delivery": "Delivery", "review_score": "Avg. Review Score"},
    template="plotly_white",
)
st.plotly_chart(fig, width="stretch")
st.caption("Late deliveries score noticeably lower -- this is the direct commercial cost of lateness.")

st.subheader("15 Lowest-Rated Categories")
by_category = (
    f_reviews.groupby("product_category_name_english")["review_score"]
    .mean()
    .sort_values()
    .head(15)
    .reset_index()
)
fig = px.bar(
    by_category, x="review_score", y="product_category_name_english", orientation="h",
    labels={"review_score": "Avg. Review Score", "product_category_name_english": "Category"},
    template="plotly_white",
)
st.plotly_chart(fig, width="stretch")
st.caption("Categories most worth investigating for a quality or expectation-setting issue.")
