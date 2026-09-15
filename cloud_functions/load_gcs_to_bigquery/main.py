"""
GCS -> BigQuery `raw` dataset loader, triggered per-file on Cloud Storage
object-finalize events (Eventarc) under gs://<bucket>/raw/.

Loads the finalized CSV into an ephemeral per-table staging table (safe to
WRITE_TRUNCATE -- it holds nothing but that one file), then MERGEs it into
the persistent `raw.<table>` table: new rows are inserted, rows that
already exist are updated in place, and rows already in `raw` that aren't
in this load are left untouched. Unlike loading straight into `raw` with
WRITE_TRUNCATE, this never wipes the table between runs -- it upserts, the
same "only new data is updated" behavior the old federated Cloud SQL ->
BigQuery pull was meant to give, just implemented as a real MERGE instead
of a full CREATE OR REPLACE.

MERGE requires its target table to already exist -- BigQuery won't create
one on the fly the way a plain load job will. That was never an issue
while `raw.*` already existed (first from the old Postgres federation,
then just persisting across testing), until the whole `raw` dataset got
deleted and every MERGE started failing with `NotFound: Table raw.<table>
was not found`. `create_table(..., exists_ok=True)` below closes that
cold-start gap -- idempotent, safe to run on every invocation, not just
the first one ever.
"""

import logging
import os

import functions_framework
from google.cloud import bigquery

from table_config import TABLE_CONFIG, build_merge_sql

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
RAW_DATASET = os.environ.get("RAW_DATASET", "raw")
STAGE_DATASET = os.environ.get("STAGE_DATASET", "raw_stage")
RAW_PREFIX = os.environ.get("RAW_PREFIX", "raw/")

bq = bigquery.Client(project=PROJECT_ID)


@functions_framework.cloud_event
def load_gcs_to_bigquery(cloud_event):
    data = cloud_event.data
    bucket_name = data["bucket"]
    object_name = data["name"]

    if not object_name.startswith(RAW_PREFIX):
        logger.info("Ignoring %s (outside %s)", object_name, RAW_PREFIX)
        return

    filename = object_name.rsplit("/", 1)[-1]
    config = TABLE_CONFIG.get(filename)
    if config is None:
        logger.info("Ignoring %s (no table config)", filename)
        return

    gcs_uri = f"gs://{bucket_name}/{object_name}"
    stage_table = f"{PROJECT_ID}.{STAGE_DATASET}.{config.table}"

    logger.info("Loading %s -> %s (staging)", gcs_uri, stage_table)
    load_job = bq.load_table_from_uri(
        gcs_uri,
        stage_table,
        job_config=bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV,
            skip_leading_rows=1,
            schema=config.schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            # order_reviews' free-text review_comment_message routinely
            # contains literal newlines inside quoted fields -- without
            # this, BigQuery's CSV parser splits those into bogus extra
            # rows with the wrong column count. Harmless for every other
            # table, so applied to all loads rather than special-cased.
            allow_quoted_newlines=True,
        ),
    )
    load_job.result()
    logger.info("Staged %d rows into %s", load_job.output_rows, stage_table)

    raw_table = f"{PROJECT_ID}.{RAW_DATASET}.{config.table}"
    bq.create_table(bigquery.Table(raw_table, schema=config.schema), exists_ok=True)

    merge_sql = build_merge_sql(PROJECT_ID, RAW_DATASET, STAGE_DATASET, config)
    logger.info("Merging into raw.%s:\n%s", config.table, merge_sql)
    merge_job = bq.query(merge_sql)
    merge_job.result()
    logger.info(
        "Merged into raw.%s -- %d rows affected (inserted + updated)",
        config.table,
        merge_job.num_dml_affected_rows,
    )
