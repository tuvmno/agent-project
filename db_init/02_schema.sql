CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS reports (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    stock_name VARCHAR(255),
    stock_code VARCHAR(32),
    broker VARCHAR(255),
    date DATE,
    category VARCHAR(64),
    pdf_url TEXT,
    minio_path TEXT,
    content TEXT,
    summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_processed BOOLEAN DEFAULT FALSE
);

CREATE UNIQUE INDEX IF NOT EXISTS reports_title_date_category_idx
ON reports (title, date, category);

CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    report_id INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(768),
    page_num INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_type VARCHAR(50) DEFAULT 'text',
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS chunks_report_id_idx ON chunks (report_id);
