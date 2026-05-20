create table if not exists voice_turns (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references workspaces(id) on delete cascade,
    conversation_id uuid not null references conversations(id) on delete cascade,
    user_message_id uuid not null references messages(id) on delete cascade,
    assistant_message_id uuid not null references messages(id) on delete cascade,
    input_audio_bucket text,
    input_audio_path text,
    output_audio_bucket text,
    output_audio_path text,
    transcript text not null,
    transcript_confidence double precision,
    input_duration_ms integer,
    output_duration_ms integer,
    stt_provider text not null,
    stt_model text not null,
    tts_provider text,
    tts_model text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists voice_turns_workspace_conversation_idx
    on voice_turns(workspace_id, conversation_id, created_at);

create index if not exists voice_turns_conversation_assistant_idx
    on voice_turns(conversation_id, assistant_message_id);

alter table voice_turns enable row level security;

drop policy if exists voice_turns_select_policy on voice_turns;
create policy voice_turns_select_policy
    on voice_turns
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = voice_turns.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists voice_turns_insert_policy on voice_turns;
create policy voice_turns_insert_policy
    on voice_turns
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = voice_turns.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists voice_turns_update_policy on voice_turns;
create policy voice_turns_update_policy
    on voice_turns
    for update
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = voice_turns.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists voice_turns_delete_policy on voice_turns;
create policy voice_turns_delete_policy
    on voice_turns
    for delete
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = voice_turns.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );
