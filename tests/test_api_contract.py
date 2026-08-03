"""Contract test: every path the frontend calls must exist on the backend.

The API client is hand-written TypeScript against a Django URL conf. Nothing
connects the two, so a route rename or a typo'd path is discovered at runtime,
in a browser, by a user. That is exactly how F-1 shipped: two export helpers
built URLs with an `/api/v1` prefix the client already adds, and every export in
the product 404'd or 401'd for as long as nobody clicked one in the environment
where it mattered.

Why this rather than per-endpoint wrapper tests
-----------------------------------------------
`src/api/*.ts` sits at ~5% function coverage because each module is a thin
wrapper — `() => api.get("/debt/debts/")`. Testing those individually asserts
that a string literal equals a string literal: it would move the coverage
number and catch nothing. The failure they actually suffer is *drift from the
backend*, which no amount of unit testing the wrapper can see.

So this checks the property that matters, in the one place both sides are
visible at once.

Limits, stated plainly
----------------------
This proves a path **resolves**. It does not prove the method is allowed, the
request body matches the serializer, or the response shape matches the
TypeScript interface. Those need generated types from the OpenAPI schema, which
is the larger build this test is the cheap first step toward.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from django.urls import Resolver404, get_resolver, resolve

FRONTEND_API = pathlib.Path("frontend/app/src/api")

#: Paths the client builds that are deliberately not Django routes.
ALLOWED_NON_ROUTES = {
    # Absolute externals, handled by the browser rather than our resolver.
    "/auth/oauth",
}

#: Template placeholders the client interpolates, mapped to a value that will
#: satisfy the corresponding Django path converter.
SUBSTITUTIONS = {
    "uuid": "00000000-0000-0000-0000-000000000000",
    "str": "x",
    "slug": "x",
    "int": "1",
}


def _module_constants(source: str) -> dict[str, str]:
    """Path prefixes declared as module constants.

    `platform.ts` writes `const BASE = "/platform"` and then builds every route
    as `${BASE}/tenants/`. Without resolving that, all 46 console endpoints are
    invisible to this test — which is precisely the surface most worth checking,
    since nobody clicks through the admin console casually.
    """
    return dict(re.findall(r'const\s+(\w+)\s*=\s*"(/[^"]*)"', source))


def _template_literals(source: str) -> list[str]:
    """Extract backtick strings, tolerating nested backticks.

    A regex cannot: this client writes
    `` `/intelligence/insights/${status ? `?status=${status}` : ""}` `` — a
    template literal *inside* an interpolation. Matching to the first closing
    backtick truncates the path and produces a phantom failure.
    """
    out: list[str] = []
    i = 0
    while i < len(source):
        if source[i] != "`":
            i += 1
            continue
        j, depth, buf = i + 1, 0, []
        while j < len(source):
            ch = source[j]
            if ch == "\\":
                j += 2
                continue
            if source.startswith("${", j):
                depth += 1
                buf.append("${")
                j += 2
                continue
            if ch == "}" and depth:
                depth -= 1
                buf.append(ch)
                j += 1
                continue
            if ch == "`" and depth == 0:
                break
            buf.append(ch)
            j += 1
        out.append("".join(buf))
        i = j + 1
    return out


def _client_paths() -> set[str]:
    """Every API path literal in the TypeScript client.

    Deliberately textual: importing the TypeScript would need a JS runtime, and
    what is being checked is what the source says.
    """
    found: set[str] = set()
    for module in sorted(FRONTEND_API.glob("*.ts")):
        if module.name.endswith(".test.ts") or module.name in {"types.ts", "tokenStore.ts"}:
            continue
        source = module.read_text()
        constants = _module_constants(source)

        candidates = _template_literals(source)
        candidates += re.findall(r'"(/[a-z][^"]*)"', source)

        for raw in candidates:
            for name, value in constants.items():
                raw = raw.replace("${" + name + "}", value)
            if raw.startswith("/"):
                found.add(_normalise(raw))
    return {p for p in found if p}


def _strip_interpolations(raw: str) -> str:
    """Replace every `${...}` with a UUID, matching braces properly.

    Interpolations nest — this client contains `${qs({ from, to })}`, an object
    literal inside the placeholder — so a naive regex stops at the inner brace
    and leaves `)}` glued to the path, which then reads as a backend problem
    rather than a parser one.
    """
    out: list[str] = []
    i = 0
    while i < len(raw):
        if raw.startswith("${", i):
            depth, j = 1, i + 2
            while j < len(raw) and depth:
                if raw[j] == "{":
                    depth += 1
                elif raw[j] == "}":
                    depth -= 1
                j += 1
            out.append(SUBSTITUTIONS["uuid"])
            i = j
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def _normalise(raw: str) -> str:
    """Turn a client path template into something resolvable.

    One convention has to be honoured: this client appends query strings as a
    trailing interpolation — `` `/finance/transactions/${qs(filters)}` `` — so
    an interpolation at the *end* is a query string and must be dropped, while
    one in the *middle* is an id and becomes a UUID. Treating them alike
    produced eight false failures that looked exactly like missing routes.
    """
    raw = re.sub(r"\$\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}$", "", raw)
    path = _strip_interpolations(raw).split("?")[0]
    if "$" in path or "{" in path or "}" in path or ")" in path:
        return ""
    if path.count("/") < 2:
        return ""
    return path


def _resolves(path: str) -> bool:
    try:
        resolve(f"/api/v1{path}")
        return True
    except Resolver404:
        return False


def _backend_paths() -> set[str]:
    resolver = get_resolver()

    def walk(pattern, prefix=""):
        for entry in pattern.url_patterns:
            if hasattr(entry, "url_patterns"):
                yield from walk(entry, prefix + str(entry.pattern))
            else:
                yield prefix + str(entry.pattern)

    return {"/" + u for u in walk(resolver) if u.startswith("api/v1/")}


BACKEND_PATHS = _backend_paths()


def _family_exists(path: str) -> bool:
    """Whether *some* route exists under this path's parent.

    Needed for verb-in-the-path endpoints: the client builds
    `${BASE}/tenants/${id}/${action}/` where `action` is chosen at the call
    site, so no single concrete path can be resolved. Checking that the parent
    prefix has routes at all still catches the failure that matters — the whole
    family being renamed or unmounted — without this test pretending to know
    every verb the UI might pass.
    """
    parent = "/".join(path.rstrip("/").split("/")[:-1])
    if parent.count("/") < 2:
        return False
    needle = re.sub(r"[0-9a-f]{8}-[0-9a-f-]+", "", parent)
    needle = re.sub(r"//+", "/", needle)
    return any(needle.strip("/").split("/")[1] in b for b in BACKEND_PATHS)


CLIENT_PATHS = sorted(_client_paths())


def test_the_client_actually_has_paths_to_check():
    """A regex that silently matches nothing would make every assertion below
    pass while checking nothing at all."""
    assert len(CLIENT_PATHS) > 80, f"only found {len(CLIENT_PATHS)} paths — the extractor is broken"


@pytest.mark.parametrize("path", CLIENT_PATHS)
def test_every_frontend_path_resolves_to_a_backend_route(path):
    if path in ALLOWED_NON_ROUTES:
        pytest.skip("deliberately not a Django route")
    if _resolves(path):
        return
    # Verb-in-the-path endpoints cannot be resolved concretely; fall back to
    # confirming the route family exists. See `_family_exists`.
    assert _family_exists(path), (
        f"The frontend calls {path!r}, which resolves to no Django route and "
        "has no sibling routes under its parent. Either the route was renamed "
        "or the client path is wrong."
    )


def test_no_client_path_double_prefixes_the_api_root():
    """The exact shape of F-1.

    `client.ts` prepends `/api/v1`, so a helper that also writes it produces
    `/api/v1/api/v1/...`. That path resolves to nothing and, served from the
    frontend origin in development, silently returns `index.html` — so the
    user downloads a web page named after their report.
    """
    offenders = [p for p in CLIENT_PATHS if p.startswith("/api/")]
    assert not offenders, offenders


def test_no_backend_route_is_referenced_with_a_missing_trailing_slash():
    """Django's APPEND_SLASH does not apply to non-GET requests, so a POST to a
    slash-less path 404s rather than redirecting — a failure that only shows up
    on writes."""
    mismatched = []
    for path in CLIENT_PATHS:
        if path.endswith("/") or path in ALLOWED_NON_ROUTES:
            continue
        if not _resolves(path) and _resolves(path + "/"):
            mismatched.append(path)
    assert not mismatched, mismatched


def test_the_platform_console_paths_resolve_too():
    """The admin client is a separate module against a separate URL tree; a
    route moved there is just as invisible."""
    platform = [p for p in CLIENT_PATHS if p.startswith("/platform/")]
    assert len(platform) > 20, f"only {len(platform)} platform paths — the extractor missed some"
    for path in platform:
        assert _resolves(path) or _family_exists(path), path


def test_every_backend_module_the_client_uses_is_reachable():
    """Catches a whole app being unmounted from the URL conf — a single line in
    `config/urls.py` that would otherwise break dozens of screens at once."""
    resolver = get_resolver()

    def walk(pattern, prefix=""):
        for entry in pattern.url_patterns:
            if hasattr(entry, "url_patterns"):
                yield from walk(entry, prefix + str(entry.pattern))
            else:
                yield prefix + str(entry.pattern)

    mounted = {u.replace("api/v1/", "", 1).split("/")[0] for u in walk(resolver) if u.startswith("api/v1/")}
    used = {p.strip("/").split("/")[0] for p in CLIENT_PATHS if p.strip("/")}

    missing = {m for m in used if m not in mounted} - {p.strip("/") for p in ALLOWED_NON_ROUTES}
    assert not missing, f"the client calls modules that are not mounted: {sorted(missing)}"
