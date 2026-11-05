"""Synthetic markers only; no corpus payloads or inference."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from data_processing.augment import augment
from data_processing.normalize import canonical_json, normalize
from data_processing.split import split


def fixture(tmp_path, *, benign=True):
    base = {
        "id": "attack", "text": "SYNTHETIC_MARKER_é🙂", "label": 1,
        "label_source": "test", "attack_family": "heldout-marker", "group_id": "marker-group",
        "variant_type": "plain", "source": "test", "license": "CC0-1.0", "publishable": "no",
        "timestamp": "2026-11-05T00:00:00Z", "channel": "direct",
        "techniques": ["novel"], "spans": None,
    }
    rows = [base]
    if benign:
        rows.append(base | {"id": "benign", "text": "Weekly project notes. ", "label": 0,
                            "techniques": [], "spans": [], "attack_family": "benign", "group_id": "benign-group"})
    raw, normalized, manifest = [tmp_path / name for name in ("raw.jsonl", "normalized.jsonl", "m.json")]
    raw.write_text("".join(canonical_json(r) + "\n" for r in rows))
    normalize(raw, normalized, manifest)
    split(normalized, manifest, {"heldout_families": [],
          "proportions": {"train": 0.98, "dev": 0.01, "test": 0.01}}, tmp_path / "splits")
    return base, tmp_path / "splits/train.jsonl", tmp_path / "splits/split_manifest.json"


def test_replay_spans_controls_and_coverage(tmp_path):
    base, source, manifest = fixture(tmp_path)
    output = tmp_path / "augmented.jsonl"
    result = augment(source, output, manifest, 17)
    original = output.read_bytes(), output.with_suffix(".manifest.json").read_bytes()
    assert augment(source, output, manifest, 17) == result
    assert original == (output.read_bytes(), output.with_suffix(".manifest.json").read_bytes())
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert result["records"] == 10
    assert result["split"] == "train"
    assert result["evaluator_approved"] is False
    assert len({r["id"] for r in rows}) == 10
    assert result["attack_channels"] == {"direct": 1, "document": 2, "email": 1, "tool_output": 1}
    assert result["attack_lengths"]["8192+"] == 1
    assert {r["source"] for r in rows[2:]} == {
        "augmented:document", "augmented:email", "augmented:tool_output", "augmented:long_context"}
    for row in rows[2:]:
        assert row["attack_family"] == base["attack_family"]
        assert row["group_id"] == base["group_id"]
        assert row["publishable"] == "no"
        if row["source"] == "augmented:long_context":
            assert len(row["text"]) >= 8192
            assert "Weekly project notes." in row["text"]
        if row["label"]:
            turn, start, end = row["spans"][0]
            assert turn == 0
            assert row["text"][start:end] == base["text"]
            assert row["techniques"] == base["techniques"]
        else:
            assert row["spans"] == row["techniques"] == []
            assert base["text"] not in row["text"]
    command = [sys.executable, "-m", "data_processing.augment", str(source), str(output),
               "--dataset-manifest", str(manifest), "--seed", "17"]
    assert json.loads(subprocess.check_output(command)) == result
    coverage = subprocess.check_output([sys.executable, str(Path(__file__).parents[1] / "ops/coverage.py"),
                                       str(output.with_suffix(".manifest.json"))], text=True)
    assert "| augmented.manifest | 1 LOW | 0 GAP | 2 LOW | 1 LOW | 1 LOW | 0 GAP | 1 LOW |" in coverage
    augment(source, output, manifest, 18)
    assert output.read_bytes() != original[0]


def test_split_isolation_and_validation(tmp_path):
    _, source, manifest = fixture(tmp_path)
    # Other splits are never read, even when they contain invalid bytes.
    source.with_name("dev.jsonl").write_bytes(b"\xff")
    output = tmp_path / "output.jsonl"
    augment(source, output, manifest, 0)
    before = output.read_bytes()
    source.write_text(source.read_text() + "{}\n")
    with pytest.raises(ValueError, match="checksum"):
        augment(source, output, manifest, 0)
    assert output.read_bytes() == before
    with pytest.raises(ValueError, match="distinct"):
        augment(source, source, manifest, 0)


def test_missing_benign_and_empty_split(tmp_path):
    _, source, manifest = fixture(tmp_path, benign=False)
    with pytest.raises(ValueError, match="benign rows in the same split"):
        augment(source, tmp_path / "output.jsonl", manifest, 0)
    result = augment(source.with_name("heldout.jsonl"), tmp_path / "empty.jsonl", manifest, 0)
    assert result["records"] == 0
    assert result["split"] == "heldout"


def test_pinned_heldout_and_unsplit_rejection(tmp_path):
    _, source, manifest = fixture(tmp_path)
    metadata = json.loads(manifest.read_text())["splits"]["train"]
    pinned = tmp_path / "pinned.json"
    pinned.write_text(canonical_json(metadata | {"schema_version": 2, "split": "heldout"}))
    output = tmp_path / "output.jsonl"
    result = augment(source, output, pinned, 0)
    assert result["split"] == "heldout"
    assert "heldout-marker" in result["attack_families"]
    pinned.write_text(canonical_json(metadata | {"schema_version": 2}))
    with pytest.raises(ValueError, match="pinned split"):
        augment(source, output, pinned, 0)


def test_all_positions_and_exact_original_text(tmp_path):
    _, source, manifest = fixture(tmp_path)
    output = tmp_path / "output.jsonl"
    starts = set()
    for seed in range(12):
        augment(source, output, manifest, seed)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        attack = next(r for r in rows if r["source"] == "augmented:long_context" and r["label"])
        starts.add(attack["spans"][0][1])
    assert len(starts) == 3
