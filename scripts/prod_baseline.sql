-- Baseline замер прода (PR-0). Только SELECT, никаких UPDATE/DELETE.
-- Запуск: sqlite3 data/molvi.db < scripts/prod_baseline.sql

-- 1) Минуты использования: среднее/максимум у пользователей с ненулевым расходом.
--    Порог 38 мин — ориентир по unit-экономике (см. README про 50 ₽/час).
SELECT
    COUNT(*)                    AS users_with_usage,
    ROUND(AVG(minutes_used), 2) AS avg_minutes_used,
    ROUND(MAX(minutes_used), 2) AS max_minutes_used,
    SUM(CASE WHEN minutes_used >= 38 THEN 1 ELSE 0 END) AS users_over_38min
FROM users
WHERE minutes_used > 0;

-- 2) Сколько уникальных пользователей хотя бы раз упёрлись в пэйвол.
SELECT COUNT(DISTINCT user_id) AS users_hit_paywall
FROM events
WHERE type = 'paywall';

-- 3a) Топ-10 часов по числу распознаваний (пиковая нагрузка).
SELECT
    strftime('%Y-%m-%d %H:00', created_at) AS hour_bucket,
    COUNT(*) AS recognitions
FROM events
WHERE type = 'recognize'
GROUP BY hour_bucket
ORDER BY recognitions DESC
LIMIT 10;

-- 3b) Среднее число распознаваний в день.
SELECT
    ROUND(1.0 * COUNT(*) / NULLIF(COUNT(DISTINCT DATE(created_at)), 0), 2) AS avg_recognitions_per_day,
    COUNT(DISTINCT DATE(created_at)) AS days_with_data
FROM events
WHERE type = 'recognize';

-- 4) Итоги для сверки с маркетинговым «5000+ пользователей» на сайте.
SELECT
    (SELECT COUNT(*) FROM users) AS total_users,
    (SELECT COUNT(*) FROM events WHERE type = 'recognize') AS total_recognitions,
    (SELECT ROUND(SUM(duration_sec) / 3600.0, 1) FROM events WHERE type = 'recognize') AS total_hours_recognized;

-- 5) Баг «документ не тарифицируется»: распознавания без duration_sec.
SELECT
    (SELECT COUNT(*) FROM events WHERE type = 'recognize' AND duration_sec IS NULL) AS recognize_without_duration,
    (SELECT COUNT(*) FROM events WHERE type = 'recognize') AS recognize_total;

-- 6) Объём и возраст расшифровок в records — вход для решения о retention.
SELECT
    COUNT(*)                                      AS records_count,
    SUM(LENGTH(transcript))                       AS transcript_total_chars,
    ROUND(SUM(LENGTH(transcript)) / 1048576.0, 2) AS transcript_total_mb_approx,
    MIN(created_at)                               AS oldest_record_at
FROM records;
