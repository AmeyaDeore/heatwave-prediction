-- 0003: region hierarchy fields (Revision 2, Part 02 R2.2), mirroring config/regions.yaml.
-- Additive: existing rows become cities with no division until the startup upsert fills them.
-- Same portability rules as 0001 (plain ALTER TABLE ADD COLUMN, no SQLite-only syntax).

ALTER TABLE regions ADD COLUMN division TEXT;
ALTER TABLE regions ADD COLUMN kind TEXT NOT NULL DEFAULT 'city' CHECK (kind IN ('city', 'area'));
ALTER TABLE regions ADD COLUMN parent_region_id TEXT REFERENCES regions (region_id);
