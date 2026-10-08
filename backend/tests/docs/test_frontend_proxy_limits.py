"""The frontend proxy configuration matches the documented limit policy
(`UX-02`, D-068, `docs/api-specification.md` §15).

nginx's default `client_max_body_size` of 1 MB refused larger uploads in the
Compose deployment before the backend saw them. The policy is: the proxy
applies no size limit and streams bodies, and the backend is the single
authority. This is a structural test of the shipped file; behavior of the size
limit itself is proven in `tests/api/test_request_limits.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

NGINX_CONF = Path(__file__).resolve().parents[3] / "frontend" / "nginx.conf"


def _api_location(text: str) -> str:
    match = re.search(r"location /api/v1/ \{(?P<body>.*?)\n    \}", text, re.DOTALL)
    assert match is not None, "the /api/v1/ location block must exist"
    return match.group("body")


def test_the_api_location_applies_no_proxy_size_limit_and_streams_request_bodies() -> None:
    block = _api_location(NGINX_CONF.read_text(encoding="utf-8"))

    assert re.search(r"^\s*client_max_body_size\s+0;", block, re.MULTILINE)
    assert re.search(r"^\s*proxy_request_buffering\s+off;", block, re.MULTILINE)


def test_the_api_location_allows_long_requests() -> None:
    block = _api_location(NGINX_CONF.read_text(encoding="utf-8"))

    read = re.search(r"^\s*proxy_read_timeout\s+(\d+)s;", block, re.MULTILINE)
    send = re.search(r"^\s*proxy_send_timeout\s+(\d+)s;", block, re.MULTILINE)
    assert read is not None and int(read.group(1)) >= 300
    assert send is not None and int(send.group(1)) >= 300


def test_no_other_size_limit_is_set_anywhere_in_the_file() -> None:
    text = NGINX_CONF.read_text(encoding="utf-8")
    directives = re.findall(r"^\s*client_max_body_size\s+(\S+);", text, re.MULTILINE)

    assert directives == ["0"]


def test_the_proxy_still_forwards_only_the_api_prefix_to_the_backend() -> None:
    block = _api_location(NGINX_CONF.read_text(encoding="utf-8"))

    assert "proxy_pass http://backend:8000/api/v1/;" in block
