"""Capture hidden-state activations from a Hugging Face causal LM into safetensors shards."""

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
from pathlib import Path

from data_processing.normalize import FIELDS, canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, number, read_rows

DEFAULT_MODEL = "hf-internal-testing/tiny-random-LlamaForCausalLM"
DEFAULT_MIN_FREE_GB = 20.0
SAFE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _import_ml():
    try:
        import torch
        import transformers
        from huggingface_hub import try_to_load_from_cache
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from transformers.utils import logging as hf_logging
    except ImportError as error:
        raise ValueError("torch, transformers, and safetensors are required for activations") from error
    hf_logging.set_verbosity_error()
    hf_logging.disable_progress_bar()
    return torch, transformers, try_to_load_from_cache, AutoModelForCausalLM, AutoTokenizer


def resolve_dtype(name, torch):
    mapping = {
        "fp16": ("float16", torch.float16),
        "float16": ("float16", torch.float16),
        "bf16": ("bfloat16", torch.bfloat16),
        "bfloat16": ("bfloat16", torch.bfloat16),
        "fp32": ("float32", torch.float32),
        "float32": ("float32", torch.float32),
    }
    if not isinstance(name, str) or name not in mapping:
        raise ValueError("dtype must be fp16/float16, bf16/bfloat16, or fp32/float32")
    return mapping[name]


def load_model_and_tokenizer(model_name, revision=None, device="cpu"):
    _, _, _, auto_model, auto_tokenizer = _import_ml()
    try:
        tokenizer = auto_tokenizer.from_pretrained(
            model_name, revision=revision, local_files_only=True
        )
        model = auto_model.from_pretrained(
            model_name, revision=revision, local_files_only=True
        )
    except OSError:
        tokenizer = auto_tokenizer.from_pretrained(model_name, revision=revision)
        model = auto_model.from_pretrained(model_name, revision=revision)
    model.to(device)
    model.eval()
    return model, tokenizer


def weights_digest(model):
    torch, _, _, _, _ = _import_ml()
    result = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous()
        result.update(f"{name}:{array.dtype}:{tuple(array.shape)}:".encode())
        result.update(memoryview(array.view(torch.uint8).numpy()))
    return result.hexdigest()


def build_model_identity(model, model_name, revision=None):
    _, _, try_to_load_from_cache, _, _ = _import_ml()
    repo_id = str(model_name or getattr(model.config, "_name_or_path", "unknown"))
    commit_hash = revision or getattr(model.config, "_commit_hash", None)
    if not commit_hash:
        try:
            cached = try_to_load_from_cache(repo_id, "config.json", revision=revision)
            if isinstance(cached, str) and Path(cached).parent.parent.name == "snapshots":
                commit_hash = Path(cached).parent.name
        except (OSError, ValueError):
            commit_hash = None
    weights_sha256 = weights_digest(model)
    return {
        "repo_id": repo_id,
        "commit_hash": commit_hash or f"sha256:{weights_sha256}",
        "weights_sha256": weights_sha256,
    }


def build_tokenizer_version(tokenizer):
    _, transformers, _, _, _ = _import_ml()
    vocab = tokenizer.get_vocab() if hasattr(tokenizer, "get_vocab") else {}
    payload = {
        "class": tokenizer.__class__.__name__,
        "transformers_version": transformers.__version__,
        "vocab": vocab,
        "special_tokens": getattr(tokenizer, "special_tokens_map", {}),
    }
    vocab_hash = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{tokenizer.__class__.__name__}-transformers-{transformers.__version__}-sha256-{vocab_hash}"


def select_layers(num_layers, layer_step=3, layers=None):
    if type(num_layers) is not int or num_layers < 1:
        raise ValueError("model must have at least one hidden layer")
    if layers is not None:
        if (not isinstance(layers, (list, tuple)) or not layers
                or any(type(idx) is not int or not (0 <= idx < num_layers) for idx in layers)
                or len(set(layers)) != len(layers)):
            raise ValueError("layers must be a nonempty list of unique valid layer indices")
        return sorted(layers)
    if type(layer_step) is not int or layer_step < 1:
        raise ValueError("layer_step must be a positive integer")
    return list(range(0, num_layers, layer_step))


def select_sampled_ids(ids, per_token_fraction=None, per_token_count=None, seed=0):
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if per_token_fraction is not None and per_token_count is not None:
        raise ValueError("specify at most one of per_token_fraction or per_token_count")
    if per_token_count is not None:
        if type(per_token_count) is not int or per_token_count < 0:
            raise ValueError("per_token_count must be a nonnegative integer")
        target = min(per_token_count, len(ids))
    else:
        fraction = 0.05 if per_token_fraction is None else number(
            per_token_fraction, "per_token_fraction", 1.0
        )
        target = round(len(ids) * fraction)
    if target <= 0:
        return set()
    ranked = sorted(
        ids,
        key=lambda pid: (hashlib.sha256(f"{seed}:{pid}".encode()).hexdigest(), pid),
    )
    return set(ranked[:target])


def serialize_shard(torch, tensors, metadata):
    dtype_tags = {
        torch.float16: "F16",
        torch.bfloat16: "BF16",
        torch.float32: "F32",
    }
    header = {"__metadata__": dict(sorted(metadata.items()))}
    buffers = []
    offset = 0
    for key in sorted(tensors):
        array = tensors[key].detach().cpu().contiguous()
        buf = memoryview(array.view(torch.uint8).numpy()).tobytes()
        buffers.append(buf)
        header[key] = {
            "dtype": dtype_tags[array.dtype],
            "shape": list(array.shape),
            "data_offsets": [offset, offset + len(buf)],
        }
        offset += len(buf)
    header_bytes = canonical_json(header).encode("utf-8")
    pad = (-len(header_bytes)) % 8
    if pad:
        header_bytes += b" " * pad
    return struct.pack("<Q", len(header_bytes)) + header_bytes + b"".join(buffers)


def shard_filename(prompt_id):
    if SAFE_ID.fullmatch(prompt_id) and prompt_id not in {".", ".."}:
        return f"{prompt_id}.safetensors"
    digest_hex = hashlib.sha256(prompt_id.encode("utf-8")).hexdigest()
    return f"id-{digest_hex}.safetensors"


def read_dataset(dataset, dataset_manifest=None):
    dataset = Path(dataset)
    manifest = None
    if dataset_manifest is not None:
        manifest = load_json(dataset_manifest)
        if (not isinstance(manifest, dict) or manifest.get("schema_version") != 2
                or manifest.get("output_sha256") != digest(dataset)):
            raise ValueError("dataset manifest version/checksum mismatch; schema version 2 required")
    rows, ids = [], set()
    for line, row in read_rows(dataset):
        if manifest is not None or (isinstance(row, dict) and set(row) == FIELDS):
            try:
                row = validate_record(row)
            except ValueError as error:
                raise ValueError(f"dataset line {line}: {error}") from None
        else:
            if not isinstance(row, dict):
                raise ValueError(f"dataset line {line}: record must be an object")
            for field in ("id", "text"):
                if not isinstance(row.get(field), str) or not row[field].strip():
                    raise ValueError(f"dataset line {line}: {field} must be a nonempty string")
        if row["id"] in ids:
            raise ValueError("duplicate dataset id")
        ids.add(row["id"])
        rows.append({"id": row["id"], "text": row["text"]})
    if manifest is not None and manifest.get("records") != len(rows):
        raise ValueError("dataset manifest record count mismatch")
    return rows


