from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def is_local_authority(value: str) -> bool:
    try:
        parsed = urlsplit(f"//{value}")
        _ = parsed.port
        return (
            parsed.hostname is not None
            and parsed.hostname.lower() in LOCAL_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
        )
    except ValueError:
        return False


def is_local_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return (
            parsed.scheme == "http"
            and parsed.hostname is not None
            and parsed.hostname.lower() in LOCAL_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


class LocalRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        hosts = request.headers.getlist("host")
        if len(hosts) != 1 or not is_local_authority(hosts[0]):
            return JSONResponse({"detail": "host_not_allowed"}, status_code=400)

        if request.method in MUTATING_METHODS:
            origins = request.headers.getlist("origin")
            if len(origins) != 1 or not is_local_origin(origins[0]):
                return JSONResponse({"detail": "origin_not_allowed"}, status_code=403)
            if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
                return JSONResponse({"detail": "json_required"}, status_code=415)

        return await call_next(request)
