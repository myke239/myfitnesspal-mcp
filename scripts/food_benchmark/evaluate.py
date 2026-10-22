"""Score committed predictions against a separate key; never fits correction factors."""

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def load_jsonl(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def score(predictions, truth):
    if len({r["sample_id"] for r in predictions}) != len(predictions):
        raise ValueError("Duplicate prediction IDs")
    if len({r["sample_id"] for r in truth}) != len(truth):
        raise ValueError("Duplicate truth IDs")
    predicted = {r["sample_id"]: r for r in predictions}
    answers = {r["sample_id"]: r for r in truth}
    if set(predicted) - set(answers):
        raise ValueError("Predictions contain unknown sample IDs")
    if not predictions:
        raise ValueError("No predictions to evaluate")
    records = []
    for sample_id, prediction in predicted.items():
        target = answers[sample_id]["mass_g"]
        mass, low, high = (prediction[k] for k in ("mass_g", "lower_g", "upper_g"))
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in (target, mass, low, high)
        ):
            raise ValueError("Masses must be finite numbers")
        if target <= 0 or not 0 <= low <= mass <= high:
            raise ValueError("Invalid target or prediction interval")
        records.append(
            {
                "sample_id": sample_id,
                "error_g": mass - target,
                "absolute_error_g": abs(mass - target),
                "absolute_percentage_error": abs(mass - target) / target * 100,
                "in_interval": low <= target <= high,
                "interval_width_g": high - low,
                "target_mass_g": target,
            }
        )
    result = {
        "scored": len(records),
        "expected": len(truth),
        "prediction_completion_fraction": len(records) / len(truth),
        "mass_mae_g": statistics.mean(r["absolute_error_g"] for r in records),
        "mass_median_ape_percent": statistics.median(
            r["absolute_percentage_error"] for r in records
        ),
        "mass_mean_ape_percent": statistics.mean(
            r["absolute_percentage_error"] for r in records
        ),
        "mass_wape_percent": sum(r["absolute_error_g"] for r in records)
        / sum(r["target_mass_g"] for r in records)
        * 100,
        "mass_bias_g": statistics.mean(r["error_g"] for r in records),
        "overestimation_fraction": sum(r["error_g"] > 0 for r in records)
        / len(records),
        "subjective_interval_coverage": sum(r["in_interval"] for r in records)
        / len(records),
        "mean_interval_width_g": statistics.mean(
            r["interval_width_g"] for r in records
        ),
        "errors_above_50_percent": sum(
            r["absolute_percentage_error"] > 50 for r in records
        ),
        "errors_above_100_percent": sum(
            r["absolute_percentage_error"] > 100 for r in records
        ),
        "limitations": [
            "Development pilot, not a held-out accuracy estimate.",
            "Subjective intervals are not advertised as calibrated confidence intervals.",
            "Food identification is descriptive and has not been independently graded.",
        ],
    }
    nutrition = {}
    for metric in ("kcal", "protein_g", "fat_g", "carbohydrate_g"):
        pairs = [
            (predicted[sid].get(metric), answers[sid].get(metric)) for sid in predicted
        ]
        pairs = [(p, t) for p, t in pairs if p is not None and t is not None]
        if any(
            not isinstance(v, (int, float))
            or isinstance(v, bool)
            or not math.isfinite(v)
            or v < 0
            for pair in pairs
            for v in pair
        ):
            raise ValueError("Invalid nutrition prediction/target")
        nutrition[metric] = {"scored": len(pairs), "expected": len(truth)}
        if pairs:
            nutrition[metric].update(
                mae=statistics.mean(abs(p - t) for p, t in pairs),
                bias=statistics.mean(p - t for p, t in pairs),
                wape_percent=sum(abs(p - t) for p, t in pairs)
                / sum(t for _, t in pairs)
                * 100
                if sum(t for _, t in pairs) > 0
                else None,
            )
    result["nutrition_metrics"] = nutrition
    if not any(item["scored"] for item in nutrition.values()):
        result["limitations"].append("No calorie or macro predictions were scored.")
    return result, records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    result, records = score(load_jsonl(args.predictions), load_jsonl(args.truth))
    if not args.allow_partial and result["scored"] != result["expected"]:
        raise ValueError(
            "Incomplete prediction set; use --allow-partial only for an explicitly partial report"
        )
    committed = args.predictions.with_name("predictions-commit.json")
    if committed.exists():
        if (
            json.loads(committed.read_text())["sha256"]
            != hashlib.sha256(args.predictions.read_bytes()).hexdigest()
        ):
            raise ValueError("Predictions changed after the blind commit")
    result["predictions_sha256"] = hashlib.sha256(
        args.predictions.read_bytes()
    ).hexdigest()
    result["truth_sha256"] = hashlib.sha256(args.truth.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    args.output.with_name(args.output.stem + "-records.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
