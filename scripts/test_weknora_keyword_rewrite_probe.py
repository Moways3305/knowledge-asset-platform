import json
import re
import sqlite3
import unittest

from weknora_keyword_rewrite_probe import REFERENCE_CAP, build_sql, compare_results


class KeywordRewriteTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE embeddings (id integer,score real,content text,source_id text,"
            "source_type integer,chunk_id text,knowledge_id text,knowledge_base_id text,"
            "tag_id text,is_enabled boolean)"
        )
        # Many high-score generated questions would exhaust an early LIMIT.
        rows = [
            (i, 1000 - i, "needle", f"c{i}-q", 0, f"c{i}", "doc", "kb", "tag", True)
            for i in range(1, 31)
        ]
        rows += [
            (31, 9, "needle", "body", 0, "body", "doc", "kb", "tag", True),
            (32, 8, "needle", "body2", 0, "body2", "doc", "kb", "tag", None),
            (33, 8, "needle", "faq-q", 0, "faq", "doc", "faq", "tag", True),
            (34, 7, "needle", "body3", 0, "body3", "doc", "kb", "tag", True),
            (35, 100, "needle", "off", 0, "off", "doc", "kb", "tag", False),
            (36, 100, "needle", "other", 0, "other", "doc", "other-kb", "tag", True),
            (37, 100, "needle", "other-doc", 0, "other-doc", "other-doc", "kb", "tag", True),
            (38, 100, "needle", "other-tag", 0, "other-tag", "doc", "kb", "other-tag", True),
            (39, 100, "needle", None, 0, "null-source", "doc", "kb", "tag", True),
        ]
        self.db.executemany("INSERT INTO embeddings VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    def execute(self, mode, limit=3, keyword="needle"):
        sql, args = build_sql(["kb", "faq"], ["kb"], keyword, limit, mode, True, ["doc"], ["tag"])
        # SQLite checks relational/filter/limit semantics only, not BM25 plans.
        sql = sql.replace("paradedb.score(id)", "score").replace("content |||", "content LIKE")
        return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def test_filters_before_limit_and_preserves_faq_nullable_enabled_and_scope(self):
        actual = self.execute("rewrite")
        self.assertEqual({r["id"] for r in actual}, {31, 32, 33})
        report = compare_results(self.execute("scores"), self.execute("eligible"), actual, 3)
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["eligible_count"], 4)
        self.assertNotIn("needle", json.dumps(report))

    def test_empty_results_are_correct_but_do_not_prove_positive_recall(self):
        self.assertEqual(self.execute("rewrite", keyword="absent"), [])
        self.assertTrue(compare_results([], [], [], 3)["passed"])

    def test_under_recall_wrong_rank_score_duplicate_and_forbidden_rows_fail(self):
        scores, eligible = self.execute("scores"), self.execute("eligible")
        actual = self.execute("rewrite")
        variants = [
            actual[:1],
            [actual[0]] * 3,
            [*actual[:2], {"id": 34, "score": 7}],
            [*actual[:2], {"id": 36, "score": 8}],
            [{**row, "score": 123} for row in actual],
        ]
        for candidate in variants:
            with self.subTest(candidate=candidate):
                self.assertFalse(compare_results(scores, eligible, candidate, 3)["passed"])

    def test_reference_cap_is_failure_not_silent_truncation(self):
        scores = [{"id": i, "score": 1} for i in range(REFERENCE_CAP + 1)]
        self.assertFalse(compare_results(scores, [], [], 3)["passed"])

    def test_prepared_sql_has_no_early_limit_or_injected_values(self):
        secret = "quote'\\; DROP TABLE ignored; --"
        sql, values = build_sql(
            [secret, "b"],
            [secret],
            secret,
            500,
            prepared=True,
            documents=["doc1", "doc2"],
            tags=["tag"],
        )
        self.assertNotIn(secret, sql)
        self.assertIn("AS MATERIALIZED", sql)
        self.assertEqual(sql.count("LIMIT"), 1)
        self.assertLess(sql.index("FROM scored WHERE"), sql.index("LIMIT"))
        self.assertGreater(sql.index("source_id <> chunk_id"), sql.index("FROM scored WHERE"))
        self.assertEqual(
            [int(n) for n in re.findall(r"\$(\d+)", sql)], list(range(1, len(values) + 1))
        )
        self.assertEqual(values, [secret, "b", "doc1", "doc2", "tag", secret, True, secret, 500])


if __name__ == "__main__":
    unittest.main()
