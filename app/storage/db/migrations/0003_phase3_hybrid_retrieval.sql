alter table document_chunks
add column if not exists search_vector tsvector generated always as (
    to_tsvector('english', coalesce(content, ''))
) stored;

create index if not exists document_chunks_search_vector_idx
on document_chunks using gin (search_vector);
