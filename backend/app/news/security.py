import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.task_context import ToolFailure
from app.news.schemas import normalize_host


def resolve_addresses(host: str, port: int) -> list[str]:
    try:
        ip = ipaddress.ip_address(host)
        return [str(ip)]
    except ValueError:
        pass
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ToolFailure("dns_resolution_failed") from error
    return list(dict.fromkeys(result[4][0] for result in results))


def validate_public_http_url(
    url: str,
    allowed_hosts: tuple[str, ...] | list[str],
    resolver=resolve_addresses,
) -> tuple[str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = normalize_host(parsed.hostname or "")
    except (ValueError, UnicodeError) as error:
        raise ToolFailure("url_denied") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (port is not None and port != (443 if parsed.scheme == "https" else 80))
        or host not in {normalize_host(allowed) for allowed in allowed_hosts}
    ):
        raise ToolFailure("url_denied")

    effective_port = port or (443 if parsed.scheme == "https" else 80)
    addresses = resolver(host, effective_port)
    if not addresses:
        raise ToolFailure("dns_resolution_failed")
    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
        except ValueError as error:
            raise ToolFailure("dns_resolution_failed") from error
        if not address.is_global:
            raise ToolFailure("ssrf_blocked")
    return host, effective_port
