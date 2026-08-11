"""
tests/integration/metrics_helpers.py

Generic Prometheus counter-reading utilities shared across every
integration metrics module (test_client_metrics.py now; test_site_
metrics.py, test_contact_metrics.py, and beyond as those resource
families gain their own business metrics). Delta-based reading, not
absolute totals — counters are module-level singletons that persist
and accumulate across every test in the same process.
"""


def counter_total(counter) -> float:
    return sum(
        sample.value
        for sample in counter.collect()[0].samples
        if sample.name.endswith("_total")
    )


def counter_total_for_label(counter, **labels: str) -> float:
    for sample in counter.collect()[0].samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value
    return 0.0
