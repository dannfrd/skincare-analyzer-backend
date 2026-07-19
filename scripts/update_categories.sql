-- ============================================================
-- Kategori Skincare yang Terkoreksi berdasarkan:
-- 1. Definisi BPOM: produk kosmetik untuk perawatan kulit wajah
-- 2. Panduan skincare internasional (Healthline, CeraVe, Kiehl's)
-- 3. Produk yang umum beredar di pasar Indonesia
--
-- DIKELUARKAN dari daftar:
-- - Perawatan Rambut  → haircare, bukan skincare
-- - BB/CC Cream, Primer, Tinted Moisturizer → makeup/base makeup
-- - "Krim Mata" dimerge ke "Eye Care" (menghindari redundansi)
-- - "Mist & Setting Spray" → Setting Spray adalah makeup, 
--   diganti menjadi "Facial Mist" saja (skincare)
--
-- Cara menjalankan:
-- 1. Login ke VPS: ssh user@ip_vps_kamu
-- 2. Login ke MySQL: mysql -u root -p skincare_analyzer
-- 3. Copy-paste script ini
-- ============================================================

-- Hapus data kategori lama
TRUNCATE TABLE product_categories;

-- Insert kategori skincare yang sudah dikoreksi
INSERT INTO product_categories (name, icon, color, sort_order, is_active) VALUES
-- === PEMBERSIH (Cleansing Step) ===
('Cleanser',          'cleaning_services',  '#4CB35B', 1,  1),   -- Facial wash, foam, gel cleanser
('Micellar Water',    'water_drop',         '#34D399', 2,  1),   -- Micellar, cleansing water
('Cleansing Oil/Balm','opacity',            '#A78BFA', 3,  1),   -- Double cleanse, cleansing balm

-- === TREATMENT DASAR (Prep & Hydration) ===
('Toner',             'science',            '#3B82F6', 4,  1),   -- Hydrating toner, astringent
('Essence',           'auto_awesome',       '#8B5CF6', 5,  1),   -- Essence, pre-serum, pitera

-- === TREATMENT AKTIF (Targeted Treatment) ===
('Serum',             'biotech',            '#7C3AED', 6,  1),   -- Vitamin C, niacinamide, HA serum
('Ampoule',           'colorize',           '#6D28D9', 7,  1),   -- Concentrated ampoule, booster
('Spot Treatment',    'healing',            '#DC2626', 8,  1),   -- Acne spot, obat totol jerawat
('Retinol',           'nights_stay',        '#1D4ED8', 9,  1),   -- Retinol, retinoid, vitamin A

-- === PELEMBAP (Moisturizing) ===
('Moisturizer',       'spa',                '#F59E0B', 10, 1),   -- Moisturizer, krim wajah, lotion
('Night Cream',       'nightlight',         '#1E40AF', 11, 1),   -- Night cream, sleeping cream

-- === MATA & BIBIR ===
('Eye Care',          'visibility',         '#0EA5E9', 12, 1),   -- Eye cream, eye serum, eye gel
('Lip Care',          'favorite',           '#E11D48', 13, 1),   -- Lip balm, lip serum, lip scrub

-- === PELINDUNG ===
('Sunscreen',         'wb_sunny',           '#EF4444', 14, 1),   -- Sunscreen, SPF, sunblock

-- === PERAWATAN BERKALA ===
('Exfoliator',        'grain',              '#F97316', 15, 1),   -- Scrub, AHA/BHA, peeling gel
('Face Mask',         'face_retouching_natural', '#EC4899', 16, 1), -- Clay mask, sleeping mask
('Sheet Mask',        'receipt_long',       '#10B981', 17, 1),   -- Sheet mask, bio-cellulose mask
('Facial Mist',       'air',                '#67E8F9', 18, 1),   -- Facial mist, toning spray

-- === MINYAK WAJAH ===
('Facial Oil',        'water',              '#D97706', 19, 1),   -- Rosehip oil, jojoba oil, bakuchiol

-- === LAINNYA ===
('Lainnya',           'category',           '#6B7280', 20, 1);  -- Produk skincare di luar kategori

-- Verifikasi hasilnya
SELECT id, name, sort_order, is_active FROM product_categories ORDER BY sort_order;
