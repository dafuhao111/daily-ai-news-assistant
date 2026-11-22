import calendar
import hashlib
import html
import logging
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx

from app.core.task_context import ToolContext, ToolFailure
from app.news.schemas import (
    NewsArticle,
    RSSSource,
    has_sensitive_query_parameter,
    normalize_host,
)
from app.news.security import resolve_addresses, validate_public_http_url

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_REQUEST_SECONDS = 20.0
MAX_FEED_ITEMS_PER_SOURCE = 50
MAX_RSS_ITEMS_PER_TOOL_RESULT = 10
MAX_FEED_TITLE_CHARS = 240
MAX_FEED_SUMMARY_CHARS = 480
MAX_ARTICLE_CHARS = 24_000
MAX_ARTICLE_RESULT_CHARS = 2_500
TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "mc_cid", "mc_eid"}
HTML_TAG = re.compile(r"<[^>]+>")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._suppressed = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed:
            self.parts.append(data)


def plain_text(value: str, limit: int) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        text_value = " ".join(parser.parts)
    except Exception:  # noqa: BLE001 - malformed feed HTML still needs a bounded text fallback
        text_value = HTML_TAG.sub(" ", value)
    text_value = html.unescape(re.sub(r"\s+", " ", text_value)).strip()
    return text_value[:limit]


def canonicalize_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
        host = normalize_host(parsed.hostname or "")
    except (ValueError, UnicodeError) as error:
        raise ToolFailure("invalid_article_url") from error
    if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ToolFailure("invalid_article_url")
    if port is not None and port != (443 if parsed.scheme == "https" else 80):
        raise ToolFailure("invalid_article_url")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMETERS
    ]
    if has_sensitive_query_parameter(url):
        raise ToolFailure("article_url_contains_secret")
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", urlencode(query), ""))


def _parse_published(entry) -> tuple[str | None, str | None, str | None]:
    raw = entry.get("published")
    parsed = entry.get("published_parsed")
    source_field = "published" if raw else None
    if not raw:
        raw = entry.get("updated")
        parsed = entry.get("updated_parsed")
        source_field = "updated" if raw else None
    if not raw:
        return None, None, None
    published_at_utc = None
    try:
        explicit_time = parsedate_to_datetime(str(raw))
    except (ValueError, TypeError, OverflowError):
        try:
            explicit_time = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            explicit_time = None
    # Keep original evidence, but never invent a timezone for an ambiguous date.
    if parsed and explicit_time is not None and explicit_time.utcoffset() is not None:
        try:
            published_at_utc = datetime.fromtimestamp(
                calendar.timegm(parsed), timezone.utc
            ).isoformat(timespec="seconds")
        except (OverflowError, OSError, TypeError, ValueError):
            published_at_utc = None
    return str(raw)[:240], published_at_utc, source_field


def _article_id(canonical_url: str) -> tuple[str, str]:
    url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
    return url_hash[:32], url_hash


def _rss_item_summary(article: NewsArticle) -> dict[str, object]:
    return {
        "article_id": article.article_id,
        "title": article.title,
        "summary": article.summary[:240],
        "source_id": article.source_id,
        "source_name": article.source_name,
        "category": article.category,
        "url": article.url,
        "published_at_raw": article.published_at_raw,
        "published_at_utc": article.published_at_utc,
        "published_at_field": article.published_at_field,
        "fetched_at_utc": article.fetched_at_utc,
    }


