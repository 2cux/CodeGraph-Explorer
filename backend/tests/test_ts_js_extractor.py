"""Tests for TypeScript / JavaScript extractor."""

import pytest
from pathlib import Path

from codegraph.language_support.ts_js.extractor import (
    TypeScriptExtractor,
    JavaScriptExtractor,
)
from codegraph.language_support.registry import reset_registry
from codegraph.graph.models import NodeType


FIXTURES_TS = Path(__file__).parent / "fixtures" / "typescript_project"
FIXTURES_JS = Path(__file__).parent / "fixtures" / "javascript_project"


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()


# ── TypeScript Extractor Tests ──────────────────────────────────────────


class TestTypeScriptExtractor:
    """Extraction tests for TypeScript (.ts, .tsx) files."""

    def test_extract_function_declaration(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export function hello(name: string): string { return 'Hi'; }",
            project_root="/tmp",
        )
        assert result.language_id == "typescript"
        names = [s.name for s in result.symbols]
        assert "hello" in names
        hello = next(s for s in result.symbols if s.name == "hello")
        assert hello.type == NodeType.function

    def test_extract_class_declaration(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export class Button { label: string; constructor(label: string) { this.label = label; } handleClick() { this.doStuff(); } }",
            project_root="/tmp",
        )
        assert result.language_id == "typescript"
        names = [s.name for s in result.symbols]
        assert "Button" in names

    def test_extract_interface_declaration(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export interface User { id: number; name: string; }",
            project_root="/tmp",
        )
        names = [s.name for s in result.symbols]
        assert "User" in names

    def test_extract_type_alias(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export type ID = string | number;",
            project_root="/tmp",
        )
        names = [s.name for s in result.symbols]
        assert "ID" in names

    def test_extract_default_export(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export default function App() { return null; }",
            project_root="/tmp",
        )
        exports = result.exports
        defaults = [e for e in exports if e.is_default]
        assert len(defaults) >= 1

    def test_extract_named_export(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export function hello() {}\nexport const Arrow = () => {};",
            project_root="/tmp",
        )
        export_names = [e.name for e in result.exports]
        assert "hello" in export_names

    def test_extract_default_import(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content='import React from "react";',
            project_root="/tmp",
        )
        imps = result.imports
        assert any(i.local_name == "React" and i.imported_name == "default" for i in imps)

    def test_extract_named_import(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content='import { useState, useEffect } from "react";',
            project_root="/tmp",
        )
        local_names = [i.local_name for i in result.imports]
        assert "useState" in local_names

    def test_extract_namespace_import(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content='import * as React from "react";',
            project_root="/tmp",
        )
        imps = result.imports
        assert any(i.imported_name == "*" for i in imps)

    def test_extract_relative_import(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="src/test.ts",
            content='import { Button } from "./components/Button";',
            project_root="/tmp",
        )
        imps = result.imports
        assert any(not i.is_external and i.module_path.startswith("./") for i in imps)

    def test_package_import_is_external(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content='import lodash from "lodash";\nimport { useState } from "react";',
            project_root="/tmp",
        )
        for i in result.imports:
            assert i.is_external

    def test_this_method_call(self):
        ext = TypeScriptExtractor()
        code = '''
export class Button {
  handleClick() { this.logClick(); }
  logClick() {}
}
'''
        result = ext.extract(file_path="test.ts", content=code, project_root="/tmp")
        this_calls = [c for c in result.calls if "this." in c.target_expression]
        assert len(this_calls) >= 1

    def test_barrel_export(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content='export * from "./components/Button";',
            project_root="/tmp",
        )
        barrel = [e for e in result.exports if e.name == "*"]
        assert len(barrel) >= 1

    def test_language_id_on_all_symbols(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export function hello() {}\nexport const x = 1;",
            project_root="/tmp",
        )
        for s in result.symbols:
            assert s.language_id == "typescript"
            assert s.metadata.get("support_level") == "beta"

    def test_empty_file(self):
        ext = TypeScriptExtractor()
        result = ext.extract(file_path="empty.ts", content="", project_root="/tmp")
        assert result.language_id == "typescript"
        assert len(result.diagnostics) == 0

    def test_parser_error_diagnostic(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="broken.ts",
            content="this is not valid typescript @@@",
            project_root="/tmp",
        )
        # Should not raise; diagnostics may be produced
        assert result.language_id == "typescript"

    def test_arrow_function(self):
        ext = TypeScriptExtractor()
        result = ext.extract(
            file_path="test.ts",
            content="export const Arrow = () => { return 1; };",
            project_root="/tmp",
        )
        names = [s.name for s in result.symbols]
        assert "Arrow" in names


