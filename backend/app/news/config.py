import json
from pathlib import Path

from pydantic import ValidationError

from app.news.schemas import RSSSource

MAX_SOURCE_CONFIG_BYTES = 64 * 1024
MAX_RSS_SOURCES = 20


def load_rss_sources(path: str | Path) -> tuple[RSSSource, ...]:
    source_path = Path(path)
    if not source_path.exists():
        return ()
    try:
        if source_path.stat().st_size > MAX_SOURCE_CONFIG_BYTES:
            raise ValueError("rss_source_config_too_large")
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or len(raw) > MAX_RSS_SOURCES:
            raise ValueError("rss_source_config_invalid")
        sources = tuple(RSSSource.model_validate(item) for item in raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("rss_source_config_invalid") from error
    except ValueError as error:
        if str(error) in {"rss_source_config_too_large", "rss_source_config_invalid"}:
            raise
        raise ValueError("rss_source_config_invalid") from error
    ids = [source.source_id for source in sources]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_rss_source_id")
    return sources
