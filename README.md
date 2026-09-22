# Olist Marketplace Data Pipeline

A data pipeline for Olist's Brazilian e-commerce marketplace dataset, built for a
**BI/analytics dashboard** -- not a predictive-ML project. The Kaggle source
dataset is pulled into Cloud Storage on a schedule, merged into BigQuery, and
reshaped into a star schema with dbt for downstream dashboarding. (An earlier
Postgres/Cloud SQL staging path is parked, not deleted -- see
[docs/automated_pipeline.md](docs/automated_pipeline.md#parked-postgres-staging).)

This README covers overall design decisions and the current step-by-step CLI
setup. Deeper rationale for each subsystem lives in its own doc:

- [docs/automated_pipeline.md](docs/automated_pipeline.md) -- ingestion
  architecture ("why"), the full IAM reference (every service account and
  why it needs each role), and the parked Postgres path.
- [docs/dbt_testing_and_staging.md](docs/dbt_testing_and_staging.md) -- the
  star schema, SCD Type 2 reasoning, and what all 54 dbt tests actually check.
- [docs/dashboard.md](docs/dashboard.md) -- the Streamlit dashboard's
  multi-page structure, layout/chart provenance, and caching behavior.

## Business case

The dashboard is meant to give stakeholders visibility into three things the
raw data already shows real signal on:

- **Delivery performance** -- 8.1% of delivered orders arrive after their
  estimated date; 1,359 orders have carrier/approval timestamp inversions
  worth investigating.
- **Customer satisfaction** -- review scores skew positive overall, but ~14.6%
  are 1-2 star and worth segmenting by seller, category, and delivery delay.
- **Marketplace/seller health** -- order volume, revenue, and cancellation
  patterns across sellers and product categories.

The pipeline is built around **constraint-first integrity** (dbt tests enforce
what's provably clean -- see [docs/dbt_testing_and_staging.md](docs/dbt_testing_and_staging.md))
plus **transparent flagging** (real anomalies are surfaced as queryable data,
never silently dropped or hidden).

## Architecture

```
Kaggle (olistbr/brazilian-ecommerce)
  -> pull_kaggle_to_gcs (Cloud Function, Cloud Scheduler cron)
       only re-pulls when Kaggle's last-updated metadata moves
    -> GCS bucket, raw/*.csv
      -> load_gcs_to_bigquery (Cloud Function, GCS object-finalize trigger)
           per-file CSV load -> staging table -> MERGE into `raw.<table>`
           writes a completion marker; once all 9 tables have one, triggers
           dbt-build-job and clears the markers for tomorrow
        -> BigQuery `raw` dataset   (upsert: insert new, update matched, never truncate)
          -> dbt-build-job (Cloud Run Job) -> `dbt build`
            -> dbt staging models + star schema marts (dim_*, fct_*, incl. anomaly monitors)
              -> Streamlit dashboard (Cloud Run service, reads star_schema_olist directly)

GitHub `main`, merge touching dbt_olist/**
  -> Cloud Build trigger (path-filtered)
    -> dbt-build-job (same Cloud Run Job as above) -> `dbt build`
```

Two independent paths reach the same `dbt-build-job`: one reacting to new
*data* (event-driven), one reacting to new *code* (GitHub-merge-driven).
Code for both Cloud Functions lives in `cloud_functions/`. **Full rationale
for every "why" behind this diagram -- MERGE vs `WRITE_TRUNCATE`, one
function vs two, the Kaggle API quirks, the two CSV load bugs, why the dbt
trigger uses completion markers -- is in
[docs/automated_pipeline.md](docs/automated_pipeline.md).**

## Status

Verified live against the actual deployed project, not just design intent:

| Stage | Status |
|---|---|
| Data integrity check (9 raw CSVs) | Done -- solid referential integrity overall; found duplicate geolocation rows, timestamp anomalies, late deliveries, orphan categories (see `src/data_integrity_check.py`) |
| Postgres staging schema (Cloud SQL) | **Parked** -- superseded by the GCS/BigQuery pipeline below; scripts kept in `src/` for reference, see [docs/automated_pipeline.md](docs/automated_pipeline.md#parked-postgres-staging) |
| BigQuery <-> Cloud SQL federated connection | **Parked** -- replaced by the two Cloud Functions below |
| `pull_kaggle_to_gcs` (Kaggle -> GCS) | **Done** -- deployed, `ACTIVE`, nightly Cloud Scheduler job confirmed `ENABLED` |
| `load_gcs_to_bigquery` (GCS -> BigQuery, MERGE upsert) | **Done** -- deployed, `ACTIVE`, Eventarc GCS trigger confirmed live |
| Raw data materialized into BigQuery | **Done** -- all 9 `raw.*` tables confirmed populated |
| dbt star schema (staging + marts) | **Done** -- all 8 marts confirmed populated; built via a manual `dbt build`, see next row |
| `dbt-build-job` automation (code-triggered, Cloud Build) | **Written, not provisioned** -- `gcloud run jobs list` and `gcloud builds triggers list` both come back empty; the Cloud Run Job and the GitHub-merge trigger were never actually created, and the one-time manual GitHub-App-connection step wasn't completed. `dbt build` is 100% manual today despite this code existing |
| `dbt-build-job` automation (data-triggered, event-driven) | **Written, not provisioned** -- same root cause: depends on `dbt-build-job` existing, which it doesn't yet |
| Anomaly monitoring | Done -- warn-severity dbt tests on `fct_orders` flag columns, see [docs/dbt_testing_and_staging.md](docs/dbt_testing_and_staging.md) |
| SCD Type 2 (seller location) | Done -- `dbt snapshot` on sellers |
| Dashboard/BI tool connection | **Not currently deployed** -- built, deployed once, verified working, then deliberately deleted (`gcloud run services delete`, not just idled) to close the public `--allow-unauthenticated` URL while unused; absent from `gcloud run services list` right now. Redeploy with the step 9 command any time, nothing lost |

**No component in this pipeline redeploys itself on a code push.** Every
deploy for every service (both Cloud Functions, the dashboard) is a manual
`gcloud` command run from "How to run" below. The one CI/CD mechanism
anyone designed here -- the dbt Cloud Build trigger -- exists only as code
and documentation, not as a provisioned resource yet (see the table above).

## Project structure

```
.
├── data/                    Raw Olist CSVs + integrity-check output
├── cloud_functions/          Active ingestion pipeline (Kaggle -> GCS -> BigQuery)
│   ├── pull_kaggle_to_gcs/     Cloud Scheduler-triggered pull, skips unchanged data
│   └── load_gcs_to_bigquery/   GCS-triggered load + MERGE upsert into `raw`
├── src/                     Parked Postgres pipeline scripts (see docs/automated_pipeline.md)
│   ├── data_integrity_check.py
│   ├── staging_schema.sql
│   ├── apply_schema.py
│   └── load_to_cloudsql.py
├── dbt_olist/                dbt project (staging models, star schema marts, snapshot)
│   ├── models/staging/
│   ├── models/marts/
│   ├── snapshots/
│   ├── macros/
│   ├── Dockerfile               dbt-build-job image (Cloud Run Job)
│   ├── .dockerignore
│   └── profiles.yml.ci          Baked-in, secret-free profile (method: oauth)
├── cloudbuild.yaml            Cloud Build config for dbt-build-job (repo root)
├── dashboard/                 Streamlit dashboard (Cloud Run service), multi-page
│   ├── app.py                   Entry point: page config, shared sidebar filters, navigation
│   ├── common.py                 BigQuery client, cached queries, filter helpers (shared by all pages)
│   ├── pages/                    One file per business-case question (see docs/dashboard.md)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .streamlit/config.toml
├── docs/                     Design-rationale docs (see links at the top of this file)
│   ├── automated_pipeline.md
│   ├── dbt_testing_and_staging.md
│   └── dashboard.md
├── notebooks/                Exploratory notebook(s)
├── .env.example               Template for the parked Postgres path's connection details
└── .gitignore
```

## How to run

Values below are this project's actual GCP project (`project-858e450f-408c-4bd2-941`,
project number `588691405952`), region (`asia-southeast1` -- matches the
existing `raw` BigQuery dataset's location), and bucket name
(`project-858e450f-408c-4bd2-941-olist-raw`). Commands are PowerShell. This
sequence already follows the dependency-safe order (why it's ordered this
way is in [docs/automated_pipeline.md](docs/automated_pipeline.md#correct-order-for-a-from-scratch-setup)).

### Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth application-default login`)
- A Kaggle account with an API token: kaggle.com -> Account -> Settings ->
  API -> **Create New Token** -> downloads `kaggle.json` (`{"username": ..., "key": ...}`)
- `dbt-core` + `dbt-bigquery` installed

### 1. Enable required APIs (one-time)

```powershell
gcloud services enable cloudfunctions.googleapis.com cloudscheduler.googleapis.com cloudbuild.googleapis.com eventarc.googleapis.com artifactregistry.googleapis.com run.googleapis.com secretmanager.googleapis.com pubsub.googleapis.com --project=project-858e450f-408c-4bd2-941
```

### 2. Store Kaggle credentials in Secret Manager

Open the downloaded `kaggle.json` and copy the `username`/`key` values in below
(`-NoNewline` matters -- a trailing newline in the key breaks Kaggle auth):

```powershell
Set-Content -Path "$env:TEMP\kaggle-username.txt" -Value "<your-kaggle-username>" -NoNewline
gcloud secrets create kaggle-username --data-file="$env:TEMP\kaggle-username.txt" --project=project-858e450f-408c-4bd2-941

Set-Content -Path "$env:TEMP\kaggle-key.txt" -Value "<your-kaggle-api-key>" -NoNewline
gcloud secrets create kaggle-key --data-file="$env:TEMP\kaggle-key.txt" --project=project-858e450f-408c-4bd2-941

Remove-Item "$env:TEMP\kaggle-username.txt", "$env:TEMP\kaggle-key.txt"
```

### 3. Grant IAM roles

See [docs/automated_pipeline.md's IAM reference](docs/automated_pipeline.md#iam-reference-every-service-account-and-why)
for what each grant below is for and how it was discovered.

Force-provision the two Google-managed service agents first -- granting
their roles before they exist fails outright:

```powershell
gcloud storage service-agent --project=project-858e450f-408c-4bd2-941
gcloud beta services identity create --service=eventarc.googleapis.com --project=project-858e450f-408c-4bd2-941
```

Then grant the default compute service account
(`588691405952-compute@developer.gserviceaccount.com`) everything it needs
*except* the `run.invoker`/`run.developer` bindings on resources that don't
exist yet:

```powershell
gcloud secrets add-iam-policy-binding kaggle-username --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --project=project-858e450f-408c-4bd2-941
gcloud secrets add-iam-policy-binding kaggle-key --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/secretmanager.secretAccessor" --project=project-858e450f-408c-4bd2-941
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/cloudbuild.builds.builder"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/eventarc.eventReceiver"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:service-588691405952@gs-project-accounts.iam.gserviceaccount.com" --role="roles/pubsub.publisher"
```

### 4. Create the bucket and staging dataset (one-time)

`raw` already exists (from the parked Postgres path) -- only `raw_stage` is new:

```powershell
gcloud storage buckets create gs://project-858e450f-408c-4bd2-941-olist-raw --project=project-858e450f-408c-4bd2-941 --location=asia-southeast1 --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://project-858e450f-408c-4bd2-941-olist-raw --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/storage.objectAdmin"
bq mk --dataset --location=asia-southeast1 project-858e450f-408c-4bd2-941:raw_stage
```

### 5. Deploy `pull-kaggle-to-gcs` + its schedule

Gen2 function *resource names* follow Cloud Run naming (hyphens, no
underscores) even though the Python entry-point function is still
`pull_kaggle_to_gcs`:

```powershell
gcloud functions deploy pull-kaggle-to-gcs --gen2 --runtime=python312 --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --source=cloud_functions/pull_kaggle_to_gcs --entry-point=pull_kaggle_to_gcs --trigger-http --no-allow-unauthenticated --memory=512Mi --timeout=300s --set-env-vars=BUCKET_NAME=project-858e450f-408c-4bd2-941-olist-raw --set-secrets='KAGGLE_USERNAME=kaggle-username:latest,KAGGLE_KEY=kaggle-key:latest'

gcloud iam service-accounts create scheduler-invoker --project=project-858e450f-408c-4bd2-941 --display-name="Cloud Scheduler invoker for pull-kaggle-to-gcs"
gcloud functions add-invoker-policy-binding pull-kaggle-to-gcs --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --member="serviceAccount:scheduler-invoker@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com"

$FUNCTION_URL = gcloud functions describe pull-kaggle-to-gcs --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --format="value(serviceConfig.uri)"
gcloud scheduler jobs create http pull-kaggle-nightly --project=project-858e450f-408c-4bd2-941 --location=asia-southeast1 --schedule="0 3 * * *" --uri=$FUNCTION_URL --http-method=POST --oidc-service-account-email="scheduler-invoker@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com"
```

### 6. Deploy `load-gcs-to-bigquery` (GCS-triggered)

```powershell
gcloud functions deploy load-gcs-to-bigquery --gen2 --runtime=python312 --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --source=cloud_functions/load_gcs_to_bigquery --entry-point=load_gcs_to_bigquery --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" --trigger-event-filters="bucket=project-858e450f-408c-4bd2-941-olist-raw" --trigger-location=asia-southeast1 --set-env-vars='GCP_PROJECT_ID=project-858e450f-408c-4bd2-941,RAW_DATASET=raw,STAGE_DATASET=raw_stage'
```

Now that the service exists, grant the last deferred binding from step 3 --
the Eventarc trigger's identity (the default compute SA) needs this to
actually invoke the function, not just receive the event:

```powershell
gcloud functions add-invoker-policy-binding load-gcs-to-bigquery --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com"
```

### 7. Verify

```powershell
gcloud functions call pull-kaggle-to-gcs --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --gen2
gcloud functions logs read pull-kaggle-to-gcs --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --gen2 --limit=50
gcloud functions logs read load-gcs-to-bigquery --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --gen2 --limit=50
gcloud storage ls gs://project-858e450f-408c-4bd2-941-olist-raw/raw/
bq query --use_legacy_sql=false --project_id=project-858e450f-408c-4bd2-941 "SELECT COUNT(*) FROM raw.orders"
```

### 8. Run the dbt transformation

```
cd dbt_olist
dbt deps
dbt build
```

This runs staging views, the star schema marts, the seller snapshot, and all
54 tests together (see [docs/dbt_testing_and_staging.md](docs/dbt_testing_and_staging.md)
for what each one checks). Produces `staging.*` (typed/cleaned views),
`star_schema_olist.*` (the star schema), and `snapshots.sellers_snapshot`.

### 9. Deploy the dashboard

`dashboard/` is a native Streamlit multi-page app -- see
[docs/dashboard.md](docs/dashboard.md) for its structure, layout
provenance, and caching behavior.

```powershell
gcloud run deploy olist-dashboard --source=dashboard --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --platform=managed --allow-unauthenticated
```

No new IAM grant needed -- it runs as the same default compute service
account already holding `bigquery.dataEditor` + `bigquery.jobUser` from
step 3. `--allow-unauthenticated` means anyone with the URL can query
BigQuery through this dashboard at your cost, with no auth check -- see
[docs/dashboard.md](docs/dashboard.md) for the trade-off and the
authenticated-only alternative.

#### Spin down / restore the dashboard

Cloud Run already scales to zero, so there's no idle compute cost to save
by stopping it -- the actual thing worth turning off is the public URL
itself. Deleting the service (not just leaving it idle) closes that off
completely:

```powershell
gcloud run services delete olist-dashboard --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --quiet
```

Nothing is lost -- the service is built entirely from `dashboard/` in this
repo. Restore it any time with the exact same command from step 9. The
built container image stays in Artifact Registry after deletion (a small,
ongoing storage cost) -- harmless to leave, or list/delete it with
`gcloud artifacts docker images list` / `delete` if you'd rather not.

### 10. Automate dbt build on code changes (Cloud Build -> Cloud Run Job)

See [docs/automated_pipeline.md](docs/automated_pipeline.md#why-the-dbt-trigger-uses-completion-markers-and-a-lock-not-a-direct-call)
for scope and reasoning. Create the dedicated trigger service account first
(see [the IAM reference](docs/automated_pipeline.md#6-dbt-build-trigger-dedicated-service-account-you-create)
for why a dedicated SA, not Cloud Build's default):

```powershell
gcloud iam service-accounts create dbt-build-trigger --project=project-858e450f-408c-4bd2-941 --display-name="Cloud Build trigger for dbt-build-job"

gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:dbt-build-trigger@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:dbt-build-trigger@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding project-858e450f-408c-4bd2-941 --member="serviceAccount:dbt-build-trigger@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com" --role="roles/run.developer"
gcloud iam service-accounts add-iam-policy-binding 588691405952-compute@developer.gserviceaccount.com --member="serviceAccount:dbt-build-trigger@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com" --role="roles/iam.serviceAccountUser" --project=project-858e450f-408c-4bd2-941
```

Bootstrap the image once, manually, so there's something for `gcloud run
jobs create` to point at (the trigger only ever *updates* an existing job):

```powershell
gcloud builds submit --tag=gcr.io/project-858e450f-408c-4bd2-941/dbt-runner:latest dbt_olist --project=project-858e450f-408c-4bd2-941

gcloud run jobs create dbt-build-job --image=gcr.io/project-858e450f-408c-4bd2-941/dbt-runner:latest --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --memory=1Gi --cpu=1 --task-timeout=1800s --max-retries=1
```

**Manual, one-time step that can't be scripted:** connect this GitHub repo
to Cloud Build. It requires installing/authorizing the Cloud Build GitHub
App against your GitHub account in a browser -- there's no CLI-only path
around that OAuth consent screen. In the GCP Console: Cloud Build ->
Triggers -> Connect Repository -> GitHub -> authorize -> select
`NTungka/Module-2-Project`.

Once connected, create the trigger, path-filtered to only fire on changes
that could affect the dbt build (`--included-files="dbt_olist/**"`), and
explicitly assigned to `dbt-build-trigger` (note: `--service-account`
takes the full resource path, not just the bare email):

```powershell
gcloud builds triggers create github --name=dbt-build-on-merge --repo-name=Module-2-Project --repo-owner=NTungka --branch-pattern="^main$" --included-files="dbt_olist/**" --build-config=cloudbuild.yaml --service-account="projects/project-858e450f-408c-4bd2-941/serviceAccounts/dbt-build-trigger@project-858e450f-408c-4bd2-941.iam.gserviceaccount.com" --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941
```

### 11. Automate dbt build on data changes (event-driven)

See [docs/automated_pipeline.md](docs/automated_pipeline.md#why-the-dbt-trigger-uses-completion-markers-and-a-lock-not-a-direct-call)
for why this uses completion markers + an atomic lock instead of firing on
every file merge. Grant the last deferred binding from the IAM reference --
this must come *after* `dbt-build-job` exists (step 10):

```powershell
gcloud run jobs add-iam-policy-binding dbt-build-job --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --member="serviceAccount:588691405952-compute@developer.gserviceaccount.com" --role="roles/run.developer"
```

Then redeploy `load-gcs-to-bigquery` so the marker-tracking and trigger
code in `main.py` actually ships (same command as step 6 -- deploys are
idempotent):

```powershell
gcloud functions deploy load-gcs-to-bigquery --gen2 --runtime=python312 --region=asia-southeast1 --project=project-858e450f-408c-4bd2-941 --source=cloud_functions/load_gcs_to_bigquery --entry-point=load_gcs_to_bigquery --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" --trigger-event-filters="bucket=project-858e450f-408c-4bd2-941-olist-raw" --trigger-location=asia-southeast1 --set-env-vars='GCP_PROJECT_ID=project-858e450f-408c-4bd2-941,RAW_DATASET=raw,STAGE_DATASET=raw_stage'
```

From the next full pull onward, the chain runs itself end to end: Kaggle ->
GCS -> `raw.*` -> (once all 9 land) `dbt-build-job` -> `staging.*` +
`star_schema_olist.*`. Verify with `gcloud run jobs executions list
--job=dbt-build-job --region=asia-southeast1
--project=project-858e450f-408c-4bd2-941` after a full pull -- as the
Status table above notes, this hasn't been exercised against a real batch
yet, since `dbt-build-job` itself isn't provisioned.

## Known open items

- Neither dbt-build automation path (code-triggered or data-triggered) is
  actually provisioned yet -- see the Status table above for the precise,
  live-verified gap. `dbt build` is 100% manual today.
- Streamlit dashboard (`dashboard/`) is not currently deployed -- verified,
  built, then deliberately deleted; see Status above and
  [docs/dashboard.md](docs/dashboard.md).
- `dim_customers` / `dim_products` SCD Type 2 decisions remain open pending
  clarification of the live source system's design -- see
  [docs/dbt_testing_and_staging.md](docs/dbt_testing_and_staging.md).
- No Cloud Monitoring alert or notification is wired to a failed
  `dbt-build-job` execution -- a failed automated build (once the
  automation above is actually provisioned) is discoverable in logs, not
  something that proactively pages anyone.

## Current Pipeline decisions

![Current Pipeline decisions](./Software%20Architecture%20DB%20Project%202.jpeg)

## Repo Citations
This project utilizes contributions from different contributors whom took a seperate approach to the pipeline setup. They are cited here

1. CI/CD & Automation + RestAPI Kaggle Approach (Mythili https://github.com/MCgit3/mod2_dbt_project)
2. Dagster Orchestration + BQ Architecture (Priya https://github.com/Priya2026-debug/Module2_Bigdata_Proj)
3. RestAPI Kaggle Approach & Streamlit Dashboard (Rohit https://github.com/reyanshjaiswal/rohit-module2-project
4. Business Ideation & Alternate medallion architecture (Alok https://github.com/recianchap/Group_4_Module_2_Project)
5. Business Ideation, Presentation & EDA/Analytics (Grace https://github.com/chungchung-coding/olist-data-platform) 
