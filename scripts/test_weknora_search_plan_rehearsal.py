import json
import unittest

from weknora_search_plan_rehearsal import (
    disabled_question_ids,
    literal,
    plan_summary,
    query,
    query_parts,
    retrieval_limit,
    statements,
)


class SearchPlanTests(unittest.TestCase):
    def test_plan_report_does_not_expose_conditions_identifiers_or_content(self):
        value = [
            {
                "Plan": {
                    "Node Type": "Limit",
                    "Filter": "SECRET content",
                    "Plans": [
                        {
                            "Node Type": "Custom Scan",
                            "Custom Plan Provider": "ParadeDB Scan",
                            "Index Name": "secret_index",
                            "Workers Planned": 2,
                        }
                    ],
                }
            }
        ]
        summary = plan_summary(value)
        self.assertEqual(summary["nodes"], ["Custom Scan", "Limit"])
        self.assertEqual(summary["custom_providers"], ["ParadeDB"])
        self.assertTrue(summary["parallel"])
        self.assertNotIn("secret", json.dumps(summary).lower())
        self.assertNotIn("content", json.dumps(summary))

    def test_unknown_plan_fields_and_provider_text_are_not_returned(self):
        self.assertEqual(
            plan_summary({"Node Type": "SECRET", "Custom Plan Provider": "secret value"}),
            {"nodes": [], "custom_providers": [], "parallel": False},
        )

    def test_scope_values_are_escaped_even_with_nonstandard_string_settings(self):
        self.assertEqual(literal("a\\b'c"), "E'a\\\\b''c'")
        sql = query(["fixture-one", "fixture-two"])
        self.assertIn("\"knowledge_base_id\" IN (E'fixture-one',E'fixture-two')", sql)
        self.assertTrue(sql.startswith("SELECT "))
        self.assertTrue(sql.endswith("LIMIT 20"))

    def test_question_exclusion_matches_upstream_faq_and_nil_semantics(self):
        libraries = [
            {"id": "nil", "type": "document", "question_generation_config": None},
            {"id": "off", "type": "document", "question_generation_config": {"enabled": False}},
            {"id": "on", "type": "document", "question_generation_config": {"enabled": True}},
            {"id": "faq", "type": "faq", "question_generation_config": None},
        ]
        self.assertEqual(disabled_question_ids(libraries), ["nil", "off"])
        sql, _ = query_parts(["nil", "on"], ["nil"], 500)
        self.assertIn("NOT (knowledge_base_id IN (E'nil') AND source_type = 0", sql)
        self.assertIn("chunk_id <> '' AND source_id <> chunk_id", sql)
        self.assertIn("substr(source_id, 1, length(chunk_id) + 1) = chunk_id || '-'", sql)
        self.assertTrue(sql.endswith("LIMIT 500"))

    def test_retrieval_depth_uses_tenant_default_request_floor_and_pool_cap(self):
        self.assertEqual(retrieval_limit(None, 1), 250)
        self.assertEqual(retrieval_limit({"embedding_top_k": 0}, 2), 500)
        self.assertEqual(retrieval_limit({"embedding_top_k": -1}, 1), 250)
        self.assertEqual(retrieval_limit({"embedding_top_k": 1}, 1), 50)
        self.assertEqual(retrieval_limit({"embedding_top_k": 12}, 2), 120)
        self.assertEqual(retrieval_limit({"embedding_top_k": 1000000}, 13), 500)

    def test_prepared_parameters_include_scope_query_enabled_exclusions_and_limit(self):
        ids = ["a\\b'c", "two"]
        sql, values = query_parts(ids, [ids[0]], 120, True)
        self.assertNotIn(ids[0], sql)
        self.assertIn('"knowledge_base_id" IN ($1,$2)', sql)
        self.assertIn("content ||| $3", sql)
        self.assertIn("is_enabled = $4", sql)
        self.assertIn("NOT (knowledge_base_id IN ($5)", sql)
        self.assertTrue(sql.endswith("LIMIT $6"))
        self.assertEqual(values, [*ids, "项目", True, ids[0], 120])
        setup, execute = statements(ids, [ids[0]], 120, True)
        self.assertEqual(setup, "PREPARE kap_search_probe AS " + sql + "; ")
        self.assertIn(literal(ids[0]), execute)
        self.assertTrue(execute.endswith(",120)"))
        self.assertNotIn("$", execute)

    def test_rejects_unbounded_or_cross_scope_search(self):
        for ids, excluded, limit in [([], [], 20), (["a"], ["b"], 20), (["a"], [], 501)]:
            with self.assertRaises(RuntimeError):
                query_parts(ids, excluded, limit)
        with self.assertRaises(RuntimeError):
            retrieval_limit(None, 0)


if __name__ == "__main__":
    unittest.main()
