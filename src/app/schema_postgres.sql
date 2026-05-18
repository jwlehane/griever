-- Canonical Postgres schema for griever.
--
-- Applied once at startup when DATABASE_URL is set (see init_schema in
-- src/app/db.py). For local dev (SQLite), the equivalent schema is created
-- on-demand via the legacy migration block in TaxGrieveCore.ensure_property
-- — see schema_sqlite.sql for the parallel definition.
--
-- Keep these two files in lockstep. Any column added here must be added in
-- the SQLite migration block too, and vice versa.

CREATE TABLE IF NOT EXISTS properties (
    id                  SERIAL PRIMARY KEY,
    address             TEXT,
    sbl                 TEXT,
    sqft                REAL,
    acreage             REAL,
    bedrooms            REAL,
    bathrooms           REAL,
    year_built          INTEGER,
    assessment_2025     REAL,
    assessment_2026     REAL,
    latitude            REAL,
    longitude           REAL,
    zip                 TEXT,
    property_class      TEXT,
    condition_code      TEXT,
    grade               TEXT,
    basement_type       TEXT,
    heat_type           TEXT,
    style               TEXT,
    is_flood_zone       INTEGER DEFAULT 0,
    nuisance_rail       INTEGER DEFAULT 0,
    nuisance_highway    INTEGER DEFAULT 0,
    amenity_park        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS properties_sbl_idx ON properties (sbl);
CREATE INDEX IF NOT EXISTS properties_address_idx ON properties (address);

CREATE TABLE IF NOT EXISTS sales_comps (
    id                  SERIAL PRIMARY KEY,
    target_property_id  INTEGER REFERENCES properties(id) ON DELETE CASCADE,
    address             TEXT,
    sbl                 TEXT,
    sale_price          REAL,
    sale_date           TEXT,
    sqft                REAL,
    acreage             REAL,
    bedrooms            REAL,
    bathrooms           REAL,
    year_built          INTEGER,
    zpid                TEXT,
    status              TEXT DEFAULT 'VERIFIED',
    similarity_score    REAL DEFAULT 0,
    is_outlier          INTEGER DEFAULT 0,
    assessment_2026     REAL,
    assessment_2025     REAL,
    distance_miles      REAL,
    rejection_reason    TEXT,
    is_selected         INTEGER DEFAULT 0,
    grade               TEXT,
    condition_code      TEXT,
    bldg_grade          TEXT,
    basement_type       TEXT,
    heat_type           TEXT,
    style               TEXT,
    property_class      TEXT,
    is_flood_zone       INTEGER DEFAULT 0,
    nuisance_rail       INTEGER DEFAULT 0,
    nuisance_highway    INTEGER DEFAULT 0,
    amenity_park        INTEGER DEFAULT 0
);

-- The runtime upsert path joins on (target_property_id, zpid). The unique
-- index makes ON CONFLICT possible (Postgres analogue of INSERT OR REPLACE).
CREATE UNIQUE INDEX IF NOT EXISTS sales_comps_target_zpid_uq
    ON sales_comps (target_property_id, zpid)
    WHERE zpid IS NOT NULL;

CREATE INDEX IF NOT EXISTS sales_comps_target_idx ON sales_comps (target_property_id);
CREATE INDEX IF NOT EXISTS sales_comps_status_idx ON sales_comps (status);