# ── JavaScript Extractor Tests ──────────────────────────────────────────


class TestJavaScriptExtractor:
    """Extraction tests for JavaScript (.js, .jsx, .mjs, .cjs) files."""

    def test_extract_function_declaration(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="function hello(name) { return 'Hi ' + name; }",
            project_root="/tmp",
        )
        assert result.language_id == "javascript"
        names = [s.name for s in result.symbols]
        assert "hello" in names

    def test_extract_class(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="class Button { handleClick() { this.logClick(); } }",
            project_root="/tmp",
        )
        names = [s.name for s in result.symbols]
        assert "Button" in names

    def test_commonjs_require(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content='const helpers = require("./utils/helpers");',
            project_root="/tmp",
        )
        imps = result.imports
        assert any("helpers" in i.local_name for i in imps)

    def test_commonjs_exports_foo(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content='exports.hello = function(name) { return "Hi"; };',
            project_root="/tmp",
        )
        assert len(result.exports) >= 1

    def test_commonjs_module_exports(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="module.exports = { hello, Button };",
            project_root="/tmp",
        )
        exports = result.exports
        assert any(e.is_default for e in exports)

    def test_es_import(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content='import { useState } from "react";',
            project_root="/tmp",
        )
        assert len(result.imports) >= 1

    def test_es_export(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="export function hello() {}\nexport const x = 1;",
            project_root="/tmp",
        )
        assert len(result.exports) >= 1

    def test_arrow_function(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="const Arrow = () => {};",
            project_root="/tmp",
        )
        names = [s.name for s in result.symbols]
        assert "Arrow" in names

    def test_language_id_on_all_symbols(self):
        ext = JavaScriptExtractor()
        result = ext.extract(
            file_path="test.js",
            content="function hello() {}\nconst x = 1;",
            project_root="/tmp",
        )
        for s in result.symbols:
            assert s.language_id == "javascript"
            assert s.metadata.get("support_level") == "beta"


# ── Fixture-based integration tests ─────────────────────────────────────


class TestTypeScriptFixture:
    """End-to-end extraction of the TypeScript fixture project."""

    def test_extract_fixture_components_button(self):
        ext = TypeScriptExtractor()
        f = FIXTURES_TS / "src" / "components" / "Button.tsx"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_TS))
        assert result.language_id == "typescript"
        names = {s.name for s in result.symbols}
        assert "Button" in names
        assert "handleClick" in names

    def test_extract_fixture_utils_helpers(self):
        ext = TypeScriptExtractor()
        f = FIXTURES_TS / "src" / "utils" / "helpers.ts"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_TS))
        names = {s.name for s in result.symbols}
        assert "generateId" in names
        assert "validateId" in names

    def test_extract_fixture_services_api_imports(self):
        ext = TypeScriptExtractor()
        f = FIXTURES_TS / "src" / "services" / "api.ts"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_TS))
        # Should have at least 3 imports: formatDate, generateId, validateId, Button, ID, React
        assert len(result.imports) >= 3

    def test_extract_fixture_barrel_index(self):
        ext = TypeScriptExtractor()
        f = FIXTURES_TS / "src" / "index.ts"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_TS))
        barrels = [e for e in result.exports if e.name == "*"]
        assert len(barrels) >= 1


class TestJavaScriptFixture:
    """End-to-end extraction of the JavaScript fixture project."""

    def test_extract_fixture_index_commonjs(self):
        ext = JavaScriptExtractor()
        f = FIXTURES_JS / "src" / "index.js"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_JS))
        assert result.language_id == "javascript"
        # Should have require() imports
        assert len(result.imports) >= 2

    def test_extract_fixture_commonjs_lib(self):
        ext = JavaScriptExtractor()
        f = FIXTURES_JS / "src" / "lib" / "commonjs.js"
        result = ext.extract(file_path=str(f), project_root=str(FIXTURES_JS))
        names = {s.name for s in result.symbols}
        assert "buildPath" in names
        assert "createServer" in names
