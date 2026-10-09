#!/usr/bin/env python3
"""Harness-only checks; does not import or benchmark a parser prototype."""
import importlib.util
import copy
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


architecture = load("architecture", HERE / "architecture-benchmark.py")
original = load("original", HERE / "upstream-large-memory.py")
derivation = load("derivation", HERE / "architecture-derive-memory.py")


class HarnessTests(unittest.TestCase):
    def test_fingerprint_matches_previous_typed_traversal(self):
        cases = [None, "", "hello🙂", {}, [], {"n": None},
                 {"z": ["a", "b", {"x": "東京"}], "b": {"more": [None, "c"]}}]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(architecture.fingerprint(value), original.fingerprint(value))

    def test_fingerprint_visits_all_siblings_and_values(self):
        a = {"root": [{"k": str(index)} for index in range(10000)]}
        b = {"root": [{"k": str(index)} for index in range(10000)]}
        b["root"][-1]["k"] = "changed"
        self.assertNotEqual(architecture.fingerprint(a), architecture.fingerprint(b))

    def test_fingerprint_does_not_use_python_recursion(self):
        value = "leaf"
        for _ in range(10000):
            value = {"n": value}
        actual = architecture.fingerprint(value)
        self.assertEqual(actual["type_counts"]["dict"], 10000)
        self.assertEqual(actual["type_counts"]["str"], 10001)

    def test_fingerprint_sorts_dictionary_keys(self):
        self.assertEqual(architecture.fingerprint({"a": "A", "b": "B"}),
                         architecture.fingerprint({"b": "B", "a": "A"}))

    def test_fixture_size_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as directory:
            for shape in ("records", "large_text"):
                a = original.create_fixture(Path(directory), shape, 1)
                b = original.create_fixture(Path(directory), shape, 1)
                self.assertEqual(a["sha256"], b["sha256"])
                self.assertEqual(a["bytes"], 1024 ** 2)

    def test_memory_derivation_preserves_original_measurements(self):
        samples = [
            {"peak_rss_bytes": peak, "baseline_current_rss_bytes": current,
             "baseline_peak_rss_bytes": prior, "incremental_peak_rss_bytes": max(0, peak - prior),
             "retained_output_current_rss_bytes": retained,
             "retained_current_increase_bytes": retained - current}
            for peak, current, prior, retained in [(20, 10, 15, 18), (30, 80, 90, 28), (100, 90, 95, 97)]
        ]
        before = copy.deepcopy(samples)
        value = {"metadata": {}, "workloads": {"case": {
            "samples": {"variant": samples}, "medians": {"variant": {"incremental_peak_rss_bytes": 5}}}}}
        derivation.derive(value)
        medians = value["workloads"]["case"]["medians"]["variant"]
        self.assertEqual(medians[derivation.FIELD], 10)  # Median of deltas, not delta of medians.
        self.assertEqual(medians["incremental_peak_rss_bytes"], 5)
        self.assertEqual([sample[derivation.FIELD] for sample in samples], [10, 0, 10])
        for old, new in zip(before, samples):
            self.assertEqual(old, {key: value for key, value in new.items() if key != derivation.FIELD})
        self.assertTrue(value["metadata"]["derived_memory_metrics"]["original_measurements_preserved"])

    def test_memory_derivation_rejects_inconsistent_existing_value(self):
        value = {"metadata": {}, "workloads": {"case": {"samples": {"variant": [
            {"peak_rss_bytes": 20, "baseline_current_rss_bytes": 10, derivation.FIELD: 123}
        ]}}}}
        with self.assertRaises(ValueError):
            derivation.derive(value)

    def test_diagnostics_redact_runtime_paths(self):
        text = architecture.sanitize_error("/private/snapshot/src/native.cpp /private/fixtures/test.xml",
                                            {"baseline": "/private/snapshot"}, "/private/fixtures")
        self.assertEqual(text, "<baseline-snapshot>/src/native.cpp <fixtures>/test.xml")


if __name__ == "__main__":
    unittest.main()