class NewsService:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Callable[[str, int], list[str]] = resolve_addresses,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.transport = transport
        self.resolver = resolver
        self.now = now or (lambda: datetime.now(timezone.utc))

    def fetch_rss_tool(self, source_ids: list[str], context: ToolContext) -> dict[str, object]:
        if not context.news_sources:
            raise ToolFailure("no_sources_configured")
        repository = context.news_repository
        if repository is not None:
            repository.sync_sources(context.news_sources)
        sources = {source.source_id: source for source in context.news_sources}
        fetched_count = 0
        duplicate_count = 0
        articles_by_source: list[list[NewsArticle]] = []
        errors: list[dict[str, str]] = []
        for source_id in source_ids:
            source = sources.get(source_id)
            if source is None:
                context.news_source_outcomes[source_id] = "source_not_found"
                errors.append({"source_id": source_id, "error": "source_not_found"})
                continue
            if not source.enabled:
                context.news_source_outcomes[source_id] = "source_disabled"
                errors.append({"source_id": source_id, "error": "source_disabled"})
                continue
            try:
                articles, duplicates = self.fetch_rss(source, context)
            except ToolFailure as error:
                context.news_source_outcomes[source_id] = error.code
                logger.warning(
                    "rss source fetch failed (run_id=%s, source_id=%s, error_code=%s)",
                    context.run_id,
                    source.source_id,
                    error.code,
                )
                pending = []
                if repository is not None:
                    repository.record_source_fetch(source_id, error.code)
                    pending = repository.pending_candidates(source_id)
                recovered = []
                for article in pending:
                    if article.article_id in context.news_candidates:
                        duplicate_count += 1
                        continue
                    context.news_candidates[article.article_id] = article
                    recovered.append(article)
                if recovered:
                    articles_by_source.append(recovered)
                errors.append({"source_id": source_id, "error": error.code})
                continue
            fetched_count += 1
            duplicate_count += duplicates
            if repository is not None:
                repository.record_source_fetch(source_id)
                _active, included_skipped = repository.save_candidates(source, articles)
                duplicate_count += included_skipped
                articles = repository.pending_candidates(source_id)
            context.news_source_outcomes[source_id] = "succeeded"
            available = []
            for article in articles:
                if article.article_id in context.news_candidates:
                    duplicate_count += 1
                    continue
                context.news_candidates[article.article_id] = article
                available.append(article)
            articles_by_source.append(available)

        total_available = sum(len(articles) for articles in articles_by_source)
        if fetched_count == 0 and total_available == 0:
            error_codes = {error["error"] for error in errors}
            if error_codes == {"source_disabled"}:
                raise ToolFailure("source_disabled")
            if error_codes == {"source_not_found"}:
                raise ToolFailure("source_not_found")
            if len(errors) == 1:
                raise ToolFailure(errors[0]["error"])
            raise ToolFailure("all_sources_failed")
        reported: list[NewsArticle] = [articles[0] for articles in articles_by_source if articles]
        for offset in range(1, MAX_FEED_ITEMS_PER_SOURCE):
            for articles in articles_by_source:
                if offset < len(articles):
                    reported.append(articles[offset])
                if len(reported) >= MAX_RSS_ITEMS_PER_TOOL_RESULT:
                    break
            if len(reported) >= MAX_RSS_ITEMS_PER_TOOL_RESULT:
                break
        context.news_visible_article_ids.update(article.article_id for article in reported)
        total_items = sum(len(articles) for articles in articles_by_source)
        truncated = total_items > len(reported)
        return {
            "items": [_rss_item_summary(article) for article in reported],
            "sources_fetched": fetched_count,
            "duplicates_skipped": duplicate_count,
            "source_errors": errors,
            "truncated": truncated,
        }

    def search_news_tool(self, query: str, limit: int, context: ToolContext) -> dict[str, object]:
        articles = self.search_news(query, limit, context)
        total_matches = self.count_news_matches(query, context)
        context.news_visible_article_ids.update(article.article_id for article in articles)
        return {
            "items": [_rss_item_summary(article) for article in articles],
            "match_count": total_matches,
            "truncated": total_matches > len(articles),
        }

    def fetch_article_tool(self, article_id: str, context: ToolContext) -> dict[str, object]:
        article, content, chunk_index, more_chunks = self.fetch_article(article_id, context)
        context.news_visible_article_ids.add(article.article_id)
        return {
            "article_id": article.article_id,
            "title": article.title,
            "source_id": article.source_id,
            "source_name": article.source_name,
            "url": article.url,
            "published_at_raw": article.published_at_raw,
            "published_at_utc": article.published_at_utc,
            "published_at_field": article.published_at_field,
            "fetched_at_utc": article.fetched_at_utc,
            "content_excerpt": content,
            "chunk_index": chunk_index,
            "truncated": more_chunks,
            "source_truncated": article.article_text_truncated,
        }

    def _download(
        self,
        url: str,
        allowed_hosts: tuple[str, ...] | list[str],
    ) -> tuple[bytes, str, str]:
        started = time.monotonic()
        current_url = url
        headers = {"User-Agent": "DailyAINewsAssistant/0.1 (+local single-user reader)"}
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
                headers=headers,
            ) as client:
                for redirect_count in range(MAX_REDIRECTS + 1):
                    resolved: list[str] = []

                    def resolve_once(host, port, resolved=resolved):
                        addresses = self.resolver(host, port)
                        resolved.extend(addresses)
                        return addresses

                    host, _port = validate_public_http_url(current_url, allowed_hosts, resolve_once)
                    # Pin live connections to the already-validated address. Keep the
                    # original Host and TLS SNI for certificate verification. The
                    # transport must not resolve the name again (DNS rebinding).
                    target = current_url
                    options = {}
                    if self.transport is None:
                        target = httpx.URL(current_url).copy_with(host=resolved[0])
                        options = {"headers": {"Host": host}, "extensions": {"sni_hostname": host}}
                    if time.monotonic() - started > MAX_REQUEST_SECONDS:
                        raise ToolFailure("request_timeout")
                    with client.stream("GET", target, **options) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location or redirect_count >= MAX_REDIRECTS:
                                raise ToolFailure("redirect_denied")
                            current_url = urljoin(current_url, location)
                            continue
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ToolFailure("http_error")
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            if time.monotonic() - started > MAX_REQUEST_SECONDS:
                                raise ToolFailure("request_timeout")
                            size += len(chunk)
                            if size > MAX_RESPONSE_BYTES:
                                raise ToolFailure("response_too_large")
                            chunks.append(chunk)
                        return (
                            b"".join(chunks),
                            current_url,
                            response.headers.get("content-type", ""),
                        )
        except ToolFailure:
            raise
        except httpx.TimeoutException as error:
            raise ToolFailure("request_timeout") from error
        except httpx.RequestError as error:
            raise ToolFailure("network_error") from error
        raise ToolFailure("redirect_denied")

    def fetch_rss(self, source: RSSSource, context: ToolContext) -> tuple[list[NewsArticle], int]:
        body, _final_url, _content_type = self._download(source.feed_url, source.allowed_hosts)
        upper_body = body.upper()
        if b"<!DOCTYPE" in upper_body or b"<!ENTITY" in upper_body:
            raise ToolFailure("feed_parse_error")
        parsed = feedparser.parse(body)
        if parsed.bozo:
            raise ToolFailure("feed_parse_error")
        fetched_at = self.now().astimezone(timezone.utc).isoformat(timespec="seconds")
        articles: list[NewsArticle] = []
        duplicates = 0
        seen_ids = set(context.news_candidates)
        for entry in parsed.entries[:MAX_FEED_ITEMS_PER_SOURCE]:
            title = plain_text(str(entry.get("title", "")), MAX_FEED_TITLE_CHARS)
            original_url = str(entry.get("link", "")).strip()
            if not title or not original_url or len(original_url) > 1000:
                continue
            try:
                canonical_url = canonicalize_url(original_url)
            except ToolFailure:
                continue
            article_id, url_hash = _article_id(canonical_url)
            if article_id in seen_ids:
                duplicates += 1
                continue
            seen_ids.add(article_id)
            summary_source = entry.get("summary", "")
            if not summary_source and entry.get("content"):
                summary_source = entry.content[0].get("value", "")
            summary = plain_text(str(summary_source), MAX_FEED_SUMMARY_CHARS)
            published_raw, published_at_utc, published_field = _parse_published(entry)
            article = NewsArticle(
                article_id=article_id,
                url_hash=url_hash,
                source_id=source.source_id,
                source_name=source.name,
                category=source.category,
                title=title,
                summary=summary,
                url=original_url,
                canonical_url=canonical_url,
                published_at_raw=published_raw,
                published_at_utc=published_at_utc,
                published_at_field=published_field,
                fetched_at_utc=fetched_at,
            )
            articles.append(article)
        return articles, duplicates

    def search_news(
        self,
        query: str,
        limit: int,
        context: ToolContext,
    ) -> list[NewsArticle]:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return []
        matches = []
        for article in context.news_candidates.values():
            searchable = " ".join(
                (
                    article.title,
                    article.summary,
                    article.source_name,
                    article.category,
                    article.article_text or "",
                )
            ).casefold()
            if all(term in searchable for term in terms):
                matches.append(article)
        return matches[:limit]

    def count_news_matches(self, query: str, context: ToolContext) -> int:
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            return 0
        count = 0
        for article in context.news_candidates.values():
            searchable = " ".join(
                (
                    article.title,
                    article.summary,
                    article.source_name,
                    article.category,
                    article.article_text or "",
                )
            ).casefold()
            if all(term in searchable for term in terms):
                count += 1
        return count

    def fetch_article(
        self, article_id: str, context: ToolContext
    ) -> tuple[NewsArticle, str, int, bool]:
        article = context.news_candidates.get(article_id)
        if article is None:
            raise ToolFailure("article_not_found")
        source = next(
            (source for source in context.news_sources if source.source_id == article.source_id),
            None,
        )
        if source is None or not source.enabled:
            raise ToolFailure("source_not_available")
        if not article.article_text:
            body, _final_url, content_type = self._download(article.url, source.allowed_hosts)
            try:
                text_body = body.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise ToolFailure("article_encoding_error") from error
            if "html" in content_type.casefold() or "<html" in text_body[:1000].casefold():
                text_body = plain_text(text_body, MAX_ARTICLE_CHARS + 1)
            else:
                text_body = re.sub(r"\s+", " ", text_body).strip()[: MAX_ARTICLE_CHARS + 1]
            if not text_body:
                raise ToolFailure("article_unavailable")
            article.article_text_truncated = len(text_body) > MAX_ARTICLE_CHARS
            article.article_text = text_body[:MAX_ARTICLE_CHARS]
            article.fetched_at_utc = (
                self.now().astimezone(timezone.utc).isoformat(timespec="seconds")
            )
            if context.news_repository is not None:
                context.news_repository.save_article_text(
                    article.article_id,
                    article.article_text,
                    article.article_text_truncated,
                )

        content = article.article_text or ""
        start = context.article_offsets.get(article_id, 0)
        end = min(start + MAX_ARTICLE_RESULT_CHARS, len(content))
        context.article_offsets[article_id] = end
        chunk_index = start // MAX_ARTICLE_RESULT_CHARS + 1
        return article, content[start:end], chunk_index, end < len(content)
