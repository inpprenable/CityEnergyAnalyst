"""Proxy auth mode (CEA_AUTH_PROVIDER=proxy): the Identity gateway (Traefik + oauth2-proxy)
authenticates the User and forwards their Keycloak subject in X-Auth-Request-User.
See docs/adr/0001-identity-from-gateway-headers.md."""
import asyncio
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import HTTPException, Request

import cea.interfaces.dashboard.dependencies as dependencies
from cea.interfaces.dashboard.dependencies import get_auth_client, get_user, get_user_id
from cea.interfaces.dashboard.settings import Settings

PROXY = Settings.model_construct(local=False, auth_provider="proxy")
STACKAUTH = Settings.model_construct(local=False, auth_provider="stackauth")
SUB = "f3b1c2d4-0000-4000-8000-keycloak-sub"


def _make_request(headers: dict, path: str = "/project/", method: str = "GET",
                  route_name: Optional[str] = None, path_params: Optional[dict] = None) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "path_params": path_params or {},
    }
    if route_name is not None:
        scope["route"] = SimpleNamespace(name=route_name)
    return Request(scope)


@pytest.fixture(autouse=True)
def provisioned_users(monkeypatch):
    """Record first-login provisioning instead of touching the database."""
    seen = []

    async def fake_ensure_user_cached(user_id):
        seen.append(user_id)

    monkeypatch.setattr(dependencies, "ensure_user_cached", fake_ensure_user_cached)
    return seen


def test_proxy_mode_identifies_user_from_gateway_header(provisioned_users):
    request = _make_request({"X-Auth-Request-User": SUB})

    assert asyncio.run(get_user_id(request, PROXY)) == SUB
    assert provisioned_users == [SUB]


def test_proxy_mode_without_gateway_header_is_anonymous(provisioned_users):
    request = _make_request({})

    assert asyncio.run(get_user_id(request, PROXY)) is None
    assert provisioned_users == []


def test_stackauth_mode_ignores_forged_gateway_header(provisioned_users, monkeypatch):
    """Forgetting CEA_AUTH_PROVIDER=proxy must fail closed, not trust a client-supplied header."""
    monkeypatch.setattr(dependencies, "get_auth_client", lambda request, settings: None)  # no StackAuth session
    request = _make_request({"X-Auth-Request-User": SUB})

    assert asyncio.run(get_user_id(request, STACKAUTH)) is None
    assert provisioned_users == []


def test_proxy_mode_still_accepts_worker_callback_token(monkeypatch):
    """Worker callbacks reach CEA directly, without the gateway, and act for the Job's User."""
    monkeypatch.setattr(dependencies, "verify_worker_token",
                        lambda token, job_id: "job-owner" if (token, job_id) == ("tok", "job1") else None)
    request = _make_request({"X-CEA-Worker-Token": "tok"}, path="/server/jobs/started/job1", method="POST",
                            route_name="set_job_started", path_params={"job_id": "job1"})

    assert asyncio.run(get_user_id(request, PROXY)) == "job-owner"


def test_proxy_mode_user_profile_comes_from_gateway_headers():
    request = _make_request({
        "X-Auth-Request-User": SUB,
        "X-Auth-Request-Email": "ada@example.org",
        "X-Auth-Request-Preferred-Username": "ada",
    })

    assert get_user(request, None, PROXY) == {
        "id": SUB,
        "primary_email": "ada@example.org",
        "display_name": "ada",
        "onboarded": True,  # onboarding belongs to the Host platform, not CEA
        "pro_user": False,
    }


def test_proxy_mode_user_profile_falls_back_when_gateway_omits_details():
    user = get_user(_make_request({"X-Auth-Request-User": SUB}), None, PROXY)

    assert (user["primary_email"], user["display_name"]) == ("unknown@example.com", "Unknown User")


def test_proxy_mode_user_profile_requires_gateway_header():
    with pytest.raises(HTTPException) as exc_info:
        get_user(_make_request({}), None, PROXY)
    assert exc_info.value.status_code == 401


def test_proxy_mode_needs_no_stackauth_configuration():
    """get_user depends on get_auth_client; without StackAuth settings it must not crash every request."""
    request = _make_request({"X-Auth-Request-User": SUB, "Cookie": "stack-access=stale-token"})

    assert get_auth_client(request, PROXY) is None


@pytest.fixture
def proxy_socket(monkeypatch):
    """Socket.IO server in proxy mode; records joined rooms and provisioned Users."""
    import cea.interfaces.dashboard.lib.socketio as cea_socketio

    rooms, provisioned = [], []

    async def fake_enter_room(sid, room):
        rooms.append(room)

    async def fake_ensure_user_cached(user_id):
        provisioned.append(user_id)

    monkeypatch.setattr(cea_socketio, "get_settings", lambda: PROXY)
    monkeypatch.setattr(cea_socketio.sio, "enter_room", fake_enter_room)
    monkeypatch.setattr(cea_socketio, "ensure_user_cached", fake_ensure_user_cached)
    return cea_socketio, rooms, provisioned


def test_proxy_mode_socket_joins_the_users_room(proxy_socket):
    cea_socketio, rooms, provisioned = proxy_socket

    assert asyncio.run(cea_socketio.connect("sid1", {"HTTP_X_AUTH_REQUEST_USER": SUB}, None)) is True
    assert rooms == [f"user-{SUB}"]
    assert provisioned == [SUB]


def test_proxy_mode_socket_without_gateway_header_is_refused(proxy_socket):
    from socketio.exceptions import ConnectionRefusedError

    cea_socketio, rooms, provisioned = proxy_socket

    with pytest.raises(ConnectionRefusedError):
        asyncio.run(cea_socketio.connect("sid1", {}, None))
    assert rooms == [] and provisioned == []

