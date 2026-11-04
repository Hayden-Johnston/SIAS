"""Edge-case tests for sources.py loaders: malformed input, missing fields, empty files."""

import json

import pytest

from data_processing.sources import load_source

REVISION = "a" * 40
TIMESTAMP = "2026-11-04T00:00:00Z"


def test_malformed_jsonl_line_fails_cleanly(tmp_path):
    """A non-JSON line in a JSONL file raises ValueError without leaking payload text."""
    path = tmp_path / "input.jsonl"
    path.write_text('{"text": "synthetic", "label": 1}\nnot valid json\n', encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="invalid source fields or format"):
        load_source("deepset", [path], output, manifest,
                    revision=REVISION, timestamp=TIMESTAMP)
    assert not output.exists()
    assert not manifest.exists()


def test_missing_required_field_fails_cleanly(tmp_path):
    """A row missing a required field raises ValueError without leaking field values."""
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps({"text": "synthetic"}) + "\n", encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="invalid source fields or format"):
        load_source("deepset", [path], output, manifest,
                    revision=REVISION, timestamp=TIMESTAMP)
    assert not output.exists()
    assert not manifest.exists()


def test_empty_file_produces_zero_records(tmp_path):
    """An empty JSONL file produces a valid manifest with zero records."""
    path = tmp_path / "input.jsonl"
    path.write_text("", encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    result = load_source("deepset", [path], output, manifest,
                         revision=REVISION, timestamp=TIMESTAMP)
    assert result["records"] == 0
    assert result["labels"] == {}
    assert result["loader"]["input_rows"] == 0


def test_unknown_source_name_raises_key_error(tmp_path):
    """An unknown source name raises KeyError (not caught by the row-level handler)."""
    path = tmp_path / "input.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    with pytest.raises(KeyError):
        load_source("nonexistent_source", [path], output, manifest,
                    revision=REVISION, timestamp=TIMESTAMP)


def test_duplicate_identical_rows_are_deduplicated(tmp_path):
    """Two identical rows produce one record and increment the duplicate count."""
    path = tmp_path / "input.jsonl"
    rows = [{"text": "synthetic", "label": 1}] * 2
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    result = load_source("deepset", [path], output, manifest,
                         revision=REVISION, timestamp=TIMESTAMP)
    assert result["records"] == 1
    assert result["loader"]["duplicates"] == 1


def test_json_array_line_is_rejected(tmp_path):
    """A JSONL line that is a valid JSON array (not an object) raises ValueError."""
    path = tmp_path / "input.jsonl"
    path.write_text(json.dumps(["synthetic"]) + "\n", encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    with pytest.raises(ValueError, match="invalid source fields or format"):
        load_source("deepset", [path], output, manifest,
                    revision=REVISION, timestamp=TIMESTAMP)
    assert not output.exists()
    assert not manifest.exists()
