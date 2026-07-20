-- Read-only PR12 production checks. Replace local-default when another stable owner is configured.

select public.food_knowledge_schema_version_v1() as schema_version;

select 'foods' as table_name, count(*) as row_count from public.foods
union all select 'food_aliases', count(*) from public.food_aliases
union all select 'nutrition_sources', count(*) from public.nutrition_sources
union all select 'nutrition_facts', count(*) from public.nutrition_facts
union all select 'food_encounters', count(*) from public.food_encounters
order by table_name;

select
  f.owner_user_id,
  count(distinct f.food_id) as foods,
  count(distinct a.alias_id) as aliases,
  count(distinct (s.food_id, s.source_id)) as nutrition_sources,
  count(distinct nf.nutrition_fact_id) as nutrition_facts
from public.foods f
left join public.food_aliases a on a.food_id = f.food_id and a.owner_user_id = f.owner_user_id
left join public.nutrition_sources s on s.food_id = f.food_id
left join public.nutrition_facts nf on nf.food_id = s.food_id and nf.source_id = s.source_id
where f.owner_user_id = 'local-default'
group by f.owner_user_id;

select owner_user_id, count(*) as encounters
from public.food_encounters
where owner_user_id = 'local-default'
group by owner_user_id;

-- Every query below must return zero rows.
select owner_user_id, idempotency_key, count(*)
from public.food_encounters
group by owner_user_id, idempotency_key
having count(*) > 1;

select owner_user_id, identity_key, count(*)
from public.foods
where scope = 'personal' and status <> 'archived'
group by owner_user_id, identity_key
having count(*) > 1;

select food_id, use_count, usage_count
from public.foods
where use_count <> usage_count;

select a.alias_id
from public.food_aliases a
left join public.foods f
  on f.food_id = a.food_id and f.owner_user_id = a.owner_user_id
where f.food_id is null;

select nf.nutrition_fact_id
from public.nutrition_facts nf
left join public.nutrition_sources s
  on s.food_id = nf.food_id and s.source_id = nf.source_id
where s.source_id is null;

select e.encounter_id
from public.food_encounters e
join public.foods f on f.food_id = e.resolved_food_id
where e.owner_user_id <> f.owner_user_id;

select relname, relrowsecurity
from pg_class
where relnamespace = 'public'::regnamespace
  and relname in ('foods', 'food_aliases', 'nutrition_sources', 'nutrition_facts', 'food_encounters')
order by relname;

select tablename, policyname, roles, cmd
from pg_policies
where schemaname = 'public'
  and tablename in ('foods', 'food_aliases', 'nutrition_sources', 'nutrition_facts', 'food_encounters')
order by tablename, policyname;

select tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename in ('foods', 'food_aliases', 'nutrition_sources', 'nutrition_facts', 'food_encounters')
order by tablename, indexname;
