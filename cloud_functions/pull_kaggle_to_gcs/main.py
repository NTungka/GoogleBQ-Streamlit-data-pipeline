"""
Kaggle -> GCS pull, triggered on a Cloud Scheduler cadence (HTTP function).

Only re-pulls when Kaggle's copy of the dataset has actually changed:
checks the dataset's last-updated metadata against a marker file in GCS,
and skips the download+upload entirely if it hasn't moved.

Modeled directly on the working reference implementation at
mod2_dbt_project/cloud_funtions/mod2_dataset_robot/main.py -- same
dataset_list(search=...) + ref-match + dataset.lastUpdated approach, same
kaggle.api.dataset_download_files(..., path="/tmp/...", unzip=True)
download (rather than kagglehub, whose default cache location isn't
guaranteed writable in a Cloud Functions container -- only /tmp is).
Two earlier attempts here crashed in production: kaggle.api.dataset_view()
doesn't exist on the installed KaggleApi class, and dataset_list(search=,
user=) returned zero results with the added `user` filter -- the
reference's plain `search=` (no `user`) is what actually works.

This function only uploads to GCS; the BigQuery load (with a MERGE
upsert, not the reference's WRITE_TRUNCATE) is load_gcs_to_bigquery's job,
triggered separately off the GCS object-finalize event.
"""

import logging
import os
import shutil
from pathlib import Path

import functions_framework
import kaggle
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

KAGGLE_DATASET = "olistbr/brazilian-ecommerce"
KAGGLE_SEARCH_TERM = "brazilian-ecommerce"
BUCKET_NAME = os.environ["BUCKET_NAME"]
RAW_PREFIX = os.environ.get("RAW_PREFIX", "raw")
MARKER_BLOB = "_meta/last_updated.txt"
DOWNLOAD_PATH = "/tmp/kaggle_data"

# Must match the filenames Kaggle ships in olistbr/brazilian-ecommerce, and
# the keys in cloud_functions/load_gcs_to_bigquery/table_config.py.
EXPECTED_FILES = [
    "olist_customers_dataset.csv",
    "olist_sellers_dataset.csv",
    "olist_products_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "product_category_name_translation.csv",
]


def _kaggle_last_updated() -> str:
    kaggle.api.authenticate()
    datasets = kaggle.api.dataset_list(search=KAGGLE_SEARCH_TERM)
    refs_seen = []
    for dataset in datasets:
        ref = str(getattr(dataset, "ref", ""))
        refs_seen.append(ref)
        if ref == KAGGLE_DATASET:
            # The reference implementation this is modeled on uses
            # `lastUpdated` (camelCase); the kaggle package version that
            # actually installs here renamed it to `last_updated`
            # (snake_case) -- try both so a future package upgrade in
            # either direction doesn't silently break this again.
            for attr in ("last_updated", "lastUpdated"):
                value = getattr(dataset, attr, None)
                if value is not None:
                    return str(value)
            raise AttributeError(
                f"Dataset object for {KAGGLE_DATASET} has neither 'last_updated' "
                f"nor 'lastUpdated'. Actual attributes: {sorted(vars(dataset).keys())}"
            )
    raise LookupError(
        f"'{KAGGLE_DATASET}' not found via dataset_list(search='{KAGGLE_SEARCH_TERM}') "
        f"-- refs seen: {refs_seen}"
    )


def _read_marker(bucket: storage.Bucket) -> str | None:
    blob = bucket.blob(MARKER_BLOB)
    if not blob.exists():
        return None
    return blob.download_as_text().strip()


def _write_marker(bucket: storage.Bucket, value: str) -> None:
    bucket.blob(MARKER_BLOB).upload_from_string(value)


@functions_framework.http
def pull_kaggle_to_gcs(request):
    bucket = storage.Client().bucket(BUCKET_NAME)

    latest = _kaggle_last_updated()
    current = _read_marker(bucket)

    if latest == current:
        logger.info("Kaggle dataset unchanged (last_updated=%s) -- skipping pull.", latest)
        return {"status": "skipped", "last_updated": latest}, 200

    logger.info("Kaggle dataset changed (%s -> %s) -- pulling.", current, latest)

    if os.path.exists(DOWNLOAD_PATH):
        shutil.rmtree(DOWNLOAD_PATH)
    os.makedirs(DOWNLOAD_PATH, exist_ok=True)

    kaggle.api.dataset_download_files(KAGGLE_DATASET, path=DOWNLOAD_PATH, unzip=True)

    uploaded = []
    for filename in EXPECTED_FILES:
        local_path = Path(DOWNLOAD_PATH) / filename
        if not local_path.exists():
            logger.warning("Expected file missing from Kaggle download: %s", filename)
            continue
        blob = bucket.blob(f"{RAW_PREFIX}/{filename}")
        blob.upload_from_filename(str(local_path))
        uploaded.append(filename)
        logger.info("Uploaded %s -> gs://%s/%s/%s", filename, BUCKET_NAME, RAW_PREFIX, filename)

    # Written last, only after every file uploaded successfully -- a
    # failed run leaves the marker stale so the next scheduled run retries
    # the full pull instead of silently skipping it.
    _write_marker(bucket, latest)
    return {"status": "pulled", "last_updated": latest, "files": uploaded}, 200
