create table if not exists audio_documents (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references workspaces(id) on delete cascade,
    document_id uuid not null unique references documents(id) on delete cascade,
    audio_bucket text,
    audio_path text,
    mime_type text not null,
    audio_format text not null,
    estimated_duration_ms integer,
    transcript_language text,
    transcription_provider text,
    transcription_model text,
    segment_count integer not null default 0,
    warning_count integer not null default 0,
    warnings jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists audio_documents_workspace_document_idx
    on audio_documents(workspace_id, document_id);

create index if not exists audio_documents_workspace_created_idx
    on audio_documents(workspace_id, created_at desc);

alter table audio_documents enable row level security;

drop policy if exists audio_documents_select_policy on audio_documents;
create policy audio_documents_select_policy
    on audio_documents
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = audio_documents.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists audio_documents_insert_policy on audio_documents;
create policy audio_documents_insert_policy
    on audio_documents
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = audio_documents.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists audio_documents_update_policy on audio_documents;
create policy audio_documents_update_policy
    on audio_documents
    for update
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = audio_documents.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists audio_documents_delete_policy on audio_documents;
create policy audio_documents_delete_policy
    on audio_documents
    for delete
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = audio_documents.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );
