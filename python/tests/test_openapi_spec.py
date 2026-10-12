"""The mock hub against the hub's own Service API spec.

Both client suites run against mock_server.py, so a mock that has drifted from
the real hub lets a client pass CI and then fail on a live node.
openapi/service-api.json is generated from the hub (nova-hub's
export_openapi.py), and these tests hold the mock to it: the same routes, and
JSON bodies of the shape the spec says.

When the hub's Service API changes, regenerate the spec, commit it here, and
let these tests say what the mock is missing.
"""

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from .mock_server import service_app

SPEC_PATH = Path(__file__).parents[2] / "openapi" / "service-api.json"
SPEC = json.loads(SPEC_PATH.read_text())
MOCK_PREFIX = "/service/api/v1"


def _spec_routes() -> set[tuple[str, str]]:
    base = SPEC["servers"][0]["url"]
    return {
        (method.upper(), base + path)
        for path, ops in SPEC["paths"].items()
        for method in ops
    }


def _mock_routes() -> set[tuple[str, str]]:
    return {
        (method.upper(), MOCK_PREFIX + path)
        for path, ops in service_app.openapi()["paths"].items()
        for method in ops
    }


def test_spec_is_the_service_api():
    assert SPEC["info"]["title"] == "Nova Hub - Service API"
    assert SPEC["info"]["version"], "the spec should say which hub version it came from"
    assert all(path.startswith("/api/v1/") for path in SPEC["paths"])


def test_mock_serves_every_route_in_the_spec():
    missing = _spec_routes() - _mock_routes()
    assert not missing, f"in the hub's spec but not the mock: {sorted(missing)}"


def test_mock_serves_nothing_the_hub_does_not():
    extra = _mock_routes() - _spec_routes()
    assert not extra, f"in the mock but not the hub's spec: {sorted(extra)}"


# --- Response shapes ----------------------------------------------------------

def _resolve(schema: dict) -> dict:
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = SPEC["components"]["schemas"][name]
    return schema


_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _problems(value, schema: dict, where: str = "body") -> list[str]:
    """Where value does not fit schema. Enough JSON Schema for FastAPI's output.

    Stricter than JSON Schema in one way: a property the spec does not
    declare is a problem, because that is the mock inventing a field a client
    could come to rely on.
    """
    schema = _resolve(schema)
    if "anyOf" in schema:
        if any(not _problems(value, option, where) for option in schema["anyOf"]):
            return []
        return [f"{where}: {value!r} matches none of {schema['anyOf']}"]
    kind = schema.get("type")
    if kind and not _TYPES[kind](value):
        return [f"{where}: expected {kind}, got {value!r}"]
    found = []
    if kind == "object":
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                found.append(f"{where}: missing {name!r}")
        for name, item in value.items():
            if name not in properties:
                found.append(f"{where}: {name!r} is not in the spec")
            else:
                found += _problems(item, properties[name], f"{where}.{name}")
    elif kind == "array":
        for i, item in enumerate(value):
            found += _problems(item, schema.get("items", {}), f"{where}[{i}]")
    return found


def _ok_schema(method: str, path: str) -> dict:
    response = SPEC["paths"][path][method]["responses"]["200"]
    return response["content"]["application/json"]["schema"]


def _call(url: str, method: str = "GET", token: str | None = None,
          data: bytes | None = None, content_type: str | None = None):
    request = urllib.request.Request(url, data=data, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if content_type:
        request.add_header("Content-Type", content_type)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def _sign_in(url: str, config: dict) -> dict:
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
    }).encode()
    return _call(f"{url}{MOCK_PREFIX}/auth/token", "POST", data=form,
                 content_type="application/x-www-form-urlencoded")


@pytest.fixture
def signed_in(mock_server_url, test_client_config):
    """A token for the standard test client, and the token response itself."""
    body = _sign_in(mock_server_url, test_client_config)
    return body["access_token"], body


def test_token_response(signed_in):
    _, body = signed_in
    assert _problems(body, _ok_schema("post", "/api/v1/auth/token")) == []


@pytest.mark.parametrize("path", ["/api/v1/auth/verify", "/api/v1/me"])
def test_account_responses(mock_server_url, signed_in, path):
    token, _ = signed_in
    body = _call(f"{mock_server_url}{MOCK_PREFIX}{path[len('/api/v1'):]}", token=token)
    assert _problems(body, _ok_schema("get", path)) == []


def test_upload_and_list_responses(mock_server_url, multi_bbs_config):
    sender = _sign_in(mock_server_url, multi_bbs_config["bbs1"])["access_token"]
    receiver = _sign_in(mock_server_url, multi_bbs_config["bbs2"])["access_token"]
    base = f"{mock_server_url}{MOCK_PREFIX}/leagues/555B/packets"

    uploaded = _call(f"{base}/555B0102.001", "PUT", token=sender, data=b"packet",
                     content_type="application/octet-stream")
    assert _problems(
        uploaded, _ok_schema("put", "/api/v1/leagues/{league_id}/packets/{filename}")
    ) == []

    listed = _call(base, token=receiver)
    assert listed["packets"], "BBS 2 should see the packet BBS 1 sent it"
    assert _problems(listed, _ok_schema("get", "/api/v1/leagues/{league_id}/packets")) == []
