"""
Shared pytest fixtures + import-time shims.

Stubs lightweight optional dependencies (structlog) that aren't strictly
needed by the unit suite, and **skips** test modules whose hard runtime
dependencies (aiosqlite, pytest-asyncio, streamlit, etc.) aren't installed —
preventing the entire collection from erroring out on a vanilla Python.

If you have all deps installed locally, the real packages take precedence
(we only stub on ImportError; we only skip on missing-import).
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _stub_structlog() -> None:
    """structlog is used by src/utils/logging_setup.py. Tests don't need real
    structured logging — a no-op shim is fine."""
    if "structlog" in sys.modules:
        return
    try:
        import structlog  # noqa: F401
    except ImportError:
        pass
    else:
        return

    mod = types.ModuleType("structlog")

    class _NoopLogger:
        def __getattr__(self, _name: str):
            return lambda *args, **kwargs: None

    def get_logger(*args, **kwargs):
        return _NoopLogger()

    def configure(*args, **kwargs):
        return None

    def make_filtering_bound_logger(level):
        return _NoopLogger

    def stdlib_get_logger(*args, **kwargs):
        return _NoopLogger()

    mod.get_logger = get_logger
    mod.configure = configure
    mod.make_filtering_bound_logger = make_filtering_bound_logger

    contextvars = types.ModuleType("structlog.contextvars")
    contextvars.merge_contextvars = lambda *a, **kw: {}
    contextvars.bind_contextvars = lambda *a, **kw: None
    contextvars.clear_contextvars = lambda: None
    mod.contextvars = contextvars

    stdlib = types.ModuleType("structlog.stdlib")
    stdlib.LoggerFactory = lambda *a, **kw: None
    stdlib.BoundLogger = _NoopLogger
    stdlib.add_log_level = lambda *a, **kw: {}
    stdlib.add_logger_name = lambda *a, **kw: {}
    stdlib.filter_by_level = lambda *a, **kw: {}
    mod.stdlib = stdlib

    processors = types.ModuleType("structlog.processors")
    processors.TimeStamper = lambda **kw: (lambda *a, **k: {})
    processors.StackInfoRenderer = lambda: (lambda *a, **k: {})
    processors.format_exc_info = lambda *a, **kw: {}
    processors.UnicodeDecoder = lambda: (lambda *a, **k: {})
    processors.JSONRenderer = lambda **kw: (lambda *a, **k: "")
    processors.KeyValueRenderer = lambda **kw: (lambda *a, **k: "")
    mod.processors = processors

    dev = types.ModuleType("structlog.dev")
    dev.ConsoleRenderer = lambda **kw: (lambda *a, **k: "")
    mod.dev = dev

    sys.modules["structlog"] = mod
    sys.modules["structlog.contextvars"] = contextvars
    sys.modules["structlog.stdlib"] = stdlib
    sys.modules["structlog.processors"] = processors
    sys.modules["structlog.dev"] = dev


_stub_structlog()


# --------------------------------------------------------------------------
# Auto-skip tests whose hard runtime deps are not installed locally.
# --------------------------------------------------------------------------

# Map test module basename → module(s) that must be importable for it to run.
_TEST_DEPS: dict[str, tuple[str, ...]] = {
    "test_database":               ("aiosqlite",),
    "test_helpers":                ("aiosqlite",),
    "test_decide":                 ("aiosqlite",),
    "test_execute":                ("aiosqlite",),
    "test_track":                  ("aiosqlite",),
    "test_end_to_end":             ("aiosqlite",),
    "test_ensemble":               ("aiosqlite",),
    "test_agents":                 ("aiosqlite",),
    "test_openrouter_client":      ("aiosqlite",),
    "test_issue9_price_field_fix": ("aiosqlite",),
    "test_issue42_price_sanity":   ("aiosqlite",),
    "test_direct_order_placement": ("aiosqlite",),
    "test_real_order_placement":   ("aiosqlite",),
    "test_live_order_execution":   ("aiosqlite",),
    # safe_compounder pulls in src.strategies.__init__ → category_scorer → aiosqlite
    "test_safe_compounder":        ("aiosqlite",),
}


def _import_ok(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def pytest_ignore_collect(collection_path, config):
    """Skip importing test modules whose hard deps are missing — otherwise
    pytest fails the entire collection on a vanilla Python install. Tests
    that DO run (no missing deps) are unaffected.
    """
    module_name = collection_path.stem
    deps = _TEST_DEPS.get(module_name)
    if not deps:
        return False
    missing = [d for d in deps if not _import_ok(d)]
    return bool(missing)


# --------------------------------------------------------------------------
# Isolate the on-disk token cache so tests don't pollute data/.
# --------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _isolate_token_cache(tmp_path_factory):
    """Point the persistent condition_id → token_ids cache at a temp dir for
    the duration of the test session. Without this, every test that calls
    `register_market()` writes to `data/token_cache.json` in the working
    tree, polluting the repo state and risking cross-test bleed-through."""
    try:
        from src.clients import polymarket_client as pmc
    except ImportError:
        return
    tmp_path = tmp_path_factory.mktemp("token_cache") / "cache.json"
    original = pmc.DEFAULT_TOKEN_CACHE_PATH
    pmc.DEFAULT_TOKEN_CACHE_PATH = tmp_path
    try:
        yield
    finally:
        pmc.DEFAULT_TOKEN_CACHE_PATH = original
