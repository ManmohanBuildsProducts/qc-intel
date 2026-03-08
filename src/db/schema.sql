-- QC Intel database schema
-- Entity/observation split: stable product identity vs daily observations

-- Stable product identity (upserted per platform, deduplicated)
CREATE TABLE IF NOT EXISTS product_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL CHECK(platform IN ('blinkit','zepto','instamart')),
    platform_product_id TEXT NOT NULL,
    name TEXT NOT NULL,
    brand TEXT,
    category TEXT NOT NULL,
    subcategory TEXT,
    unit TEXT,
    image_url TEXT,
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, platform_product_id)
);

-- Daily observations (one per scrape run per product per pincode)
CREATE TABLE IF NOT EXISTS product_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER NOT NULL REFERENCES product_catalog(id),
    scrape_run_id TEXT NOT NULL,
    pincode TEXT NOT NULL,
    price REAL NOT NULL,
    mrp REAL,
    in_stock INTEGER NOT NULL DEFAULT 1,
    max_cart_qty INTEGER NOT NULL DEFAULT 0,
    inventory_count INTEGER,
    time_of_day TEXT NOT NULL CHECK(time_of_day IN ('morning','night')),
    observed_at TEXT NOT NULL DEFAULT (datetime('now')),
    raw_json TEXT
);

-- Daily sales estimates (computed from observation pairs)
CREATE TABLE IF NOT EXISTS daily_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER NOT NULL REFERENCES product_catalog(id),
    pincode TEXT NOT NULL,
    sale_date TEXT NOT NULL,
    morning_qty INTEGER NOT NULL,
    night_qty INTEGER NOT NULL,
    estimated_sales INTEGER NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('high','medium','low','no_data')),
    restock_flag INTEGER NOT NULL DEFAULT 0,
    UNIQUE(catalog_id, pincode, sale_date)
);

-- Normalized canonical products (cross-platform)
CREATE TABLE IF NOT EXISTS canonical_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    brand TEXT,
    category TEXT NOT NULL,
    unit_normalized TEXT,
    embedding BLOB,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Mapping: catalog product -> canonical product
CREATE TABLE IF NOT EXISTS product_mappings (
    catalog_id INTEGER NOT NULL REFERENCES product_catalog(id),
    canonical_id INTEGER NOT NULL REFERENCES canonical_products(id),
    similarity_score REAL NOT NULL,
    mapped_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(catalog_id)
);

-- Scrape run metadata (provenance)
CREATE TABLE IF NOT EXISTS scrape_runs (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    pincode TEXT NOT NULL,
    category TEXT NOT NULL,
    time_of_day TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    products_found INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('running','completed','failed'))
);

-- Unique constraint: one observation per product/pincode/date/time_of_day
CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_unique ON product_observations(catalog_id, pincode, date(observed_at), time_of_day);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_catalog_platform ON product_catalog(platform);
CREATE INDEX IF NOT EXISTS idx_catalog_brand ON product_catalog(brand);
CREATE INDEX IF NOT EXISTS idx_catalog_category ON product_catalog(category);
CREATE INDEX IF NOT EXISTS idx_obs_catalog ON product_observations(catalog_id);
CREATE INDEX IF NOT EXISTS idx_obs_pincode ON product_observations(pincode);
CREATE INDEX IF NOT EXISTS idx_obs_date ON product_observations(date(observed_at));
CREATE INDEX IF NOT EXISTS idx_obs_run ON product_observations(scrape_run_id);
CREATE INDEX IF NOT EXISTS idx_sales_catalog ON daily_sales(catalog_id);
CREATE INDEX IF NOT EXISTS idx_sales_date ON daily_sales(sale_date);
CREATE INDEX IF NOT EXISTS idx_canonical_category ON canonical_products(category);
CREATE INDEX IF NOT EXISTS idx_mapping_canonical ON product_mappings(canonical_id);
