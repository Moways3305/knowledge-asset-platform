import copy
import unittest

import weknora_model_registry_probe as probe


class RegistryLiveTests(unittest.TestCase):
    def setUp(self):
        probe.REPORT["checks"] = []
        root = "https://ws-fixture.cn-beijing.maas.aliyuncs.com"
        self.data = {
            "aes_key": "unused",
            "models": {
                "embedding": {
                    "name": "text-embedding-v3",
                    "parameters": {
                        "base_url": root + "/compatible-mode/v1",
                        "api_key": "synthetic-shared",
                    },
                },
                "rerank": {
                    "name": "qwen3-rerank",
                    "parameters": {
                        "base_url": root + "/api/v1/services/rerank/text-rerank/text-rerank",
                        "api_key": "synthetic-shared",
                    },
                },
                "chat": {
                    "name": "deepseek-chat",
                    "parameters": {
                        "base_url": "https://api.deepseek.com/v1",
                        "api_key": "synthetic-deepseek",
                    },
                },
            },
        }

    def test_shared_key_and_selected_configuration_are_read_only(self):
        original = copy.deepcopy(self.data)
        selected = probe.selected_models(self.data, "ws-fixture")
        self.assertEqual(selected["embedding"]["key"], selected["rerank"]["key"])
        self.assertEqual(self.data, original)
        self.assertNotIn("synthetic-shared", str(probe.REPORT))

    def test_different_rerank_key_fails_closed(self):
        self.data["models"]["rerank"]["parameters"]["api_key"] = "wrong-synthetic-key"
        with self.assertRaisesRegex(RuntimeError, "aliyun_same_api_key"):
            probe.selected_models(self.data, "ws-fixture")

    def test_unapproved_endpoint_and_custom_auth_rejected(self):
        for field, value in (
            ("base_url", "https://other.invalid/v1"),
            ("custom_headers", {"Authorization": "synthetic"}),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.data)
                changed["models"]["chat"]["parameters"][field] = value
                with self.assertRaises(RuntimeError):
                    probe.selected_models(changed, "ws-fixture")


if __name__ == "__main__":
    unittest.main()
