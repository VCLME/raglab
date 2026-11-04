from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from fastapi import APIRouter, Depends

from raglab.api.deps import get_current_settings
from raglab.api.schemas import LLMModelsResponse, LLMProviderInfo
from raglab.config import Settings
from raglab.llm.providers import describe_provider

router = APIRouter(tags=["llm"])


@router.get("/api/llm/models", response_model=LLMModelsResponse)
def list_llm_models(settings: Settings = Depends(get_current_settings)) -> LLMModelsResponse:
    """Enabled generation providers (RAGLAB_LLM_PROVIDERS order) and their models.

    Servers are probed in parallel with RAGLAB_READY_TIMEOUT_SECONDS each; an
    unreachable one is reported `available: false` instead of failing the call.
    llama-server is never started from here.
    """
    names = settings.llm_provider_names
    timeout = settings.ready_timeout_seconds
    with ThreadPoolExecutor(max_workers=len(names), thread_name_prefix="raglab-llm-probe") as pool:
        # copy_context keeps the request id on the probes' log lines.
        futures = [
            pool.submit(copy_context().run, describe_provider, settings, name, timeout=timeout) for name in names
        ]
        entries = [future.result() for future in futures]
    providers = [LLMProviderInfo(**entry) for entry in entries]
    default = next(provider for provider in providers if provider.name == settings.default_llm_provider)
    return LLMModelsResponse(
        default_provider=settings.default_llm_provider,
        default_model=default.default_model,
        providers=providers,
    )
