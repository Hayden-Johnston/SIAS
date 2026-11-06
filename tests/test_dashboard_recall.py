"""Unit tests for dashboard per-technique/per-channel recall loaders (ticket 0073)."""

import importlib.util
import json
from pathlib import Path

import pytest

from data_processing.run import rate

spec = importlib.util.spec_from_file_location(
    "dashboard_server", Path(__file__).parents[1] / "dashboard" / "server.py"
)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def base_manifest():
    """Minimal valid manifest with no slices key."""
    return {
        "schema_version": 1, "status": "complete", "run_id": "run-0",
        "timestamp": "2026-11-04T00:00:00Z", "iteration": 0,
        "pipeline_version": "pipeline-0", "dataset_sha256": "a" * 64,
        "evaluation_split": "held_out", "records": 0, "evaluator_approved": False,
        "metrics": {"tp": 0, "fp": 0, "fn": 0, "tn": 0,
                    "detection": rate(0, 0), "false_positive": rate(0, 0)},
        "attack_distribution": {},
        "stages": [],
    }


def slice_entry(n, tp, fn):
    """Build a valid slice group entry."""
    return {
        "n": n, "small_sample": n < 20, "tp": tp, "fn": fn,
        "detection": rate(tp, tp + fn),
        "false_positive": rate(0, 0),
    }


# --- Empty manifests ---

def test_no_slices_key():
    """A manifest without a slices key produces empty by_* dicts and None novel_technique."""
    result = dashboard.manifest_fields(base_manifest())
    assert result["slices"]["by_channel"] == {}
    assert result["slices"]["by_technique"] == {}
    assert result["slices"]["by_length_bucket"] == {}
    assert result["slices"]["by_attack_family"] == {}
    assert result["slices"]["novel_technique"] is None


def test_empty_slices_dict():
    """An empty slices dict produces empty by_* dicts and None novel_technique."""
    record = base_manifest()
    record["slices"] = {}
    result = dashboard.manifest_fields(record)
    assert result["slices"]["by_channel"] == {}
    assert result["slices"]["by_technique"] == {}
    assert result["slices"]["novel_technique"] is None


# --- Missing keys ---

def test_missing_by_channel():
    """slices without by_channel defaults to an empty dict."""
    record = base_manifest()
    record["slices"] = {"by_technique": {"enc": slice_entry(10, 8, 2)}}
    result = dashboard.manifest_fields(record)
    assert result["slices"]["by_channel"] == {}
    assert result["slices"]["by_technique"]["enc"]["n"] == 10


def test_missing_novel_technique():
    """slices without novel_technique defaults to None."""
    record = base_manifest()
    record["slices"] = {"by_channel": {"direct": slice_entry(5, 3, 2)}}
    result = dashboard.manifest_fields(record)
    assert result["slices"]["novel_technique"] is None
    assert result["slices"]["by_channel"]["direct"]["n"] == 5


# --- Null slices ---

def test_slices_none_rejected(tmp_path):
    """A null slices value raises, so run_metrics skips the manifest."""
    record = base_manifest()
    record["slices"] = None
    with pytest.raises(AttributeError):
        dashboard.manifest_fields(record)
    # In run_metrics context, the manifest is silently skipped.
    directory = tmp_path / "run-0"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(record))
    assert dashboard.run_metrics(tmp_path) == []


def test_by_field_none_rejected(tmp_path):
    """A null by_* field raises, so run_metrics skips the manifest."""
    record = base_manifest()
    record["slices"] = {"by_channel": None}
    with pytest.raises(AttributeError):
        dashboard.manifest_fields(record)
    directory = tmp_path / "run-0"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(record))
    assert dashboard.run_metrics(tmp_path) == []


def test_novel_technique_none():
    """An explicit null novel_technique stays None."""
    record = base_manifest()
    record["slices"] = {"novel_technique": None}
    result = dashboard.manifest_fields(record)
    assert result["slices"]["novel_technique"] is None


def test_novel_technique_empty_list():
    """An empty novel_technique list stays empty."""
    record = base_manifest()
    record["slices"] = {"novel_technique": []}
    result = dashboard.manifest_fields(record)
    assert result["slices"]["novel_technique"] == []


# --- Zero denominators ---

def test_zero_denominator_slice():
    """A slice group with n=0 has null detection value and ci95."""
    record = base_manifest()
    record["slices"] = {"by_technique": {"ghost": slice_entry(0, 0, 0)}}
    result = dashboard.manifest_fields(record)
    group = result["slices"]["by_technique"]["ghost"]
    assert group["n"] == 0
    assert group["small_sample"] is True
    assert group["detection"]["value"] is None
    assert group["detection"]["ci95"] == [None, None]
    assert group["detection"]["n"] == 0


def test_zero_denominator_channel():
    """A channel slice with n=0 produces a valid null rate."""
    record = base_manifest()
    record["slices"] = {"by_channel": {"empty": slice_entry(0, 0, 0)}}
    result = dashboard.manifest_fields(record)
    group = result["slices"]["by_channel"]["empty"]
    assert group["detection"]["value"] is None
    assert group["false_positive"]["value"] is None


def test_zero_denominator_novel_technique():
    """A novel technique entry with n=0 has a null detection rate."""
    record = base_manifest()
    record["slices"] = {"novel_technique": [
        {"technique": "unknown", "n": 0, "small_sample": True,
         "detection": rate(0, 0)}
    ]}
    result = dashboard.manifest_fields(record)
    entry = result["slices"]["novel_technique"][0]
    assert entry["technique"] == "unknown"
    assert entry["n"] == 0
    assert entry["detection"]["value"] is None
    assert entry["detection"]["ci95"] == [None, None]


# --- Multiple slices coexist ---

def test_all_slice_fields_populated():
    """All four by_* fields plus novel_technique can be populated simultaneously."""
    record = base_manifest()
    record["slices"] = {
        "by_channel": {"direct": slice_entry(20, 15, 5)},
        "by_length_bucket": {"0-4096": slice_entry(10, 7, 3)},
        "by_technique": {"encoding": slice_entry(8, 6, 2)},
        "by_attack_family": {"synthetic": slice_entry(5, 4, 1)},
        "novel_technique": [{"technique": "new", "n": 3, "small_sample": True,
                              "detection": rate(2, 3)}],
    }
    result = dashboard.manifest_fields(record)
    assert result["slices"]["by_channel"]["direct"]["tp"] == 15
    assert result["slices"]["by_length_bucket"]["0-4096"]["fn"] == 3
    assert result["slices"]["by_technique"]["encoding"]["n"] == 8
    assert result["slices"]["by_attack_family"]["synthetic"]["tp"] == 4
    assert result["slices"]["novel_technique"][0]["detection"]["value"] == 2 / 3
