-- Mirae Web3 Trust Discovery DB Schema v1

create table if not exists candidates (
    id bigserial primary key,

    main_username text not null,
    display_name text,
    bio text,

    relevance_score integer default 0,
    identity_score integer default 0,
    wallet_score integer default 0,
    contact_score integer default 0,
    overall_trust_score integer default 0,

    status text default 'new',

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists profiles (
    id bigserial primary key,

    candidate_id bigint references candidates(id) on delete cascade,

    platform text not null,
    username text not null,
    display_name text,
    bio text,

    profile_url text,
    source_url text,
    matched_keyword text,

    confidence integer default 50,
    evidence_type text default 'discovered',

    created_at timestamptz default now(),

    unique(platform, username)
);

create table if not exists contacts (
    id bigserial primary key,

    candidate_id bigint references candidates(id) on delete cascade,

    contact_type text not null,
    value text not null,

    confidence integer default 0,
    status text default 'possible',

    evidence_url text,
    evidence_text text,

    created_at timestamptz default now(),

    unique(contact_type, value)
);

create table if not exists wallets (
    id bigserial primary key,

    candidate_id bigint references candidates(id) on delete cascade,

    wallet_type text not null,
    wallet_address text,
    chain text,
    name_service text,

    confidence integer default 0,
    status text default 'possible',

    evidence_url text,
    evidence_text text,
    evidence_type text default 'public_text',

    created_at timestamptz default now(),

    unique(wallet_type, wallet_address, name_service)
);

create table if not exists evidence (
    id bigserial primary key,

    candidate_id bigint references candidates(id) on delete cascade,

    entity_type text not null,
    entity_value text,

    source_platform text,
    source_url text,
    evidence_text text,

    confidence integer default 0,

    created_at timestamptz default now()
);

create table if not exists parser_jobs (
    id bigserial primary key,

    job_type text not null,
    query text,
    status text default 'new',

    result_count integer default 0,

    created_at timestamptz default now(),
    finished_at timestamptz
);

create index if not exists idx_candidates_main_username
on candidates(lower(main_username));

create index if not exists idx_profiles_username
on profiles(lower(username));

create index if not exists idx_profiles_platform
on profiles(platform);

create index if not exists idx_contacts_value
on contacts(lower(value));

create index if not exists idx_wallets_address
on wallets(lower(wallet_address));

create index if not exists idx_wallets_name_service
on wallets(lower(name_service));

create index if not exists idx_evidence_candidate_id
on evidence(candidate_id);