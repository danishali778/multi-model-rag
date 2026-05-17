create table if not exists evaluation_runs (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenants(id) on delete cascade,
    run_type text not null,
    model_profile text not null,
    metrics jsonb not null default '{}'::jsonb,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists audit_logs_tenant_event_created_idx
on audit_logs (tenant_id, event_type, created_at desc);

create index if not exists audit_logs_tenant_actor_created_idx
on audit_logs (tenant_id, actor_id, created_at desc);

create index if not exists model_usage_tenant_created_idx
on model_usage (tenant_id, created_at desc);

create index if not exists model_usage_tenant_profile_created_idx
on model_usage (tenant_id, model_profile, created_at desc);

create index if not exists feedback_tenant_created_idx
on feedback (tenant_id, created_at desc);

create index if not exists feedback_message_idx
on feedback (message_id);

create index if not exists ingestion_jobs_tenant_status_created_idx
on ingestion_jobs (tenant_id, status, created_at desc);

create index if not exists conversations_tenant_user_updated_idx
on conversations (tenant_id, user_id, updated_at desc);

alter table evaluation_runs enable row level security;

create policy evaluation_runs_select_policy on evaluation_runs
for select
using (
    exists (
        select 1 from tenant_members tm
        where tm.tenant_id = evaluation_runs.tenant_id
          and tm.user_id = app_request_user_id()
          and tm.role in ('owner', 'admin')
          and tm.status = 'active'
    )
);

create policy evaluation_runs_insert_policy on evaluation_runs
for insert
with check (
    exists (
        select 1 from tenant_members tm
        where tm.tenant_id = evaluation_runs.tenant_id
          and tm.user_id = app_request_user_id()
          and tm.role in ('owner', 'admin')
          and tm.status = 'active'
    )
);
