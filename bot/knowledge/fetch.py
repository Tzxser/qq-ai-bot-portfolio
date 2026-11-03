import html
import ipaddress
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .service import DEFAULT_SOURCE, validate_source_url


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            value = re.sub(r"\s+", " ", html.unescape(data)).strip()
            if value:
                self.parts.append(value)


def fetch_draft(url=DEFAULT_SOURCE, timeout=15, max_bytes=2_000_000):
    if not validate_source_url(url):
        raise ValueError("source_not_allowed")
    host = urlsplit(url).hostname
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise RuntimeError("source_unavailable") from exc
    if not addresses or any(ipaddress.ip_address(address).is_private or
                            ipaddress.ip_address(address).is_loopback or
                            ipaddress.ip_address(address).is_link_local or
                            ipaddress.ip_address(address).is_reserved for address in addresses):
        raise ValueError("source_resolves_to_private_address")
    request = Request(url, headers={"User-Agent": "qq-ai-bot-knowledge-draft/1"})
    opener = build_opener(_NoRedirect())
    try:
        response = opener.open(request, timeout=timeout)
    except Exception as exc:
        raise RuntimeError("source_unavailable") from exc
    if response.status != 200 or response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
        raise RuntimeError("source_rejected")
    body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise RuntimeError("source_too_large")
    parser = _Text()
    parser.feed(body.decode("utf-8", "replace"))
    text = "\n".join(parser.parts)
    return {
        "id": "site-home-draft-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "title": "公开站点抓取草稿（待审核）",
        "body": text[:100_000],
        "category": "draft",
        "source_type": "public_site",
        "source_url": url,
        "source_ref": "homepage",
        "group_scope": [],
        "source_updated_at": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "valid_from": None,
        "valid_until": None,
        "review_status": "pending",
        "reviewed_by": None,
        "version": 1,
        "owner_department": None,
    }
