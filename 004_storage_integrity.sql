-- Make new writes safer without assuming that all historical rows are clean.
-- NOT VALID checks are enforced for new/updated rows but do not scan old data.

CREATE INDEX IF NOT EXISTS idx_profiles_platform_username_normalized
ON profiles(lower(platform), lower(username));

CREATE OR REPLACE FUNCTION set_candidate_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_candidates_updated_at ON candidates;
CREATE TRIGGER trg_candidates_updated_at
BEFORE UPDATE ON candidates
FOR EACH ROW
EXECUTE FUNCTION set_candidate_updated_at();

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'candidates_scores_range' AND conrelid = 'candidates'::regclass) THEN
        ALTER TABLE candidates ADD CONSTRAINT candidates_scores_range CHECK (
            relevance_score BETWEEN 0 AND 100
            AND identity_score BETWEEN 0 AND 100
            AND wallet_score BETWEEN 0 AND 100
            AND contact_score BETWEEN 0 AND 100
            AND overall_trust_score BETWEEN 0 AND 100
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'candidates_status_allowed' AND conrelid = 'candidates'::regclass) THEN
        ALTER TABLE candidates ADD CONSTRAINT candidates_status_allowed CHECK (
            status IN ('new', 'weak', 'needs_review', 'valid', 'strong')
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'profiles_confidence_range' AND conrelid = 'profiles'::regclass) THEN
        ALTER TABLE profiles ADD CONSTRAINT profiles_confidence_range
            CHECK (confidence BETWEEN 0 AND 100) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'contacts_confidence_range' AND conrelid = 'contacts'::regclass) THEN
        ALTER TABLE contacts ADD CONSTRAINT contacts_confidence_range
            CHECK (confidence BETWEEN 0 AND 100) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'wallets_confidence_range' AND conrelid = 'wallets'::regclass) THEN
        ALTER TABLE wallets ADD CONSTRAINT wallets_confidence_range
            CHECK (confidence BETWEEN 0 AND 100) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evidence_confidence_range' AND conrelid = 'evidence'::regclass) THEN
        ALTER TABLE evidence ADD CONSTRAINT evidence_confidence_range
            CHECK (confidence BETWEEN 0 AND 100) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'parser_jobs_status_allowed' AND conrelid = 'parser_jobs'::regclass) THEN
        ALTER TABLE parser_jobs ADD CONSTRAINT parser_jobs_status_allowed CHECK (
            status IN ('new', 'running', 'done', 'failed')
        ) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'parser_jobs_result_count_nonnegative' AND conrelid = 'parser_jobs'::regclass) THEN
        ALTER TABLE parser_jobs ADD CONSTRAINT parser_jobs_result_count_nonnegative
            CHECK (result_count >= 0) NOT VALID;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION create_discovered_candidate(
    p_platform text,
    p_username text,
    p_display_name text,
    p_bio text,
    p_profile_url text,
    p_source_url text,
    p_matched_keyword text,
    p_relevance_score integer,
    p_status text,
    p_evidence_text text
)
RETURNS TABLE(
    result_status text,
    candidate_id bigint,
    profile_id bigint,
    evidence_id bigint
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    v_platform text := btrim(coalesce(p_platform, ''));
    v_username text := btrim(coalesce(p_username, ''));
    v_candidate_id bigint;
    v_profile_id bigint;
    v_evidence_id bigint;
BEGIN
    IF v_platform = '' OR v_username = '' THEN
        RAISE EXCEPTION 'platform and username are required'
            USING ERRCODE = '22023';
    END IF;

    -- Serialize the same normalized identity inside this transaction. This avoids
    -- two concurrent discovery workers creating two candidates for Alice/alice.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(lower(v_platform) || chr(31) || lower(v_username), 0)
    );

    SELECT p.candidate_id, p.id
    INTO v_candidate_id, v_profile_id
    FROM profiles p
    WHERE lower(p.platform) = lower(v_platform)
      AND lower(p.username) = lower(v_username)
    ORDER BY p.id
    LIMIT 1;

    IF FOUND THEN
        RETURN QUERY SELECT 'exists'::text, v_candidate_id, v_profile_id, NULL::bigint;
        RETURN;
    END IF;

    INSERT INTO candidates (
        main_username, display_name, bio, relevance_score, identity_score,
        wallet_score, contact_score, overall_trust_score, status
    ) VALUES (
        v_username, nullif(btrim(coalesce(p_display_name, '')), ''),
        nullif(btrim(coalesce(p_bio, '')), ''), p_relevance_score, 50,
        0, 0, p_relevance_score, p_status
    )
    RETURNING id INTO v_candidate_id;

    INSERT INTO profiles (
        candidate_id, platform, username, display_name, bio, profile_url,
        source_url, matched_keyword, confidence, evidence_type
    ) VALUES (
        v_candidate_id, v_platform, v_username,
        nullif(btrim(coalesce(p_display_name, '')), ''),
        nullif(btrim(coalesce(p_bio, '')), ''),
        nullif(btrim(coalesce(p_profile_url, '')), ''),
        nullif(btrim(coalesce(p_source_url, '')), ''),
        nullif(btrim(coalesce(p_matched_keyword, '')), ''),
        70, 'parser_discovery'
    )
    RETURNING id INTO v_profile_id;

    INSERT INTO evidence (
        candidate_id, entity_type, entity_value, source_platform,
        source_url, evidence_text, confidence
    ) VALUES (
        v_candidate_id, 'candidate_discovery', v_username, v_platform,
        coalesce(
            nullif(btrim(coalesce(p_source_url, '')), ''),
            nullif(btrim(coalesce(p_profile_url, '')), '')
        ),
        nullif(btrim(coalesce(p_evidence_text, '')), ''), 70
    )
    RETURNING id INTO v_evidence_id;

    RETURN QUERY SELECT 'created'::text, v_candidate_id, v_profile_id, v_evidence_id;
END;
$$;

COMMENT ON FUNCTION create_discovered_candidate(
    text, text, text, text, text, text, text, integer, text, text
) IS 'Atomically creates discovery candidate, profile and evidence; normalized duplicate calls return exists.';
