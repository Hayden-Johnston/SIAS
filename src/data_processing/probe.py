"""Train a deterministic logistic probe on dev activations and export replay scores."""

import argparse
import hashlib
import json
from pathlib import Path

from data_processing.normalize import canonical_json, validate_record
from data_processing.run import atomic_write, digest, load_json, read_rows

IDENTITY_FIELDS = ("model_identity", "tokenizer_version", "layers", "dtype")


def read_labels(path):
    labels = {}
    for line, row in read_rows(path):
        try:
            row = validate_record(row)
        except ValueError as error:
            raise ValueError(f"dataset line {line}: {error}") from None
        if row["id"] in labels:
            raise ValueError("duplicate dataset id")
        labels[row["id"]] = row["label"]
    return labels


def load_vectors(index_path, ids, layer):
    import numpy as np
    import torch
    from safetensors import safe_open

    index_path = Path(index_path)
    if index_path.suffix == ".jsonl":
        index_path = index_path.with_suffix(".json")
    header = load_json(index_path)
    if not isinstance(header, dict) or header.get("schema_version") != 2:
        raise ValueError("activation index must use append-only schema version 2")
    if any(header.get(field) is None for field in IDENTITY_FIELDS):
        raise ValueError("activation index missing identity")
    identity = {field: header[field] for field in IDENTITY_FIELDS}
    layers = identity["layers"]
    if (not isinstance(layers, list) or not layers
            or any(type(value) is not int or value < 0 for value in layers)
            or len(set(layers)) != len(layers) or layer not in layers):
        raise ValueError("requested layer not in valid index layers")
    dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16,
             "float32": torch.float32}.get(identity["dtype"])
    if dtype is None:
        raise ValueError("unsupported activation dtype")
    vectors, seen, inputs = {}, set(), {index_path.resolve()}
    entries_path = index_path.with_suffix(".jsonl")
    inputs.add(entries_path.resolve())
    with entries_path.open("rb") as reader:
        for line in reader:
            if not line.endswith(b"\n"):
                break  # Match capture resume: incomplete final appends are uncommitted.
            try:
                entry = json.loads(line)
            except (ValueError, UnicodeError):
                raise ValueError("invalid activation index entry") from None
            if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                    or entry["id"] in seen):
                raise ValueError("invalid or duplicate activation id")
            seen.add(entry["id"])
            for field in IDENTITY_FIELDS:
                if entry.get(field) != identity[field]:
                    raise ValueError(f"shard {field} mismatch")
            if not isinstance(entry.get("file"), str) or not entry["file"]:
                raise ValueError("shard entry missing file")
            shard = (index_path.parent / entry["file"]).resolve()
            if not shard.is_relative_to(index_path.parent.resolve()):
                raise ValueError("shard path outside activation directory")
            inputs.add(shard)
            if digest(shard) != entry.get("sha256"):
                raise ValueError("shard checksum mismatch")
            with safe_open(str(shard), framework="pt", device="cpu") as handle:
                meta = handle.metadata() or {}
                expected = {"prompt_id": entry["id"], **{
                    key: canonical_json(value) if key in ("model_identity", "layers") else value
                    for key, value in identity.items()
                }}
                if any(meta.get(key) != value for key, value in expected.items()):
                    raise ValueError("shard metadata identity mismatch")
                if entry["id"] not in ids:
                    continue
                tensor = handle.get_tensor("last_token")
                if (list(tensor.shape) != [len(layers), header.get("hidden_size")]
                        or tensor.dtype != dtype):
                    raise ValueError("last_token shape/dtype mismatch")
                vector = tensor[layers.index(layer)].to(torch.float64).numpy()
                if not np.isfinite(vector).all():
                    raise ValueError("nonfinite activation")
                vectors[entry["id"]] = vector
    missing = sorted(ids - vectors.keys())
    if missing:
        raise ValueError("missing activation ids: " + canonical_json(missing))
    return vectors, identity, inputs


