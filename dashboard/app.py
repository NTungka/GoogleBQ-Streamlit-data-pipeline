"""
Entry point for the multi-page Olist marketplace dashboard.

st.navigation()/st.Page() (native multi-page, not a sidebar-radio switch
over one script) replaces the single-file app.py this used to be -- one
page per business-case question, in pages/. This script re-runs on every
page navigation (st.navigation dispatches into it), so the sidebar filters
rendered here via common.render_sidebar_filters() appear on every page and
persist across navigations through st.session_state. See common.py for
the full layout note.
"""

import streamlit as st

from common import render_sidebar_filters

st.set_page_config(layout="wide", page_title="Olist Marketplace Dashboard")

st.sidebar.title("Olist Marketplace Dashboard")
st.sidebar.caption("As an Olist marketplace operator, I would like to know...")

render_sidebar_filters()

pages = [
    st.Page("pages/1_sales_overview.py", title="...when demand is strongest, and what's selling", icon="📈"),
    st.Page("pages/2_delivery_performance.py", title="...where deliveries are slow or late", icon="🚚"),
    st.Page("pages/3_customer_satisfaction.py", title="...how delivery delays affect satisfaction", icon="⭐"),
    st.Page("pages/4_marketplace_health.py", title="...which sellers and categories drive the marketplace", icon="🏪"),
    st.Page("pages/5_customer_segments.py", title="...who my best customers are", icon="👥"),
]
st.navigation(pages).run()
