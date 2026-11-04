"""Approved-source loaders use synthetic fixtures only."""

import gzip
import json

import pytest

from data_processing.sources import convert, load_source

REVISION = "a" * 40
TIMESTAMP = "2026-11-04T00:00:00Z"


def run_loader(tmp_path, source, rows):
    path = tmp_path / "input.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    output, manifest = tmp_path / "out.jsonl", tmp_path / "manifest.json"
    result = load_source(source, [path], output, manifest,
                         revision=REVISION, timestamp=TIMESTAMP)
    return result, [json.loads(line) for line in output.read_text().splitlines()]


@pytest.mark.parametrize("source,row,label,techniques", [
    ("deepset", {"text": "synthetic café\n", "label": 1}, 1, ["novel"]),
    ("deepset", {"text": "synthetic benign", "label": 0}, 0, []),
    ("jackhhao", {"prompt": "synthetic", "type": "jailbreak"}, 1, ["novel"]),
    ("jackhhao", {"prompt": "synthetic", "type": "benign"}, 0, []),
    ("trustair", {"prompt": "synthetic", "jailbreak": True}, 1, ["novel"]),
    ("trustair", {"prompt": "synthetic", "jailbreak": True,
                  "community": "fixture-family", "community_id": 1.0}, 1, ["named_jailbreak"]),
    ("trustair", {"prompt": "synthetic", "jailbreak": False}, 0, []),
    ("gandalf", {"text": "synthetic"}, 1, ["override"]),
    ("spml", {"User Prompt": "synthetic", "Prompt injection": "1"}, 1, ["novel"]),
    ("spml", {"User Prompt": "synthetic", "Prompt injection": "0"}, 0, []),
    ("llmail", {"text": "synthetic", "annotation": {"attack_attempt": "True"}}, 1, ["novel"]),
    ("llmail", {"text": "synthetic", "annotation": {"attack_attempt": True}}, 1, ["novel"]),
    ("dolly", {"instruction": "synthetic", "context": "context"}, 0, []),
])
def test_source_labels_provenance_and_taxonomy(tmp_path, source, row, label, techniques):
    result, rows = run_loader(tmp_path, source, [row])
    record = rows[0]
    assert record["label"] == label
    assert record["techniques"] == techniques
    assert record["spans"] == (None if label else [])
    assert record["channel"] == ("email" if source == "llmail" else "direct")
    assert record["publishable"] == "yes"
    assert record["source"].endswith("/tree/" + REVISION)
    assert record["timestamp"] == TIMESTAMP
    assert result["evaluator_approved"] is False
    if source == "dolly":
        assert record["text"] == "synthetic\n\ncontext"
        assert record["license"] == "CC-BY-SA-3.0"
    if source == "deepset":
        assert record["text"] == row["text"]


