import json
import unittest
from pathlib import Path

from data_processing.measurements import measure_all, measure_results


class MeasureResultsTests(unittest.TestCase):
    def test_mixed_tp_fp_fn_tn_counts(self):
        # a: predicted 1, expected 1 -> TP
        # b: predicted 0, expected 0 -> TN
        # c: predicted 1, expected 0 -> FP
        # d: predicted 0, expected 1 -> FN
        results = {
            "a": [0.9, 1, 100.0],
            "b": [0.1, 0, 200.0],
            "c": [0.6, 0, 300.0],
            "d": [0.4, 1, 400.0],
        }
        m = measure_results(results)
        self.assertEqual(m["true_positives"], 1)
        self.assertEqual(m["true_negatives"], 1)
        self.assertEqual(m["false_positives"], 1)
        self.assertEqual(m["false_negatives"], 1)
        self.assertEqual(m["correct"], 2)
        self.assertEqual(m["total_lines"], 4)
        self.assertEqual(m["total_benign"], 2)
        self.assertEqual(m["total_attacks"], 2)
        self.assertEqual(m["accuracy"], 50.0)
        self.assertEqual(m["precision"], 0.5)
        self.assertEqual(m["tpr"], 50.0)
        self.assertEqual(m["fpr"], 50.0)
        self.assertEqual(m["fnr"], 50.0)
        self.assertEqual(m["tnr"], 50.0)
        self.assertEqual(m["fdr"], 50.0)
        self.assertEqual(m["average_time_ms"], 250.0)
        self.assertEqual(sorted(m["lines_incorrect"]), ["c", "d"])

    def test_all_correct(self):
        results = {
            "a": [0.9, 1, 100.0],
            "b": [0.2, 0, 200.0],
            "c": [0.8, 1, 300.0],
        }
        m = measure_results(results)
        self.assertEqual(m["true_positives"], 2)
        self.assertEqual(m["true_negatives"], 1)
        self.assertEqual(m["false_positives"], 0)
        self.assertEqual(m["false_negatives"], 0)
        self.assertEqual(m["accuracy"], 100.0)
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["tpr"], 100.0)
        self.assertEqual(m["fpr"], 0.0)
        self.assertEqual(m["fnr"], 0.0)
        self.assertEqual(m["tnr"], 100.0)
        self.assertEqual(m["fdr"], 0.0)
        self.assertEqual(m["average_time_ms"], 200.0)
        self.assertEqual(m["lines_incorrect"], [])

    def test_score_rounding_boundary(self):
        # round(0.5) == 0 in Python (banker's rounding)
        # Include both classes to avoid 0/0 in precision/fpr
        results = {"a": [0.5, 0, 100.0], "b": [0.9, 1, 200.0]}
        m = measure_results(results)
        self.assertEqual(m["true_negatives"], 1)
        self.assertEqual(m["true_positives"], 1)

        # 0.5000001 rounds to 1
        results = {"a": [0.5000001, 1, 100.0], "b": [0.1, 0, 200.0]}
        m = measure_results(results)
        self.assertEqual(m["true_positives"], 1)
        self.assertEqual(m["true_negatives"], 1)

    def test_empty_input(self):
        m = measure_results({})
        self.assertEqual(m["average_time_ms"], 0)
        self.assertIsNone(m["accuracy"])
        self.assertIsNone(m["precision"])
        self.assertIsNone(m["tpr"])
        self.assertIsNone(m["fpr"])
        self.assertIsNone(m["fnr"])
        self.assertIsNone(m["tnr"])
        self.assertIsNone(m["fdr"])
        self.assertEqual(m["total_lines"], 0)

    def test_all_benign(self):
        results = {
            "a": [0.1, 0, 100.0],
            "b": [0.2, 0, 200.0],
        }
        m = measure_results(results)
        self.assertEqual(m["true_negatives"], 2)
        self.assertEqual(m["accuracy"], 100.0)
        self.assertEqual(m["fpr"], 0.0)
        self.assertEqual(m["tnr"], 100.0)
        self.assertIsNone(m["precision"])
        self.assertIsNone(m["tpr"])
        self.assertIsNone(m["fnr"])
        self.assertIsNone(m["fdr"])

    def test_all_attack(self):
        results = {
            "a": [0.9, 1, 100.0],
            "b": [0.8, 1, 200.0],
        }
        m = measure_results(results)
        self.assertEqual(m["true_positives"], 2)
        self.assertEqual(m["accuracy"], 100.0)
        self.assertEqual(m["precision"], 1.0)
        self.assertEqual(m["tpr"], 100.0)
        self.assertEqual(m["fnr"], 0.0)
        self.assertEqual(m["fdr"], 0.0)
        self.assertIsNone(m["fpr"])
        self.assertIsNone(m["tnr"])


class MeasureAllTests(unittest.TestCase):
    def test_measure_all_writes_outputs(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "data" / "results" / "run1"
            sub = run / "model_a"
            sub.mkdir(parents=True)
            results = {"k1": [0.9, 1, 100.0], "k2": [0.1, 0, 200.0]}
            (sub / "batch.json").write_text(json.dumps(results))

            # Run measure_all with cwd patched to tmp
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                measure_all()
            finally:
                os.chdir(old_cwd)

            measurements = json.loads((run / "measurements.json").read_text())
            incorrect = json.loads((run / "incorrect_lines.json").read_text())

            self.assertIn("model_a/batch.json", measurements)
            m = measurements["model_a/batch.json"]
            self.assertEqual(m["true_positives"], 1)
            self.assertEqual(m["true_negatives"], 1)
            self.assertNotIn("lines_incorrect", m)
            self.assertEqual(incorrect["model_a/batch.json"], [])

    def test_measure_all_skips_existing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "data" / "results" / "run1"
            sub = run / "model_a"
            sub.mkdir(parents=True)
            results = {"k1": [0.9, 1, 100.0]}
            (sub / "batch.json").write_text(json.dumps(results))
            # Pre-existing measurements.json should cause skip
            (run / "measurements.json").write_text("{}")

            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                measure_all()
            finally:
                os.chdir(old_cwd)

            # File unchanged
            self.assertEqual((run / "measurements.json").read_text(), "{}")

    def test_measure_all_missing_dir_raises(self):
        # BUG: Path("data/results").iterdir() raises FileNotFoundError if dir absent
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            import os
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self.assertRaises(FileNotFoundError):
                    measure_all()
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
