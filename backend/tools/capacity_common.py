"""Hard boundaries shared by the disposable capacity tools, never imported by app."""

import os

DATABASE = "postgresql+asyncpg://capacity:capacity@postgres:5432/kap_capacity_test"
API = "https://api:8443"
FIXTURE = "http://fixture:9000"
PASSWORD = "capacity-synthetic-password-123"


def guard():
    expected = {
        "KAP_CAPACITY_ISOLATED": "1",
        "APP_ENV": "prod",
        "DATABASE_URL": DATABASE,
        "REDIS_URL": "redis://redis:6379/0",
        "WEKNORA_BASE_URL": FIXTURE,
        "WEKNORA_API_KEY": "sk-synthetic-only",
        "LLM_BASE_URL": FIXTURE + "/v1",
        "LLM_API_KEY": "synthetic-only",
        "STORAGE_ROOT": "/data/uploads",
    }
    if any(os.environ.get(key) != value for key, value in expected.items()):
        raise SystemExit("Refusing non-isolated capacity environment")


def email(index):
    return f"capacity-{index}@example.invalid"
