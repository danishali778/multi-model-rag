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

alter table connector_sync_states enable row level security;

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
