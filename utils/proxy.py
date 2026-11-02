"""把 DY_PROXY 转成 requests / websocket-client 都能用的参数。"""
from __future__ import annotations

from urllib.parse import unquote, urlparse


def proxies_from_url(url: str | None) -> dict | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    return {"http": raw, "https": raw}


def websocket_proxy_kwargs(proxies: dict | None) -> dict:
    if not proxies:
        return {}
    raw = (proxies.get("https") or proxies.get("http") or "").strip()
    if not raw:
        return {}
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        return {}
    scheme = (parsed.scheme or "http").lower()
    if scheme.startswith("socks5"):
        proxy_type = "socks5"
    elif scheme.startswith("socks4"):
        proxy_type = "socks4"
    else:
        proxy_type = "http"
    kwargs = {
        "http_proxy_host": parsed.hostname,
        "http_proxy_port": int(parsed.port),
        "proxy_type": proxy_type,
    }
    if parsed.username:
        kwargs["http_proxy_auth"] = (
            unquote(parsed.username),
            unquote(parsed.password or ""),
        )
    return kwargs
