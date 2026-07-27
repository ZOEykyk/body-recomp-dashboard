-- Run after 20260720_food_knowledge.sql and 20260727_pr13_food_alias.sql.

select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'food_aliases'
  and column_name in ('source', 'ai_model', 'approved_by_user')
order by column_name;

select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and indexname = 'food_aliases_owner_alias_uidx';

select routine_name
from information_schema.routines
where routine_schema = 'public'
  and routine_name = 'upsert_food_alias_v1';

select public.food_knowledge_schema_version_v1() as schema_version;

select owner_user_id, normalized_alias, count(distinct food_id) as food_count
from public.food_aliases
group by owner_user_id, normalized_alias
having count(distinct food_id) > 1;

select count(*) as unapproved_reviewed_aliases
from public.food_aliases
where review_status = 'reviewed'
  and approved_by_user is not true;
