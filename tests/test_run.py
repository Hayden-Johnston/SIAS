import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_processing import run
from data_processing.normalize import normalize
from data_processing.run import digest, metrics, rate, replay


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = self.root / "source.jsonl"
        with source.open("w") as writer:
            for index, label in enumerate([1, 0, 1, 0]):
                row = {"channel": "direct", "techniques": ["novel"] if label else [],
                           "spans": None if label else [], "id": str(index), "text": "Synthetic fixture text", "label": label,
                           "label_source": "synthetic", "attack_family": "fixture" if label else "benign",
                           "group_id": str(index), "variant_type": "plain", "source": "synthetic",
                           "license": "CC0-1.0", "publishable": "no", "timestamp": "2026-11-04T00:00:00Z"}
                writer.write(json.dumps(row) + "\n")
        normalize(source, self.root / "dataset.jsonl", self.root / "dataset.manifest.json")
        self.config = {"run_id": "fixture-run", "timestamp": "2026-11-04T00:00:00Z", "iteration": 0,
                           "pipeline_version": "fixture-v1", "dataset": "dataset.jsonl",
                           "dataset_manifest": "dataset.manifest.json", "evaluation_split": "validation",
                           "stages": []}
        self.add_stage("first", [("0", 0.9), ("1", 0.1), ("2", 0.2), ("3", 0.1)])
        self.add_stage("second", [("1", 0.9), ("2", 0.1), ("3", 0.1)])
        self.config_path = self.root / "config.json"
        self.run_directory = self.root / "run"
        self.save_config()

    def add_stage(self, name, scores):
        cache = self.root / f"{name}.jsonl"
        cache.write_text("".join(json.dumps({"id": key, "score": score, "latency_ms": 2.0}) + "\n"
                                 for key, score in scores))
        self.config["stages"].append({"name": name, "version": "fixture-v1", "threshold": 0.5,
                                         "cache": cache.name, "cache_sha256": digest(cache)})

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def replay(self):
        return replay(self.config_path, self.run_directory)

    def test_cascade_counts_stage_latency_and_replay(self):
        first = self.replay()
        self.assertEqual({key: first["metrics"][key] for key in ("tp", "fp", "fn", "tn")},
                         {"tp": 1, "fp": 1, "fn": 1, "tn": 1})
        self.assertEqual(first["metrics"]["detection"]["value"], 0.5)
        self.assertEqual(first["metrics"]["detection"]["n"], 2)
        self.assertEqual(first["metrics"]["false_positive"]["value"], 0.5)
        self.assertEqual(first["attack_distribution"], {"fixture": 2})
        self.assertEqual([stage["reached"] for stage in first["stages"]], [4, 3])
        self.assertEqual([stage["caught"] for stage in first["stages"]], [1, 1])
        self.assertEqual([stage["cached_latency_ms_total"] for stage in first["stages"]], [8, 6])
        results_before = (self.run_directory / "results.jsonl").read_bytes()
        before = (self.run_directory / "manifest.json").read_bytes()
        self.assertEqual(first, self.replay())
        self.assertEqual(before, (self.run_directory / "manifest.json").read_bytes())
        self.assertEqual(results_before, (self.run_directory / "results.jsonl").read_bytes())
        self.assertEqual({p.name for p in self.run_directory.iterdir()},
                         {"results.jsonl", "manifest.json"})
        self.assertEqual(first["results_sha256"], digest(self.run_directory / "results.jsonl"))
        self.assertFalse(first["evaluator_approved"])
        for path in self.run_directory.iterdir():
            self.assertNotIn("Synthetic fixture text", path.read_text())

    def test_changed_config_replaces_outputs(self):
        before = self.replay()
        self.config["stages"][1]["threshold"] = 0.95
        self.save_config()
        after = self.replay()
        self.assertNotEqual(before["identity_sha256"], after["identity_sha256"])
        self.assertNotEqual(before["results_sha256"], after["results_sha256"])
        self.assertEqual(after["metrics"]["fp"], 0)

    def test_failed_manifest_replace_leaves_detectable_stale_pair(self):
        before = self.replay()
        manifest = self.run_directory / "manifest.json"
        original = manifest.read_bytes()
        self.config["stages"][1]["threshold"] = 0.95
        self.save_config()
        replace = run.os.replace

        def fail_manifest(source, destination):
            if destination == manifest:
                raise OSError("synthetic replacement failure")
            replace(source, destination)

        with (patch.object(run.os, "replace", side_effect=fail_manifest),
              self.assertRaises(OSError)):
            self.replay()
        self.assertEqual(manifest.read_bytes(), original)
        self.assertNotEqual(before["results_sha256"], digest(self.run_directory / "results.jsonl"))
        self.assertEqual({p.name for p in self.run_directory.iterdir()},
                         {"results.jsonl", "manifest.json"})
        self.assertEqual(self.replay()["results_sha256"], digest(self.run_directory / "results.jsonl"))

    def test_cache_mutation_is_rejected_before_run_creation(self):
        (self.root / "first.jsonl").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "cache checksum mismatch"):
            self.replay()
        self.assertFalse(self.run_directory.exists())

    def test_version_1_dataset_manifest_is_rejected(self):
        path = self.root / "dataset.manifest.json"
        manifest = json.loads(path.read_text())
        manifest["schema_version"] = 1
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "schema version 2 required"):
            self.replay()
        self.assertFalse(self.run_directory.exists())

    def test_dataset_mutation_is_rejected(self):
        with (self.root / "dataset.jsonl").open("a") as writer:
            writer.write("changed\n")
        with self.assertRaisesRegex(ValueError, "dataset manifest version/checksum mismatch"):
            self.replay()

    def test_missing_score_does_not_infer_or_mark_complete(self):
        cache = self.root / "second.jsonl"
        cache.write_text("")
        self.config["stages"][1]["cache_sha256"] = digest(cache)
        self.save_config()
        with self.assertRaisesRegex(ValueError, "missing required cached score"):
            self.replay()
        self.assertFalse((self.run_directory / "manifest.json").exists())
        self.assertFalse((self.run_directory / "results.jsonl").exists())

    def test_missing_score_preserves_previous_outputs(self):
        self.replay()
        before = {p.name: p.read_bytes() for p in self.run_directory.iterdir()}
        cache = self.root / "second.jsonl"
        cache.write_text("")
        self.config["stages"][1]["cache_sha256"] = digest(cache)
        self.save_config()
        with self.assertRaisesRegex(ValueError, "missing required cached score"):
            self.replay()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.run_directory.iterdir()})

    def test_invalid_scores_and_ids_are_rejected(self):
        cache = self.root / "first.jsonl"
        for entry in [{"id": "0", "score": float("nan"), "latency_ms": 2},
                      {"id": "0", "score": True, "latency_ms": 2},
                      {"id": "0", "score": 0.1, "latency_ms": -1},
                      {"id": "unknown", "score": 0.1, "latency_ms": 1}]:
            cache.write_text(json.dumps(entry) + "\n")
            self.config["stages"][0]["cache_sha256"] = digest(cache)
            self.save_config()
            with self.assertRaises(ValueError):
                self.replay()
        self.assertFalse(self.run_directory.exists())

    def test_duplicate_stages_are_rejected(self):
        self.config["stages"][1]["name"] = "first"
        self.save_config()
        with self.assertRaisesRegex(ValueError, "duplicate stage"):
            self.replay()

    def test_timestamp_requires_timezone(self):
        for timestamp in ("not-a-date", "2026-11-04T00:00:00"):
            self.config["timestamp"] = timestamp
            self.save_config()
            with self.assertRaisesRegex(ValueError, "timestamp"):
                self.replay()

    def test_timestamp_is_canonical_utc(self):
        self.config["timestamp"] = "2026-11-04T02:00:00+02:00"
        self.save_config()
        self.assertEqual(self.replay()["timestamp"], "2026-11-04T00:00:00Z")

    def test_threshold_boundary_is_inclusive(self):
        self.config["stages"][0]["threshold"] = 0.9
        self.save_config()
        result = self.replay()
        self.assertEqual(result["stages"][0]["caught"], 1)
        self.assertEqual(result["stages"][0]["score_summary"]["max"], 0.9)

    def test_duplicate_cached_id_is_rejected(self):
        cache = self.root / "first.jsonl"
        with cache.open("a") as writer:
            writer.write(json.dumps({"id": "0", "score": 0.5, "latency_ms": 1}) + "\n")
        self.config["stages"][0]["cache_sha256"] = digest(cache)
        self.save_config()
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            self.replay()

    def test_run_output_cannot_overwrite_input(self):
        self.config_path.rename(self.root / "manifest.json")
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            replay(self.root / "manifest.json", self.root)

    def test_empty_dataset_produces_valid_manifest(self):
        # An empty dataset (0 rows) is valid and produces a manifest with 0 records.
        empty = self.root / "empty.jsonl"
        empty.write_bytes(b"")
        manifest = self.root / "empty.manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 2,
            "output_sha256": digest(empty),
            "records": 0,
        }))
        # Use a single stage with an empty cache.
        cache = self.root / "empty_cache.jsonl"
        cache.write_bytes(b"")
        self.config["dataset"] = "empty.jsonl"
        self.config["dataset_manifest"] = "empty.manifest.json"
        self.config["stages"] = [{"name": "s", "version": "v1", "threshold": 0.5,
                                   "cache": "empty_cache.jsonl", "cache_sha256": digest(cache)}]
        self.save_config()
        result = self.replay()
        self.assertEqual(result["records"], 0)
        self.assertEqual(result["metrics"]["detection"]["value"], None)
        self.assertEqual(result["metrics"]["false_positive"]["value"], None)
        self.assertEqual(result["stages"][0]["reached"], 0)

    def test_duplicate_dataset_ids_are_rejected(self):
        # Two rows with the same id in the dataset are rejected by prepare().
        # Write directly (bypassing normalize) to test run.py's own check.
        source = self.root / "source.jsonl"
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        rows[1]["id"] = rows[0]["id"]  # Make duplicate
        data = "".join(json.dumps(r) + "\n" for r in rows)
        dataset = self.root / "dataset.jsonl"
        dataset.write_text(data)
        manifest = self.root / "dataset.manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 2,
            "output_sha256": digest(dataset),
            "records": len(rows),
        }))
        with self.assertRaisesRegex(ValueError, "duplicate dataset id"):
            self.replay()

    def test_unknown_evaluation_split_is_rejected(self):
        self.config["evaluation_split"] = "unknown_split"
        self.save_config()
        with self.assertRaisesRegex(ValueError, "evaluation_split must be train, validation, or held_out"):
            self.replay()

    def test_cli_returns_only_aggregate_manifest(self):
        result = subprocess.run(
            [sys.executable, "-m", "data_processing.run", str(self.config_path),
             str(self.run_directory)], capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["records"], 4)
        self.assertNotIn("Synthetic fixture text", result.stdout + result.stderr)


