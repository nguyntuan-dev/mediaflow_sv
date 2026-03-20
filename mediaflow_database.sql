-- ============================================================
--  MediaFlow — mediaflow_database.sql
--  PostgreSQL Database Setup
--
--  Cách chạy:
--    1. Mở pgAdmin hoặc psql
--    2. Chạy toàn bộ file này
--
--  Hoặc dùng lệnh terminal:
--    psql -U postgres -f mediaflow_database.sql
-- ============================================================


-- ============================================================
--  1. TẠO DATABASE
-- ============================================================
CREATE DATABASE mediaflow
    WITH
    OWNER      = postgres
    ENCODING   = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE   = 'en_US.UTF-8'
    TEMPLATE   = template0;

-- Kết nối vào database vừa tạo
\c mediaflow;


-- ============================================================
--  2. BẢNG LỊCH SỬ TẢI XUỐNG
-- ============================================================
CREATE TABLE IF NOT EXISTS download_history (
    id          SERIAL          PRIMARY KEY,
    platform    VARCHAR(20)     NOT NULL,
    title       VARCHAR(200)    NOT NULL,
    quality     VARCHAR(10)     NOT NULL,
    format      VARCHAR(10)     NOT NULL,
    size        VARCHAR(20)     DEFAULT '~0 MB',
    source_url  TEXT,
    ip_address  VARCHAR(50),
    created_at  TIMESTAMP       DEFAULT NOW()
);

-- Index để query nhanh hơn
CREATE INDEX idx_history_platform   ON download_history(platform);
CREATE INDEX idx_history_created_at ON download_history(created_at DESC);
CREATE INDEX idx_history_ip         ON download_history(ip_address);


-- ============================================================
--  3. BẢNG FILE ĐÃ TẢI
-- ============================================================
CREATE TABLE IF NOT EXISTS files (
    id           SERIAL          PRIMARY KEY,
    filename     VARCHAR(200)    NOT NULL,
    file_size    BIGINT          DEFAULT 0,
    download_url TEXT,
    platform     VARCHAR(20),
    format       VARCHAR(10),
    quality      VARCHAR(10),
    created_at   TIMESTAMP       DEFAULT NOW()
);

CREATE INDEX idx_files_platform   ON files(platform);
CREATE INDEX idx_files_created_at ON files(created_at DESC);


-- ============================================================
--  4. BẢNG THEO DÕI IP BỊ BLOCK
-- ============================================================
CREATE TABLE IF NOT EXISTS blocked_ips (
    id             SERIAL          PRIMARY KEY,
    ip_address     VARCHAR(50)     NOT NULL UNIQUE,
    reason         VARCHAR(200),
    wrong_attempts INTEGER         DEFAULT 0,
    blocked_until  TIMESTAMP,
    created_at     TIMESTAMP       DEFAULT NOW()
);

CREATE INDEX idx_blocked_ip ON blocked_ips(ip_address);


-- ============================================================
--  5. BẢNG LOG REQUEST (tùy chọn — ghi lại mọi lượt gọi API)
-- ============================================================
CREATE TABLE IF NOT EXISTS request_logs (
    id          SERIAL          PRIMARY KEY,
    ip_address  VARCHAR(50),
    method      VARCHAR(10),
    path        VARCHAR(200),
    status_code INTEGER,
    user_agent  TEXT,
    created_at  TIMESTAMP       DEFAULT NOW()
);

CREATE INDEX idx_logs_ip         ON request_logs(ip_address);
CREATE INDEX idx_logs_created_at ON request_logs(created_at DESC);

-- Tự động xóa log cũ hơn 30 ngày (chạy thủ công hoặc dùng pg_cron)
-- DELETE FROM request_logs WHERE created_at < NOW() - INTERVAL '30 days';


-- ============================================================
--  6. DỮ LIỆU MẪU (để test)
-- ============================================================
INSERT INTO download_history (platform, title, quality, format, size, source_url, ip_address)
VALUES
    ('tiktok',   'TikTok Video — @creator_vn — tiktok_abc123.mp4',   '1080p', 'MP4',  '24 MB', 'https://www.tiktok.com/@creator/video/123', '127.0.0.1'),
    ('youtube',  'YouTube — Top Trending 2025 — youtube_def456.mp3', 'Audio', 'MP3',  '8 MB',  'https://www.youtube.com/watch?v=abc123',    '127.0.0.1'),
    ('facebook', 'Facebook — summer_clip — facebook_ghi789.mp4',     '720p',  'MP4',  '15 MB', 'https://www.facebook.com/watch?v=xyz789',   '127.0.0.1');

INSERT INTO files (filename, file_size, download_url, platform, format, quality)
VALUES
    ('tiktok_abc123.mp4',   25165824, '/downloads/tiktok_abc123.mp4',   'tiktok',   'MP4', '1080p'),
    ('youtube_def456.mp3',   8388608, '/downloads/youtube_def456.mp3',  'youtube',  'MP3', 'Audio'),
    ('facebook_ghi789.mp4', 15728640, '/downloads/facebook_ghi789.mp4', 'facebook', 'MP4', '720p');


-- ============================================================
--  7. VIEW TIỆN ÍCH
-- ============================================================

-- Thống kê số lượt tải theo nền tảng
CREATE OR REPLACE VIEW stats_by_platform AS
SELECT
    platform,
    COUNT(*)                            AS total_downloads,
    SUM(file_size) / (1024*1024)       AS total_mb,
    MAX(created_at)                     AS last_download
FROM files
GROUP BY platform
ORDER BY total_downloads DESC;

-- Top 10 lịch sử gần nhất
CREATE OR REPLACE VIEW recent_history AS
SELECT
    id, platform, title, quality, format, size, created_at
FROM download_history
ORDER BY created_at DESC
LIMIT 10;


-- ============================================================
--  8. KIỂM TRA KẾT QUẢ
-- ============================================================
SELECT 'download_history' AS table_name, COUNT(*) AS rows FROM download_history
UNION ALL
SELECT 'files',            COUNT(*) FROM files
UNION ALL
SELECT 'blocked_ips',      COUNT(*) FROM blocked_ips
UNION ALL
SELECT 'request_logs',     COUNT(*) FROM request_logs;
