import os

import pytest

os.environ.setdefault("OPS_LLM_PROVIDER", "fake")
os.environ.setdefault("OPS_LOGS_BACKEND", "mock")
os.environ.setdefault("OPS_METRICS_BACKEND", "mock")
os.environ.setdefault("OPS_EMBEDDINGS_PROVIDER", "none")


@pytest.fixture
def tmp_checkpoint_db(tmp_path):
    return str(tmp_path / "checkpoints.sqlite")


@pytest.fixture
def settings_factory(tmp_checkpoint_db):
    from ops_copilot.config import Settings

    def _make(**overrides):
        defaults = {
            "llm_provider": "fake",
            "logs_backend": "mock",
            "metrics_backend": "mock",
            "embeddings_provider": "none",
            "checkpoint_db_path": tmp_checkpoint_db,
        }
        defaults.update(overrides)
        return Settings(**defaults)

    return _make
