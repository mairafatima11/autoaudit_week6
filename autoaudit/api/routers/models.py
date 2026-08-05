from __future__ import annotations

from fastapi import APIRouter, Depends

from ...config import Config
from ...llm.registry import PRIMARY_PROVIDER, SECONDARY_PROVIDER, ProviderRegistry
from ...llm.router import ModelRouter
from ...schemas import ModelComparison
from ..dependencies import get_config
from ..schemas_api import ModelCompareRequest

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/available")
def available_models(config: Config = Depends(get_config)):
    registry = ProviderRegistry(config)
    return {
        "primary": PRIMARY_PROVIDER,
        "secondary": SECONDARY_PROVIDER,
        "providers": [
            {
                "id": name,
                "model": config.groq_model if name == "groq" else config.gemini_model,
                "live": config.is_live() and bool(config.groq_api_key if name == "groq" else config.gemini_api_key),
            }
            for name in registry.available_providers()
        ],
    }


@router.get("/health")
def provider_health(config: Config = Depends(get_config)):
    """Provider health checks backing the automatic-failover requirement.
    In mock mode every provider reports healthy instantly (no network to
    fail); in live mode this does a real, cheap probe call per provider."""
    registry = ProviderRegistry(config)
    results = registry.health_check_all()
    return {
        name: {"provider": h.provider, "healthy": h.healthy, "latency_ms": h.latency_ms, "detail": h.detail}
        for name, h in results.items()
    }


@router.post("/compare", response_model=ModelComparison)
def compare_models(req: ModelCompareRequest, config: Config = Depends(get_config)):
    registry = ProviderRegistry(config)
    model_router = ModelRouter(registry.get_all())
    return model_router.compare(req.prompt, system=req.system, providers=req.providers)
