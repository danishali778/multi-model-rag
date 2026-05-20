create table if not exists document_blocks (
    id uuid primary key,
    workspace_id uuid not null references workspaces(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    block_type text not null,
    text text not null,
    page_number integer,
    heading_level integer,
    section_title text,
    subsection_title text,
    section_path jsonb not null default '[]'::jsonb,
    order_index integer not null,
    parent_block_id uuid references document_blocks(id) on delete cascade,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

alter table document_chunks
    add column if not exists parent_block_id uuid references document_blocks(id) on delete set null,
    add column if not exists chunk_role text not null default 'child',
    add column if not exists page_number integer,
    add column if not exists chunk_type text,
    add column if not exists section_title text,
    add column if not exists subsection_title text,
    add column if not exists section_path jsonb not null default '[]'::jsonb,
    add column if not exists block_order_start integer,
    add column if not exists block_order_end integer;

create index if not exists document_blocks_workspace_document_order_idx
    on document_blocks(workspace_id, document_id, order_index);

create index if not exists document_blocks_document_parent_idx
    on document_blocks(document_id, parent_block_id);

create index if not exists document_chunks_role_parent_idx
    on document_chunks(chunk_role, parent_block_id);

create index if not exists document_chunks_document_role_idx
    on document_chunks(document_id, chunk_role);

create index if not exists document_chunks_section_path_gin
    on document_chunks using gin(section_path);

alter table document_blocks enable row level security;

drop policy if exists document_blocks_select_policy on document_blocks;
create policy document_blocks_select_policy
    on document_blocks
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_blocks.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_blocks_insert_policy on document_blocks;
create policy document_blocks_insert_policy
    on document_blocks
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_blocks.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_blocks_update_policy on document_blocks;
create policy document_blocks_update_policy
    on document_blocks
    for update
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_blocks.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_blocks_delete_policy on document_blocks;
create policy document_blocks_delete_policy
    on document_blocks
    for delete
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_blocks.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );
