import os

# Tests must never download pricing data or send telemetry on import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "1")
