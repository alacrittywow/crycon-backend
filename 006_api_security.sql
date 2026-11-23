-- Keep staging data private until a deliberate public read model is designed.
-- The backend secret key maps to service_role; browser-facing anon/authenticated
-- roles receive no table or RPC access from this migration.

ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE parser_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE known_aliases ENABLE ROW LEVEL SECURITY;

-- PostgreSQL grants EXECUTE on new functions to PUBLIC by default. Remove that
-- implicit surface and grant the backend role only in Supabase environments.
REVOKE EXECUTE ON FUNCTION search_candidates_fuzzy(text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION create_discovered_candidate(
    text, text, text, text, text, text, text, integer, text, text
) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION enqueue_parser_job(text, text, text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION claim_parser_job(text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION heartbeat_parser_job(bigint, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION complete_parser_job(bigint, text, integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION fail_parser_job(bigint, text, text, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION set_candidate_updated_at() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION set_parser_job_updated_at() FROM PUBLIC;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL PRIVILEGES ON TABLE
            candidates, profiles, contacts, wallets, evidence, parser_jobs,
            known_aliases
        FROM anon;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON TABLES FROM anon;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON SEQUENCES FROM anon;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL PRIVILEGES ON TABLE
            candidates, profiles, contacts, wallets, evidence, parser_jobs,
            known_aliases
        FROM authenticated;
        REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON TABLES FROM authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE ALL PRIVILEGES ON SEQUENCES FROM authenticated;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
            candidates, profiles, contacts, wallets, evidence, parser_jobs,
            known_aliases
        TO service_role;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
        GRANT EXECUTE ON FUNCTION search_candidates_fuzzy(text, integer)
            TO service_role;
        GRANT EXECUTE ON FUNCTION create_discovered_candidate(
            text, text, text, text, text, text, text, integer, text, text
        ) TO service_role;
        GRANT EXECUTE ON FUNCTION enqueue_parser_job(text, text, text, integer)
            TO service_role;
        GRANT EXECUTE ON FUNCTION claim_parser_job(text, integer) TO service_role;
        GRANT EXECUTE ON FUNCTION heartbeat_parser_job(bigint, text) TO service_role;
        GRANT EXECUTE ON FUNCTION complete_parser_job(bigint, text, integer)
            TO service_role;
        GRANT EXECUTE ON FUNCTION fail_parser_job(bigint, text, text, boolean)
            TO service_role;
    END IF;
END;
$$;

COMMENT ON TABLE candidates IS
    'Backend-only staging table. No anon/authenticated policies are installed.';
