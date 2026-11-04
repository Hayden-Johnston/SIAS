import json
import tempfile
import unittest
from pathlib import Path

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
                row = dict(id=str(index), text="Synthetic fixture text", label=label,
                           label_source="synthetic", attack_family="fixture" if label else "benign",
                           group_id=str(index), variant_type="plain", source="synthetic",
                           license="CC0-1.0", publishable="no", timestamp="2026-11-04T00:00:00Z")
                writer.write(json.dumps(row) + "\n")
        normalize(source, self.root / "dataset.jsonl", self.root / "dataset.manifest.json")
        self.config = dict(run_id="fixture-run", timestamp="2026-11-04T00:00:00Z", iteration=0,
                           pipeline_version="fixture-v1", dataset="dataset.jsonl",
                           dataset_manifest="dataset.manifest.json", evaluation_split="validation",
                           stages=[])
        self.add_stage("first", [("0", 0.9), ("1", 0.1), ("2", 0.2), ("3", 0.1)])
        self.add_stage("second", [("1", 0.9), ("2", 0.1), ("3", 0.1)])
        self.config_path = self.root / "config.json"
        self.run_directory = self.root / "run"
        self.save_config()

    def add_stage(self, name, scores):
        cache = self.root / f"{name}.jsonl"
        cache.write_text("".join(json.dumps(dict(id=key, score=score, latency_ms=2.0)) + "\n"
                                 for key, score in scores))
        self.config["stages"].append(dict(name=name, version="fixture-v1", threshold=0.5,
                                         cache=cache.name, cache_sha256=digest(cache)))

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def replay(self):
        return replay(self.config_path, self.run_directory)

    def test_cascade_counts_stage_latency_and_replay(self):
        first = self.replay()
        self.assertEqual({key: first["metrics"][key] for key in ("tp", "fp", "fn", "tn")},
                         dict(tp=1, fp=1, fn=1, tn=1))
        self.assertEqual(first["metrics"]["detection"]["value"], 0.5)
        self.assertEqual(first["metrics"]["detection"]["n"], 2)
        self.assertEqual(first["metrics"]["false_positive"]["value"], 0.5)
        self.assertEqual(first["attack_distribution"], {"fixture": 2})
        self.assertEqual([stage["reached"] for stage in first["stages"]], [4, 3])
        self.assertEqual([stage["caught"] for stage in first["stages"]], [1, 1])
        self.assertEqual([stage["cached_latency_ms_total"] for stage in first["stages"]], [8, 6])
        before = (self.run_directory / "manifest.json").read_bytes()
        self.assertEqual(first, self.replay())
        self.assertEqual(before, (self.run_directory / "manifest.json").read_bytes())
        self.assertEqual(first["results_sha256"], digest(self.run_directory / "results.jsonl"))
        self.assertFalse(first["evaluator_approved"])
        for path in self.run_directory.iterdir():
            self.assertNotIn("Synthetic fixture text", path.read_text())

    def test_resume_after_partial_final_journal_line(self):
        expected = self.replay()
        journal = self.run_directory / "results.jsonl"
        complete = journal.read_bytes()
        lines = complete.splitlines(keepends=True)
        journal.write_bytes(b"".join(lines[:2]) + b'{"id": "unfinished')
        (self.run_directory / "manifest.json").unlink()
        self.assertEqual(expected, self.replay())
        self.assertEqual(complete, journal.read_bytes())

    def test_checkpoint_corruption_is_rejected(self):
        self.replay()
        journal = self.run_directory / "results.jsonl"
        rows = [json.loads(line) for line in journal.read_text().splitlines()]
        rows[0]["stages"][0]["score"] = 0.99
        journal.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaisesRegex(ValueError, "checkpoint differs"):
            self.replay()

    def test_config_change_requires_new_run_directory(self):
        self.replay()
        self.config["stages"][0]["threshold"] = 0.7
        self.save_config()
        with self.assertRaisesRegex(ValueError, "inputs/config changed"):
            self.replay()

    def test_cache_mutation_is_rejected_before_run_creation(self):
        (self.root / "first.jsonl").write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "cache checksum mismatch"):
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
        self.assertEqual(len((self.run_directory / "results.jsonl").read_text().splitlines()), 1)

    def test_invalid_scores_and_ids_are_rejected(self):
        cache = self.root / "first.jsonl"
        for entry in [dict(id="0", score=float("nan"), latency_ms=2),
                      dict(id="0", score=True, latency_ms=2),
                      dict(id="0", score=0.1, latency_ms=-1),
                      dict(id="unknown", score=0.1, latency_ms=1)]:
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

    def test_threshold_boundary_is_inclusive(self):
        self.config["stages"][0]["threshold"] = 0.9
        self.save_config()
        result = self.replay()
        self.assertEqual(result["stages"][0]["caught"], 1)
        self.assertEqual(result["stages"][0]["score_summary"]["max"], 0.9)

    def test_duplicate_cached_id_is_rejected(self):
        cache = self.root / "first.jsonl"
        with cache.open("a") as writer:
            writer.write(json.dumps(dict(id="0", score=0.5, latency_ms=1)) + "\n")
        self.config["stages"][0]["cache_sha256"] = digest(cache)
        self.save_config()
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            self.replay()

    def test_run_output_cannot_overwrite_input(self):
        self.config_path.rename(self.root / "manifest.json")
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            replay(self.root / "manifest.json", self.root)

    def test_cli_returns_only_aggregate_manifest(self):
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-m", "data_processing.run", str(self.config_path),
             str(self.run_directory)], capture_output=True, text=True, check=True,
        )
        self.assertEqual(json.loads(result.stdout)["records"], 4)
        self.assertNotIn("Synthetic fixture text", result.stdout + result.stderr)

    def test_active_writer_prevents_replay(self):
        import fcntl
        self.run_directory.mkdir()
        with (self.run_directory / ".lock").open("a") as writer:
            fcntl.flock(writer, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "active writer"):
                self.replay()

    def test_missing_identity_refuses_existing_artifacts(self):
        self.run_directory.mkdir()
        (self.run_directory / "results.jsonl").touch()
        with self.assertRaisesRegex(ValueError, "without an identity"):
            self.replay()


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