class ChunkReplayTests(unittest.TestCase):
    setUp = ReplayTests.setUp
    add_stage = ReplayTests.add_stage
    save_config = ReplayTests.save_config
    replay = ReplayTests.replay

    def chunk_stage(self, chunk_chars=8, overlap_chars=2):
        self.config["stages"] = self.config["stages"][:1]
        stage = self.config["stages"][0]
        stage.update(chunk_chars=chunk_chars, overlap_chars=overlap_chars)
        return stage

    def write_cache(self, entries):
        stage = self.config["stages"][0]
        path = self.root / stage["cache"]
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
        stage["cache_sha256"] = digest(path)
        self.save_config()

    def test_windows_end_alignment_and_empty_turn(self):
        self.assertEqual(run.windows(17, 8, 2), [(0, 8), (6, 14), (9, 17)])
        self.assertEqual(run.windows(8, 8, 2), [(0, 8)])
        self.assertEqual(run.windows(0, 8, 2), [(0, 0)])
        self.assertEqual(run.windows(16, 8, 0), [(0, 8), (8, 16)])

    def test_single_chunk_metrics_equivalent_to_row_cache(self):
        before = self.replay()
        for stage in self.config["stages"]:
            stage.update(chunk_chars=100, overlap_chars=10)
            path = self.root / stage["cache"]
            entries = [json.loads(line) | {"turn": 0, "start": 0}
                       for line in path.read_text().splitlines()]
            path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
            stage["cache_sha256"] = digest(path)
        self.save_config()
        after = self.replay()
        self.assertEqual(before["metrics"], after["metrics"])
        for old, new in zip(before["stages"], after["stages"]):
            for key in old:
                self.assertEqual(old[key], new[key])
        self.assertEqual(after["stages"][0]["location"]["overall"], rate(0, 0))

    def test_multi_turn_boundary_location_and_replay(self):
        source = self.root / "source.jsonl"
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        rows[0].update(channel="multi_turn", text=json.dumps([
            {"role": "user", "content": "x" * 17},
            {"role": "assistant", "content": "y" * 3}]), spans=[[0, 7, 10], [1, 0, 1]])
        rows[1].update(channel="document", text="z" * 4097)
        rows[2].update(channel="email", text="w" * 16385, spans=[[0, 0, 1]])
        source.write_text("".join(json.dumps(row) + "\n" for row in rows))
        normalize(source, self.root / "dataset.jsonl", self.root / "dataset.manifest.json")
        self.chunk_stage()
        entries = []
        for row in rows:
            turns = ([message["content"] for message in json.loads(row["text"])]
                     if row["channel"] == "multi_turn" else [row["text"]])
            for turn, text in enumerate(turns):
                for start, _ in run.windows(len(text), 8, 2):
                    score = 0.9 if (row["id"], turn, start) == ("0", 0, 6) else 0.1
                    if row["id"] == "2" and start == 6:
                        score = 0.4  # Highest chunk misses the known span, below threshold.
                    entries.append({"id": row["id"], "turn": turn, "start": start,
                                    "score": score, "latency_ms": 2})
        self.write_cache(entries)
        manifest = self.replay()
        stage = manifest["stages"][0]
        self.assertEqual(stage["location"]["overall"], rate(1, 2))
        self.assertEqual(stage["location"]["by_channel"]["multi_turn"], rate(1, 1))
        self.assertEqual(stage["location"]["by_channel"]["email"], rate(0, 1))
        self.assertEqual(stage["location"]["by_length_bucket"]["0-4096"], rate(1, 1))
        self.assertEqual(stage["location"]["by_length_bucket"]["16385+"], rate(0, 1))
        self.assertEqual(stage["spans_longer_than_overlap"], 1)
        self.assertEqual(stage["cached_latency_ms_total"], 2 * len(entries))
        results = [json.loads(line) for line in
                   (self.run_directory / "results.jsonl").read_text().splitlines()]
        self.assertEqual(results[0]["stages"][0]["best_chunk"], [0, 6, 14])
        self.assertEqual(results[1]["length_bucket"], "4097-16384")
        self.assertNotIn("turn_lengths", results[0])
        before = {p.name: p.read_bytes() for p in self.run_directory.iterdir()}
        self.write_cache(list(reversed(entries)))
        # The cache hash changes run identity, but result selection ignores file order.
        reordered = self.replay()
        self.assertEqual(manifest["results_sha256"], reordered["results_sha256"])
        self.write_cache(entries)
        self.assertEqual(manifest, self.replay())
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.run_directory.iterdir()})
        self.write_cache(entries[1:])
        with self.assertRaisesRegex(ValueError, "missing required cached score"):
            self.replay()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.run_directory.iterdir()})

    def test_chunk_validation(self):
        self.chunk_stage()
        valid = {"id": "0", "turn": 0, "start": 0, "score": 0.5, "latency_ms": 1}
        for field, value in [("turn", True), ("turn", -1), ("turn", 1),
                             ("start", True), ("start", 1), ("start", -1)]:
            self.write_cache([valid | {field: value}])
            with self.assertRaisesRegex(ValueError, "invalid chunk coordinates"):
                self.replay()
        self.write_cache([valid, valid])
        with self.assertRaisesRegex(ValueError, "duplicate id/chunk"):
            self.replay()
        for chunk, overlap in [(0, 0), (8, 8), (8, -1), (True, 0), (8, 1.5)]:
            self.config["stages"][0].update(chunk_chars=chunk, overlap_chars=overlap)
            self.save_config()
            with self.assertRaisesRegex(ValueError, "chunk_chars"):
                self.replay()

    def test_unreached_chunk_stage_needs_no_scores(self):
        self.config["stages"][0]["threshold"] = 0
        stage = self.config["stages"][1]
        path = self.root / stage["cache"]
        path.write_text("")
        stage.update(chunk_chars=8, overlap_chars=2, cache_sha256=digest(path))
        self.save_config()
        stage_result = self.replay()["stages"][1]
        self.assertEqual(stage_result["reached"], 0)
        self.assertEqual(stage_result["location"]["overall"], rate(0, 0))
        self.assertEqual(stage_result["spans_longer_than_overlap"], 0)

    def test_location_intersection_and_ties(self):
        row = {"id": "x", "label": 1, "turn_lengths": [12], "spans": [[0, 8, 9]]}
        stage = {"name": "test", "threshold": 0.5, "chunk_chars": 8, "overlap_chars": 0}
        cache = {("x", 0, start): {"score": 0.4, "latency_ms": 1} for start in (0, 4)}
        result = run.evaluate(row, [(stage, cache)])["stages"][0]
        self.assertEqual(result["best_chunk"], [0, 0, 8])
        self.assertFalse(result["located"])  # Touching the end is not an intersection.
        row["spans"] = [[0, 7, 9]]
        self.assertTrue(run.evaluate(row, [(stage, cache)])["stages"][0]["located"])



class MetricTests(unittest.TestCase):
    def test_wilson_interval_matches_known_case(self):
        result = rate(50, 100)
        self.assertAlmostEqual(result["ci95"][0], 0.4038315, places=6)
        self.assertAlmostEqual(result["ci95"][1], 0.5961685, places=6)

    def test_zero_observed_errors_still_has_nonzero_upper_bound(self):
        self.assertGreater(rate(0, 15000)["ci95"][1], 0.0002)
        self.assertLess(rate(300000, 300000)["ci95"][0], 0.99999)

    def test_empty_denominators_are_undefined(self):
        self.assertIsNone(metrics([])["detection"]["value"])
        self.assertEqual(rate(0, 0)["ci95"], [None, None])


if __name__ == "__main__":
    unittest.main()
