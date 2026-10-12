"""OTel semconv opt-in — must be imported before strands to include tool I/O in spans."""
import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

# amp-instrumentation explicitly sets TRACELOOP_METRICS_ENABLED=false before
# calling Traceloop.init() (lazy, on first request). opentelemetry-instrumentation-
# bedrock 0.62.4 reads that env var in is_metrics_enabled() and, when False, sets
# ALL metric instruments to None instead of NoOp objects. guardrail.py:179 then
# crashes with AttributeError: 'NoneType'.add when Bedrock returns guardrail metadata.
#
# Fix: patch is_metrics_enabled in the bedrock module to always return True. This
# runs at import time (server startup), before the lazy init fires on first request.
# With metrics enabled, _create_metrics() runs and create_counter() calls use our
# MeterProvider below — producing real (functional) counter objects.
from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
from opentelemetry import metrics as _otel_metrics
_otel_metrics.set_meter_provider(_MeterProvider())

import opentelemetry.instrumentation.bedrock as _bdr_module
_bdr_module.is_metrics_enabled = lambda: True
