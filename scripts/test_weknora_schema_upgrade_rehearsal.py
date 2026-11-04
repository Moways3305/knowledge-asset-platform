"""Migration identity and protected-field checks; no Docker required."""

import unittest

import weknora_schema_upgrade_rehearsal as schema


class SchemaSafetyTests(unittest.TestCase):
    def test_manifest_is_order_independent_but_detects_changes(self):
        first = "a" * 64 + "  /app/migrations/versioned/000001_init.up.sql"
        second = "b" * 64 + "  /app/migrations/versioned/000002_more.up.sql"
        original = schema.manifest_digest(first + "\n" + second)
        self.assertEqual(original, schema.manifest_digest(second + "\n" + first))
        self.assertNotEqual(original, schema.manifest_digest(first))
        self.assertNotEqual(
            original, schema.manifest_digest(first + "\n" + second.replace("b" * 64, "c" * 64))
        )
        self.assertNotEqual(
            original, schema.manifest_digest(first + "\n" + second.replace("more", "renamed"))
        )

    def test_manifest_rejects_missing_malformed_or_duplicate_files(self):
        line = "a" * 64 + "  /app/migrations/versioned/000001_init.up.sql"
        for text in ["", "not-a-hash file.sql", line + "\n" + line, line.replace(".sql", ".txt")]:
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                schema.manifest_digest(text)

    def test_protection_retains_sensitive_model_and_identity_columns(self):
        columns = ["id", "parameters", "updated_at", "deleted_at", 'odd"name']
        projected = schema.projection("models", columns)
        for column in columns:
            self.assertIn(schema.pg.ident(column), projected)

    def test_only_documented_migration_changes_are_exempted(self):
        self.assertEqual(
            schema.projection("chunks", ["id", "content", "updated_at", "deleted_at"]),
            '"id","content"',
        )
        projected = schema.projection("knowledges", ["id", "file_name", "file_path", "updated_at"])
        self.assertIn("regexp_replace(file_name, '^.*/', '') AS file_name", projected)
        self.assertIn('"file_path"', projected)
        self.assertIn('"updated_at"', projected)


if __name__ == "__main__":
    unittest.main()
