from __future__ import annotations


def test_config_endpoint_exposes_safe_fields_only(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    # Champs publics attendus
    assert "generation_model" in body
    assert "embedding_model_name" in body
    assert "ollama_base_url" in body
    assert "adminer_url" in body
    # Aucune info sensible type mot de passe ou URL DB brute
    assert "database_url" not in body
    assert all("password" not in key.lower() for key in body.keys())


def test_config_says_why_the_reranker_has_no_gpu(client):
    body = client.get("/api/config").json()
    assert body["rerank_device"]
    assert body["rerank_gpu_status"] in {"ok", "device_cpu", "torch_missing", "cuda_unavailable"}
    assert body["rerank_gpu"] == (body["rerank_gpu_status"] == "ok")
