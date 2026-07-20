begin;

create table if not exists public.foods (
  food_id text primary key check (btrim(food_id) <> ''),
  owner_user_id text not null check (btrim(owner_user_id) <> ''),
  scope text not null default 'personal' check (scope in ('personal', 'official', 'shared')),
  brand text,
  canonical_name text not null check (btrim(canonical_name) <> ''),
  variant text,
  size text,
  identity_key text not null check (btrim(identity_key) <> ''),
  category text,
  default_quantity numeric check (default_quantity is null or default_quantity > 0),
  default_unit text,
  notes text,
  status text not null default 'candidate' check (status in ('candidate', 'active', 'archived')),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'reviewed', 'rejected')),
  use_count bigint not null default 0 check (use_count >= 0),
  usage_count bigint not null default 0 check (usage_count >= 0),
  first_used_at timestamptz,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  schema_version text not null default '1.1' check (btrim(schema_version) <> ''),
  created_by text,
  updated_by text,
  unique (food_id, owner_user_id),
  check (use_count = usage_count),
  check (last_used_at is null or first_used_at is null or last_used_at >= first_used_at)
);

create table if not exists public.food_aliases (
  alias_id text primary key check (btrim(alias_id) <> ''),
  food_id text not null,
  owner_user_id text not null check (btrim(owner_user_id) <> ''),
  alias text not null check (btrim(alias) <> ''),
  normalized_alias text not null check (btrim(normalized_alias) <> ''),
  language text,
  confidence text check (confidence is null or confidence in ('high', 'medium', 'low')),
  review_status text not null default 'pending_review' check (review_status in ('pending_review', 'reviewed', 'rejected')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (food_id, normalized_alias),
  foreign key (food_id, owner_user_id)
    references public.foods(food_id, owner_user_id) on delete cascade
);

create table if not exists public.nutrition_sources (
  source_id text not null check (btrim(source_id) <> ''),
  food_id text not null references public.foods(food_id) on delete cascade,
  source_type text not null check (btrim(source_type) <> ''),
  publisher text,
  source_ref text,
  captured_at timestamptz,
  verified_at timestamptz,
  valid_from date,
  valid_to date,
  product_version text,
  reviewer text,
  verification_status text not null default 'pending_review'
    check (verification_status in ('verified', 'pending_review', 'rejected', 'expired', 'superseded')),
  confidence text check (confidence is null or confidence in ('high', 'medium', 'low')),
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (food_id, source_id),
  check (valid_to is null or valid_from is null or valid_to >= valid_from)
);

create table if not exists public.nutrition_facts (
  nutrition_fact_id text primary key check (btrim(nutrition_fact_id) <> ''),
  source_id text not null,
  food_id text not null,
  basis text not null check (basis in ('per_item', 'per_package', 'per_serving', 'per_100g', 'per_100ml', 'total', 'unknown')),
  serving_quantity numeric check (serving_quantity is null or serving_quantity > 0),
  serving_unit text,
  calories_kcal numeric check (calories_kcal is null or calories_kcal >= 0),
  protein_g numeric check (protein_g is null or protein_g >= 0),
  fat_g numeric check (fat_g is null or fat_g >= 0),
  carbs_g numeric check (carbs_g is null or carbs_g >= 0),
  sugar_g numeric check (sugar_g is null or sugar_g >= 0),
  fiber_g numeric check (fiber_g is null or fiber_g >= 0),
  salt_g numeric check (salt_g is null or salt_g >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (food_id, source_id, basis, serving_quantity, serving_unit),
  foreign key (food_id, source_id)
    references public.nutrition_sources(food_id, source_id) on delete cascade
);

create table if not exists public.food_encounters (
  encounter_id text primary key check (btrim(encounter_id) <> ''),
  idempotency_key text not null check (btrim(idempotency_key) <> ''),
  owner_user_id text not null check (btrim(owner_user_id) <> ''),
  record_date date not null,
  occurred_at timestamptz,
  meal_type text not null check (btrim(meal_type) <> ''),
  original_text text,
  original_fragment text not null check (btrim(original_fragment) <> ''),
  parsed_identity jsonb not null default '{}'::jsonb check (jsonb_typeof(parsed_identity) = 'object'),
  resolved_food_id text references public.foods(food_id) on delete set null,
  resolution_status text,
  selected_source_type text,
  selected_source_id text,
  selected_nutrition jsonb check (selected_nutrition is null or jsonb_typeof(selected_nutrition) = 'object'),
  resolution_origin text,
  resolution_confidence text,
  quantity numeric check (quantity is null or quantity > 0),
  unit text,
  parser_version text,
  lookup_version text,
  source_policy_version text,
  resolver_version text,
  needs_review boolean not null default false,
  candidate_reason text,
  created_at timestamptz not null default now(),
  schema_version text not null default '1.1' check (btrim(schema_version) <> ''),
  unique (owner_user_id, idempotency_key)
);

create unique index if not exists foods_personal_identity_active_uidx
  on public.foods(owner_user_id, identity_key)
  where scope = 'personal' and status <> 'archived';
create index if not exists foods_owner_status_idx on public.foods(owner_user_id, status);
create index if not exists foods_owner_usage_idx on public.foods(owner_user_id, usage_count desc, last_used_at desc);
create index if not exists foods_owner_updated_idx on public.foods(owner_user_id, updated_at desc);
create index if not exists food_aliases_owner_normalized_idx on public.food_aliases(owner_user_id, normalized_alias);
create index if not exists food_encounters_owner_date_idx on public.food_encounters(owner_user_id, record_date desc);
create index if not exists food_encounters_food_idx on public.food_encounters(resolved_food_id);

create or replace function public.set_food_knowledge_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.assert_food_encounter_owner()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.resolved_food_id is not null and not exists (
    select 1 from public.foods
    where food_id = new.resolved_food_id
      and owner_user_id = new.owner_user_id
  ) then
    raise exception 'Encounter resolved food owner mismatch';
  end if;
  return new;
end;
$$;

drop trigger if exists foods_set_updated_at on public.foods;
create trigger foods_set_updated_at before update on public.foods
for each row execute function public.set_food_knowledge_updated_at();
drop trigger if exists food_aliases_set_updated_at on public.food_aliases;
create trigger food_aliases_set_updated_at before update on public.food_aliases
for each row execute function public.set_food_knowledge_updated_at();
drop trigger if exists nutrition_sources_set_updated_at on public.nutrition_sources;
create trigger nutrition_sources_set_updated_at before update on public.nutrition_sources
for each row execute function public.set_food_knowledge_updated_at();
drop trigger if exists nutrition_facts_set_updated_at on public.nutrition_facts;
create trigger nutrition_facts_set_updated_at before update on public.nutrition_facts
for each row execute function public.set_food_knowledge_updated_at();
drop trigger if exists food_encounters_assert_owner on public.food_encounters;
create trigger food_encounters_assert_owner before insert or update on public.food_encounters
for each row execute function public.assert_food_encounter_owner();

create or replace function public.assert_food_knowledge_owner(p_owner_user_id text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if p_owner_user_id is null or btrim(p_owner_user_id) = '' then
    raise exception 'owner_user_id is required';
  end if;
  if auth.role() <> 'service_role' and coalesce(auth.uid()::text, '') <> p_owner_user_id then
    raise exception 'Food Knowledge owner mismatch';
  end if;
end;
$$;

create or replace function public.upsert_food_knowledge_internal(
  p_owner_user_id text,
  p_food_payload jsonb,
  p_increment_usage boolean default false
)
returns public.foods
language plpgsql
security definer
set search_path = public
as $$
declare
  v_food jsonb := p_food_payload -> 'food';
  v_alias jsonb;
  v_source jsonb;
  v_fact jsonb;
  v_row public.foods;
  v_existing_id text;
  v_now timestamptz := now();
begin
  perform public.assert_food_knowledge_owner(p_owner_user_id);
  if coalesce(v_food ->> 'food_id', '') = '' then
    raise exception 'food_id is required';
  end if;
  if coalesce(v_food ->> 'canonical_name', '') = '' then
    raise exception 'canonical_name is required';
  end if;
  if coalesce(v_food ->> 'identity_key', '') = '' then
    raise exception 'identity_key is required';
  end if;
  if auth.role() <> 'service_role' and coalesce(v_food ->> 'scope', 'personal') <> 'personal' then
    raise exception 'Only service role may write shared Food Knowledge';
  end if;
  if exists (
    select 1 from public.foods
    where food_id = v_food ->> 'food_id'
      and owner_user_id <> p_owner_user_id
  ) then
    raise exception 'food_id belongs to another owner';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_owner_user_id || '|' || coalesce(v_food ->> 'identity_key', ''), 0));
  select food_id into v_existing_id
  from public.foods
  where owner_user_id = p_owner_user_id
    and identity_key = coalesce(v_food ->> 'identity_key', '')
    and scope = 'personal'
    and status <> 'archived'
  limit 1;
  if found and v_existing_id <> v_food ->> 'food_id' then
    v_food := jsonb_set(v_food, '{food_id}', to_jsonb(v_existing_id));
  end if;

  insert into public.foods (
    food_id, owner_user_id, scope, brand, canonical_name, variant, size, identity_key,
    category, default_quantity, default_unit, notes, status, review_status,
    use_count, usage_count, first_used_at, last_used_at, created_at, updated_at,
    schema_version, created_by, updated_by
  ) values (
    v_food ->> 'food_id', p_owner_user_id, coalesce(v_food ->> 'scope', 'personal'),
    v_food ->> 'brand', v_food ->> 'canonical_name', v_food ->> 'variant', v_food ->> 'size',
    coalesce(v_food ->> 'identity_key', ''), v_food ->> 'category',
    nullif(v_food ->> 'default_quantity', '')::numeric, v_food ->> 'default_unit', v_food ->> 'notes',
    coalesce(v_food ->> 'status', 'candidate'), coalesce(v_food ->> 'review_status', 'pending_review'),
    case when p_increment_usage then 1 else coalesce((v_food ->> 'use_count')::bigint, 0) end,
    case when p_increment_usage then 1 else coalesce((v_food ->> 'usage_count')::bigint, 0) end,
    case when p_increment_usage then coalesce(nullif(v_food ->> 'first_used_at', '')::timestamptz, v_now) else nullif(v_food ->> 'first_used_at', '')::timestamptz end,
    nullif(v_food ->> 'last_used_at', '')::timestamptz,
    coalesce(nullif(v_food ->> 'created_at', '')::timestamptz, v_now), v_now,
    coalesce(v_food ->> 'schema_version', '1.1'), v_food ->> 'created_by', v_food ->> 'updated_by'
  )
  on conflict (food_id) do update set
    brand = excluded.brand,
    canonical_name = excluded.canonical_name,
    variant = excluded.variant,
    size = excluded.size,
    identity_key = excluded.identity_key,
    category = excluded.category,
    default_quantity = excluded.default_quantity,
    default_unit = excluded.default_unit,
    notes = excluded.notes,
    status = excluded.status,
    review_status = excluded.review_status,
    use_count = case when p_increment_usage then public.foods.use_count + 1 else excluded.use_count end,
    usage_count = case when p_increment_usage then public.foods.usage_count + 1 else excluded.usage_count end,
    first_used_at = coalesce(public.foods.first_used_at, excluded.first_used_at),
    last_used_at = case when p_increment_usage then excluded.last_used_at else coalesce(excluded.last_used_at, public.foods.last_used_at) end,
    schema_version = excluded.schema_version,
    updated_by = excluded.updated_by,
    updated_at = v_now
  returning * into v_row;

  for v_alias in select value from jsonb_array_elements(coalesce(p_food_payload -> 'aliases', '[]'::jsonb)) loop
    if coalesce(v_alias ->> 'normalized_alias', '') <> '' then
      insert into public.food_aliases (
        alias_id, food_id, owner_user_id, alias, normalized_alias, language, confidence, review_status
      ) values (
        'alias_' || md5(p_owner_user_id || '|' || v_row.food_id || '|' || (v_alias ->> 'normalized_alias')),
        v_row.food_id, p_owner_user_id, v_alias ->> 'alias', v_alias ->> 'normalized_alias',
        v_alias ->> 'language', v_alias ->> 'confidence', coalesce(v_alias ->> 'review_status', 'pending_review')
      ) on conflict (food_id, normalized_alias) do update set
        alias = excluded.alias,
        confidence = excluded.confidence,
        review_status = excluded.review_status;
    end if;
  end loop;

  for v_source in select value from jsonb_array_elements(coalesce(p_food_payload -> 'nutrition_sources', '[]'::jsonb)) loop
    if coalesce(v_source ->> 'source_id', '') = '' or coalesce(v_source ->> 'source_type', '') = '' then
      raise exception 'nutrition source_id and source_type are required';
    end if;
    insert into public.nutrition_sources (
      source_id, food_id, source_type, publisher, source_ref, captured_at, verified_at,
      valid_from, valid_to, product_version, reviewer, verification_status, confidence, notes
    ) values (
      v_source ->> 'source_id', v_row.food_id, v_source ->> 'source_type', v_source ->> 'publisher',
      v_source ->> 'source_ref', nullif(v_source ->> 'captured_at', '')::timestamptz,
      nullif(v_source ->> 'verified_at', '')::timestamptz, nullif(v_source ->> 'valid_from', '')::date,
      nullif(v_source ->> 'valid_to', '')::date, v_source ->> 'product_version', v_source ->> 'reviewer',
      coalesce(v_source ->> 'verification_status', 'pending_review'), v_source ->> 'confidence', v_source ->> 'notes'
    ) on conflict (food_id, source_id) do update set
      source_type = excluded.source_type,
      publisher = excluded.publisher,
      source_ref = excluded.source_ref,
      captured_at = excluded.captured_at,
      verified_at = excluded.verified_at,
      valid_from = excluded.valid_from,
      valid_to = excluded.valid_to,
      product_version = excluded.product_version,
      reviewer = excluded.reviewer,
      verification_status = excluded.verification_status,
      confidence = excluded.confidence,
      notes = excluded.notes;
  end loop;

  for v_fact in select value from jsonb_array_elements(coalesce(p_food_payload -> 'nutrition_facts', '[]'::jsonb)) loop
    if not exists (
      select 1 from public.nutrition_sources
      where source_id = v_fact ->> 'source_id'
        and food_id = v_row.food_id
    ) then
      raise exception 'nutrition fact source does not belong to food';
    end if;
    insert into public.nutrition_facts (
      nutrition_fact_id, source_id, food_id, basis, serving_quantity, serving_unit,
      calories_kcal, protein_g, fat_g, carbs_g, sugar_g, fiber_g, salt_g
    ) values (
      'nf_' || md5(v_row.food_id || '|' || (v_fact ->> 'source_id') || '|' || coalesce(v_fact ->> 'basis', 'unknown') || '|' || coalesce(v_fact ->> 'serving_quantity', '') || '|' || coalesce(v_fact ->> 'serving_unit', '')),
      v_fact ->> 'source_id', v_row.food_id, coalesce(v_fact ->> 'basis', 'unknown'),
      nullif(v_fact ->> 'serving_quantity', '')::numeric, v_fact ->> 'serving_unit',
      nullif(v_fact ->> 'calories_kcal', '')::numeric, nullif(v_fact ->> 'protein_g', '')::numeric,
      nullif(v_fact ->> 'fat_g', '')::numeric, nullif(v_fact ->> 'carbs_g', '')::numeric,
      nullif(v_fact ->> 'sugar_g', '')::numeric, nullif(v_fact ->> 'fiber_g', '')::numeric,
      nullif(v_fact ->> 'salt_g', '')::numeric
    ) on conflict (nutrition_fact_id) do update set
      basis = excluded.basis,
      serving_quantity = excluded.serving_quantity,
      serving_unit = excluded.serving_unit,
      calories_kcal = excluded.calories_kcal,
      protein_g = excluded.protein_g,
      fat_g = excluded.fat_g,
      carbs_g = excluded.carbs_g,
      sugar_g = excluded.sugar_g,
      fiber_g = excluded.fiber_g,
      salt_g = excluded.salt_g;
  end loop;

  return v_row;
end;
$$;

create or replace function public.upsert_food_knowledge_v1(p_owner_user_id text, p_food_payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_food public.foods;
begin
  select * into v_food from public.upsert_food_knowledge_internal(p_owner_user_id, p_food_payload, false);
  return jsonb_build_object('food', to_jsonb(v_food));
end;
$$;

create or replace function public.save_food_encounter_v1(
  p_owner_user_id text,
  p_food_payload jsonb,
  p_encounter jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_food public.foods;
  v_encounter public.food_encounters;
  v_inserted boolean := false;
begin
  perform public.assert_food_knowledge_owner(p_owner_user_id);

  if coalesce(p_encounter ->> 'encounter_id', '') = '' then
    raise exception 'encounter_id is required';
  end if;
  if coalesce(p_encounter ->> 'idempotency_key', '') = '' then
    raise exception 'idempotency_key is required';
  end if;
  if coalesce(p_encounter ->> 'record_date', '') = '' then
    raise exception 'record_date is required';
  end if;
  if coalesce(p_encounter ->> 'meal_type', '') = '' then
    raise exception 'meal_type is required';
  end if;
  if coalesce(p_encounter ->> 'original_fragment', '') = '' then
    raise exception 'original_fragment is required';
  end if;

  perform pg_advisory_xact_lock(
    hashtextextended(p_owner_user_id || '|' || (p_encounter ->> 'idempotency_key'), 1)
  );

  select * into v_encounter
  from public.food_encounters
  where owner_user_id = p_owner_user_id
    and idempotency_key = p_encounter ->> 'idempotency_key';

  if found then
    select * into v_food from public.foods where food_id = v_encounter.resolved_food_id;
    return jsonb_build_object('inserted', false, 'food', to_jsonb(v_food), 'encounter', to_jsonb(v_encounter));
  end if;

  select * into v_food from public.upsert_food_knowledge_internal(p_owner_user_id, p_food_payload, true);

  insert into public.food_encounters (
    encounter_id, idempotency_key, owner_user_id, record_date, occurred_at, meal_type,
    original_text, original_fragment, parsed_identity, resolved_food_id, resolution_status,
    selected_source_type, selected_source_id, selected_nutrition, resolution_origin,
    resolution_confidence, quantity, unit, parser_version, lookup_version,
    source_policy_version, resolver_version, needs_review, candidate_reason, created_at, schema_version
  ) values (
    p_encounter ->> 'encounter_id', p_encounter ->> 'idempotency_key', p_owner_user_id,
    (p_encounter ->> 'record_date')::date, nullif(p_encounter ->> 'occurred_at', '')::timestamptz,
    p_encounter ->> 'meal_type', p_encounter ->> 'original_text', p_encounter ->> 'original_fragment',
    coalesce(p_encounter -> 'parsed_identity', '{}'::jsonb), v_food.food_id,
    p_encounter ->> 'resolution_status', p_encounter ->> 'selected_source_type',
    p_encounter ->> 'selected_source_id', p_encounter -> 'selected_nutrition',
    p_encounter ->> 'resolution_origin', p_encounter ->> 'resolution_confidence',
    nullif(p_encounter ->> 'quantity', '')::numeric, p_encounter ->> 'unit',
    p_encounter ->> 'parser_version', p_encounter ->> 'lookup_version',
    p_encounter ->> 'source_policy_version', p_encounter ->> 'resolver_version',
    coalesce((p_encounter ->> 'needs_review')::boolean, false), p_encounter ->> 'candidate_reason',
    coalesce(nullif(p_encounter ->> 'created_at', '')::timestamptz, now()),
    coalesce(p_encounter ->> 'schema_version', '1.1')
  )
  on conflict (owner_user_id, idempotency_key) do nothing
  returning * into v_encounter;

  if not found then
    raise exception 'Encounter idempotency conflict occurred during transaction';
  end if;
  v_inserted := true;
  return jsonb_build_object('inserted', v_inserted, 'food', to_jsonb(v_food), 'encounter', to_jsonb(v_encounter));
end;
$$;

create or replace function public.food_knowledge_schema_version_v1()
returns text
language sql
stable
set search_path = public
as $$
  select '20260720.2'::text;
$$;

alter table public.foods enable row level security;
alter table public.food_aliases enable row level security;
alter table public.nutrition_sources enable row level security;
alter table public.nutrition_facts enable row level security;
alter table public.food_encounters enable row level security;

drop policy if exists foods_owner_all on public.foods;
drop policy if exists foods_owner_select on public.foods;
create policy foods_owner_select on public.foods for select to authenticated
using (owner_user_id = auth.uid()::text);
drop policy if exists foods_shared_read on public.foods;
create policy foods_shared_read on public.foods for select to anon, authenticated
using (scope in ('official', 'shared'));

drop policy if exists food_aliases_owner_all on public.food_aliases;
drop policy if exists food_aliases_owner_select on public.food_aliases;
create policy food_aliases_owner_select on public.food_aliases for select to authenticated
using (owner_user_id = auth.uid()::text);
drop policy if exists food_aliases_shared_read on public.food_aliases;
create policy food_aliases_shared_read on public.food_aliases for select to anon, authenticated
using (exists (select 1 from public.foods f where f.food_id = food_aliases.food_id and f.scope in ('official', 'shared')));

drop policy if exists nutrition_sources_visible on public.nutrition_sources;
create policy nutrition_sources_visible on public.nutrition_sources for select to anon, authenticated
using (exists (
  select 1 from public.foods f
  where f.food_id = nutrition_sources.food_id
    and (f.scope in ('official', 'shared') or f.owner_user_id = auth.uid()::text)
));
drop policy if exists nutrition_sources_owner_write on public.nutrition_sources;

drop policy if exists nutrition_facts_visible on public.nutrition_facts;
create policy nutrition_facts_visible on public.nutrition_facts for select to anon, authenticated
using (exists (
  select 1 from public.foods f
  where f.food_id = nutrition_facts.food_id
    and (f.scope in ('official', 'shared') or f.owner_user_id = auth.uid()::text)
));
drop policy if exists nutrition_facts_owner_write on public.nutrition_facts;

drop policy if exists food_encounters_owner_all on public.food_encounters;
drop policy if exists food_encounters_owner_select on public.food_encounters;
create policy food_encounters_owner_select on public.food_encounters for select to authenticated
using (owner_user_id = auth.uid()::text);

grant select on public.foods, public.food_aliases, public.nutrition_sources, public.nutrition_facts
  to anon, authenticated;
grant select on public.food_encounters to authenticated;
revoke insert, update, delete on public.foods, public.food_aliases, public.nutrition_sources,
  public.nutrition_facts, public.food_encounters from anon, authenticated;
grant select, insert, update, delete on public.foods, public.food_aliases, public.nutrition_sources,
  public.nutrition_facts, public.food_encounters to service_role;

revoke all on function public.assert_food_knowledge_owner(text) from public, anon, authenticated;
revoke all on function public.upsert_food_knowledge_internal(text, jsonb, boolean) from public, anon, authenticated;
revoke all on function public.upsert_food_knowledge_v1(text, jsonb) from public, anon;
revoke all on function public.save_food_encounter_v1(text, jsonb, jsonb) from public, anon;
revoke all on function public.food_knowledge_schema_version_v1() from public;
grant execute on function public.upsert_food_knowledge_v1(text, jsonb) to authenticated, service_role;
grant execute on function public.save_food_encounter_v1(text, jsonb, jsonb) to authenticated, service_role;
grant execute on function public.food_knowledge_schema_version_v1() to anon, authenticated, service_role;

commit;
