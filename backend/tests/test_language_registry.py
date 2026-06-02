"""Tests for LanguageRegistry — extension matching, enable/disable, etc."""

import pytest

from codegraph.language_support.registry import (
    SupportLevel,
    LanguageRegistration,
    LanguageRegistry,
    get_registry,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_registry()
    yield
    reset_registry()


class TestLanguageRegistration:
    def test_defaults(self):
        reg = LanguageRegistration(language_id="python")
        assert reg.language_id == "python"
        assert reg.extensions == []
        assert reg.filenames == []
        assert reg.support_level == SupportLevel.PRODUCTION
        assert reg.enabled is True

    def test_full(self):
        reg = LanguageRegistration(
            language_id="typescript",
            extensions=[".ts", ".tsx"],
            filenames=["tsconfig.json"],
            support_level=SupportLevel.BETA,
            enabled=False,
        )
        assert reg.language_id == "typescript"
        assert reg.extensions == [".ts", ".tsx"]
        assert reg.filenames == ["tsconfig.json"]
        assert reg.support_level == SupportLevel.BETA
        assert reg.enabled is False

    def test_extension_normalized_on_register(self):
        reg = LanguageRegistration(
            language_id="python", extensions=["py", "pyi"]
        )
        lr = LanguageRegistry()
        lr.register(reg)
        # Extensions without leading dot should still match
        assert lr.detect("test.py") == "python"
        assert lr.detect("stub.pyi") == "python"


class TestLanguageRegistry:
    def test_empty_registry(self):
        lr = LanguageRegistry()
        assert len(lr) == 0
        assert lr.detect("test.py") is None
        assert lr.is_supported("test.py") is False
        assert lr.list_enabled() == []

    def test_register_and_detect_extension(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        assert lr.detect("src/app/auth.py") == "python"
        assert lr.detect("/absolute/path/to/file.py") == "python"
        assert lr.detect("file.py") == "python"

    def test_detect_unsupported_extension(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        assert lr.detect("README.md") is None
        assert lr.detect("main.js") is None
        assert lr.detect("image.png") is None

    def test_detect_without_extension(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        assert lr.detect("Dockerfile") is None
        assert lr.detect("Makefile") is None

    def test_register_and_detect_filename(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"], filenames=["pyproject.toml", "setup.py"]
        ))
        assert lr.detect("pyproject.toml") == "python"
        assert lr.detect("setup.py") == "python"  # extension match wins
        assert lr.detect("other.py") == "python"

    def test_detect_disabled_language(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"], enabled=False
        ))
        assert lr.detect("test.py") is None
        assert lr.is_supported("test.py") is False

    def test_enable_disable(self):
        lr = LanguageRegistry()
        reg = LanguageRegistration(
            language_id="python", extensions=[".py"]
        )
        lr.register(reg)

        assert lr.detect("file.py") == "python"

        reg.enabled = False
        lr.register(reg)  # re-register to update maps
        assert lr.detect("file.py") is None

        reg.enabled = True
        lr.register(reg)
        assert lr.detect("file.py") == "python"

    def test_is_supported(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        assert lr.is_supported("main.py") is True
        assert lr.is_supported("main.js") is False

    def test_get_existing(self):
        lr = LanguageRegistry()
        reg = LanguageRegistration(language_id="python", extensions=[".py"])
        lr.register(reg)
        assert lr.get("python") is reg

    def test_get_nonexistent(self):
        lr = LanguageRegistry()
        assert lr.get("typescript") is None

    def test_list_enabled(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"], enabled=True
        ))
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts"], enabled=False
        ))
        enabled = lr.list_enabled()
        assert len(enabled) == 1
        assert enabled[0].language_id == "python"

    def test_list_all_includes_disabled(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"], enabled=True
        ))
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts"], enabled=False
        ))
        assert len(lr.list_all()) == 2

    def test_language_ids_returns_enabled(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"], enabled=True
        ))
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts"], enabled=False
        ))
        assert lr.language_ids() == ["python"]

    def test_contains(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(language_id="python", extensions=[".py"]))
        assert "python" in lr
        assert "typescript" not in lr

    def test_unregister(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        assert lr.detect("test.py") == "python"
        lr.unregister("python")
        assert lr.detect("test.py") is None
        assert len(lr) == 0

    def test_multiple_languages(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts", ".tsx"]
        ))
        assert lr.detect("file.py") == "python"
        assert lr.detect("file.ts") == "typescript"
        assert lr.detect("component.tsx") == "typescript"
        assert lr.detect("README.md") is None

    def test_unsupported_file_returns_none_not_error(self):
        """Unsupported files must return None, not raise."""
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"]
        ))
        # These should all return None without error
        assert lr.detect("file.js") is None
        assert lr.detect("file.rb") is None
        assert lr.detect("Makefile") is None
        assert lr.detect("") is None

    def test_support_level_values(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="python", extensions=[".py"],
            support_level=SupportLevel.PRODUCTION,
        ))
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts"],
            support_level=SupportLevel.BETA, enabled=False,
        ))
        assert lr.get("python").support_level == SupportLevel.PRODUCTION
        assert lr.get("typescript").support_level == SupportLevel.BETA


