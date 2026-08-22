"""Tests for Vite manifest CSS collection.

Vendor chunks (katex, hljs) carry their own CSS since the bundle split -
the index route must inject every stylesheet reachable from the entry's
static import graph, not just the entry's own CSS.
"""

from src.utils.assets import collect_entry_css


def test_entry_only_css() -> None:
    manifest = {
        "src/main.ts": {"file": "main-abc.js", "isEntry": True, "css": ["main-abc.css"]},
    }
    assert collect_entry_css(manifest, "src/main.ts") == ["main-abc.css"]


def test_collects_css_from_imported_chunks() -> None:
    manifest = {
        "src/main.ts": {
            "file": "main-abc.js",
            "isEntry": True,
            "css": ["main-abc.css"],
            "imports": ["_vendor-katex-x.js", "_vendor-hljs-y.js"],
        },
        "_vendor-katex-x.js": {"file": "vendor-katex-x.js", "css": ["vendor-katex-x.css"]},
        "_vendor-hljs-y.js": {"file": "vendor-hljs-y.js", "css": ["vendor-hljs-y.css"]},
    }
    css = collect_entry_css(manifest, "src/main.ts")
    # Vendor CSS first so app styles keep the last word; entry CSS last
    assert css == ["vendor-katex-x.css", "vendor-hljs-y.css", "main-abc.css"]


def test_walks_nested_imports_and_survives_cycles() -> None:
    manifest = {
        "src/main.ts": {"file": "main.js", "isEntry": True, "imports": ["_a.js"]},
        "_a.js": {"file": "a.js", "css": ["a.css"], "imports": ["_b.js"]},
        "_b.js": {"file": "b.js", "css": ["b.css"], "imports": ["_a.js"]},
    }
    # Deeper dependencies first so dependents override in the cascade
    assert collect_entry_css(manifest, "src/main.ts") == ["b.css", "a.css"]


def test_deduplicates_shared_css() -> None:
    manifest = {
        "src/main.ts": {"file": "main.js", "isEntry": True, "imports": ["_a.js", "_b.js"]},
        "_a.js": {"file": "a.js", "css": ["shared.css"]},
        "_b.js": {"file": "b.js", "css": ["shared.css"]},
    }
    assert collect_entry_css(manifest, "src/main.ts") == ["shared.css"]


def test_missing_entry_returns_empty() -> None:
    assert collect_entry_css({}, "src/main.ts") == []


def test_ignores_dynamic_imports() -> None:
    # Dynamically imported chunks load their own CSS at import time
    manifest = {
        "src/main.ts": {
            "file": "main.js",
            "isEntry": True,
            "css": ["main.css"],
            "dynamicImports": ["src/components/SettingsPopup.ts"],
        },
        "src/components/SettingsPopup.ts": {"file": "settings.js", "css": ["settings.css"]},
    }
    assert collect_entry_css(manifest, "src/main.ts") == ["main.css"]