def validate_existing_index(index_path, output_dir, identity, tok_version, selected_layers, dtype_name):
    existing = load_json(index_path)
    if not isinstance(existing, dict) or existing.get("schema_version") not in (1, 2):
        raise ValueError("invalid activation index format")
    checks = [
        ("model_identity", existing.get("model_identity"), identity),
        ("tokenizer_version", existing.get("tokenizer_version"), tok_version),
        ("layers", existing.get("layers"), selected_layers),
        ("dtype", existing.get("dtype"), dtype_name),
    ]
    for name, found, expected in checks:
        if found != expected:
            raise ValueError(f"index {name} mismatch; refusing to append")
    entries_path = output_dir / "index.jsonl"
    valid_bytes = 0
    if existing["schema_version"] == 1:
        if not isinstance(existing.get("shards"), dict):
            raise ValueError("invalid activation index format")
        entries = list(existing["shards"].values())
        if any(not isinstance(entry, dict) or entry.get("id") != key
               for key, entry in existing["shards"].items()):
            raise ValueError("invalid shard entry in index")
    else:
        entries = []
        if entries_path.exists():
            with entries_path.open("rb") as handle:
                for line in handle:
                    if not line.endswith(b"\n"):
                        break  # An interrupted append is not committed; recapture its shard.
                    try:
                        entries.append(json.loads(line))
                    except (ValueError, UnicodeDecodeError):
                        raise ValueError("invalid shard entry in index") from None
                    valid_bytes += len(line)
        elif existing.get("records"):
            raise ValueError("activation index.jsonl missing")
    shards = {}
    for entry in entries:
        if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                or entry["id"] in shards):
            raise ValueError("invalid shard entry in index")
        prompt_id = entry["id"]
        for name, expected in (
            ("model_identity", identity),
            ("tokenizer_version", tok_version),
            ("layers", selected_layers),
            ("dtype", dtype_name),
        ):
            if entry.get(name) != expected:
                raise ValueError(f"shard {name} mismatch; refusing to append")
        rel_file = entry.get("file")
        if not isinstance(rel_file, str) or not rel_file:
            raise ValueError("shard entry missing file path")
        shard_path = output_dir / rel_file
        if not shard_path.is_file() or digest(shard_path) != entry.get("sha256"):
            raise ValueError("existing shard file missing or checksum mismatch")
        shards[prompt_id] = entry
    if existing["schema_version"] == 1:
        # One-time migration; replace the header only after all old entries are written.
        atomic_write(entries_path, b"".join(
            (canonical_json(entry) + "\n").encode("utf-8") for entry in entries
        ))
    elif entries_path.exists() and entries_path.stat().st_size != valid_bytes:
        with entries_path.open("r+b") as handle:
            handle.truncate(valid_bytes)
    return shards


def append_index(index_path, entry):
    data = (canonical_json(entry) + "\n").encode("utf-8")
    with index_path.open("ab", buffering=0) as handle:
        if handle.write(data) != len(data):
            raise OSError("incomplete activation index append")
        os.fsync(handle.fileno())


def write_index(index_path, status, identity, tok_version, selected_layers, dtype_name,
                hidden_size, max_tokens, shards):
    index = {
        "schema_version": 2,
        "status": status,
        "model_identity": identity,
        "tokenizer_version": tok_version,
        "layers": selected_layers,
        "dtype": dtype_name,
        "hidden_size": hidden_size,
        "max_tokens": max_tokens,
        "records": len(shards),
        "truncated_count": sum(1 for entry in shards.values() if entry["truncated"]),
        "per_token_count": sum(1 for entry in shards.values() if entry["has_per_token"]),
    }
    atomic_write(index_path, (canonical_json(index) + "\n").encode("utf-8"))
    return index


