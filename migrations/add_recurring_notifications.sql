-- Migration: Add recurring notification support
-- Run this against the Dermify database

ALTER TABLE notifications
  ADD COLUMN repeat_daily  TINYINT(1)  NOT NULL DEFAULT 0     COMMENT '1 = kirim ulang setiap hari',
  ADD COLUMN repeat_time   VARCHAR(5)  NULL                   COMMENT 'Jam pengiriman harian, format HH:MM (WIB)',
  ADD COLUMN last_sent_at  DATETIME    NULL                   COMMENT 'Terakhir berhasil dikirim oleh scheduler';
