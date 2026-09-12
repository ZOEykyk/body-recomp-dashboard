from __future__ import annotations

import unittest

from food_master_models import new_food_record
from scripts.validate_pr12 import FakeSupabaseClient
from supabase_food_master_repository import SupabaseFoodMasterRepository, SupabaseRepositoryError


class ReadbackFailureClient(FakeSupabaseClient):
    def __init__(self) -> None:
        super().__init__()
        self.upsert_completed = False

    def request(self, method: str, path: str, *, payload=None, prefer=None):
        if path.startswith("rpc/upsert_food_knowledge_v1"):
            result = super().request(method, path, payload=payload, prefer=prefer)
            self.upsert_completed = True
            return result
        if self.upsert_completed and method == "GET" and path.startswith("foods?"):
            raise SupabaseRepositoryError("temporary read-back failure")
        return super().request(method, path, payload=payload, prefer=prefer)


class SupabaseRepositoryResilienceTests(unittest.TestCase):
    def test_committed_upsert_survives_transient_verification_read_failure(self) -> None:
        client = ReadbackFailureClient()
        repository = SupabaseFoodMasterRepository(client)
        food = new_food_record(
            "cloud-user",
            {"canonical_name": "Hosted acceptance probe", "quantity": 1, "unit": "個"},
            now="2026-09-07T00:00:00+00:00",
        )

        stored = repository.upsert_food("cloud-user", food)

        self.assertTrue(client.upsert_completed)
        self.assertEqual(stored["food_id"], food["food_id"])
        self.assertEqual(repository.cache_revision(), 1)


if __name__ == "__main__":
    unittest.main()
