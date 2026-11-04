import json
import unittest

from weknora_search_plan_rehearsal import literal, plan_summary, query


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
        self.assertIn("knowledge_base_id IN (E'fixture-one',E'fixture-two')", sql)
        self.assertTrue(sql.startswith("SELECT "))
        self.assertTrue(sql.endswith("LIMIT 20"))


if __name__ == "__main__":
    unittest.main()
