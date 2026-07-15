-- ==============================================================================
-- DERMIFY - DATABASE CLEANUP & STANDARDIZATION MIGRATION SCRIPT
-- ==============================================================================
-- Skrip ini aman dijalankan di phpMyAdmin untuk membersihkan nilai NULL 
-- pada data pemindai lama (April 2026 / Legacy Scans) serta menstandarisasi
-- teks 'Unknown' agar tampilan tabel di Admin Dashboard menjadi rapi dan lengkap.
-- ==============================================================================

-- 1. STANDARDISASI TABEL `analyses` (Membersihkan nilai NULL pada kolom baru)
UPDATE `analyses` 
SET 
    `overall_score` = COALESCE(`overall_score`, 100),
    `classification` = COALESCE(`classification`, 'Safe (Legacy Scan)'),
    `warnings_count` = COALESCE(`warnings_count`, 0),
    `unknown_count` = COALESCE(`unknown_count`, 0),
    `ai_model` = COALESCE(`ai_model`, 'Rule-Based-v1'),
    `ai_output` = COALESCE(`ai_output`, `recommendation`),
    `status` = COALESCE(`status`, 'completed')
WHERE `overall_score` IS NULL 
   OR `classification` IS NULL 
   OR `ai_model` IS NULL;


-- 2. STANDARDISASI TABEL `ingredients` (Mengganti fungsi 'Unknown' atau kosong)
UPDATE `ingredients` 
SET 
    `function` = 'General Skincare Ingredient' 
WHERE `function` = 'Unknown' 
   OR `function` IS NULL 
   OR TRIM(`function`) = '';

UPDATE `ingredients` 
SET 
    `description` = 'Bahan kosmetik / perawatan kulit umum.' 
WHERE `description` = 'Unknown' 
   OR `description` IS NULL 
   OR TRIM(`description`) = '';


-- 3. STANDARDISASI TABEL `analysis_details` (Membersihkan detail yang sudah tersimpan)
UPDATE `analysis_details` 
SET 
    `function` = 'General Skincare Ingredient' 
WHERE `function` = 'Unknown' 
   OR `function` IS NULL 
   OR TRIM(`function`) = '';

UPDATE `analysis_details` 
SET 
    `benefit` = 'Komponen formula perawatan kulit untuk menjaga tekstur dan efektivitas produk.' 
WHERE `benefit` = 'Unknown' 
   OR `benefit` IS NULL 
   OR TRIM(`benefit`) = '';

-- ==============================================================================
-- SELESAI. Semua data pemindai lawas sekarang sudah standar dan siap ditampilkan!
-- ==============================================================================
