create table if not exists idempotency_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    workspace_id uuid,
    route_key text not null,
    idempotency_key text not null,
    request_hash text not null,
    status text not null,
    response_status_code integer,
    response_body jsonb,
    resource_type text,
    resource_id uuid,
    locked_at timestamptz not null default now(),
    completed_at timestamptz,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, route_key, idempotency_key)
);

create index if not exists idempotency_requests_route_status_idx
    on idempotency_requests (route_key, status);

create index if not exists idempotency_requests_expires_at_idx
    on idempotency_requests (expires_at);

alter table idempotency_requests enable row level security;

create policy idempotency_requests_select_policy on idempotency_requests
for select
using (user_id = app_request_user_id());
