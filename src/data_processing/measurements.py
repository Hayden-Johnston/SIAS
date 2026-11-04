import json
from pathlib import Path


def _safe_div(num, den):
    """Return num/den, or None if den is 0."""
    if den == 0:
        return None
    return num / den


def measure_results(results:dict):
    false_positive = 0
    false_negative = 0
    true_positive = 0
    true_negative = 0
    total_benign = 0
    total_attacks = 0
    correct = 0
    total_time = 0
    lines_incorrect = []
    total_lines = len(results)
    for k, v in results.items():
        out = round(v[0])
        expected = v[1]
        if expected == 0:
            total_benign += 1
        elif expected == 1:
            total_attacks += 1
        if out == expected:
            correct += 1
            if out == 0:
                true_negative += 1
            elif out == 1:
                true_positive += 1
        else:
            lines_incorrect.append(k)
            if out == 0:
                false_negative += 1
            elif out == 1:
                false_positive += 1
        total_time += v[2]
    mean_time = total_time / total_lines if total_lines else 0
    accuracy = _safe_div(correct, total_lines)
    precision = _safe_div(true_positive, true_positive + false_positive)
    true_pos_rate = _safe_div(true_positive, true_positive + false_negative)
    false_pos_rate = _safe_div(false_positive, total_benign)
    false_neg_rate = _safe_div(false_negative, total_attacks)
    true_neg_rate = _safe_div(true_negative, true_negative + false_positive)
    false_disc_rate = _safe_div(false_positive, false_positive + true_positive)

    res = {
        "tpr": true_pos_rate * 100 if true_pos_rate is not None else None,
        "fpr": false_pos_rate * 100 if false_pos_rate is not None else None,
        "tnr": true_neg_rate * 100 if true_neg_rate is not None else None,
        "fnr": false_neg_rate * 100 if false_neg_rate is not None else None,
        "fdr": false_disc_rate * 100 if false_disc_rate is not None else None,
        "accuracy": accuracy * 100 if accuracy is not None else None,
        "precision": precision,
        "total_lines": total_lines,
        "total_benign": total_benign,
        "total_attacks": total_attacks,
        "true_positives": true_positive,
        "false_negatives": false_negative,
        "false_positives": false_positive,
        "true_negatives": true_negative,
        "correct": correct,
        "average_time_ms": mean_time,
        "lines_incorrect": lines_incorrect
    }

    return res

def measure_all():
    for run in Path("data/results").iterdir():
        if not run.is_dir():
            continue
        output = run / "measurements.json"
        if output.exists():
            continue
        measurements = {}
        incorrect_lines = {}
        for path in run.glob("*/*.json"):
            with path.open("r", encoding="utf-8") as f:
                results = json.load(f)
            key = path.relative_to(run).as_posix()
            metrics = measure_results(results)
            incorrect_lines[key] = metrics.pop("lines_incorrect")
            measurements[key] = metrics
        with (run / "incorrect_lines.json").open("w", encoding="utf-8") as f:
            json.dump(incorrect_lines, f, indent=4)
        with output.open("w", encoding="utf-8") as f:
            json.dump(measurements, f, indent=4)

if __name__ == "__main__":
    measure_all()