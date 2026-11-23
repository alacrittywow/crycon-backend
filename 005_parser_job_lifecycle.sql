-- Durable parser job lifecycle for concurrent workers.

ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS attempt_count integer NOT NULL DEFAULT 0;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 3;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS heartbeat_at timestamptz;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS locked_by text;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS error_text text;
ALTER TABLE parser_jobs ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE UNIQUE INDEX IF NOT EXISTS idx_parser_jobs_idempotency
ON parser_jobs(job_type, idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_parser_jobs_claim
ON parser_jobs(status, created_at, id)
WHERE status IN ('new', 'running');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'parser_jobs_attempt_count_nonnegative'
          AND conrelid = 'parser_jobs'::regclass
    ) THEN
        ALTER TABLE parser_jobs ADD CONSTRAINT parser_jobs_attempt_count_nonnegative
            CHECK (attempt_count >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'parser_jobs_max_attempts_range'
          AND conrelid = 'parser_jobs'::regclass
    ) THEN
        ALTER TABLE parser_jobs ADD CONSTRAINT parser_jobs_max_attempts_range
            CHECK (max_attempts BETWEEN 1 AND 20) NOT VALID;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION set_parser_job_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_parser_jobs_updated_at ON parser_jobs;
CREATE TRIGGER trg_parser_jobs_updated_at
BEFORE UPDATE ON parser_jobs
FOR EACH ROW
EXECUTE FUNCTION set_parser_job_updated_at();

CREATE OR REPLACE FUNCTION enqueue_parser_job(
    p_job_type text,
    p_query text,
    p_idempotency_key text,
    p_max_attempts integer DEFAULT 3
)
RETURNS SETOF parser_jobs
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    v_job_type text := btrim(coalesce(p_job_type, ''));
    v_key text := nullif(btrim(coalesce(p_idempotency_key, '')), '');
    v_job parser_jobs%ROWTYPE;
BEGIN
    IF v_job_type = '' THEN
        RAISE EXCEPTION 'job_type is required' USING ERRCODE = '22023';
    END IF;
    IF p_max_attempts NOT BETWEEN 1 AND 20 THEN
        RAISE EXCEPTION 'max_attempts must be between 1 and 20'
            USING ERRCODE = '22023';
    END IF;

    IF v_key IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(
            hashtextextended(lower(v_job_type) || chr(31) || v_key, 2)
        );
        SELECT * INTO v_job
        FROM parser_jobs
        WHERE job_type = v_job_type AND idempotency_key = v_key
        ORDER BY id
        LIMIT 1;
        IF FOUND THEN
            RETURN NEXT v_job;
            RETURN;
        END IF;
    END IF;

    INSERT INTO parser_jobs (
        job_type, query, status, result_count, idempotency_key, max_attempts
    ) VALUES (
        v_job_type, nullif(btrim(coalesce(p_query, '')), ''), 'new', 0,
        v_key, p_max_attempts
    )
    RETURNING * INTO v_job;

    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION claim_parser_job(
    p_worker_id text,
    p_stale_after_seconds integer DEFAULT 300
)
RETURNS SETOF parser_jobs
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    v_worker_id text := btrim(coalesce(p_worker_id, ''));
    v_stale_after integer := greatest(coalesce(p_stale_after_seconds, 300), 1);
    v_job parser_jobs%ROWTYPE;
BEGIN
    IF v_worker_id = '' THEN
        RAISE EXCEPTION 'worker_id is required' USING ERRCODE = '22023';
    END IF;

    UPDATE parser_jobs
    SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'new' END,
        error_text = CASE
            WHEN attempt_count >= max_attempts THEN 'worker lease expired; attempts exhausted'
            ELSE 'worker lease expired; queued for retry'
        END,
        finished_at = CASE WHEN attempt_count >= max_attempts THEN now() ELSE NULL END,
        locked_by = NULL,
        heartbeat_at = NULL
    WHERE status = 'running'
      AND coalesce(heartbeat_at, started_at, created_at)
          < now() - make_interval(secs => v_stale_after);

    SELECT * INTO v_job
    FROM parser_jobs
    WHERE status = 'new' AND attempt_count < max_attempts
    ORDER BY created_at, id
    FOR UPDATE SKIP LOCKED
    LIMIT 1;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE parser_jobs
    SET status = 'running',
        attempt_count = attempt_count + 1,
        started_at = now(),
        heartbeat_at = now(),
        finished_at = NULL,
        locked_by = v_worker_id
    WHERE id = v_job.id
    RETURNING * INTO v_job;

    RETURN NEXT v_job;
END;
$$;

CREATE OR REPLACE FUNCTION heartbeat_parser_job(
    p_job_id bigint,
    p_worker_id text
)
RETURNS boolean
LANGUAGE sql
VOLATILE
SECURITY INVOKER
AS $$
    WITH updated AS (
        UPDATE parser_jobs
        SET heartbeat_at = now()
        WHERE id = p_job_id
          AND status = 'running'
          AND locked_by = p_worker_id
        RETURNING 1
    )
    SELECT EXISTS(SELECT 1 FROM updated);
$$;

CREATE OR REPLACE FUNCTION complete_parser_job(
    p_job_id bigint,
    p_worker_id text,
    p_result_count integer DEFAULT 0
)
RETURNS boolean
LANGUAGE sql
VOLATILE
SECURITY INVOKER
AS $$
    WITH updated AS (
        UPDATE parser_jobs
        SET status = 'done',
            result_count = greatest(coalesce(p_result_count, 0), 0),
            finished_at = now(),
            heartbeat_at = now(),
            locked_by = NULL,
            error_text = NULL
        WHERE id = p_job_id
          AND status = 'running'
          AND locked_by = p_worker_id
        RETURNING 1
    )
    SELECT EXISTS(SELECT 1 FROM updated);
$$;

CREATE OR REPLACE FUNCTION fail_parser_job(
    p_job_id bigint,
    p_worker_id text,
    p_error_text text,
    p_retryable boolean DEFAULT true
)
RETURNS text
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    v_job parser_jobs%ROWTYPE;
    v_status text;
BEGIN
    SELECT * INTO v_job
    FROM parser_jobs
    WHERE id = p_job_id AND status = 'running' AND locked_by = p_worker_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    v_status := CASE
        WHEN coalesce(p_retryable, false) AND v_job.attempt_count < v_job.max_attempts
            THEN 'new'
        ELSE 'failed'
    END;

    UPDATE parser_jobs
    SET status = v_status,
        error_text = left(nullif(btrim(coalesce(p_error_text, '')), ''), 2000),
        finished_at = CASE WHEN v_status = 'failed' THEN now() ELSE NULL END,
        heartbeat_at = NULL,
        locked_by = NULL
    WHERE id = p_job_id;

    RETURN v_status;
END;
$$;
