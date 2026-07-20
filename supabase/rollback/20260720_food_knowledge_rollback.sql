begin;

drop function if exists public.save_food_encounter_v1(text, jsonb, jsonb);
drop function if exists public.upsert_food_knowledge_v1(text, jsonb);
drop function if exists public.upsert_food_knowledge_internal(text, jsonb, boolean);
drop function if exists public.assert_food_knowledge_owner(text);
drop function if exists public.food_knowledge_schema_version_v1();
drop table if exists public.food_encounters;
drop table if exists public.nutrition_facts;
drop table if exists public.nutrition_sources;
drop table if exists public.food_aliases;
drop table if exists public.foods;
drop function if exists public.assert_food_encounter_owner();
drop function if exists public.set_food_knowledge_updated_at();

commit;
