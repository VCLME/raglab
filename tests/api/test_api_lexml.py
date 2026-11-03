from __future__ import annotations

from unittest.mock import patch


def test_fulltext_endpoint_forwards_year_range(client):
    with patch("raglab.api.routers.lexml.FullTextCollector") as collector_cls:
        collector_cls.return_value.collect.return_value = {"documents": 3}
        response = client.post("/api/lexml/fulltext", json={"year_from": 2000, "year_to": 2002, "per_year": 2})

    assert response.status_code == 200
    assert response.json() == {"documents": 3}
    kwargs = collector_cls.return_value.collect.call_args.kwargs
    assert list(kwargs["years"]) == [2000, 2001, 2002]
    assert kwargs["per_year"] == 2
    assert kwargs["seed"] == 42


def test_questions_endpoint_uses_defaults(client):
    with patch("raglab.api.routers.lexml.generate_questions") as generate:
        generate.return_value = {"case_count": 10}
        response = client.post("/api/lexml/questions", json={"count": 10})

    assert response.status_code == 200
    kwargs = generate.call_args.kwargs
    assert kwargs["count"] == 10
    assert kwargs["backend"] == "llamacpp"
    assert kwargs["corpus_dir"].as_posix().endswith("data/lexml/fulltext/corpus")
    assert kwargs["output_dir"].as_posix().endswith("data/benchmarks/lexml_fulltext")
