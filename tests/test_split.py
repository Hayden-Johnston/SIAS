"""Tests for deterministic family-based split assignment."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from data_processing.normalize import canonical_json
from data_processing.split import split, validate_split_config


def record(**changes):
    row = {
        "id": "fixture-1", "text": "synthetic", "label": 0,
        "label_source": "synthetic-test", "attack_family": "benign", "group_id": "group-1",
        "variant_type": "plain", "source": "synthetic", "license": "CC0-1.0", "publishable": "no",
        "timestamp": "2026-11-04T08:00:00+02:00",
        "channel": "direct", "techniques": [], "spans": [],
    }
    return row | changes


def attack_record(family, group, **changes):
    base = record(label=1, attack_family=family, group_id=group,
                  techniques=["novel"], variant_type="plain",
                  id=f"att-{family}-{group}")
    return base | changes


def make_manifest(rows):
    """Create a valid manifest for a set of rows (matching output checksum)."""
    data = "".join(canonical_json(r) + "\n" for r in rows).encode("utf-8")
    return {
        "schema_version": 2,
        "output_sha256": hashlib.sha256(data).hexdigest(),
        "records": len(rows),
    }


CONFIG = {"heldout_families": ["heldout-fam"], "proportions": {"train": 0.6, "dev": 0.2, "test": 0.2}}


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input = self.root / "input.jsonl"
        self.manifest = self.root / "manifest.json"
        self.output_dir = self.root / "splits"

    def write_input(self, rows):
        data = "".join(canonical_json(r) + "\n" for r in rows).encode("utf-8")
        self.input.write_bytes(data)
        self.manifest.write_text(canonical_json(make_manifest(rows)) + "\n")

    def run_split(self, config=None):
        return split(self.input, self.manifest, config or CONFIG, self.output_dir)

    def read_split(self, name):
        path = self.output_dir / f"{name}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_heldout_families_are_assigned_to_heldout(self):
        rows = [
            attack_record("heldout-fam", "g1"),
            attack_record("heldout-fam", "g2"),
            attack_record("other-fam", "g3"),
            record(group_id="g4"),
        ]
        self.write_input(rows)
        result = self.run_split()
        heldout = self.read_split("heldout")
        self.assertEqual(len(heldout), 2)
        self.assertTrue(all(r["attack_family"] == "heldout-fam" for r in heldout))
        self.assertEqual(result["splits"]["heldout"]["records"], 2)
        self.assertEqual(result["splits"]["heldout"]["attack_families"], {"heldout-fam": 2})

    def test_group_integrity_all_rows_in_same_group_share_split(self):
        # Multiple variants of the same attack family must all land in the same split.
        rows = [
            attack_record("fam-a", "g1"),
            attack_record("fam-a", "g1", variant_type="paraphrase", id="att-fam-a-g1-p"),
            attack_record("fam-a", "g1", variant_type="obfuscated", id="att-fam-a-g1-o",
                         techniques=["encoding", "novel"]),
        ]
        self.write_input(rows)
        self.run_split()
        # Find which split the family landed in.
        found_in = None
        for name in ("train", "dev", "test", "heldout"):
            split_rows = self.read_split(name)
            if any(r["attack_family"] == "fam-a" for r in split_rows):
                self.assertIsNone(found_in, "family found in multiple splits")
                found_in = name
                self.assertEqual(len(split_rows), 3)
        self.assertIsNotNone(found_in, "family not found in any split")

    def test_benign_group_integrity(self):
        # All benign rows in the same group_id go to the same split.
        rows = [
            record(group_id="bg1", id="b1"),
            record(group_id="bg1", id="b2", text="synthetic 2"),
            record(group_id="bg1", id="b3", text="synthetic 3"),
        ]
        self.write_input(rows)
        self.run_split()
        found_in = None
        for name in ("train", "dev", "test", "heldout"):
            split_rows = self.read_split(name)
            if any(r["group_id"] == "bg1" for r in split_rows):
                self.assertIsNone(found_in, "group found in multiple splits")
                found_in = name
                self.assertEqual(len(split_rows), 3)
        self.assertIsNotNone(found_in)

    def test_group_spanning_families_fails(self):
        rows = [
            attack_record("fam-a", "g1"),
            attack_record("fam-b", "g1"),
        ]
        self.write_input(rows)
        with self.assertRaisesRegex(ValueError, "group_id spans multiple attack families"):
            self.run_split()

    def test_stability_when_rows_are_appended(self):
        # Split a set, then add more rows; original rows keep their splits.
        rows = [
            attack_record("fam-a", "g1"),
            attack_record("fam-b", "g2"),
            record(group_id="bg1"),
            record(group_id="bg2", id="b2", text="synthetic 2"),
        ]
        self.write_input(rows)
        self.run_split()
        first_assignment = {
            name: {r["id"] for r in self.read_split(name)}
            for name in ("train", "dev", "test", "heldout")
        }

        # Append new rows with new families/groups.
        more_rows = rows + [
            attack_record("fam-c", "g3"),
            record(group_id="bg3", id="b3", text="synthetic 3"),
        ]
        self.write_input(more_rows)
        self.run_split()
        second_assignment = {
            name: {r["id"] for r in self.read_split(name)}
            for name in ("train", "dev", "test", "heldout")
        }

        for name in ("train", "dev", "test", "heldout"):
            self.assertTrue(first_assignment[name] <= second_assignment[name],
                            f"rows moved out of {name}")

    def test_determinism_byte_identical_replay(self):
        rows = [
            attack_record("fam-a", "g1"),
            attack_record("fam-b", "g2"),
            record(group_id="bg1"),
        ]
        self.write_input(rows)
        self.run_split()
        first = {name: (self.output_dir / f"{name}.jsonl").read_bytes()
                 for name in ("train", "dev", "test", "heldout")}
        first_manifest = (self.output_dir / "split_manifest.json").read_bytes()

        self.run_split()
        second = {name: (self.output_dir / f"{name}.jsonl").read_bytes()
                  for name in ("train", "dev", "test", "heldout")}
        second_manifest = (self.output_dir / "split_manifest.json").read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(first_manifest, second_manifest)

    def test_checksum_mismatch_fails(self):
        rows = [record()]
        self.write_input(rows)
        # Corrupt the manifest checksum.
        bad_manifest = make_manifest(rows)
        bad_manifest["output_sha256"] = "0" * 64
        self.manifest.write_text(canonical_json(bad_manifest) + "\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.run_split()

    def test_manifest_has_no_text(self):
        rows = [
            attack_record("fam-a", "g1"),
            record(group_id="bg1"),
        ]
        self.write_input(rows)
        self.run_split()
        manifest_text = (self.output_dir / "split_manifest.json").read_text()
        self.assertNotIn("synthetic", manifest_text)

    def test_manifest_counts_by_label_channel_technique_family(self):
        rows = [
            attack_record("fam-a", "g1", channel="email"),
            attack_record("fam-a", "g2", channel="document", techniques=["encoding"]),
            record(group_id="bg1", channel="direct"),
        ]
        self.write_input(rows)
        result = self.run_split()
        total_records = sum(s["records"] for s in result["splits"].values())
        self.assertEqual(total_records, 3)
        # Verify counts are present in each split's manifest entry.
        for entry in result["splits"].values():
            self.assertIn("labels", entry)
            self.assertIn("channels", entry)
            self.assertIn("techniques", entry)
            self.assertIn("attack_families", entry)

    def test_empty_input_is_valid(self):
        self.write_input([])
        result = self.run_split()
        for name in ("train", "dev", "test", "heldout"):
            self.assertEqual(result["splits"][name]["records"], 0)

    def test_config_validation(self):
        bad_configs = [
            {},
            {"heldout_families": "not-a-list"},
            {"heldout_families": [""], "proportions": {"train": 0.6, "dev": 0.2, "test": 0.2}},
            {"heldout_families": [], "proportions": {"train": 0.6, "dev": 0.2}},
            {"heldout_families": [], "proportions": {"train": 0.6, "dev": 0.2, "test": 0.3}},
            {"heldout_families": [], "proportions": {"train": 0, "dev": 0.5, "test": 0.5}},
            {"heldout_families": [], "proportions": {"train": 1.1, "dev": 0.5, "test": 0.5}},
            {"heldout_families": [], "proportions": {"train": True, "dev": 0.5, "test": 0.5}},
            {"unknown": 1},
        ]
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_split_config(config)

    def test_proportions_distribute_all_families(self):
        # With enough families, all three non-heldout splits should get some.
        rows = [attack_record(f"fam-{i}", f"g{i}") for i in range(50)]
        self.write_input(rows)
        result = self.run_split()
        non_heldout = {n: result["splits"][n]["records"] for n in ("train", "dev", "test")}
        self.assertEqual(sum(non_heldout.values()), 50)
        # With 50 families and 60/20/20, all splits should be non-empty.
        self.assertTrue(all(v > 0 for v in non_heldout.values()))

    def test_row_missing_required_field_raises_keyerror(self):
        # split() accesses fields directly without schema validation.
        for field in ("group_id", "attack_family", "label", "channel", "techniques"):
            row = record()
            del row[field]
            rows = [row]
            self.write_input(rows)
            with self.subTest(field=field), self.assertRaises(KeyError):
                self.run_split()

    def test_empty_input_yields_zero_records(self):
        self.write_input([])
        result = self.run_split()
        self.assertEqual(sum(s["records"] for s in result["splits"].values()), 0)

    def test_duplicate_ids_are_allowed(self):
        # split() does not check for duplicate ids; both rows are processed.
        rows = [
            record(id="dup-1"),
            record(id="dup-1", text="synthetic 2", group_id="bg2"),
        ]
        self.write_input(rows)
        result = self.run_split()
        total = sum(s["records"] for s in result["splits"].values())
        self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
