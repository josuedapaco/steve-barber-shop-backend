CREATE TABLE shop_busyness (
    id INTEGER PRIMARY KEY CHECK (id=1),
    percentage INTEGER NOT NULL CHECK (percentage BETWEEN 0 AND 100),
    updated_at TEXT NOT NULL,
    updated_by_role TEXT NOT NULL,
    updated_by_subject TEXT NOT NULL
);
