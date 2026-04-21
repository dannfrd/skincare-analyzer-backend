-- =========================
-- USERS
-- =========================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NULL DEFAULT 'user',
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    provider ENUM('manual','google') NULL DEFAULT 'manual',
    firebase_uid VARCHAR(255) NULL
);

-- =========================
-- PRODUCTS
-- =========================
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150),
    brand VARCHAR(100),
    category VARCHAR(100),
    description TEXT,
    image_url VARCHAR(255),
    barcode VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- INGREDIENTS (MASTER DATA)
-- =========================
CREATE TABLE IF NOT EXISTS ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(150) UNIQUE,
    description TEXT,
    `function` VARCHAR(100), -- ditambahkan kembali
    risk_level VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================
-- SCANS
-- =========================
CREATE TABLE IF NOT EXISTS scans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT,
    image_url VARCHAR(255),
    extracted_text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_scan_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_scan_product
        FOREIGN KEY (product_id) REFERENCES products(id)
        ON DELETE SET NULL
);

-- =========================
-- SCAN INGREDIENTS
-- =========================
CREATE TABLE IF NOT EXISTS scan_ingredients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    scan_id INT NOT NULL,
    ingredient_id INT NOT NULL,

    CONSTRAINT fk_si_scan
        FOREIGN KEY (scan_id) REFERENCES scans(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_si_ingredient
        FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        ON DELETE CASCADE,

    CONSTRAINT unique_scan_ingredient
        UNIQUE (scan_id, ingredient_id) -- 🔥 cegah duplikasi
);

-- =========================
-- ANALYSES
-- =========================
CREATE TABLE IF NOT EXISTS analyses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    scan_id INT NOT NULL,
    summary TEXT,
    recommendation TEXT,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_analysis_scan
        FOREIGN KEY (scan_id) REFERENCES scans(id)
        ON DELETE CASCADE
);

-- =========================
-- ANALYSIS DETAILS
-- =========================
CREATE TABLE IF NOT EXISTS analysis_details (
    id INT AUTO_INCREMENT PRIMARY KEY,
    analysis_id INT NOT NULL,
    ingredient_id INT NOT NULL,
    `function` VARCHAR(100), -- ditambahkan (context-specific)
    benefit TEXT,
    risk TEXT,

    CONSTRAINT fk_ad_analysis
        FOREIGN KEY (analysis_id) REFERENCES analyses(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_ad_ingredient
        FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
        ON DELETE CASCADE
);

-- =========================
-- USER HISTORIES
-- =========================
CREATE TABLE IF NOT EXISTS user_histories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    analysis_id INT NOT NULL,
    viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_uh_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_uh_analysis
        FOREIGN KEY (analysis_id) REFERENCES analyses(id)
        ON DELETE CASCADE
);

-- =========================
-- INDEXING (OPTIMIZED)
-- =========================
CREATE INDEX idx_scans_user_id ON scans(user_id);
CREATE INDEX idx_scans_product_id ON scans(product_id);

CREATE INDEX idx_analyses_scan_id ON analyses(scan_id);

CREATE INDEX idx_analysis_details_analysis_id ON analysis_details(analysis_id);
CREATE INDEX idx_analysis_details_ingredient_id ON analysis_details(ingredient_id);

CREATE INDEX idx_scan_ingredients_scan_id ON scan_ingredients(scan_id);
CREATE INDEX idx_scan_ingredients_ingredient_id ON scan_ingredients(ingredient_id);