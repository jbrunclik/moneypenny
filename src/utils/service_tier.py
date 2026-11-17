"""Which Gemini service tier served a response (Flex bills half price).

Gemini reports the tier in the `x-gemini-service-tier` response header, not
in usage_metadata (checked Nov 17 2026), so a call that asked for Flex and
fell back to standard is priced by what actually served it.
"""

from collections.abc import Mapping

FLEX = "flex"
STANDARD = "standard"


def served_tier(response: object) -> str:
    """The tier named in a google-genai response's headers ("standard" if none)."""
    http = getattr(response, "sdk_http_response", None)
    headers = getattr(http, "headers", None)
    if not isinstance(headers, Mapping):
        return STANDARD
    tier = headers.get("x-gemini-service-tier") or headers.get("X-Gemini-Service-Tier")
    return str(tier).lower() if tier else STANDARD
