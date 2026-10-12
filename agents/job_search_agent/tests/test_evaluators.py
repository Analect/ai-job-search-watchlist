"""
Unit tests for job-search agent custom evaluators.

Tests are independent of a live AMP instance: they use fixture MockTrace objects
from tests/fixtures/traces.py that provide the interface the evaluators call:
  trace.input / trace.output / trace.get_tool_calls()

Covers:
  - no_unprompted_write: SC-009 — must flag every unprompted write, never an explicit one
  - not_found_honesty: mirrors the SWA variant; adapted for the job-search error shape

Run in debug pod (or locally — no network calls, no live AMP needed):
  kubectl cp tests/ <ns>/<pod>:/app/tests/
  kubectl cp evaluators/ <ns>/<pod>:/app/evaluators/
  kubectl exec -n <ns> <pod> -- sh -c \
    "cd /app && uv pip install --system pytest && python -m pytest tests/test_evaluators.py -v"
"""
import sys
from pathlib import Path

# Resolve agent root and evaluators to sys.path for direct import
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "evaluators"))
sys.path.insert(0, str(_ROOT / "tests"))

# ---------------------------------------------------------------------------
# Shim amp_evaluation when the library is absent
# ---------------------------------------------------------------------------

try:
    from amp_evaluation import EvalResult  # type: ignore
    _REAL_LIB = True
except ImportError:
    _REAL_LIB = False
    from dataclasses import dataclass as _dc
    import types as _types

    @_dc
    class EvalResult:  # type: ignore
        score: float = 1.0
        passed: bool = True
        explanation: str = ""
        _skipped: bool = False
        _skip_reason: str = ""

        @classmethod
        def skip(cls, reason: str = "") -> "EvalResult":
            obj = cls(score=0.0, passed=False, explanation="")
            obj._skipped = True
            obj._skip_reason = reason
            return obj

        @property
        def skipped(self) -> bool:
            return self._skipped

    _mod = _types.ModuleType("amp_evaluation")
    _mod.EvalResult = EvalResult  # type: ignore
    _trace_mod = _types.ModuleType("amp_evaluation.trace")
    _trace_models_mod = _types.ModuleType("amp_evaluation.trace.models")

    @_dc
    class _StubTrace:
        pass

    _trace_models_mod.Trace = _StubTrace  # type: ignore
    sys.modules.setdefault("amp_evaluation", _mod)
    sys.modules.setdefault("amp_evaluation.trace", _trace_mod)
    sys.modules.setdefault("amp_evaluation.trace.models", _trace_models_mod)

# ---------------------------------------------------------------------------
# Import evaluators and fixtures
# ---------------------------------------------------------------------------

import no_unprompted_write  # noqa: E402
import not_found_honesty    # noqa: E402
from fixtures.traces import (  # noqa: E402
    explicit_advance_write,
    explicit_mark_write,
    implicit_signal_no_write,
    unprompted_write,
    view_only,
    not_found_tool_honest,
    not_found_tool_fabricated,
    valid_result_no_not_found,
)

# ---------------------------------------------------------------------------
# no_unprompted_write — SC-009
# ---------------------------------------------------------------------------


def test_explicit_advance_passes():
    """User explicitly asked to advance — write is permitted."""
    result = no_unprompted_write.evaluate(explicit_advance_write)
    assert not result.skipped
    assert result.passed, f"Expected pass; got: {result.explanation}"
    assert result.score == 1.0


def test_explicit_mark_passes():
    """User said 'mark' and 'flag' — explicit intent, write permitted."""
    result = no_unprompted_write.evaluate(explicit_mark_write)
    assert not result.skipped
    assert result.passed, f"Expected pass; got: {result.explanation}"


def test_implicit_signal_no_write_skips():
    """User showed interest but mark_for_advancement was not called — skip."""
    result = no_unprompted_write.evaluate(implicit_signal_no_write)
    assert result.skipped, "Expected skip when write tool not called"


def test_unprompted_write_fails():
    """Agent wrote without any explicit intent — must fail (SC-009)."""
    result = no_unprompted_write.evaluate(unprompted_write)
    assert not result.skipped
    assert not result.passed, f"Expected fail; got: {result.explanation}"
    assert result.score == 0.0


def test_view_only_skips():
    """No write tool called — evaluator is not applicable."""
    result = no_unprompted_write.evaluate(view_only)
    assert result.skipped, "Expected skip when mark_for_advancement not called"


# ---------------------------------------------------------------------------
# not_found_honesty
# ---------------------------------------------------------------------------


def test_not_found_honest_response_passes():
    """Tool returned not-found; agent correctly acknowledged it."""
    result = not_found_honesty.evaluate(not_found_tool_honest)
    assert not result.skipped
    assert result.passed, f"Expected pass; got: {result.explanation}"
    assert result.score == 1.0


def test_not_found_fabricated_response_fails():
    """Tool returned not-found; agent fabricated details — must fail."""
    result = not_found_honesty.evaluate(not_found_tool_fabricated)
    assert not result.skipped
    assert not result.passed, f"Expected fail; got: {result.explanation}"
    assert result.score == 0.0


def test_valid_result_skips():
    """No not-found signal in tool results — evaluator not applicable."""
    result = not_found_honesty.evaluate(valid_result_no_not_found)
    assert result.skipped, "Expected skip when no not-found tool results"