def fit_probe(x, y):
    """Full-batch L2 logistic regression, zero initialized (no random sampling)."""
    import numpy as np

    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1
    x = (x - mean) / scale
    x = np.column_stack((x, np.ones(len(x))))
    weights = np.zeros(x.shape[1])
    penalty = 0.01  # L2 strength on coefficients; intercept is unpenalized.
    # Frobenius bound on logistic loss curvature gives a safe fixed step size.
    step = 1 / (0.25 * np.square(x).sum() / len(x) + penalty)
    for _ in range(2000):
        probability = 1 / (1 + np.exp(-np.clip(x @ weights, -700, 700)))
        gradient = x.T @ (probability - y) / len(x)
        gradient[:-1] += penalty * weights[:-1]
        weights -= step * gradient
    return mean, scale, weights


def write_cache(index, dataset, output, *, layer, train_split="dev"):
    try:
        import numpy as np
    except ImportError:
        raise ValueError("probe requires the activations extra (uv sync --extra activations)") from None

    if train_split != "dev":
        raise ValueError("train-split must be dev; test/heldout training is forbidden")
    if type(layer) is not int or layer < 0:
        raise ValueError("layer must be a nonnegative integer")
    dataset, output = Path(dataset), Path(output)
    train_path = dataset.parent / f"{train_split}.jsonl"
    manifest_path = dataset.parent / "split_manifest.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("splits"), dict):
        raise ValueError("invalid split manifest")  # noqa: TRY004 - external JSON
    train = read_labels(train_path)
    split = manifest.get("splits", {}).get(train_split, {})
    if (not isinstance(split, dict) or manifest.get("schema_version") != 2 or split.get("output_sha256") != digest(train_path)
            or split.get("records") != len(train)):
        raise ValueError("dev split manifest checksum/count mismatch")
    if set(train.values()) != {0, 1}:
        raise ValueError("dev training requires both labels")
    labels = read_labels(dataset)
    if not labels:
        raise ValueError("scoring dataset must not be empty")
    try:
        vectors, identity, inputs = load_vectors(index, train.keys() | labels.keys(), layer)
    except ImportError:
        raise ValueError("probe requires the activations extra (uv sync --extra activations)") from None
    inputs |= {path.resolve() for path in (dataset, train_path, manifest_path)}
    if output.resolve() in inputs:
        raise ValueError("output must not overwrite probe inputs")
    train_ids = sorted(train)
    mean, scale, weights = fit_probe(
        np.stack([vectors[key] for key in train_ids]), np.array([train[key] for key in train_ids])
    )
    version_data = {"identity": identity, "layer": layer, "mean": mean.tolist(),
                    "scale": scale.tolist(), "weights": weights.tolist(),
                    "producer_sha256": digest(__file__), "train_sha256": digest(train_path)}
    version = "probe-sha256-" + hashlib.sha256(canonical_json(version_data).encode()).hexdigest()
    entries = []
    for key in sorted(labels):
        logit = ((vectors[key] - mean) / scale) @ weights[:-1] + weights[-1]
        score = float(1 / (1 + np.exp(-np.clip(logit, -700, 700))))
        # No capture/inference latency is available; 0 denotes unmeasured work.
        entries.append({"id": key, "score": score, "latency_ms": 0})
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, "".join(canonical_json(row) + "\n" for row in entries).encode())
    return {"version": version, "cache_sha256": digest(output), "records": len(entries),
            "train_records": len(train), "train_split": train_split, "layer": layer,
            "identity": identity, "dataset_sha256": digest(dataset),
            "train_sha256": digest(train_path), "latency_measured": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("out_cache", type=Path)
    parser.add_argument("--layer", type=int, required=True)
    parser.add_argument("--train-split", choices=["dev"], default="dev")
    args = parser.parse_args()
    try:
        result = write_cache(args.index, args.dataset, args.out_cache,
                             layer=args.layer, train_split=args.train_split)
    except ValueError as error:
        parser.exit(2, f"probe failed: {error}\n")
    except OSError:
        parser.exit(2, "probe failed: file operation failed\n")
    print(canonical_json(result))


if __name__ == "__main__":
    main()
