# dbt build image for the Cloud Run Job triggered by Cloud Build on merges
# to main (see cloudbuild.yaml at the repo root and README.md's "Automate
# dbt build" section). Modeled on mod2_dbt_project's Dockerfile: install
# dbt-bigquery, bake `dbt deps` into the image at build time, authenticate
# non-interactively via Application Default Credentials -- `method: oauth`
# in profiles.yml resolves to the Cloud Run Job's own runtime service
# account when running on GCP compute, no keyfile needed. This is the same
# pattern mod2_dbt_project's own (committed, secret-free) profiles.yml uses
# for its dbt-job.
FROM python:3.11-slim

RUN pip install --no-cache-dir dbt-bigquery==1.11.1

WORKDIR /app
COPY . /app
COPY profiles.yml.ci /app/profiles.yml

ENV DBT_PROFILES_DIR=/app

RUN dbt deps

CMD ["dbt", "build"]
