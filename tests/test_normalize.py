import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from data_processing.normalize import normalize, validate_record


def record(**changes):
    row = dict(
        id="fixture-1", text="Synthetic café\u200b\r\n", label=0,
        label_source="synthetic-test", attack_family="benign", group_id="fixture-group",
        variant_type="plain", source="synthetic", license="CC0-1.0", publishable="no",
        timestamp="2026-11-04T08:00:00+02:00",
    )
    return row | changes


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source.jsonl"
        self.output = self.root / "output.jsonl"
        self.manifest = self.root / "manifest.json"

    def write_rows(self, rows):
        self.source.write_text("".join(json.dumps(row) + "\n" for row in rows))

    def run_normalize(self, **kwargs):
        return normalize(self.source, self.output, self.manifest, **kwargs)

    def test_replay_is_byte_identical_and_text_is_preserved(self):
        self.write_rows([record()])
        first = self.run_normalize()
        first_bytes = self.output.read_bytes(), self.manifest.read_bytes()
        self.assertEqual(first, self.run_normalize())
        self.assertEqual(first_bytes, (self.output.read_bytes(), self.manifest.read_bytes()))
        row = json.loads(self.output.read_text())
        self.assertEqual(row["text"], record()["text"])
        self.assertEqual(row["timestamp"], "2026-11-04T06:00:00Z")
        self.assertEqual(first["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(first["output_sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(first["records"], 1)
        self.assertFalse(first["evaluator_approved"])
        self.assertNotIn("text", first)
        self.assertNotIn(record()["text"], self.manifest.read_text())

    def test_mapping_and_generated_ids_are_independent_of_row_order(self):
        defaults = record()
        for field in ("id", "text", "label"):
            del defaults[field]
        mapping = {"fields": {"text": "body", "label": "class"}, "defaults": defaults}
        rows = [{"body": "Synthetic alpha", "class": 0}, {"body": "Synthetic beta", "class": 1}]
        self.write_rows(rows)
        self.run_normalize(mapping=mapping)
        first = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.write_rows(rows[::-1])
        self.run_normalize(mapping=mapping)
        second = [json.loads(line) for line in self.output.read_text().splitlines()]
        self.assertEqual(first, second[::-1])
        self.assertNotEqual(first[0]["id"], first[1]["id"])

    def test_bad_records_leave_existing_outputs_intact_and_do_not_expose_text(self):
        self.output.write_text("previous output")
        self.manifest.write_text("previous manifest")
        bad_rows = [
            record(label=True), record(label=2), record(text=""), record(publishable=True),
            record(variant_type="unknown"), record(timestamp="2026-11-04"),
            record(timestamp="invalid"), record(extra="unexpected"), ["synthetic"],
        ]
        for row in bad_rows:
            with self.subTest(row_type=type(row).__name__):
                self.write_rows([record(id="valid-first"), row])
                with self.assertRaises(ValueError) as error:
                    self.run_normalize()
                self.assertNotIn(record()["text"], str(error.exception))
                self.assertEqual(self.output.read_text(), "previous output")
                self.assertEqual(self.manifest.read_text(), "previous manifest")
                self.assertEqual(len(list(self.root.iterdir())), 3)

    def test_duplicate_ids_require_evaluator_resolution(self):
        self.write_rows([record(), record()])
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            self.run_normalize()
        self.assertFalse(self.output.exists())

    def test_invalid_json_and_utf8_errors_do_not_include_input(self):
        for content in (b'not-json secret-like-fixture', b'\xff', '{}'.encode('utf-16')):
            self.source.write_bytes(content)
            with self.assertRaisesRegex(ValueError, "line 1: invalid JSON or UTF-8"):
                self.run_normalize()

    def test_empty_input_is_valid_and_counted(self):
        self.source.write_bytes(b"")
        self.assertEqual(self.run_normalize()["records"], 0)

    def test_mapping_configuration_is_strict(self):
        self.write_rows([record()])
        mappings = [[], {"unknown": {}}, {"fields": []}, {"fields": {"unknown": "x"}},
                    {"fields": {"text": "x"}, "defaults": {"text": "y"}},
                    {"fields": {"text": 7}}, {}]
        for mapping in mappings:
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                self.run_normalize(mapping=mapping)

    def test_source_output_manifest_must_be_distinct(self):
        self.write_rows([record()])
        with self.assertRaisesRegex(ValueError, "distinct"):
            normalize(self.source, self.source, self.manifest)

    def test_missing_source_key_reports_canonical_field_only(self):
        defaults = record()
        del defaults["text"]
        self.write_rows([{}])
        with self.assertRaisesRegex(ValueError, "missing mapped field text"):
            self.run_normalize(mapping={"fields": {"text": "body"}, "defaults": defaults})

    def test_cli_has_no_payload_output_on_failure(self):
        import sys
        from unittest.mock import patch
        from data_processing.normalize import main

        self.source.write_text("private synthetic fixture, invalid JSON")
        stderr = io.StringIO()
        args = ["normalize", str(self.source), str(self.output), "--manifest", str(self.manifest)]
        with patch.object(sys, "argv", args), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 2)
        self.assertNotIn("private synthetic fixture", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
