from __future__ import annotations

from fastapi import APIRouter, Response

from raglab.observability.metrics import render_latest

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> Response:
    """Prometheus text exposition: stage latencies, scores, caches, requests."""
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)
