CREATE TABLE customers (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    phone TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
ALTER TABLE appointments ADD COLUMN customer_id TEXT REFERENCES customers(id);
INSERT INTO customers (id,name,email,phone,created_at,updated_at)
SELECT lower(hex(randomblob(16))),customer_name,normalized_email,customer_phone,first_seen,created_at
FROM (
    SELECT *,lower(trim(customer_email)) AS normalized_email,
           min(created_at) OVER (PARTITION BY lower(trim(customer_email))) AS first_seen,
           row_number() OVER (PARTITION BY lower(trim(customer_email)) ORDER BY created_at DESC,id DESC) AS position
    FROM appointments
) WHERE position=1;
UPDATE appointments SET customer_id=(SELECT id FROM customers WHERE customers.email=lower(trim(appointments.customer_email)));
CREATE INDEX appointments_customer_id ON appointments(customer_id);