def test_replay_deduplication_and_raw_checksums(tmp_path):
    import hashlib

    rows = [{"text": "synthetic", "label": 1}] * 2
    first, records = run_loader(tmp_path, "deepset", rows)
    before = (tmp_path / "out.jsonl").read_bytes(), (tmp_path / "manifest.json").read_bytes()
    second, _ = run_loader(tmp_path, "deepset", rows)
    assert first == second
    assert before == ((tmp_path / "out.jsonl").read_bytes(),
                      (tmp_path / "manifest.json").read_bytes())
    assert first["loader"]["duplicates"] == 1
    assert first["loader"]["raw_sha256"] == [
        hashlib.sha256((tmp_path / "input.jsonl").read_bytes()).hexdigest()]
    assert first["output_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert len(records) == 1
    assert records[0]["text"] not in before[1].decode()


def node(identity, role, text, replies=(), **changes):
    return {"message_id": identity, "role": role, "text": text,
            "deleted": False, "review_result": True, "replies": list(replies)} | changes


def test_oasst_paths_preserve_turns_and_tree_groups(tmp_path):
    root = node("root", "prompter", "synthetic user", [
        node("a", "assistant", "first answer"), node("b", "assistant", "second answer"),
        node("c", "assistant", "deleted answer", deleted=True),
        node("d", "assistant", "unreviewed answer", review_result=False),
    ])
    result, rows = run_loader(tmp_path, "oasst2", [{"message_tree_id": "tree", "prompt": root}])
    assert result["channels"] == {"multi_turn": 2}
    assert len({row["group_id"] for row in rows}) == 1
    assert len({row["id"] for row in rows}) == 2
    for row in rows:
        assert row["label"] == 0 and row["spans"] == [] and row["techniques"] == []
        assert json.loads(row["text"])[0] == {"role": "user", "content": "synthetic user"}
        assert json.loads(row["text"])[1]["role"] == "assistant"


def test_llmail_json_is_filtered_and_capped(tmp_path):
    path = tmp_path / "mail.json"
    rows = {f"synthetic mail {i}": {"attack_attempt": "True"} for i in range(50_002)}
    rows["synthetic failed label"] = {"attack_attempt": "False"}
    rows["synthetic ambiguous label"] = {"attack_attempt": [True]}
    path.write_text(json.dumps(rows))
    result = load_source("llmail", [path], tmp_path / "out", tmp_path / "manifest",
                         revision=REVISION, timestamp=TIMESTAMP)
    assert result["records"] == 50_000
    assert result["loader"]["excluded"] == 4
    assert result["channels"] == {"email": 50_000}


def test_spml_empty_prompt_is_counted_as_excluded(tmp_path):
    result, rows = run_loader(tmp_path, "spml", [
        {"User Prompt": "", "Prompt injection": "1"},
        {"User Prompt": "synthetic", "Prompt injection": "1"},
    ])
    assert len(rows) == 1
    assert result["loader"]["excluded"] == 1


def test_jbb_catalogs_seeds_without_scored_rows(tmp_path):
    result, rows = run_loader(tmp_path, "jbb", [{"Goal": "synthetic seed"}])
    assert rows == []
    assert result["records"] == 0 and result["labels"] == {}
    assert result["loader"]["role"] == "red_team_seeds_only"
    assert result["loader"]["input_rows"] == 1
    with pytest.raises(ValueError, match="seeds only"):
        list(convert("jbb", {"Goal": "synthetic seed"}))


@pytest.mark.parametrize("source,row", [
    ("deepset", {"text": "private synthetic fixture", "label": True}),
    ("jackhhao", {"prompt": "private synthetic fixture", "type": "private synthetic fixture"}),
    ("trustair", {"prompt": "private synthetic fixture", "jailbreak": "true"}),
    ("spml", {"User Prompt": "private synthetic fixture", "Prompt injection": "unknown"}),
    ("oasst2", {"prompt": {"role": "private synthetic fixture"}}),
])
def test_invalid_fields_fail_without_payloads_or_replacing_outputs(tmp_path, source, row):
    (tmp_path / "out.jsonl").write_text("previous")
    (tmp_path / "manifest.json").write_text("previous")
    with pytest.raises(ValueError) as error:
        run_loader(tmp_path, source, [row])
    assert "private synthetic fixture" not in str(error.value)
    assert (tmp_path / "out.jsonl").read_text() == "previous"
    assert (tmp_path / "manifest.json").read_text() == "previous"


@pytest.mark.parametrize("format", ["csv", "parquet", "jsonl.gz"])
def test_local_file_formats(tmp_path, format):
    from data_processing.sources import read_rows

    path = tmp_path / ("source." + format)
    if format == "csv":
        path.write_text('text,label\n"synthetic\nmultiline",1\n')
        assert list(read_rows(path)) == [{"text": "synthetic\nmultiline", "label": "1"}]
    else:
        rows = [{"text": "synthetic", "label": 1}]
        if format == "parquet":
            import pyarrow as pa
            import pyarrow.parquet as pq

            pq.write_table(pa.Table.from_pylist(rows), path)
        else:
            with gzip.open(path, "wt") as writer:
                writer.write(json.dumps(rows[0]) + "\n")
        assert list(read_rows(path)) == rows


def test_distinct_paths_are_required(tmp_path):
    path = tmp_path / "input"
    path.write_text("{}\n")
    with pytest.raises(ValueError, match="distinct"):
        load_source("deepset", [path], path, tmp_path / "manifest",
                    revision=REVISION, timestamp=TIMESTAMP)


def test_conflicting_source_ids_fail_instead_of_deduplicating(tmp_path):
    trees = [{"message_tree_id": "tree", "prompt": node("same-id", "prompter", text)}
             for text in ["synthetic first", "synthetic conflicting"]]
    with pytest.raises(ValueError, match="invalid source fields"):
        run_loader(tmp_path, "oasst2", trees)
    assert not (tmp_path / "out.jsonl").exists()
    assert not (tmp_path / "manifest.json").exists()
