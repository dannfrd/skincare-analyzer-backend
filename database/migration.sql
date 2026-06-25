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
    position_index INT NOT NULL DEFAULT 0,
    ocr_token VARCHAR(255),
    match_status ENUM('matched', 'unknown') NOT NULL DEFAULT 'matched',
    match_confidence DECIMAL(5,4),

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
    overall_score DECIMAL(5,2),
    classification VARCHAR(100),
    warnings_count INT NOT NULL DEFAULT 0,
    unknown_count INT NOT NULL DEFAULT 0,
    ai_model VARCHAR(100),
    ai_output LONGTEXT,
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
        ON DELETE CASCADE,

    CONSTRAINT unique_analysis_ingredient
        UNIQUE (analysis_id, ingredient_id)
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
        ON DELETE CASCADE,

    CONSTRAINT unique_user_analysis
        UNIQUE (user_id, analysis_id)
);

ALTER TABLE users
    ADD COLUMN role VARCHAR(50) NULL DEFAULT 'user';
ALTER TABLE users
    ADD COLUMN provider VARCHAR(50) NULL DEFAULT 'manual';
ALTER TABLE users
    ADD COLUMN firebase_uid VARCHAR(255) NULL;

UPDATE users
SET role = 'user'
WHERE role IS NULL OR TRIM(role) = '';

INSERT INTO users (
    name,
    email,
    password,
    role,
    provider,
    created_at
)
VALUES (
    'Dermify Administrator',
    'dermify@gmail.com',
    '$bcrypt-sha256$v=2,t=2b,r=12$QIomtU1atcsCJLi2stL/Hu$ZrI/Hwk54i7VNgDZxRsIT7Qfoqnz6iu',
    'admin',
    'manual',
    NOW()
)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    password = VALUES(password),
    role = 'admin',
    provider = 'manual';

-- =========================
-- UPGRADE EXISTING DATABASE
-- Statements ini aman dijalankan ulang melalui run_migration.py.
-- =========================
ALTER TABLE scan_ingredients
    ADD COLUMN position_index INT NOT NULL DEFAULT 0;
ALTER TABLE scan_ingredients
    ADD COLUMN ocr_token VARCHAR(255);
ALTER TABLE scan_ingredients
    ADD COLUMN match_status ENUM('matched', 'unknown') NOT NULL DEFAULT 'matched';
ALTER TABLE scan_ingredients
    ADD COLUMN match_confidence DECIMAL(5,4);

ALTER TABLE analyses
    ADD COLUMN overall_score DECIMAL(5,2);
ALTER TABLE analyses
    ADD COLUMN classification VARCHAR(100);
ALTER TABLE analyses
    ADD COLUMN warnings_count INT NOT NULL DEFAULT 0;
ALTER TABLE analyses
    ADD COLUMN unknown_count INT NOT NULL DEFAULT 0;
ALTER TABLE analyses
    ADD COLUMN ai_model VARCHAR(100);
ALTER TABLE analyses
    ADD COLUMN ai_output LONGTEXT;
ALTER TABLE analyses
    ADD COLUMN raw_result LONGTEXT;
ALTER TABLE users
    ADD COLUMN profile_picture VARCHAR(255) NULL AFTER firebase_uid;

DELETE duplicate_detail
FROM analysis_details duplicate_detail
INNER JOIN analysis_details retained_detail
    ON retained_detail.analysis_id = duplicate_detail.analysis_id
   AND retained_detail.ingredient_id = duplicate_detail.ingredient_id
   AND retained_detail.id < duplicate_detail.id;

ALTER TABLE analysis_details
    ADD CONSTRAINT unique_analysis_ingredient
    UNIQUE (analysis_id,
     ingredient_id);

DELETE duplicate_history
FROM user_histories duplicate_history
INNER JOIN user_histories retained_history
    ON retained_history.user_id = duplicate_history.user_id
   AND retained_history.analysis_id = duplicate_history.analysis_id
   AND retained_history.id < duplicate_history.id;

ALTER TABLE user_histories
    ADD CONSTRAINT unique_user_analysis
    UNIQUE (user_id, analysis_id);

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

-- =========================
-- NOTIFICATIONS
-- =========================
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
<<<<<<< HEAD
    body TEXT NULL,
    data TEXT NULL,
    topic VARCHAR(100) NULL,
    tokens TEXT NULL,
    status VARCHAR(50) DEFAULT 'draft',
    scheduled_at TIMESTAMP NULL,
    sent_by INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

=======
    body TEXT,
    data JSON NULL,
    topic VARCHAR(100) NULL,
    tokens LONGTEXT NULL,
    status ENUM('draft','scheduled','sent','failed') NOT NULL DEFAULT 'draft',
    scheduled_at TIMESTAMP NULL,
    sent_at TIMESTAMP NULL,
    sent_by INT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_notifications_user
        FOREIGN KEY (sent_by) REFERENCES users(id)
        ON DELETE SET NULL
);

CREATE INDEX idx_notifications_status ON notifications(status);
CREATE INDEX idx_notifications_scheduled_at ON notifications(scheduled_at);
>>>>>>> d54adc0cedec7835407a76baff9b0d22e25ed755
