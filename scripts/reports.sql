-- Отчёты по наблюдаемости (PR-5). Только SELECT.
-- Запуск: sqlite3 data/molvi.db < scripts/reports.sql

-- Расход токенов по моделям за 30 дней.
SELECT model, SUM(tokens_in) in_tok, SUM(tokens_out) out_tok,
       SUM(tokens_in + tokens_out) total,
       ROUND(AVG(latency_ms)/1000.0, 1) avg_sec, COUNT(*) calls
FROM events WHERE type='llm_call' AND created_at >= datetime('now','-30 days')
GROUP BY model ORDER BY total DESC;

-- Доля смены шаблона: главная метрика качества саммари. Порог провала — 35%.
SELECT ROUND(100.0 * SUM(CASE WHEN n > 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS switch_pct
FROM (SELECT job_id, COUNT(DISTINCT template) n FROM events
      WHERE type='template' AND job_id IS NOT NULL GROUP BY job_id);

-- Ошибки по типам за 30 дней.
SELECT err_code, COUNT(*) n FROM events
WHERE type='error' AND created_at >= datetime('now','-30 days')
GROUP BY err_code ORDER BY n DESC;
