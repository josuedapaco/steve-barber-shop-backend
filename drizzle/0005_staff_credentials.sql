CREATE TABLE staff_credentials (
    role TEXT NOT NULL,
    subject TEXT NOT NULL,
    pin_salt TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    session_secret TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (role, subject)
);
