"""Inspect every isolated metadata trace without printing exported content."""

import json
from collections import Counter

import mlflow
from live_acceptance_admin import ROOT
from mlflow import MlflowClient

mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'mlflow.db'}")
client = MlflowClient()
traces = []
for experiment in client.search_experiments():
    token = None
    while True:
        page = client.search_traces(
            locations=[experiment.experiment_id], max_results=100, page_token=token
        )
        traces.extend(page)
        token = page.token
        if not token:
            break
names = Counter()
statuses = Counter()
markers = [
    "ORBIT-742",
    "SECRET_TRACE_MARKER",
    "PRIVATE_TRACE_CONTENT",
    "Traceback (most recent call last)",
    "deepseek-v4.1-flash-secret",
]
for trace in traces:
    payload = trace.to_json()
    assert not any(marker in payload for marker in markers)
    for span in trace.data.spans:
        assert span.name in {"dspy.module", "dspy.lm", "dspy.tool"}
        assert not span.inputs and not span.outputs
        assert not span.events
        assert not span.status.description
        names[span.name] += 1
        statuses[str(span.status.status_code)] += 1
report = {
    "trace_count": len(traces),
    "span_names": dict(names),
    "statuses": dict(statuses),
    "marker_checks": len(markers),
    "inputs_outputs_events_status_descriptions": "absent",
}
(ROOT / "trace-privacy-results.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
