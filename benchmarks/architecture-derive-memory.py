#!/usr/bin/env python3
"""Add arithmetic RSS views without changing any original measurements.

The original incremental_peak_rss_bytes remains peak minus baseline high-water.
The additional field is peak minus pre-parse current RSS. Both use the same
already-measured numbers, so no new parser measurement or rerun is implied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics

FIELD = "incremental_peak_over_current_rss_bytes"


def derive(data):
    for workload in data["workloads"].values():
        for variant, samples in workload["samples"].items():
            for sample in samples:
                value = max(0, sample["peak_rss_bytes"] - sample["baseline_current_rss_bytes"])
                if FIELD in sample and sample[FIELD] != value:
                    raise ValueError("Existing derived field disagrees with measured RSS values")
                sample[FIELD] = value
            if samples and variant in workload.get("medians", {}):
                workload["medians"][variant][FIELD] = statistics.median(sample[FIELD] for sample in samples)
    data["metadata"]["derived_memory_metrics"] = {
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_measurements_preserved": True,
        FIELD: "max(0, peak_rss_bytes - baseline_current_rss_bytes)",
        "incremental_peak_rss_bytes": "Original recorded metric: max(0, peak_rss_bytes - baseline_peak_rss_bytes)",
        "retained_current_increase_bytes": "Original recorded metric: retained_output_current_rss_bytes - baseline_current_rss_bytes (signed)",
        "summary": "Each summary is the median of per-sample differences, not a difference of independently calculated medians.",
        "interpretation": "Arithmetic whole-process RSS comparisons, not isolated allocation attribution. Input-loading transients affect the prior high-water baseline; Linux RSS accounting/sampling can differ slightly.",
    }
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()
    for name in args.inputs:
        path = Path(name)
        data = json.loads(path.read_text())
        if not data["metadata"].get("all_requested_samples_completed"):
            raise SystemExit(f"Refusing to modify an incomplete or running result: {path.name}")
        derive(data)
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Added derived RSS views to {path.name}; original measurements preserved")
