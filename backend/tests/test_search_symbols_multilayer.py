"""Regression tests for multilayer symbol search."""

from __future__ import annotations

import json

import pytest

from codegraph.storage.sqlite_store import SqliteStore


def _node(
    symbol_id: str,
    name: str,
    *,
    type: str = "function",
    file_path: str = "app/api/auth.py",
    qualified_name: str | None = None,
    docstring: str | None = None,
    signature: str | None = None,
    tags: list[str] | None = None,
    line: int = 10,
) -> dict:
    return {
        "id": symbol_id,
        "type": type,
        "name": name,
        "qualified_name": qualified_name or f"app.{name}",
        "display_name": name,
        "file_path": file_path,
        "module": file_path.removesuffix(".py").replace("/", "."),
        "language": "python",
        "location": {"line_start": line, "line_end": line + 2},
        "signature": signature,
        "docstring": docstring,
        "code_preview": None,
        "visibility": "public",
        "tags": tags or [],
        "metadata": {},
    }


@pytest.fixture
def search_store(tmp_path):
    store = SqliteStore(tmp_path / "index.sqlite")
    store.initialize()
    store.save_nodes([
        _node(
            "app/api/auth.py::login",
            "login",
            qualified_name="app.api.auth.login",
            docstring="Authenticate a user and issue a session token.",
            signature="(username: str, password: str) -> str",
            tags=["route", "auth"],
            line=20,
        ),
        _node(
            "app/services/auth_service.py::login",
            "login",
            file_path="app/services/auth_service.py",
            qualified_name="app.services.auth_service.login",
            docstring="Service login workflow.",
            tags=["service"],
            line=30,
        ),
        _node(
            "app/api/auth.py::__init__",
            "__init__",
            file_path="app/api/auth.py",
            qualified_name="app.api.auth.__init__",
            line=1,
        ),
        _node(
            "tests/test_auth.py::test_login",
            "test_login",
            type="test",
            file_path="tests/test_auth.py",
            qualified_name="tests.test_auth.test_login",
            tags=["test"],
            line=5,
        ),
        _node(
            "external_lib.login",
            "login",
            type="external_symbol",
            file_path="",
            qualified_name="external_lib.login",
        ),
        _node(
            "app/models/user.py::User",
            "User",
            type="class",
            file_path="app/models/user.py",
            qualified_name="app.models.user.User",
            docstring="Domain profile object.",
            tags=["model"],
        ),
    ])
    yield store
    store.close()


def _ids(result: dict) -> list[str]:
    return [item["symbol_id"] for item in result["results"]]


def test_exact_symbol_id_priority(search_store):
    result = search_store.search_symbols("app/api/auth.py::login")
    assert result["results"][0]["symbol_id"] == "app/api/auth.py::login"
    assert "exact_symbol_id" in result["results"][0]["match_sources"]
    assert result["results"][0]["score"] == 1.0


def test_exact_name_priority_over_fuzzy(search_store):
    result = search_store.search_symbols("login")
    assert result["results"][0]["name"] == "login"
    assert "exact_name" in result["results"][0]["match_sources"]
    assert "fuzzy_name" not in result["results"][0]["match_sources"]


def test_fts_hits_name_path_docstring_and_tags(search_store):
    by_name = search_store.search_symbols("User")
    assert any("fts_name" in r["match_sources"] or "exact_name" in r["match_sources"] for r in by_name["results"])

    by_path = search_store.search_symbols("services")
    assert any("fts_path" in r["match_sources"] for r in by_path["results"])

    by_docstring = search_store.search_symbols("session")
    assert any("fts_docstring" in r["match_sources"] for r in by_docstring["results"])

    by_tags = search_store.search_symbols("route")
    assert any("fts_tags" in r["match_sources"] for r in by_tags["results"])


def test_like_fallback_when_fts_disabled(search_store):
    result = search_store.search_symbols("session", use_fts=False)
    assert "app/api/auth.py::login" in _ids(result)
    assert any("like_docstring" in r["match_sources"] for r in result["results"])


def test_fuzzy_fallback_only_after_earlier_layers_miss(search_store):
    exact = search_store.search_symbols("login")
    assert all("fuzzy_name" not in r["match_sources"] for r in exact["results"])

    fuzzy = search_store.search_symbols("logn")
    assert "app/api/auth.py::login" in _ids(fuzzy)
    assert any("fuzzy_name" in r["match_sources"] for r in fuzzy["results"])


def test_init_test_and_external_do_not_preempt(search_store):
    result = search_store.search_symbols("login")
    assert result["results"][0]["symbol_id"] != "tests/test_auth.py::test_login"
    assert result["results"][0]["symbol_id"] != "external_lib.login"
    assert result["results"][0]["name"] != "__init__"
    assert "external_lib.login" not in _ids(result)


def test_filters_type_path_prefix_layer_and_external(search_store):
    type_result = search_store.search_symbols("login", types=["test"])
    assert _ids(type_result) == ["tests/test_auth.py::test_login"]

    prefix_result = search_store.search_symbols("login", path_prefix="app/services")
    assert _ids(prefix_result)[0] == "app/services/auth_service.py::login"

    layer_result = search_store.search_symbols("login", layer="service")
    assert all(r["layer"] == "service" for r in layer_result["results"])

    external_result = search_store.search_symbols("login", exclude_external=False)
    assert "external_lib.login" in _ids(external_result)


def test_min_score_limit_max_and_ambiguous(search_store):
    limited = search_store.search_symbols("login", limit=1000)
    assert limited["total"] <= 100
    assert len(limited["results"]) <= 100

    min_score = search_store.search_symbols("login", min_score=0.95)
    assert all(r["score"] >= 0.95 for r in min_score["results"])

    ambiguous = search_store.search_symbols("login")
    assert ambiguous["ambiguous"] is True
    assert ambiguous["warning"] == "Ambiguous symbol match. Use symbol_id for exact lookup."
    assert len(ambiguous["candidates"]) >= 2


def test_compact_fields_are_small(search_store):
    result = search_store.search_symbols("login", limit=1)
    compact = {
        key: result["results"][0][key]
        for key in (
            "symbol_id", "name", "type", "file_path", "line_start",
            "line_end", "score", "match_sources", "layer",
        )
    }
    assert "docstring" not in compact
    assert "signature" not in compact
    assert json.dumps(compact)
