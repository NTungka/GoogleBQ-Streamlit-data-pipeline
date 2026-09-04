-- ============================================================================
-- Olist raw data staging schema (PostgreSQL)
-- Purpose: CP-consistent landing layer for raw CSV extracts before
-- transformation/load into BigQuery data warehouse.
--
-- Design principles:
--  - PKs enforced only where source data was verified duplicate-free.
--  - FKs enforced only where orphan rate was verified at 0%.
--  - CHECK constraints enforced only where zero violations were observed
--    in the source data (see data_integrity_check.py output).
--  - Known real-world anomalies (timestamp sequencing issues, late
--    deliveries, delivered-but-no-date rows) are NOT hard-blocked here --
--    they are real rows and get flagged via staging_dq_flags instead.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS staging;
SET search_path TO staging;

-- ----------------------------------------------------------------------------
-- category_translation (no dependencies)
-- ----------------------------------------------------------------------------
CREATE TABLE staging.category_translation (
    product_category_name          TEXT PRIMARY KEY,
    product_category_name_english  TEXT NOT NULL,
    _source_file                   TEXT NOT NULL DEFAULT 'product_category_name_translation.csv',
    _loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- customers (no dependencies)
-- ----------------------------------------------------------------------------
CREATE TABLE staging.customers (
    customer_id                 TEXT PRIMARY KEY,
    customer_unique_id          TEXT NOT NULL,
    customer_zip_code_prefix    INTEGER NOT NULL,
    customer_city               TEXT NOT NULL,
    customer_state              TEXT NOT NULL,
    _source_file                TEXT NOT NULL DEFAULT 'olist_customers_dataset.csv',
    _loaded_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- sellers (no dependencies)
-- ----------------------------------------------------------------------------
CREATE TABLE staging.sellers (
    seller_id                 TEXT PRIMARY KEY,
    seller_zip_code_prefix    INTEGER NOT NULL,
    seller_city                TEXT NOT NULL,
    seller_state                TEXT NOT NULL,
    _source_file                TEXT NOT NULL DEFAULT 'olist_sellers_dataset.csv',
    _loaded_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- products
-- 610 rows (1.85%) have null category/name_length/description_length/photos_qty
-- 4 rows have product_weight_g = 0 -- left permissive, no CHECK > 0
-- product_category_name -> category_translation NOT enforced as FK:
--   2 known orphan category values in source data
-- ----------------------------------------------------------------------------
CREATE TABLE staging.products (
    product_id                      TEXT PRIMARY KEY,
    product_category_name           TEXT,              -- nullable; soft-linked to category_translation, not FK-enforced
    product_name_lenght             INTEGER,
    product_description_lenght      INTEGER,
    product_photos_qty              INTEGER,
    product_weight_g                NUMERIC,
    product_length_cm               NUMERIC,
    product_height_cm               NUMERIC,
    product_width_cm                NUMERIC,
    _source_file                    TEXT NOT NULL DEFAULT 'olist_products_dataset.csv',
    _loaded_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- orders
-- order_approved_at, order_delivered_carrier_date, order_delivered_customer_date
-- are nullable (160 / 1,783 / 2,965 nulls observed respectively).
-- CHECK constraints only added where 0 violations were observed:
--   order_approved_at >= order_purchase_timestamp            (0 violations)
--   order_delivered_customer_date >= order_purchase_timestamp (0 violations)
-- delivered_carrier_date >= approved_at is NOT enforced: 1,359 real rows
-- violate it (see staging_dq_flags for these).
-- ----------------------------------------------------------------------------
CREATE TABLE staging.orders (
    order_id                         TEXT PRIMARY KEY,
    customer_id                      TEXT NOT NULL REFERENCES staging.customers(customer_id),
    order_status                     TEXT NOT NULL,
    order_purchase_timestamp         TIMESTAMPTZ NOT NULL,
    order_approved_at                TIMESTAMPTZ,
    order_delivered_carrier_date     TIMESTAMPTZ,
    order_delivered_customer_date    TIMESTAMPTZ,
    order_estimated_delivery_date    TIMESTAMPTZ NOT NULL,
    _source_file                     TEXT NOT NULL DEFAULT 'olist_orders_dataset.csv',
    _loaded_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_approved_after_purchase
        CHECK (order_approved_at IS NULL OR order_approved_at >= order_purchase_timestamp),
    CONSTRAINT chk_delivered_after_purchase
        CHECK (order_delivered_customer_date IS NULL OR order_delivered_customer_date >= order_purchase_timestamp)
);

CREATE INDEX idx_orders_customer_id ON staging.orders(customer_id);
CREATE INDEX idx_orders_status ON staging.orders(order_status);

-- ----------------------------------------------------------------------------
-- order_items
-- Composite PK (order_id, order_item_id) verified duplicate-free.
-- price > 0 and freight_value >= 0 verified: 0 violations.
-- ----------------------------------------------------------------------------
CREATE TABLE staging.order_items (
    order_id                TEXT NOT NULL REFERENCES staging.orders(order_id),
    order_item_id            INTEGER NOT NULL,
    product_id               TEXT NOT NULL REFERENCES staging.products(product_id),
    seller_id                TEXT NOT NULL REFERENCES staging.sellers(seller_id),
    shipping_limit_date      TIMESTAMPTZ NOT NULL,
    price                     NUMERIC NOT NULL CHECK (price > 0),
    freight_value             NUMERIC NOT NULL CHECK (freight_value >= 0),
    _source_file              TEXT NOT NULL DEFAULT 'olist_order_items_dataset.csv',
    _loaded_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX idx_order_items_product_id ON staging.order_items(product_id);
CREATE INDEX idx_order_items_seller_id ON staging.order_items(seller_id);

-- ----------------------------------------------------------------------------
-- order_payments
-- No natural single-column PK -- surrogate key used.
-- payment_value >= 0 (9 rows are exactly 0, none negative) -- CHECK >= 0, not > 0.
-- payment_installments >= 0 verified: 0 negative values.
-- ----------------------------------------------------------------------------
CREATE TABLE staging.order_payments (
    payment_pk               BIGSERIAL PRIMARY KEY,
    order_id                  TEXT NOT NULL REFERENCES staging.orders(order_id),
    payment_sequential         INTEGER NOT NULL,
    payment_type                TEXT NOT NULL,   -- includes unexplained 'not_defined' value -- kept as-is, flag downstream
    payment_installments        INTEGER NOT NULL CHECK (payment_installments >= 0),
    payment_value                NUMERIC NOT NULL CHECK (payment_value >= 0),
    _source_file                 TEXT NOT NULL DEFAULT 'olist_order_payments_dataset.csv',
    _loaded_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, payment_sequential)
);

CREATE INDEX idx_order_payments_order_id ON staging.order_payments(order_id);

-- ----------------------------------------------------------------------------
-- order_reviews
-- (review_id, order_id) verified as a clean composite key (0 duplicate pairs).
-- review_id alone repeats (814 dup review_ids) and order_id alone repeats
-- (551 orders with multiple reviews) -- both real, neither is independently unique.
-- review_score BETWEEN 1 AND 5 verified: 0 violations.
-- ----------------------------------------------------------------------------
CREATE TABLE staging.order_reviews (
    review_id                  TEXT NOT NULL,
    order_id                    TEXT NOT NULL REFERENCES staging.orders(order_id),
    review_score                 INTEGER NOT NULL CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title          TEXT,             -- 88% null, expected (rating-only UX)
    review_comment_message        TEXT,             -- 59% null, expected
    review_creation_date           TIMESTAMPTZ NOT NULL,
    review_answer_timestamp         TIMESTAMPTZ NOT NULL,
    _source_file                     TEXT NOT NULL DEFAULT 'olist_order_reviews_dataset.csv',
    _loaded_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (review_id, order_id)
);

CREATE INDEX idx_order_reviews_order_id ON staging.order_reviews(order_id);

-- ----------------------------------------------------------------------------
-- geolocation
-- No PK: source is 26% full-row duplicates (261,836 / 1,000,163 rows) by
-- design (repeated zip/lat/lng samples). Load as-is into a raw table, then
-- materialize a deduplicated staging_geolocation_dedup view/table for use
-- in joins -- do not enforce uniqueness here, it would reject valid raw rows.
-- ----------------------------------------------------------------------------
CREATE TABLE staging.geolocation_raw (
    geolocation_zip_code_prefix    INTEGER NOT NULL,
    geolocation_lat                 NUMERIC NOT NULL,
    geolocation_lng                  NUMERIC NOT NULL,
    geolocation_city                  TEXT NOT NULL,
    geolocation_state                  TEXT NOT NULL,
    _source_file                        TEXT NOT NULL DEFAULT 'olist_geolocation_dataset.csv',
    _loaded_at                           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_geolocation_zip ON staging.geolocation_raw(geolocation_zip_code_prefix);

-- Deduplicated + Brazil-bounding-box-filtered view for downstream use.
-- Bounding box: lat -33.75 to 5.27, lng -73.99 to -34.79 (excludes 42 known
-- out-of-country points).
CREATE VIEW staging.geolocation_clean AS
SELECT DISTINCT
    geolocation_zip_code_prefix,
    geolocation_lat,
    geolocation_lng,
    geolocation_city,
    geolocation_state
FROM staging.geolocation_raw
WHERE geolocation_lat BETWEEN -33.75 AND 5.27
  AND geolocation_lng BETWEEN -73.99 AND -34.79;

-- ----------------------------------------------------------------------------
-- Data-quality flag log
-- Captures known real anomalies that are intentionally NOT constraint-blocked,
-- so the warehouse/dashboard layer can decide how to treat them (exclude,
-- footnote, or investigate) instead of silently losing rows at load time.
-- Populate via post-load INSERT ... SELECT queries, one pass per rule.
-- ----------------------------------------------------------------------------
CREATE TABLE staging.staging_dq_flags (
    flag_id        BIGSERIAL PRIMARY KEY,
    table_name     TEXT NOT NULL,
    record_id      TEXT NOT NULL,       -- e.g. order_id
    rule_name      TEXT NOT NULL,       -- e.g. 'carrier_date_before_approved_at'
    detail         TEXT,
    flagged_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Example population queries (run after load):
--
-- INSERT INTO staging.staging_dq_flags (table_name, record_id, rule_name, detail)
-- SELECT 'orders', order_id, 'carrier_date_before_approved_at',
--        format('carrier=%s approved=%s', order_delivered_carrier_date, order_approved_at)
-- FROM staging.orders
-- WHERE order_delivered_carrier_date IS NOT NULL
--   AND order_approved_at IS NOT NULL
--   AND order_delivered_carrier_date < order_approved_at;
--
-- INSERT INTO staging.staging_dq_flags (table_name, record_id, rule_name, detail)
-- SELECT 'orders', order_id, 'delivered_but_missing_date', order_status
-- FROM staging.orders
-- WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL;
--
-- INSERT INTO staging.staging_dq_flags (table_name, record_id, rule_name, detail)
-- SELECT 'orders', order_id, 'late_delivery',
--        format('delivered=%s estimated=%s', order_delivered_customer_date, order_estimated_delivery_date)
-- FROM staging.orders
-- WHERE order_delivered_customer_date IS NOT NULL
--   AND order_delivered_customer_date > order_estimated_delivery_date;
--
-- INSERT INTO staging.staging_dq_flags (table_name, record_id, rule_name, detail)
-- SELECT 'orders', order_id, 'no_line_items', order_status
-- FROM staging.orders o
-- WHERE NOT EXISTS (SELECT 1 FROM staging.order_items oi WHERE oi.order_id = o.order_id);
--
-- INSERT INTO staging.staging_dq_flags (table_name, record_id, rule_name, detail)
-- SELECT 'products', product_id, 'orphan_category', product_category_name
-- FROM staging.products p
-- WHERE product_category_name IS NOT NULL
--   AND NOT EXISTS (
--       SELECT 1 FROM staging.category_translation ct
--       WHERE ct.product_category_name = p.product_category_name
--   );
