from __future__ import annotations

from unittest.mock import patch


def test_health_reports_ok_when_all_services_reachable(client, mock_session):
    mock_session.execute.return_value = None
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.return_value = {
            "base_url": "http://ollama:11434",
            "reachable": True,
            "models_count": 2,
            "default_generation_model": "qwen2.5:7b",
            "default_generation_model_installed": True,
        }
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert body["postgres"] == "ok"
    assert body["ollama"] == "ok"
    assert body["status"] == "ok"
    assert body["default_generation_model"] == "qwen2.5:7b"
    assert body["default_generation_model_installed"] is True


def test_health_marks_degraded_when_ollama_unreachable(client, mock_session):
    mock_session.execute.return_value = None
    with patch("raglab.api.routers.health.OllamaService") as ollama_cls:
        ollama_cls.return_value.status.side_effect = RuntimeError("connection refused")
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["api"] == "ok"
    assert body["postgres"] == "ok"
    assert body["ollama"] == "unreachable"
    assert body["status"] == "degraded"
