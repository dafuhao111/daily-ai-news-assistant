from urllib.parse import urlsplit

from langchain_openai import ChatOpenAI

from app.core.config import Settings


class ModelNotConfiguredError(RuntimeError):
    pass


def create_chat_model(settings: Settings) -> ChatOpenAI:
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
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=api_key,
        base_url=settings.llm_base_url.strip(),
        timeout=settings.agent_model_timeout_seconds,
        max_retries=0,
    )
