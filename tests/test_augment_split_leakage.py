"""Tests that augmented rows never leak a family across splits (augment + split)."""

import json
import tempfile
import unittest
from pathlib import Path

from data_processing.augment import augment
from data_processing.normalize import canonical_json, normalize
from data_processing.split import SPLITS, split


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


CONFIG = {"heldout_families": [], "proportions": {"train": 0.6, "dev": 0.2, "test": 0.2}}


class AugmentSplitLeakageTests(unittest.TestCase):
    """Each attack family has one group, so family integrity equals group integrity."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def _rows(self):
        return (
            [attack_record("fam-a", "ga")]
            + [attack_record("fam-b", "gb")]
            + [attack_record("fam-c", "gc")]
            + [record(id=f"b{i}", group_id=f"bg{i}") for i in range(3)]
        )

    def _normalize_and_split(self):
        rows = self._rows()
        raw = self.root / "raw.jsonl"
        normalized = self.root / "normalized.jsonl"
        manifest = self.root / "manifest.json"
        raw.write_text("".join(canonical_json(r) + "\n" for r in rows))
        normalize(raw, normalized, manifest)
        split_dir = self.root / "splits"
        split(normalized, manifest, CONFIG, split_dir)
        return split_dir

    @staticmethod
    def _read_split(split_dir, name):
        path = split_dir / f"{name}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    @classmethod
    def _family_splits(cls, split_dir):
        families = {}
        for name in SPLITS:
            for row in cls._read_split(split_dir, name):
                families.setdefault(row["attack_family"], set()).add(name)
        return families

    def test_no_family_in_two_splits(self):
        split_dir = self._normalize_and_split()
        for family, splits in self._family_splits(split_dir).items():
            self.assertEqual(len(splits), 1, f"family {family!r} in {splits}")

    def test_augmented_rows_keep_source_split(self):
        split_dir = self._normalize_and_split()
        # Find a split that has both attack and benign rows (augment requires benign).
        target = None
        for name in SPLITS:
            rows = self._read_split(split_dir, name)
            if any(r["label"] == 1 for r in rows) and any(r["label"] == 0 for r in rows):
                target = name
                break
        self.assertIsNotNone(target, "no split has both attack and benign rows")

        source_path = split_dir / f"{target}.jsonl"
        split_manifest = split_dir / "split_manifest.json"
        aug_path = self.root / f"aug_{target}.jsonl"
        augment(source_path, aug_path, split_manifest, seed=42)

        source_rows = self._read_split(split_dir, target)
        source_groups = {r["group_id"] for r in source_rows if r["label"] == 1}
        aug_rows = [json.loads(line) for line in aug_path.read_text().splitlines()]
        for row in aug_rows:
            if row["source"].startswith("augmented:"):
                self.assertIn(row["group_id"], source_groups,
                              f"augmented row leaked group {row['group_id']!r}")

    def test_no_family_leaks_after_re_split(self):
        """Re-split each augmented output; family integrity must still hold."""
        split_dir = self._normalize_and_split()
        for name in SPLITS:
            rows = self._read_split(split_dir, name)
            if not any(r["label"] == 1 for r in rows):
                continue
            if not any(r["label"] == 0 for r in rows):
                continue  # augment requires benign rows in the same split
            source_path = split_dir / f"{name}.jsonl"
            split_manifest = split_dir / "split_manifest.json"
            aug_path = self.root / f"aug_{name}.jsonl"
            augment(source_path, aug_path, split_manifest, seed=42)
            aug_manifest = aug_path.with_suffix(".manifest.json")
            re_split_dir = self.root / f"re_{name}"
            split(aug_path, aug_manifest, CONFIG, re_split_dir)
            for family, splits in self._family_splits(re_split_dir).items():
                self.assertEqual(len(splits), 1,
                                 f"family {family!r} in {splits} after re-split of {name}")


if __name__ == "__main__":
    unittest.main()
