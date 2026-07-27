begin;

alter table public.food_aliases
  add column if not exists source text not null default 'legacy',
  add column if not exists ai_model text,
  add column if not exists approved_by_user boolean not null default false;

update public.food_aliases
set approved_by_user = true
where review_status = 'reviewed';

do $$
begin
  if exists (
    select 1
    from public.food_aliases
    group by owner_user_id, normalized_alias
    having count(distinct food_id) > 1
  ) then
    raise exception 'Duplicate owner alias identities must be reviewed before PR13 migration';
  end if;
end;
$$;

create unique index if not exists food_aliases_owner_alias_uidx
  on public.food_aliases(owner_user_id, normalized_alias);

create or replace function public.upsert_food_alias_v1(
  p_owner_user_id text,
  p_food_id text,
  p_alias text,
  p_normalized_alias text,
  p_source text default 'manual',
  p_ai_model text default null,
  p_approved_by_user boolean default false
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.food_aliases%rowtype;
begin
  perform public.assert_food_knowledge_owner(p_owner_user_id);
  if btrim(coalesce(p_alias, '')) = '' or btrim(coalesce(p_normalized_alias, '')) = '' then
    raise exception 'alias and normalized_alias are required';
  end if;
  if not p_approved_by_user then
    raise exception 'alias must be approved before persistence';
  end if;
  if not exists (
    select 1 from public.foods
    where food_id = p_food_id and owner_user_id = p_owner_user_id and status <> 'archived'
  ) then
    raise exception 'food not found';
  end if;

  insert into public.food_aliases (
    alias_id,
    food_id,
    owner_user_id,
    alias,
    normalized_alias,
    language,
    confidence,
    review_status,
    source,
    ai_model,
    approved_by_user
  ) values (
    'alias_' || md5(p_owner_user_id || '|' || p_food_id || '|' || p_normalized_alias),
    p_food_id,
    p_owner_user_id,
    btrim(p_alias),
    btrim(p_normalized_alias),
    'ja',
    'high',
    'reviewed',
    coalesce(nullif(btrim(p_source), ''), 'manual'),
    nullif(btrim(coalesce(p_ai_model, '')), ''),
    true
  )
  on conflict (owner_user_id, normalized_alias) do update set
    alias = excluded.alias,
    source = excluded.source,
    ai_model = excluded.ai_model,
    approved_by_user = true,
    review_status = 'reviewed',
    updated_at = now()
  where public.food_aliases.food_id = excluded.food_id
  returning * into v_row;

  if v_row.alias_id is null then
    raise exception 'alias is already assigned to another food';
  end if;
  return to_jsonb(v_row);
end;
$$;

create or replace function public.food_knowledge_schema_version_v1()
returns text
language sql
stable
as $$
  select '20260727.1'::text;
$$;

revoke all on function public.upsert_food_alias_v1(text, text, text, text, text, text, boolean)
  from public, anon;
grant execute on function public.upsert_food_alias_v1(text, text, text, text, text, text, boolean)
  to authenticated, service_role;
grant execute on function public.food_knowledge_schema_version_v1()
  to anon, authenticated, service_role;

commit;
