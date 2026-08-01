from ops_copilot.config import Settings


def test_defaults_require_no_env_vars(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("OPS_"):
            monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "fake"
    assert settings.logs_backend == "mock"
    assert settings.metrics_backend == "mock"
    assert settings.auth_enabled is False


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("OPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPS_API_KEY", "secret123")
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "openai"
    assert settings.auth_enabled is True
