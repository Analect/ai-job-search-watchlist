"""OTel semconv opt-in — must be imported before strands to include tool I/O in spans."""
import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

# amp-instrumentation injects PYTHONPATH=_bootstrap so sitecustomize.py runs at
# Python startup (before any app code). That calls initialize_instrumentation()
# which sets TRACELOOP_METRICS_ENABLED=false and immediately calls Traceloop.init(),
# which calls BedrockInstrumentor().instrument() (_instrument()). Inside _instrument(),
# is_metrics_enabled() returns False and ALL MetricParams instruments are set to None.
# guardrail.py:179,208 then crash with AttributeError: 'NoneType'.add on any Bedrock
# response that includes guardrail metadata.
#
# Fix: after the bedrock module has been loaded (it's in sys.modules by the time
# this module runs), replace guardrail_converse and guardrail_handling in the bedrock
# module's namespace with None-safe wrappers. The wrapper closures installed by
# _instrument() look up those names via __init__.py's globals at call time, so this
# patch takes effect for all subsequent Bedrock calls without rebuilding any closures.
import opentelemetry.instrumentation.bedrock as _bdr

_orig_guardrail_converse = _bdr.guardrail_converse
_orig_guardrail_handling = _bdr.guardrail_handling


def _safe_guardrail_converse(span, response, vendor, model, metric_params):
    try:
        return _orig_guardrail_converse(span, response, vendor, model, metric_params)
    except AttributeError:
        pass  # metrics disabled; guardrail metric increments skipped


def _safe_guardrail_handling(span, response_body, vendor, model, metric_params):
    try:
        return _orig_guardrail_handling(span, response_body, vendor, model, metric_params)
    except AttributeError:
        pass  # metrics disabled; guardrail metric increments skipped


_bdr.guardrail_converse = _safe_guardrail_converse
_bdr.guardrail_handling = _safe_guardrail_handling
