import json
import unittest

from weknora_rehearsal_diagnostics import classify


class DiagnosticTests(unittest.TestCase):
    def test_script_start_failure_redacts_path_and_preserves_permission_category(self):
        result = classify("python: can't open file '/private/secret.py': [Errno 13] Permission denied")
        self.assertIn("script_permission_denied", result["signals"])
        self.assertNotIn("/private", json.dumps(result))
        self.assertIn(
            "gateway_not_ready",
            classify("RuntimeError: egress gateway exited before readiness")["signals"],
        )

    def test_verbose_psql_code_and_parameter_error_remain_allow_listed(self):
        result = classify("ERROR: XX000: no value found for parameter $7 secret-value")
        self.assertEqual(result["sqlstates"], ["XX000"])
        self.assertEqual(result["signals"], ["parameter_execution_error"])
        self.assertNotIn("secret-value", json.dumps(result))
        self.assertNotIn("$7", json.dumps(result))

    def test_query_shape_error_does_not_get_misclassified_as_transport(self):
        result = classify("WeKnoraError: 1007: ERROR: Unsupported query shape (SQLSTATE XX000)")
        self.assertEqual(result["signals"], ["unsupported_query_shape"])
        self.assertEqual(result["sqlstates"], ["XX000"])

    def test_reports_http_database_category_without_raw_error(self):
        result = classify(
            'app.services.weknora_client.WeKnoraError: 1007: column "private_doc_title" does not exist (SQLSTATE 42703)'
        )
        self.assertEqual(result["exception_type"], "WeKnoraError")
        self.assertEqual(result["upstream_error_categories"], ["internal_server_error"])
        self.assertEqual(result["sqlstates"], ["42703"])
        self.assertIn("missing_database_object", result["signals"])
        self.assertNotIn("private_doc_title", json.dumps(result))

    def test_does_not_emit_secrets_endpoints_ids_or_unrecognised_codes(self):
        private = (
            "sk-VERYSECRET password=hidden https://private.invalid/tenant/1234 user@example.invalid"
        )
        result = classify("httpx.ReadTimeout: " + private + "\nWeKnoraError: 9999: " + private)
        encoded = json.dumps(result)
        for value in [
            "VERYSECRET",
            "hidden",
            "private.invalid",
            "1234",
            "user@example.invalid",
            "9999",
        ]:
            self.assertNotIn(value, encoded)
        self.assertEqual(result["exception_type"], "WeKnoraError")
        self.assertEqual(result["upstream_error_categories"], [])

    def test_distinguishes_response_shape_from_transport_failure(self):
        result = classify("AttributeError: 'str' object has no attribute 'get'")
        self.assertEqual(result["exception_type"], "AttributeError")
        self.assertEqual(result["signals"], ["response_shape"])
        self.assertEqual(
            classify("httpx.ConnectError: network is unreachable")["signals"],
            ["network_unreachable"],
        )


if __name__ == "__main__":
    unittest.main()
