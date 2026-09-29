"""Where a configured provider runs, for the AI-enrichment record.

Conservative on purpose: `LOCAL` only for the in-process `mock` provider
(it makes no network call) and for `llama_cpp` when its base URL names
this machine. Every other case is `UNKNOWN`. The URL is inspected and
discarded; it is never returned or stored.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from ..domain.ai_enrichment import EnrichmentModelLocation

#: Names that always mean the machine running the product. The Compose
#: files map `host.docker.internal` to the Docker host, which is where the
#: documented local `llama-server` runs.
_LOCAL_HOSTNAMES = frozenset({"localhost", "host.docker.internal"})


def _names_this_machine(base_url: str) -> bool:
    try:
        host = urlsplit(base_url).hostname
    except ValueError:
        return False
    if not host:
        return False
    if host.lower() in _LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def model_location_for(provider_name: str, base_url: str) -> EnrichmentModelLocation:
    """`LOCAL` for a known local runtime on this machine, else `UNKNOWN`."""
    if provider_name == "mock":
        return EnrichmentModelLocation.LOCAL
    if provider_name == "llama_cpp" and _names_this_machine(base_url):
        return EnrichmentModelLocation.LOCAL
    return EnrichmentModelLocation.UNKNOWN
