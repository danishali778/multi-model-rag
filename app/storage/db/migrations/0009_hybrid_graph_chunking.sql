create table if not exists document_structure_nodes (
    id uuid primary key,
    workspace_id uuid not null references workspaces(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    node_type text not null,
    node_key text not null,
    title text,
    section_path jsonb not null default '[]'::jsonb,
    level integer,
    page_start integer,
    page_end integer,
    block_order_start integer not null,
    block_order_end integer not null,
    parent_node_id uuid references document_structure_nodes(id) on delete cascade,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    unique (document_id, node_key)
);

create table if not exists document_structure_edges (
    id uuid primary key,
    workspace_id uuid not null references workspaces(id) on delete cascade,
    document_id uuid not null references documents(id) on delete cascade,
    from_node_id uuid not null references document_structure_nodes(id) on delete cascade,
    to_node_id uuid not null references document_structure_nodes(id) on delete cascade,
    edge_type text not null,
    edge_order integer not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

alter table document_chunks
    add column if not exists node_id uuid references document_structure_nodes(id) on delete set null,
    add column if not exists parent_node_id uuid references document_structure_nodes(id) on delete set null,
    add column if not exists previous_chunk_id uuid references document_chunks(id) on delete set null,
    add column if not exists next_chunk_id uuid references document_chunks(id) on delete set null,
    add column if not exists level integer,
    add column if not exists page_start integer,
    add column if not exists page_end integer,
    add column if not exists embedding_text text;

create index if not exists document_chunks_document_node_idx
    on document_chunks(document_id, node_id);

create index if not exists document_chunks_document_prev_chunk_idx
    on document_chunks(document_id, previous_chunk_id);

create index if not exists document_chunks_document_next_chunk_idx
    on document_chunks(document_id, next_chunk_id);

create index if not exists document_structure_nodes_document_parent_order_idx
    on document_structure_nodes(document_id, parent_node_id, block_order_start);

create index if not exists document_structure_nodes_section_path_gin
    on document_structure_nodes using gin(section_path);

create index if not exists document_structure_edges_document_from_type_idx
    on document_structure_edges(document_id, from_node_id, edge_type);

alter table document_structure_nodes enable row level security;
alter table document_structure_edges enable row level security;

drop policy if exists document_structure_nodes_select_policy on document_structure_nodes;
create policy document_structure_nodes_select_policy
    on document_structure_nodes
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_nodes.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_nodes_insert_policy on document_structure_nodes;
create policy document_structure_nodes_insert_policy
    on document_structure_nodes
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_nodes.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_nodes_update_policy on document_structure_nodes;
create policy document_structure_nodes_update_policy
    on document_structure_nodes
    for update
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_nodes.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_nodes_delete_policy on document_structure_nodes;
create policy document_structure_nodes_delete_policy
    on document_structure_nodes
    for delete
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_nodes.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_edges_select_policy on document_structure_edges;
create policy document_structure_edges_select_policy
    on document_structure_edges
    for select
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_edges.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_edges_insert_policy on document_structure_edges;
create policy document_structure_edges_insert_policy
    on document_structure_edges
    for insert
    with check (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_edges.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_edges_update_policy on document_structure_edges;
create policy document_structure_edges_update_policy
    on document_structure_edges
    for update
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_edges.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );

drop policy if exists document_structure_edges_delete_policy on document_structure_edges;
create policy document_structure_edges_delete_policy
    on document_structure_edges
    for delete
    using (
        exists (
            select 1
            from workspace_members wm
            where wm.workspace_id = document_structure_edges.workspace_id
              and wm.user_id = app_request_user_id()
        )
    );
