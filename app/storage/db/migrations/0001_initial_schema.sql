create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto;

create table if not exists tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    slug text not null unique,
    plan text not null default 'dev',
    data_region text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists profiles (
    id uuid primary key,
    display_name text,
    email text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists tenant_members (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    user_id uuid not null,
    role text not null default 'member',
    status text not null default 'active',
    created_at timestamptz not null default now(),
    unique (tenant_id, user_id)
);

create table if not exists groups (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    name text not null,
    slug text not null,
    created_at timestamptz not null default now(),
    unique (tenant_id, slug)
);

create table if not exists group_members (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    group_id uuid not null references groups(id) on delete cascade,
    user_id uuid not null,
    created_at timestamptz not null default now(),
    unique (group_id, user_id)
);

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    created_by uuid,
    title text not null,
    source_type text not null,
    source_uri text,
    storage_bucket text,
    storage_path text,
    content_hash text,
    status text not null default 'pending',
    sensitivity text not null default 'internal',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table if not exists document_acl_groups (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    group_id uuid not null references groups(id) on delete cascade,
    access_level text not null default 'read',
    created_at timestamptz not null default now(),
    unique (document_id, group_id)
);

create table if not exists document_chunks (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    chunk_index integer not null,
    content text not null,
    content_hash text not null,
    token_count integer not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    search_vector tsvector generated always as (to_tsvector('english', coalesce(content, ''))) stored,
    embedding extensions.vector(384),
    embedding_model text not null,
    chunking_version text not null,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_index)
);

create index if not exists documents_tenant_status_idx on documents (tenant_id, status);
create index if not exists documents_metadata_idx on documents using gin (metadata);
create index if not exists document_chunks_tenant_document_idx on document_chunks (tenant_id, document_id);
create index if not exists document_chunks_metadata_idx on document_chunks using gin (metadata);
create index if not exists document_chunks_search_vector_idx on document_chunks using gin (search_vector);
create index if not exists document_chunks_embedding_idx
on document_chunks using hnsw (embedding vector_cosine_ops);

create table if not exists ingestion_jobs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    status text not null default 'queued',
    stage text not null default 'queued',
    attempts integer not null default 1,
    error_code text,
    error_message text,
    stats jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz
);

create table if not exists conversations (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    user_id uuid not null,
    title text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversations(id) on delete cascade,
    role text not null,
    content text not null,
    model_profile text,
    sources jsonb not null default '[]'::jsonb,
    token_usage jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists feedback (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    conversation_id uuid references conversations(id) on delete set null,
    message_id uuid references messages(id) on delete set null,
    user_id uuid,
    rating text,
    comments text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists audit_logs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    actor_id uuid,
    event_type text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists model_usage (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    user_id uuid,
    operation text not null,
    model_profile text not null default 'balanced',
    provider text not null,
    model_name text not null,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    estimated_cost_usd numeric(12, 6) not null default 0,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists connector_sync_states (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    connector_type text not null,
    source_key text not null,
    cursor jsonb not null default '{}'::jsonb,
    status text not null default 'idle',
    error_message text,
    last_run_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (tenant_id, connector_type, source_key)
);

alter table tenants enable row level security;
alter table tenant_members enable row level security;
alter table groups enable row level security;
alter table group_members enable row level security;
alter table documents enable row level security;
alter table document_acl_groups enable row level security;
alter table document_chunks enable row level security;
alter table ingestion_jobs enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;
alter table feedback enable row level security;
alter table audit_logs enable row level security;
alter table model_usage enable row level security;
alter table connector_sync_states enable row level security;

create or replace function app_request_user_id()
returns uuid
language sql
stable
set search_path = ''
as $$
    select coalesce(
        nullif(current_setting('request.jwt.claim.sub', true), '')::uuid,
        nullif(current_setting('app.current_user_id', true), '')::uuid
    )
$$;

create policy tenants_select_policy on tenants
for select
using (
    exists (
        select 1 from tenant_members tm
        where tm.tenant_id = tenants.id and tm.user_id = app_request_user_id() and tm.status = 'active'
    )
);

create policy tenant_members_select_policy on tenant_members
for select
using (user_id = app_request_user_id());

create policy groups_select_policy on groups
for select
using (
    exists (
        select 1 from tenant_members tm
        where tm.tenant_id = groups.tenant_id and tm.user_id = app_request_user_id() and tm.status = 'active'
    )
);

create policy group_members_select_policy on group_members
for select
using (user_id = app_request_user_id());

create policy profiles_select_policy on profiles
for select
using (id = app_request_user_id());

create policy documents_select_policy on documents
for select
using (
    exists (
        select 1 from tenant_members tm
        where tm.tenant_id = documents.tenant_id and tm.user_id = app_request_user_id() and tm.status = 'active'
    )
    and (
        not exists (
            select 1 from document_acl_groups dag where dag.document_id = documents.id
        )
        or exists (
            select 1
            from document_acl_groups dag
            join group_members gm on gm.group_id = dag.group_id and gm.tenant_id = dag.tenant_id
            where dag.document_id = documents.id and gm.user_id = app_request_user_id()
        )
    )
);

create policy document_chunks_select_policy on document_chunks
for select
using (
    exists (
        select 1 from documents d
        where d.id = document_chunks.document_id
    )
);

create policy document_acl_groups_select_policy on document_acl_groups
for select
using (
    exists (
        select 1 from documents d
        where d.id = document_acl_groups.document_id
    )
);

create policy ingestion_jobs_select_policy on ingestion_jobs
for select
using (
    exists (
        select 1
        from documents d
        where d.id = ingestion_jobs.document_id
    )
);

create policy conversations_select_policy on conversations
for select
using (user_id = app_request_user_id());

create policy messages_select_policy on messages
for select
using (
    exists (
        select 1
        from conversations c
        where c.id = messages.conversation_id and c.user_id = app_request_user_id()
    )
);

create policy feedback_select_policy on feedback
for select
using (user_id = app_request_user_id());

create policy audit_logs_select_policy on audit_logs
for select
using (
    exists (
        select 1
        from tenant_members tm
        where tm.tenant_id = audit_logs.tenant_id
          and tm.user_id = app_request_user_id()
          and tm.role in ('owner', 'admin')
          and tm.status = 'active'
    )
);

create policy model_usage_select_policy on model_usage
for select
using (user_id = app_request_user_id());

create policy connector_sync_states_select_policy on connector_sync_states
for select
using (
    exists (
        select 1
        from tenant_members tm
        where tm.tenant_id = connector_sync_states.tenant_id
          and tm.user_id = app_request_user_id()
          and tm.role in ('owner', 'admin')
          and tm.status = 'active'
    )
);

insert into tenants (id, name, slug, plan, status)
values ('11111111-1111-1111-1111-111111111111', 'Development Tenant', 'development', 'dev', 'active')
on conflict (id) do nothing;

insert into profiles (id, display_name, email, status)
values ('00000000-0000-0000-0000-000000000001', 'Development User', 'dev@example.com', 'active')
on conflict (id) do nothing;

insert into tenant_members (tenant_id, user_id, role, status)
values ('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000001', 'owner', 'active')
on conflict (tenant_id, user_id) do nothing;
