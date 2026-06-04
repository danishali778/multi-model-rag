create table if not exists evaluation_runs (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references workspaces(id) on delete cascade,
    run_type text not null,
    model_profile text not null,
    metrics jsonb not null default '{}'::jsonb,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists evaluation_runs_workspace_created_idx
    on evaluation_runs (workspace_id, created_at desc);

create index if not exists evaluation_runs_workspace_profile_created_idx
    on evaluation_runs (workspace_id, model_profile, created_at desc);

alter table evaluation_runs enable row level security;

drop policy if exists evaluation_runs_select_policy on evaluation_runs;
create policy evaluation_runs_select_policy
    on evaluation_runs
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = evaluation_runs.workspace_id
              and wm.user_id = app_request_user_id()
              and wm.role = 'owner'
              and wm.status = 'active'
        )
    );

drop policy if exists evaluation_runs_insert_policy on evaluation_runs;
create policy evaluation_runs_insert_policy
    on evaluation_runs
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = evaluation_runs.workspace_id
              and wm.user_id = app_request_user_id()
              and wm.role = 'owner'
              and wm.status = 'active'
        )
    );
