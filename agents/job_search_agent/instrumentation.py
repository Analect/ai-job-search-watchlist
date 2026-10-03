"""OTel semconv opt-in — must be imported before strands to include tool I/O in spans."""
import os

os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_latest_experimental")
