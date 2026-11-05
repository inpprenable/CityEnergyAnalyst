"""Identity forwarded by an authenticating gateway (auth_provider='proxy').

Traefik's ForwardAuth copies these headers from oauth2-proxy's /oauth2/auth response
(authResponseHeaders), overwriting any client-supplied value. The user id is the
Keycloak subject (`sub`), which owns Projects and must never change.
See docs/adr/0001-identity-from-gateway-headers.md.
"""
from typing import Any, Callable, Dict, Optional

USER_HEADER = "X-Auth-Request-User"
EMAIL_HEADER = "X-Auth-Request-Email"
NAME_HEADER = "X-Auth-Request-Preferred-Username"

HeaderGetter = Callable[[str], Optional[str]]


def get_gateway_user_id(get_header: HeaderGetter) -> Optional[str]:
    """User id from the gateway headers, or None when the request was not authenticated by it."""
    user_id = (get_header(USER_HEADER) or "").strip()
    return user_id or None


def get_gateway_user(get_header: HeaderGetter) -> Optional[Dict[str, Any]]:
    """User profile in the shape the /user route and GUI expect, or None when unauthenticated.

    Onboarding happens on the Host platform, so a gateway-authenticated User is always onboarded.
    """
    user_id = get_gateway_user_id(get_header)
    if user_id is None:
        return None
    return {
        "id": user_id,
        "primary_email": get_header(EMAIL_HEADER) or "unknown@example.com",
        "display_name": get_header(NAME_HEADER) or "Unknown User",
        "onboarded": True,
        "pro_user": False,
    }
