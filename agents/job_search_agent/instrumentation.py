"""OTel semconv opt-in — must be imported before strands to include tool I/O in spans."""
import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")

# Register a no-op MeterProvider before any OTel instrumentation activates.
# opentelemetry-instrumentation-bedrock (0.62.4) creates metric instruments
# (including guardrail_activation) at BedrockInstrumentor.instrument() time.
# Without a MeterProvider the instruments are None and the first Bedrock response
# event containing guardrail metadata crashes with AttributeError: 'NoneType'.
# amp-instrumentation 0.4.1 only wires a TracerProvider; this covers metrics.
from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
from opentelemetry import metrics as _otel_metrics
_otel_metrics.set_meter_provider(_MeterProvider())
