"""Prototype configuration and packaging checks; no datasets or servers are used."""

import importlib
import json
from pathlib import Path

import pytest

from llm_security import main as prototype


def test_packages_importable():
    for name in ("llm_security.pipeline", "data_processing.dataset", "llm_proxy.proxy"):
        assert importlib.import_module(name)


def test_main_uses_local_config(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[1] / "config.example.json"
    config = json.loads(example.read_text())
    monkeypatch.chdir(tmp_path)
    local = tmp_path / "config.local.json"
    local.write_text(json.dumps(config))
    # A legacy file must neither be read nor updated.
    legacy = tmp_path / "config.json"
    legacy.write_text("legacy config")
    calls = []
    dataset = object()

    def data_handler(actual):
        calls.append(("dataset", actual))
        return dataset

    class Pipeline:
        def __init__(self, actual, ds):
            assert ds is dataset
            calls.append(("pipeline", actual))

        def run(self):
            calls.append(("run", None))

    monkeypatch.setattr(prototype, "load_dotenv", lambda: None)
    monkeypatch.setattr(prototype, "DataHandler", data_handler)
    monkeypatch.setattr(prototype, "Pipeline", Pipeline)
    prototype.main()
    expected = dict(config, run_count=config["run_count"] + 1)
    assert json.loads(local.read_text()) == expected
    assert calls == [("dataset", expected), ("pipeline", expected), ("run", None)]
    assert legacy.read_text() == "legacy config"


def test_missing_local_config_does_not_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(prototype, "load_dotenv", lambda: None)
    with pytest.raises(FileNotFoundError, match="config.local.json"):
        prototype.main()
