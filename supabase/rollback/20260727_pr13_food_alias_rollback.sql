begin;

drop function if exists public.upsert_food_alias_v1(text, text, text, text, text, text, boolean);
drop index if exists public.food_aliases_owner_alias_uidx;

alter table public.food_aliases
  drop column if exists approved_by_user,
  drop column if exists ai_model,
  drop column if exists source;

create or replace function public.food_knowledge_schema_version_v1()
returns text
language sql
stable
as $$
  select '20260720.2'::text;
$$;

grant execute on function public.food_knowledge_schema_version_v1()
  to anon, authenticated, service_role;

commit;
