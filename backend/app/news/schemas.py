import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
SENSITIVE_QUERY_PARAMETERS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "password",
    "secret",
    "session",
    "signature",
    "sig",
    "token",
}


def normalize_host(host: str) -> str:
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def has_sensitive_query_parameter(url: str) -> bool:
    return any(
        key.casefold() in SENSITIVE_QUERY_PARAMETERS
        for key, _value in parse_qsl(urlsplit(url).query, keep_blank_values=True)
    )


class RSSSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    feed_url: str = Field(min_length=1, max_length=2000)
    allowed_hosts: list[str] = Field(min_length=1, max_length=10)
    category: str = Field(min_length=1, max_length=80)
    enabled: bool = True

    @field_validator("source_id")
    @classmethod
    def source_id_is_stable(cls, value: str) -> str:
        if not SOURCE_ID.fullmatch(value):
            raise ValueError("invalid_source_id")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def hosts_are_normalized(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            try:
                host = normalize_host(value)
            except UnicodeError as error:
                raise ValueError("invalid_allowed_host") from error
            if not host or "/" in host or ":" in host or "@" in host:
                raise ValueError("invalid_allowed_host")
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError("private_allowed_host")
            normalized.append(host)
        if len(set(normalized)) != len(normalized):
            raise ValueError("duplicate_allowed_host")
        return normalized

    @model_validator(mode="after")
    def feed_host_is_allowed(self) -> "RSSSource":
        try:
            parsed = urlsplit(self.feed_url)
            port = parsed.port
            host = normalize_host(parsed.hostname or "")
        except (ValueError, UnicodeError) as error:
            raise ValueError("invalid_feed_url") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or parsed.fragment
            or has_sensitive_query_parameter(self.feed_url)
            or (port is not None and port != (443 if parsed.scheme == "https" else 80))
            or host not in self.allowed_hosts
        ):
            raise ValueError("feed_url_not_allowed")
        return self


class NewsArticle(BaseModel):
    article_id: str = Field(min_length=16, max_length=64)
    url_hash: str = Field(min_length=64, max_length=64)
    source_id: str
    source_name: str
    category: str
    title: str
    summary: str
    url: str
    canonical_url: str
    published_at_raw: str | None = None
    published_at_utc: str | None = None
    published_at_field: str | None = None
    fetched_at_utc: str
    article_text: str | None = None
    article_text_truncated: bool = False
