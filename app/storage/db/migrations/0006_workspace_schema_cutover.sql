begin;

drop policy if exists tenants_select_policy on tenants;
drop policy if exists tenant_members_select_policy on tenant_members;
drop policy if exists groups_select_policy on groups;
drop policy if exists group_members_select_policy on group_members;
drop policy if exists document_acl_groups_select_policy on document_acl_groups;
drop policy if exists documents_select_policy on documents;
drop policy if exists document_chunks_select_policy on document_chunks;
drop policy if exists ingestion_jobs_select_policy on ingestion_jobs;
drop policy if exists conversations_select_policy on conversations;
drop policy if exists messages_select_policy on messages;
drop policy if exists feedback_select_policy on feedback;
drop policy if exists audit_logs_select_policy on audit_logs;
drop policy if exists model_usage_select_policy on model_usage;
drop policy if exists connector_sync_states_select_policy on connector_sync_states;
drop policy if exists evaluation_runs_select_policy on evaluation_runs;
drop policy if exists evaluation_runs_insert_policy on evaluation_runs;

drop policy if exists profiles_select_policy on profiles;

drop table if exists evaluation_runs cascade;
drop table if exists document_acl_groups cascade;
drop table if exists group_members cascade;
drop table if exists groups cascade;

alter table if exists tenants rename to workspaces;
alter table if exists tenant_members rename to workspace_members;

alter table if exists workspace_members rename column tenant_id to workspace_id;
alter table if exists documents rename column tenant_id to workspace_id;
alter table if exists document_chunks rename column tenant_id to workspace_id;
alter table if exists ingestion_jobs rename column tenant_id to workspace_id;
alter table if exists conversations rename column tenant_id to workspace_id;
alter table if exists feedback rename column tenant_id to workspace_id;
alter table if exists audit_logs rename column tenant_id to workspace_id;
alter table if exists model_usage rename column tenant_id to workspace_id;
alter table if exists connector_sync_states rename column tenant_id to workspace_id;

drop policy if exists workspaces_select_policy on workspaces;
drop policy if exists workspace_members_select_policy on workspace_members;
drop policy if exists documents_select_policy on documents;
drop policy if exists document_chunks_select_policy on document_chunks;
drop policy if exists ingestion_jobs_select_policy on ingestion_jobs;
drop policy if exists conversations_select_policy on conversations;
drop policy if exists messages_select_policy on messages;
drop policy if exists feedback_select_policy on feedback;
drop policy if exists audit_logs_select_policy on audit_logs;
drop policy if exists model_usage_select_policy on model_usage;
drop policy if exists connector_sync_states_select_policy on connector_sync_states;

alter table if exists workspaces drop constraint if exists tenants_slug_key;
alter table if exists workspaces add constraint workspaces_slug_key unique (slug);

alter table if exists workspace_members drop constraint if exists tenant_members_tenant_id_user_id_key;
alter table if exists workspace_members add constraint workspace_members_workspace_id_user_id_key unique (workspace_id, user_id);

alter table if exists connector_sync_states drop constraint if exists connector_sync_states_tenant_id_connector_type_source_key_key;
alter table if exists connector_sync_states add constraint connector_sync_states_workspace_id_connector_type_source_key_key unique (workspace_id, connector_type, source_key);

drop index if exists documents_tenant_status_idx;
create index if not exists documents_workspace_status_idx on documents (workspace_id, status);

drop index if exists document_chunks_tenant_document_idx;
create index if not exists document_chunks_workspace_document_idx on document_chunks (workspace_id, document_id);

drop index if exists audit_logs_tenant_event_created_idx;
create index if not exists audit_logs_workspace_event_created_idx on audit_logs (workspace_id, event_type, created_at desc);

drop index if exists audit_logs_tenant_actor_created_idx;
create index if not exists audit_logs_workspace_actor_created_idx on audit_logs (workspace_id, actor_id, created_at desc);

drop index if exists model_usage_tenant_created_idx;
create index if not exists model_usage_workspace_created_idx on model_usage (workspace_id, created_at desc);

drop index if exists model_usage_tenant_profile_created_idx;
create index if not exists model_usage_workspace_profile_created_idx on model_usage (workspace_id, model_profile, created_at desc);

drop index if exists feedback_tenant_created_idx;
create index if not exists feedback_workspace_created_idx on feedback (workspace_id, created_at desc);

drop index if exists ingestion_jobs_tenant_status_created_idx;
create index if not exists ingestion_jobs_workspace_status_created_idx on ingestion_jobs (workspace_id, status, created_at desc);

drop index if exists conversations_tenant_user_updated_idx;
create index if not exists conversations_workspace_user_updated_idx on conversations (workspace_id, user_id, updated_at desc);

alter table workspaces enable row level security;
alter table workspace_members enable row level security;
alter table profiles enable row level security;
alter table documents enable row level security;
alter table document_chunks enable row level security;
alter table ingestion_jobs enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;
alter table feedback enable row level security;
alter table audit_logs enable row level security;
alter table model_usage enable row level security;
alter table connector_sync_states enable row level security;

create policy workspaces_select_policy on workspaces
for select
using (
    exists (
        select 1 from workspace_members wm
        where wm.workspace_id = workspaces.id and wm.user_id = app_request_user_id() and wm.status = 'active'
    )
);

create policy workspace_members_select_policy on workspace_members
for select
using (user_id = app_request_user_id());

create policy profiles_select_policy on profiles
for select
using (id = app_request_user_id());

create policy documents_select_policy on documents
for select
using (
    exists (
        select 1 from workspace_members wm
        where wm.workspace_id = documents.workspace_id and wm.user_id = app_request_user_id() and wm.status = 'active'
    )
);

create policy document_chunks_select_policy on document_chunks
for select
using (
    exists (
        select 1
        from documents d
        join workspace_members wm on wm.workspace_id = d.workspace_id
        where d.id = document_chunks.document_id and d.deleted_at is null and wm.user_id = app_request_user_id() and wm.status = 'active'
    )
);

create policy ingestion_jobs_select_policy on ingestion_jobs
for select
using (
    exists (
        select 1
        from documents d
        join workspace_members wm on wm.workspace_id = d.workspace_id
        where d.id = ingestion_jobs.document_id and d.deleted_at is null and wm.user_id = app_request_user_id() and wm.status = 'active'
    )
);

create policy conversations_select_policy on conversations
for select
using (
    user_id = app_request_user_id()
    and exists (
        select 1 from workspace_members wm
        where wm.workspace_id = conversations.workspace_id and wm.user_id = app_request_user_id() and wm.status = 'active'
    )
);

create policy messages_select_policy on messages
for select
using (
    exists (
        select 1 from conversations c
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
        select 1 from workspace_members wm
        where wm.workspace_id = audit_logs.workspace_id and wm.user_id = app_request_user_id() and wm.role = 'owner' and wm.status = 'active'
    )
);

create policy model_usage_select_policy on model_usage
for select
using (
    exists (
        select 1 from workspace_members wm
        where wm.workspace_id = model_usage.workspace_id and wm.user_id = app_request_user_id() and wm.role = 'owner' and wm.status = 'active'
    )
);

create policy connector_sync_states_select_policy on connector_sync_states
for select
using (
    exists (
        select 1 from workspace_members wm
        where wm.workspace_id = connector_sync_states.workspace_id and wm.user_id = app_request_user_id() and wm.role = 'owner' and wm.status = 'active'
    )
);

commit;
