import json
import unittest

from weknora_rehearsal_diagnostics import classify


class DiagnosticTests(unittest.TestCase):
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
