"""Redis Streams names and consumer policy.

Single source of truth for the queue topology. Each service imports from
here rather than re-declaring the strings, which prevents drift between
producers and consumers.
"""

# --- Stream names (producer → consumer) ----------------------------------
STREAM_RAW_EVENTS = "raw_events"   # ingress → core
STREAM_TASKS = "tasks"             # core → agents
STREAM_RESULTS = "results"         # agents → egress

# --- Dead-letter streams -------------------------------------------------
STREAM_RAW_EVENTS_DLQ = "raw_events_dlq"
STREAM_TASKS_DLQ = "tasks_dlq"
STREAM_RESULTS_DLQ = "results_dlq"

# --- Consumer policy -----------------------------------------------------
# Maximum re-deliveries per message before moving to DLQ.
MAX_DELIVERIES = 3
