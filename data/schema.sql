PRAGMA foreign_keys = ON;

CREATE TABLE programs (
    program_id TEXT PRIMARY KEY,
    university TEXT NOT NULL,
    program_name TEXT NOT NULL,
    degree TEXT NOT NULL,
    campus TEXT NOT NULL,
    discipline TEXT NOT NULL,
    record_json TEXT NOT NULL,
    catalog_version TEXT NOT NULL
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES programs(program_id),
    url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    intake_key TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    snapshot_path TEXT NOT NULL,
    facts_json TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE INDEX sources_program_idx ON sources(program_id);
CREATE INDEX sources_intake_idx ON sources(intake_key);
CREATE INDEX programs_discipline_idx ON programs(discipline);

PRAGMA user_version = 1;

