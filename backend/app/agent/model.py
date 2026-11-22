from urllib.parse import urlsplit

import httpx
from langchain_openai import ChatOpenAI

from app.agent.budget_client import BudgetHTTPClient
from app.core.config import Settings


class ModelNotConfiguredError(RuntimeError):
    pass


def create_chat_model(
    settings: Settings, *, http_async_client: httpx.AsyncClient | None = None, budget_service=None
) -> ChatOpenAI:
    if not settings.llm_base_url or not settings.llm_model or not settings.llm_api_key:
        raise ModelNotConfiguredError("llm_not_configured")
    api_key = settings.llm_api_key.get_secret_value().strip()
    try:
        endpoint = urlsplit(settings.llm_base_url.strip())
        _ = endpoint.port
    except ValueError as error:
        raise ModelNotConfiguredError("llm_not_configured") from error
    if (
        not api_key
        or api_key.casefold() == "replace_me"
        or not settings.llm_model.strip()
        or settings.llm_model.casefold() == "replace_with_model_id"
        or endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise ModelNotConfiguredError("llm_not_configured")
    owned_client = http_async_client is None
    source = http_async_client or httpx.AsyncClient(
        timeout=settings.agent_model_timeout_seconds,
        trust_env=False,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )
    client = BudgetHTTPClient(
        source, settings, budget_service=budget_service, owns_source=owned_client
    )
    model = ChatOpenAI(
        model=settings.llm_model,
        api_key=api_key,
        base_url=settings.llm_base_url.strip(),
        timeout=settings.agent_model_timeout_seconds,
        max_retries=0,
        max_tokens=settings.llm_max_output_tokens,
        use_responses_api=settings.llm_api_protocol == "responses",
        store=False,
        http_async_client=client,
    )
    # LangChain caches its default async client across model instances. A task
    # must own its client so a previous asyncio.run() cannot poison another loop.
    object.__setattr__(model, "_daily_owned_http_client", client)
    return model
