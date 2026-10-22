"""Research-only affine calibration; never installs factors into production."""

import json
import statistics

from scripts.food_benchmark.acquire import ROOT, save_json


def fit(rows):
    candidates = []
    for ai in range(10, 61):
        a = ai / 20
        for b in range(-100, 101, 5):
            loss = statistics.mean(
                abs(max(1, a*r["predicted_g"]+b)-r["actual_g"])/r["actual_g"] for r in rows)
            candidates.append((loss, abs(a-1), abs(b), a, b))
    return min(candidates)[-2:]


def main():
    folder = ROOT / "work/food-estimation"
    development = json.loads((folder/"chicken-side-v2-dev/report.json").read_text())["records"]
    a, b = fit(development)
    cross_validation = []
    for i, row in enumerate(development):
        aa, bb = fit(development[:i]+development[i+1:])
        cross_validation.append(abs(max(1, aa*row["predicted_g"]+bb)-row["actual_g"])/row["actual_g"]*100)
    report = {"training_n": len(development), "a": a, "b": b,
              "leave_one_out_mean_ape": statistics.mean(cross_validation),
              "leave_one_out_within20": sum(v<=20 for v in cross_validation)/len(cross_validation),
              "promoted": False}
    for source in ("chicken-side-v2-heldout", "chicken-v2-asa-heldout"):
        rows = json.loads((folder/source/"report.json").read_text())["records"]
        errors = [abs(max(1, a*r["predicted_g"]+b)-r["actual_g"])/r["actual_g"]*100 for r in rows]
        report[source] = {"n": len(errors), "mean_ape": statistics.mean(errors),
                          "within20": sum(v<=20 for v in errors)/len(errors), "maximum_ape": max(errors)}
    save_json(folder/"chicken-calibration-experiment.json", report)


if __name__ == "__main__":
    main()
