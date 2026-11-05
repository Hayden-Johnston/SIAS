import json

import pytest
from test_sweep import config, update

from data_processing import ablation, run


def test_single_stage_rejected(tmp_path):
    """Ablation requires at least two stages."""
    scores = [[1, 0, 0, 0], [0, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", [[1, 0, 1, 0], scores[1]])
    data = json.loads(dev.read_text())
    update(dev, stages=data["stages"][:1])
    with pytest.raises(ValueError, match="multiple stages"):
        ablation.ablation(dev, held, 0)


def test_tied_weights_deterministic_choice(tmp_path):
    """Identical stage scores produce a deterministic weight choice."""
    scores = [[0.8, 0.8, 0, 0], [0.8, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", scores)
    result = ablation.ablation(dev, held, 0)
    # (0,1) and (1,0) tie on detection and FPR; lexicographic tie-break picks (0,1).
    assert result["full"]["weights"] == {"a": 0, "b": 1}
    # Repeat to confirm determinism.
    again = ablation.ablation(dev, held, 0)
    assert again["full"]["weights"] == result["full"]["weights"]
    for name in ("a", "b"):
        assert again["removed_stages"][name]["weights"] == result["removed_stages"][name]["weights"]


def test_empty_cache_raises(tmp_path):
    """An empty cache file (valid checksum) produces a missing score error."""
    scores = [[1, 0, 0, 0], [0, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", [[1, 0, 1, 0], scores[1]])
    cache = held.parent / "b.jsonl"
    cache.write_text("")
    data = json.loads(held.read_text())
    data["stages"][1]["cache_sha256"] = run.digest(cache)
    update(held, stages=data["stages"])
    with pytest.raises(ValueError, match="missing required cached score"):
        ablation.ablation(dev, held, 0)


def test_missing_cache_file_raises(tmp_path):
    """A missing cache file raises an OSError."""
    scores = [[1, 0, 0, 0], [0, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", [[1, 0, 1, 0], scores[1]])
    (held.parent / "b.jsonl").unlink()
    with pytest.raises(OSError):
        ablation.ablation(dev, held, 0)


def test_byte_identical_repeated_runs(tmp_path):
    """Two ablation runs with the same inputs produce byte-identical output."""
    scores = [[1, 0, 0, 0], [0, 0.8, 0, 0]]
    dev = config(tmp_path / "dev", "validation", scores)
    held = config(tmp_path / "held", "held_out", [[1, 0, 1, 0], scores[1]])
    output = tmp_path / "out" / "ablation.json"
    ablation.ablation(dev, held, 0, output)
    first = output.read_bytes()
    ablation.ablation(dev, held, 0, output)
    assert output.read_bytes() == first
