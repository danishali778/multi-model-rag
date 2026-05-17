alter table model_usage
add column if not exists model_profile text not null default 'balanced';

alter table model_usage
add column if not exists details jsonb not null default '{}'::jsonb;
