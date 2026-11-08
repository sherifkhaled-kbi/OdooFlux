"""Opt-in suite decorators (REQ-TST-006). A test is skipped unless its flag is exactly ``1``; the skip reason
names the flag. The flag is read when the test runs, not when it is defined."""

import functools
import os
import unittest

RUNTIME_FLAG = "ODOOFLUX_RUNTIME_TESTS"
AI_FLAG = "ODOOFLUX_AI_TESTS"


def enabled(flag: str) -> bool:
    return os.environ.get(flag) == "1"


def _requires(flag: str, what: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not enabled(flag):
                raise unittest.SkipTest(f"{what} test; set {flag}=1 to run")
            return func(*args, **kwargs)
        return wrapper
    return decorator


def requires_runtime(func):
    return _requires(RUNTIME_FLAG, "runtime (Docker)")(func)


def requires_ai(func):
    return _requires(AI_FLAG, "AI provider")(func)
