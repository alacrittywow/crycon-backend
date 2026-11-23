-- 002_search_improvements.sql

-- 1. Расширение pg_trgm
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. GIN индексы для нечёткого поиска
CREATE INDEX IF NOT EXISTS idx_candidates_main_username_trgm ON candidates USING GIN (main_username gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_candidates_display_name_trgm ON candidates USING GIN (display_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_candidates_bio_trgm ON candidates USING GIN (bio gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_profiles_username_trgm ON profiles USING GIN (username gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_contacts_value_trgm ON contacts USING GIN (value gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_wallets_address_trgm ON wallets USING GIN (wallet_address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_wallets_name_service_trgm ON wallets USING GIN (name_service gin_trgm_ops);

-- 3. Материализованное представление
CREATE MATERIALIZED VIEW mv_candidate_search AS
SELECT
    c.id AS candidate_id,
    c.main_username,
    c.display_name,
    c.bio,
    w.wallet_address,
    w.name_service,
    p.username AS profile_username,
    ct.value AS contact_value
FROM candidates c
LEFT JOIN wallets w ON c.id = w.candidate_id
LEFT JOIN profiles p ON c.id = p.candidate_id
LEFT JOIN contacts ct ON c.id = ct.candidate_id;

CREATE INDEX IF NOT EXISTS idx_mv_search_trgm ON mv_candidate_search USING GIN (
    main_username gin_trgm_ops,
    display_name gin_trgm_ops,
    bio gin_trgm_ops,
    wallet_address gin_trgm_ops,
    name_service gin_trgm_ops,
    profile_username gin_trgm_ops,
    contact_value gin_trgm_ops
);

-- 4. Функция нечёткого поиска
CREATE OR REPLACE FUNCTION search_candidates_fuzzy(
    search_query text,
    limit_rows int DEFAULT 10
)
RETURNS TABLE(candidate_id bigint, rank real) AS $$
BEGIN
    RETURN QUERY
    SELECT mv.candidate_id,
           GREATEST(
               similarity(mv.main_username, search_query),
               similarity(mv.display_name, search_query),
               similarity(mv.wallet_address, search_query),
               similarity(mv.name_service, search_query),
               similarity(mv.profile_username, search_query),
               similarity(mv.contact_value, search_query)
           ) AS rank
    FROM mv_candidate_search mv
    WHERE mv.main_username % search_query
       OR mv.display_name % search_query
       OR mv.wallet_address % search_query
       OR mv.name_service % search_query
       OR mv.profile_username % search_query
       OR mv.contact_value % search_query
    ORDER BY rank DESC
    LIMIT limit_rows;
END;
$$ LANGUAGE plpgsql STABLE;

-- 5. Таблица синонимов
CREATE TABLE IF NOT EXISTS known_aliases (
    alias text PRIMARY KEY,
    candidate_id bigint NOT NULL REFERENCES candidates(id) ON DELETE CASCADE
);