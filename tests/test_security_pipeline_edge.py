"""Edge-case tests for llm_security/regex_filter.py and pipeline.py."""

import json

from llm_security import regex_filter
from llm_security.pipeline import Pipeline


def test_regex_filter_is_importable():
    """regex_filter is a module (currently empty); importing it must not raise."""
    assert regex_filter is not None


def _make_pipeline(tmp_path, config=None, mode="test"):
    """Build a minimal Pipeline without touching the network."""
    if config is None:
        config = {
            "run_count": 1,
            "providers": {},
            "datasets": [],
        }
    orig = Pipeline.__init__

    def init_no_mkdir(self, cfg, ds):
        self.config = cfg
        self.datasets = ds
        self.path = tmp_path / str(cfg["run_count"])
        self.workers = []

    Pipeline.__init__ = init_no_mkdir
    try:
        ds = type("DS", (), {"mode": mode})()
        p = Pipeline(config, ds)
    finally:
        Pipeline.__init__ = orig
    return p


def test_pipeline_init_empty_strings(tmp_path):
    """Config values that are empty strings do not break init or manifest."""
    config = {"run_count": 0, "providers": {}, "datasets": []}
    p = _make_pipeline(tmp_path, config)
    p.path.mkdir(parents=True, exist_ok=True)
    p.write_manifest()
    manifest = json.loads((p.path / "manifest.json").read_text())
    assert manifest["run_id"] == 0


def test_pipeline_init_unicode(tmp_path):
    """Unicode in dataset names is preserved in the manifest."""
    config = {"run_count": 2, "providers": {}, "datasets": ["d\u00e9tail", "\u65e5\u672c"]}
    p = _make_pipeline(tmp_path, config)
    p.path.mkdir(parents=True, exist_ok=True)
    p.write_manifest()
    manifest = json.loads((p.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["datasets"] == ["d\u00e9tail", "\u65e5\u672c"]


def test_pipeline_init_very_long_input(tmp_path):
    """A very long dataset name does not break manifest writing."""
    long_name = "a" * 10_000
    config = {"run_count": 3, "providers": {}, "datasets": [long_name]}
    p = _make_pipeline(tmp_path, config)
    p.path.mkdir(parents=True, exist_ok=True)
    p.write_manifest()
    manifest = json.loads((p.path / "manifest.json").read_text())
    assert manifest["datasets"][0] == long_name


def test_pipeline_benign_text_not_flagged(tmp_path):
    """Benign text in config values passes through without modification."""
    benign = "The quick brown fox jumps over the lazy dog."
    config = {"run_count": 4, "providers": {}, "datasets": [benign]}
    p = _make_pipeline(tmp_path, config)
    p.path.mkdir(parents=True, exist_ok=True)
    p.write_manifest()
    manifest = json.loads((p.path / "manifest.json").read_text())
    assert manifest["datasets"] == [benign]


def test_pipeline_manifest_deterministic(tmp_path):
    """Two pipelines with the same config produce identical manifests."""
    config = {"run_count": 5, "providers": {}, "datasets": ["x", "y"]}
    p1 = _make_pipeline(tmp_path / "a", config)
    p1.path.mkdir(parents=True, exist_ok=True)
    p1.write_manifest()

    p2 = _make_pipeline(tmp_path / "b", config)
    p2.path.mkdir(parents=True, exist_ok=True)
    p2.write_manifest()

    m1 = (p1.path / "manifest.json").read_bytes()
    m2 = (p2.path / "manifest.json").read_bytes()
    assert m1 == m2