class TestTypeScriptJavaScriptDetection:
    """Phase 2: TypeScript / JavaScript beta support."""

    def test_detect_typescript_ts(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts", ".tsx"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/components/Button.ts") == "typescript"

    def test_detect_typescript_tsx(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts", ".tsx"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/components/Button.tsx") == "typescript"

    def test_detect_javascript_js(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="javascript", extensions=[".js", ".jsx", ".mjs", ".cjs"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/index.js") == "javascript"

    def test_detect_javascript_jsx(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="javascript", extensions=[".js", ".jsx", ".mjs", ".cjs"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/App.jsx") == "javascript"

    def test_detect_javascript_mjs(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="javascript", extensions=[".js", ".jsx", ".mjs", ".cjs"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/module.mjs") == "javascript"

    def test_detect_javascript_cjs(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="javascript", extensions=[".js", ".jsx", ".mjs", ".cjs"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.detect("src/module.cjs") == "javascript"

    def test_ts_support_level_beta(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts", ".tsx"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.get("typescript").support_level == SupportLevel.BETA

    def test_js_support_level_beta(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="javascript", extensions=[".js", ".jsx", ".mjs", ".cjs"],
            support_level=SupportLevel.BETA,
        ))
        assert lr.get("javascript").support_level == SupportLevel.BETA

    def test_unsupported_extension_returns_none(self):
        lr = LanguageRegistry()
        lr.register(LanguageRegistration(
            language_id="typescript", extensions=[".ts", ".tsx"]
        ))
        assert lr.detect("README.md") is None
        assert lr.detect("main.py") is None
        assert lr.detect("Dockerfile") is None

    def test_default_singleton_includes_ts_js(self):
        reset_registry()
        reg = get_registry()
        assert reg.detect("app.ts") == "typescript"
        assert reg.detect("app.tsx") == "typescript"
        assert reg.detect("app.js") == "javascript"
        assert reg.detect("app.jsx") == "javascript"
        assert reg.detect("app.mjs") == "javascript"
        assert reg.detect("app.cjs") == "javascript"
        assert reg.get("typescript").support_level == SupportLevel.BETA
        assert reg.get("javascript").support_level == SupportLevel.BETA
        assert reg.get("python").support_level == SupportLevel.PRODUCTION


class TestSingletonRegistry:
    def test_get_registry_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_default_registration_includes_python(self):
        reg = get_registry()
        assert reg.detect("test.py") == "python"
        assert reg.detect("stub.pyi") == "python"

    def test_reset_registry_clears_state(self):
        r1 = get_registry()
        r1.register(LanguageRegistration(language_id="custom", extensions=[".custom"]))
        reset_registry()
        r2 = get_registry()
        # After reset, only the default Python registration should exist
        assert "custom" not in r2
        assert "python" in r2
