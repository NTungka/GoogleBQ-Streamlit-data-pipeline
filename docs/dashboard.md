# Dashboard: architecture and layout

Design rationale for the Streamlit dashboard -- its multi-page structure,
where its layout conventions came from, and why the charts on each page
are what they are. For the actual deploy/spin-down commands, see the main
[README.md How to run, step 9](../README.md#9-deploy-the-dashboard).

## Structure

`dashboard/` is a native Streamlit multi-page app, not a single script:

- **`app.py`** -- entry point only: page config, sidebar filters, navigation.
- **`common.py`** -- the BigQuery client, all cached query functions, and
  filter-application helpers, shared by every page.
- **`pages/`** -- one file per business-case question: Sales Overview,
  Delivery Performance, Customer Satisfaction, Marketplace Health, Customer
  Segments.

### Layout and navigation

The sidebar nav is persona-framed ("As an Olist marketplace operator, I
would like to know...") rather than generic labels, and every page opens
with the same rhythm: title, one-line subheader, a KPI row, a divider,
then charts with `st.caption()` takeaways underneath. Navigation itself
uses real Streamlit multi-page (`st.navigation`/`st.Page`), not a
sidebar-radio switch over one script -- each business-case question is a
separate file in `pages/`.

Filters persist across pages via `st.session_state`: `app.py` re-runs on
every page navigation (that's how `st.navigation` dispatches), so the
filter widgets in `common.render_sidebar_filters()` render fresh each
time -- but since they're declared with fixed `key=`s, Streamlit keeps
their values in `st.session_state` across those re-renders, and every page
reads the same session state through `common.py`'s filter helpers
(`filter_by_date`, `filter_by_date_and_state`, `filter_by_date_and_category`).

### Deploy target: `mod2_dbt_project/cloudbuild.yaml`'s `deploy-streamlit` step

`gcloud run deploy --source=dashboard` builds `dashboard/Dockerfile` via
Cloud Build and deploys in one step -- the same target (a Cloud Run
service, `--platform=managed`, publicly reachable) as that project's
`deploy-streamlit` step, just without needing a separate multi-trigger
pipeline for a single service. No new IAM grant needed -- it runs as the
same default compute service account already holding
`bigquery.dataEditor` + `bigquery.jobUser` (see
[automated_pipeline.md](automated_pipeline.md)).

`--allow-unauthenticated` matches `mod2_dbt_project`'s own choice (and the
Olist dataset is public/anonymized), but it does mean anyone with the URL
can query BigQuery through this dashboard, incurring query cost, with no
auth check. Drop the flag and use `gcloud run services
add-iam-policy-binding olist-dashboard --member=<...>
--role=roles/run.invoker` instead if that's not the intended posture.

Cloud Run already scales to zero by default (no `minScale` is set), so
there's no idle *compute* cost either way -- the thing actually worth
weighing is the public URL's exposure, which is why the service has been
deliberately deleted (not just left idle) between active use; see the main
README's Status and the "Spin down / restore" subsection under step 9 for
the current state and the commands.

## Chart provenance: `olist-data-platform/analysis/`

Before replicating anything, its conclusions were cross-checked against
this project's own live data, not assumed to transfer: same `is_late`
definition (delivered after the estimate), same `order_total_value`
definition (`price + freight_value`), and two headline numbers verified
directly against `star_schema_olist` in BigQuery -- this project's Nov-2017
revenue peak (R$1,179,144) and São Paulo's revenue share (37.4%) both land
within rounding of that repo's reported R$1.17m and 38%. Given that, the
following were ported (as Plotly, to stay consistent with the rest of this
app -- their originals are matplotlib):

- **Sales Overview:** the Black Friday Nov-2017 annotation on the revenue
  trend -- their #1 finding.
- **Delivery Performance:** the seller-handling-vs-carrier-transit stacked
  bar by state (their headline delivery finding: handling is flat
  everywhere, the regional gap is entirely carrier transit), the
  delivery-days-vs-late-rate scatter, and the monthly
  volume-vs-late-rate dual-axis chart.
- **Customer Segments** (a new page, not present before this port): the
  RFM segmentation (gold/silver/repeat/lapsed/standard, same
  quartile-based rule as their `customer_metrics` dbt mart) -- this
  answers the "who is the gold audience" question the dashboard didn't
  cover at all before.

Not ported: several of the source repo's 10 output PNGs are duplicate-
numbered outputs from its notebooks rather than the documented
`run_analysis.py` script (e.g. `09_top_sellers.png`,
`10_executive_dashboard.png`), and its own README has an unresolved
git-merge-conflict block in it -- signs that repo is mid-refactor, not a
clean final set. What's here is the subset its report and script actually
document, that also maps cleanly onto this project's schema (which keeps
orders/items/payments/reviews as separate fact tables at their own grain,
rather than that repo's pre-aggregated `fct_sales`/`fct_order_summary`
marts -- see [dbt_testing_and_staging.md](dbt_testing_and_staging.md) for
why).

## Caching: what's shared, what's per-viewer

`common.py` uses `st.cache_resource` (for the BigQuery client -- stored by
reference, one shared instance) and `st.cache_data(ttl=3600)` (for the six
query loaders -- stored as a copy per return, so one caller can't mutate
what another caller sees). Both live in the Cloud Run **container's**
memory, never the browser -- Streamlit has no client-side Python runtime.

This cache is shared across every browser session hitting the same
container instance, keyed by function + arguments, not scoped per user --
the first person to load a page pays the BigQuery query cost, everyone
else within the `ttl` window gets it for free. What *is* per-session is
`st.session_state` (the sidebar filter selections) -- filtering happens in
pandas after the shared fetch, so changing a filter never re-triggers a
BigQuery query. Three consequences worth knowing: the cache doesn't
survive a redeploy or a scale-to-zero cycle (both wipe container memory);
it isn't shared across multiple concurrent instances if Cloud Run ever
scales the service horizontally (no external cache backing it); and no
user-specific data ever enters it, since the cached DataFrames are always
the full, unfiltered query results.