def capture_activations(
    dataset,
    output_dir,
    *,
    dataset_manifest=None,
    model_name=DEFAULT_MODEL,
    revision=None,
    model=None,
    tokenizer=None,
    model_identity=None,
    tokenizer_version=None,
    layer_step=3,
    layers=None,
    dtype="fp16",
    per_token_fraction=None,
    per_token_count=None,
    seed=0,
    max_tokens=512,
    device="cpu",
    min_free_gb=DEFAULT_MIN_FREE_GB,
    min_free_bytes=None,
):
    """Capture last-token, mean-pooled, and sampled per-token hidden states into safetensors shards."""
    torch, _, _, _, _ = _import_ml()
    dataset = Path(dataset)
    output_dir = Path(output_dir)
    if dataset.resolve() == output_dir.resolve():
        raise ValueError("dataset and output_dir must be distinct paths")
    if dataset_manifest is not None and Path(dataset_manifest).resolve() == output_dir.resolve():
        raise ValueError("dataset_manifest and output_dir must be distinct paths")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError("output_dir must be a directory path")
    if type(max_tokens) is not int or max_tokens < 1:
        raise ValueError("max_tokens must be a positive integer")
    if not isinstance(device, str) or not device.strip():
        raise ValueError("device must be a nonempty string")
    if min_free_bytes is None:
        limit_bytes = int(number(min_free_gb, "min_free_gb") * (1024 ** 3))
    else:
        if type(min_free_bytes) is not int or min_free_bytes < 0:
            raise ValueError("min_free_bytes must be a nonnegative integer")
        limit_bytes = min_free_bytes

    dtype_name, torch_dtype = resolve_dtype(dtype, torch)
    rows = read_dataset(dataset, dataset_manifest)
    sampled_ids = select_sampled_ids(
        [row["id"] for row in rows],
        per_token_fraction=per_token_fraction,
        per_token_count=per_token_count,
        seed=seed,
    )

    if model is None or tokenizer is None:
        model, tokenizer = load_model_and_tokenizer(model_name, revision=revision, device=device)
    else:
        model.to(device)
        model.eval()

    num_layers = int(model.config.num_hidden_layers)
    hidden_size = int(model.config.hidden_size)
    selected_layers = select_layers(num_layers, layer_step=layer_step, layers=layers)
    identity = model_identity if model_identity is not None else build_model_identity(
        model, model_name, revision=revision
    )
    tok_version = tokenizer_version if tokenizer_version is not None else build_tokenizer_version(
        tokenizer
    )

    shards_dir = output_dir / "shards"
    index_path = output_dir / "index.json"
    entries_path = output_dir / "index.jsonl"
    shards = {}
    if index_path.exists():
        shards = validate_existing_index(
            index_path, output_dir, identity, tok_version, selected_layers, dtype_name
        )

    if not index_path.exists() and entries_path.exists():
        raise ValueError("activation index header missing; refusing to append")
    shards_dir.mkdir(parents=True, exist_ok=True)
    write_index(
        index_path, "in_progress", identity, tok_version,
        selected_layers, dtype_name, hidden_size, max_tokens, shards,
    )
    entries_path.touch(exist_ok=True)
    captured = 0
    skipped = 0
    stopped_disk_limit = False

    if shutil.disk_usage(output_dir).free < limit_bytes:
        stopped_disk_limit = True
    else:
        for row in rows:
            prompt_id = row["id"]
            if prompt_id in shards:
                skipped += 1
                continue
            if shutil.disk_usage(output_dir).free < limit_bytes:
                stopped_disk_limit = True
                break

            full_ids = tokenizer.encode(row["text"], add_special_tokens=True)
            if not full_ids:
                bos = getattr(tokenizer, "bos_token_id", None)
                if bos is None:
                    raise ValueError("prompt produced zero tokens")
                full_ids = [int(bos)]
            raw_token_count = len(full_ids)
            truncated = raw_token_count > max_tokens
            token_ids = full_ids[:max_tokens]
            token_count = len(token_ids)

            with torch.no_grad():
                input_ids = torch.tensor([token_ids], dtype=torch.long, device=device)
                outputs = model(input_ids=input_ids, output_hidden_states=True)
                stacked = torch.stack(
                    [outputs.hidden_states[idx + 1][0] for idx in selected_layers],
                    dim=0,
                ).detach().cpu()
                last_token = stacked[:, -1, :].to(dtype=torch_dtype).contiguous()
                mean_pooled = (
                    stacked.to(dtype=torch.float32).mean(dim=1).to(dtype=torch_dtype).contiguous()
                )
                keep_per_token = prompt_id in sampled_ids
                tensors = {"last_token": last_token, "mean_pooled": mean_pooled}
                if keep_per_token:
                    tensors["per_token"] = stacked.to(dtype=torch_dtype).contiguous()

            shard_meta = {
                "dtype": dtype_name,
                "has_per_token": "true" if keep_per_token else "false",
                "layers": canonical_json(selected_layers),
                "max_tokens": str(max_tokens),
                "model_identity": canonical_json(identity),
                "prompt_id": prompt_id,
                "raw_token_count": str(raw_token_count),
                "token_count": str(token_count),
                "tokenizer_version": tok_version,
                "truncated": "true" if truncated else "false",
            }
            shard_bytes = serialize_shard(torch, tensors, shard_meta)
            fname = shard_filename(prompt_id)
            shard_path = shards_dir / fname
            entry = {
                "id": prompt_id,
                "file": f"shards/{fname}",
                "sha256": hashlib.sha256(shard_bytes).hexdigest(),
                "bytes": len(shard_bytes),
                "token_count": token_count,
                "raw_token_count": raw_token_count,
                "truncated": truncated,
                "has_per_token": keep_per_token,
                "model_identity": identity,
                "tokenizer_version": tok_version,
                "layers": selected_layers,
                "dtype": dtype_name,
            }
            entry_bytes = len((canonical_json(entry) + "\n").encode("utf-8"))
            if shutil.disk_usage(output_dir).free - len(shard_bytes) - entry_bytes < limit_bytes:
                stopped_disk_limit = True
                break
            atomic_write(shard_path, shard_bytes)
            append_index(entries_path, entry)
            shards[prompt_id] = entry
            captured += 1

    status = "stopped_disk_limit" if stopped_disk_limit else "complete"
    index = write_index(
        index_path, status, identity, tok_version,
        selected_layers, dtype_name, hidden_size, max_tokens, shards,
    )
    remaining = sum(1 for row in rows if row["id"] not in shards)
    return {
        "status": status,
        "stopped_disk_limit": stopped_disk_limit,
        "model_identity": identity,
        "tokenizer_version": tok_version,
        "layers": selected_layers,
        "dtype": dtype_name,
        "hidden_size": hidden_size,
        "max_tokens": max_tokens,
        "records": index["records"],
        "captured": captured,
        "skipped": skipped,
        "remaining": remaining,
        "truncated_count": index["truncated_count"],
        "per_token_count": index["per_token_count"],
        "index_sha256": hashlib.sha256(
            canonical_json([digest(index_path), digest(entries_path)]).encode("utf-8")
        ).hexdigest(),
    }


def parse_layers_arg(value):
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError("layers must not be empty")
    try:
        return [int(part) for part in parts]
    except ValueError:
        raise ValueError("layers must be comma-separated integers") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision")
    parser.add_argument("--layer-step", type=int, default=3)
    parser.add_argument("--layers")
    parser.add_argument("--dtype", default="fp16")
    parser.add_argument("--per-token-fraction", type=float)
    parser.add_argument("--per-token-count", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB)
    parser.add_argument("--min-free-bytes", type=int)
    args = parser.parse_args()
    try:
        layers = parse_layers_arg(args.layers)
        result = capture_activations(
            args.dataset,
            args.output_dir,
            dataset_manifest=args.dataset_manifest,
            model_name=args.model,
            revision=args.revision,
            layer_step=args.layer_step,
            layers=layers,
            dtype=args.dtype,
            per_token_fraction=args.per_token_fraction,
            per_token_count=args.per_token_count,
            seed=args.seed,
            max_tokens=args.max_tokens,
            device=args.device,
            min_free_gb=args.min_free_gb,
            min_free_bytes=args.min_free_bytes,
        )
    except ValueError as error:
        parser.exit(2, f"activation capture failed: {error}\n")
    except OSError:
        parser.exit(2, "activation capture failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
