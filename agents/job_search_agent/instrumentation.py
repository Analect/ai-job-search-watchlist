"""OTel semconv opt-in — must be imported before strands to include tool I/O in spans."""
import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

# amp-instrumentation explicitly sets TRACELOOP_METRICS_ENABLED=false before
# calling Traceloop.init() (lazy, on first request). opentelemetry-instrumentation-
# bedrock 0.62.4 reads that env var in is_metrics_enabled() and, when False, sets
# ALL metric instruments to None instead of NoOp objects. guardrail.py:179 then
# crashes with AttributeError: 'NoneType'.add when Bedrock returns guardrail metadata.
#
# Fix: register a post-import hook (via wrapt, a transitive OTel dep) that patches
# is_metrics_enabled to always return True when the bedrock module is imported.
# wrapt.register_post_import_hook fires immediately if the module is already present,
# or defers until it is imported — so this is safe regardless of import order and does
# NOT import the bedrock module eagerly (which causes a startup hang on this image).
from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
from opentelemetry import metrics as _otel_metrics
_otel_metrics.set_meter_provider(_MeterProvider())

import wrapt as _wrapt

def _patch_bedrock_metrics(module):
    module.is_metrics_enabled = lambda: True

_wrapt.register_post_import_hook(_patch_bedrock_metrics, 'opentelemetry.instrumentation.bedrock')
