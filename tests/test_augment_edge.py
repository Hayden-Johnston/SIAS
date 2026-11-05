"""Edge-case tests for augment.py: benign row preservation and input immutability."""

import json

from data_processing.augment import augment
from data_processing.normalize import canonical_json, normalize
from data_processing.split import split


def _fixture(tmp_path):
    """Minimal fixture: one attack + one benign row, normalized and split."""
    attack = {
        "id": "atk", "text": "SYNTHETIC_MARKER", "label": 1,
        "label_source": "test", "attack_family": "fam", "group_id": "g",
        "variant_type": "plain", "source": "test", "license": "CC0-1.0",
        "publishable": "no", "timestamp": "2026-11-05T00:00:00Z",
        "channel": "direct", "techniques": ["novel"], "spans": None,
    }
    benign = {
        "id": "ben", "text": "Benign note here. ", "label": 0,
        "label_source": "test", "attack_family": "benign", "group_id": "bg",
        "variant_type": "plain", "source": "test", "license": "CC0-1.0",
        "publishable": "no", "timestamp": "2026-11-05T00:00:00Z",
        "channel": "direct", "techniques": [], "spans": [],
    }
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(canonical_json(r) + "\n" for r in (attack, benign)))
    normalized, manifest = tmp_path / "norm.jsonl", tmp_path / "m.json"
    normalize(raw, normalized, manifest)
    split(normalized, manifest, {"heldout_families": [],
          "proportions": {"train": 0.98, "dev": 0.01, "test": 0.01}}, tmp_path / "splits")
    return attack, benign, tmp_path / "splits/train.jsonl", tmp_path / "splits/split_manifest.json"


def test_benign_rows_unchanged_in_output(tmp_path):
    """Original benign and attack rows appear in the output with all fields intact."""
    attack, benign, source, manifest = _fixture(tmp_path)
    output = tmp_path / "augmented.jsonl"
    augment(source, output, manifest, 42)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    # Benign row preserved exactly.
    out_benign = next(r for r in rows if r["id"] == "ben")
    assert out_benign == benign
    # Attack row preserved exactly.
    out_attack = next(r for r in rows if r["id"] == "atk")
    assert out_attack == attack


def test_input_file_not_overwritten(tmp_path):
    """The input dataset file is byte-identical after a successful augment run."""
    _, _, source, manifest = _fixture(tmp_path)
    input_before = source.read_bytes()
    output = tmp_path / "augmented.jsonl"
    augment(source, output, manifest, 7)
    assert source.read_bytes() == input_before
