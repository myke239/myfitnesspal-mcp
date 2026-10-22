"""Acquire mass-labelled basic foods and compare blinded portion estimates."""

import argparse
import base64
import concurrent.futures
import csv
import hashlib
import json
import os
import random
import re
import statistics
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image

from myfitnesspal_mcp import estimation
from scripts.food_benchmark.acquire import DATA, ROOT, digest, download, save_json
from scripts.food_benchmark.evaluate import load_jsonl
from scripts.food_benchmark.prepare import write_jsonl

BASICS = DATA / "basics"
GROUPS = {
    "chicken": {"chicken", "chicken breast", "grilled chicken", "chicken thighs"},
    "fish": {"fish", "salmon"},
    "steak": {"steak", "beef"},
    "salad": {"caesar salad", "garden salad", "lettuce", "greek salad"},
}


def xlsx_rows(path):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings = ["".join(item.itertext()) for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        for row in ET.fromstring(archive.read("xl/worksheets/sheet1.xml")).findall(".//m:row", ns):
            result = {}
            for cell in row:
                value = cell.findtext("m:v", "", ns)
                result[re.sub(r"\d", "", cell.attrib["r"])] = strings[int(value)] if cell.get("t") == "s" else value
            yield result


def prepare():
    """Add new images without changing the existing locked benchmark manifest."""
    import truststore
    truststore.inject_into_ssl()
    rows = []
    # ASA24 mass units are publisher portion labels, NOT inferred cup-to-gram weights.
    for row in xlsx_rows(DATA / "raw/asa24/images-asa24-2022.xlsx"):
        title = row.get("B", "").lower()
        match = re.fullmatch(r"(\d+(?:\.\d+)?) ounces?", row.get("E", ""))
        if not match:
            continue
        category = ("chicken" if title.startswith("chicken breast") else
                    "fish" if title.startswith("salmon") else
                    "steak" if "steak" in title and "chicken" not in title else None)
        if not category:
            continue
        name = row["A"]
        path = DATA / "raw/asa24/targeted" / name
        download(row["C"], path)
        with Image.open(path) as image:
            image.verify()
        rows.append({"sample_id": "ASA-" + path.stem, "image": str(path.relative_to(ROOT)),
                     "mass_g": float(match[1]) * 28.349523125, "category": category,
                     "group_id": "asa:" + title.rsplit(",", 1)[0],
                     "split": "external_locked_test", "source": "ASA24-2022",
                     "mass_basis": "publisher labelled avoirdupois ounces converted exactly to grams",
                     "image_sha256": digest(path), "source_title": row["B"]})
    write_jsonl(BASICS / "asa24-labels.jsonl", rows)
    # Primary basic-food test: >=90% mass of one named food group, preserving official split.
    folder = DATA / "raw/nutrition5k"
    available = {Path(obj["name"]).parent.name: obj for obj in json.loads((DATA / "provenance/nutrition5k-image-index.json").read_text())}
    train = set((folder / "dish_ids/splits/rgb_train_ids.txt").read_text().split())
    test = set((folder / "dish_ids/splits/rgb_test_ids.txt").read_text().split())
    found = []
    for metadata in sorted((folder / "metadata").glob("dish_metadata*.csv")):
        for row in csv.reader(metadata.open()):
            while row and row[-1] == "":
                row.pop()
            if not row or row[0] not in available:
                continue
            mass = float(row[2])
            ingredients = [(row[i+1], float(row[i+2])) for i in range(6, len(row), 7)]
            for category, names in GROUPS.items():
                target = sum(value for name, value in ingredients if name in names)
                if target < mass * .9 or target <= 0:
                    continue
                obj = available[row[0]]
                path = folder / "imagery" / row[0] / "rgb.png"
                download("https://storage.googleapis.com/nutrition5k_dataset/" + obj["name"], path)
                if base64.b64encode(bytes.fromhex(digest(path, "md5"))).decode() != obj["md5Hash"]:
                    raise ValueError("Publisher image hash mismatch")
                found.append({"sample_id": row[0], "image": str(path.relative_to(ROOT)),
                              "mass_g": target, "category": category, "group_id": row[0],
                              "split": "development" if row[0] in train else "locked_test" if row[0] in test else "excluded",
                              "source": "Nutrition5k", "mass_basis": "weighed ingredient grams",
                              "image_sha256": digest(path)})
    write_jsonl(BASICS / "nutrition5k-labels.jsonl", found)
    save_json(BASICS / "acquisition.json", {"asa24_images": len(rows), "nutrition5k_images": len(found),
                                            "terms": "ASA24 publisher freely available; Nutrition5k CC-BY-4.0",
                                            "existing_locked_manifest_unchanged": True})
    print(json.dumps({"asa": len(rows), "nutrition5k": len(found)}))


def run(args):
    rows = load_jsonl(BASICS / (args.source + "-labels.jsonl"))
    rows = [r for r in rows if r["split"] == args.split]
    if args.category != "all":
        rows = [r for r in rows if r["category"] == args.category]
    rng = random.Random(20261015)
    rng.shuffle(rows)
    rows = rows[:args.limit]
    references = []
    if args.references:
        training = sorted([r for r in load_jsonl(BASICS / "nutrition5k-side-labels.jsonl")
                           if r["split"] == "development"], key=lambda r: r["mass_g"])
        references = [training[int((len(training)-1)*q)] for q in (.15, .4, .65, .9)]
        reference_ids = {r["group_id"] for r in references}
        rows = [r for r in rows if r["group_id"] not in reference_ids]
    if not rows:
        raise ValueError("No eligible rows")
    if args.references and any(r["category"] != "chicken" for r in rows):
        raise ValueError("Chicken references may only be used for chicken cases")
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / "work"):
        raise ValueError("Benchmark output must stay within project work/")
    output.mkdir(parents=True, exist_ok=False)
    # Freeze image-only requests before opening labels in the scoring phase.
    prompts = [{"sample_id": r["sample_id"], "image": r["image"], "category": r["category"]} for r in rows]
    write_jsonl(output / "inputs.jsonl", prompts)
    os.environ["MFP_ESTIMATION_MODEL"] = args.model
    os.environ["MFP_PORTION_PROTOCOL"] = args.protocol
    # Read key once, rather than opening a decryption process for each image.
    os.environ["OPENAI_API_KEY"] = estimation.api_key()
    if references:
        import httpx
        original_post = httpx.post
        reference_content = []
        for i, reference in enumerate(references):
            reference_content.extend([
                {"type": "input_text", "text": f"TRAINING REFERENCE {i+1}: weighed chicken {reference['mass_g']} grams. Different portion; never sum it with the query."},
                {"type": "input_image", "image_url": estimation.attachment_data_url((ROOT/reference["image"]).read_bytes()), "detail": "high"},
            ])
        def with_references(url, **kwargs):
            payload = kwargs["json"]
            text, *query = payload["input"][0]["content"]
            payload["input"][0]["content"] = [
                {"type": "input_text", "text": "Learn visual chicken portion cues from the following measured examples. They are separate training portions, not extra views of the query. Physical scale may differ; do not assume identical plate diameters."},
                *reference_content,
                {"type": "input_text", "text": "QUERY TO ESTIMATE (only this final image): " + text["text"]},
                *query,
            ]
            return original_post(url, **kwargs)
        estimation.httpx.post = with_references
        save_json(output/"training-references.json", [{k:r[k] for k in ["sample_id","group_id","mass_g","image_sha256"]} for r in references])
    def infer(row):
        raw = (ROOT / row["image"]).read_bytes()
        context = "Estimate only the " + row["category"] + "; exclude other foods. No known scale reference."
        result = estimation.estimate_food(estimation.attachment_data_url(raw), context,
                                         food_focus=row["category"] if args.protocol == "basic-v2" else "")
        return {"sample_id": row["sample_id"], **result}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(infer, prompts):
            with (output / "predictions.jsonl").open("a") as handle:
                handle.write(json.dumps(result) + "\n")
            print("Completed", result["sample_id"], flush=True)
    sha = hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
    save_json(output / "prediction-commit.json", {"sha256": sha, "model": args.model,
                                                "requests": len(prompts), "labels_in_requests": False})
    predictions = load_jsonl(output / "predictions.jsonl")
    answers = {r["sample_id"]: r for r in rows}
    scored = []
    for p in predictions:
        if "estimate" not in p:
            continue
        target = answers[p["sample_id"]]
        predicted = p["estimate"]["mass_g"]
        scored.append({"sample_id": p["sample_id"], "category": target["category"],
                       "actual_g": target["mass_g"], "predicted_g": predicted,
                       "ape": abs(predicted-target["mass_g"])/target["mass_g"]*100})
    report = {"model": args.model, "protocol": args.protocol, "reference_examples": len(references), "source": args.source, "split": args.split,
              "expected": len(rows), "scored": len(scored), "records": scored,
              "limitations": "Public data; fixed capture setups and few independent food groups; not a guarantee on phone photos."}
    for category in GROUPS:
        values = [r["ape"] for r in scored if r["category"] == category]
        if values:
            report[category] = {"n": len(values), "median_ape": statistics.median(values),
                                "mean_ape": statistics.mean(values), "within20_fraction": sum(v<=20 for v in values)/len(values),
                                "max_ape": max(values)}
    save_json(output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--source", default="nutrition5k", choices=["nutrition5k", "nutrition5k-side", "asa24"])
    parser.add_argument("--protocol", default="basic-v2", choices=["legacy", "basic-v2"])
    parser.add_argument("--category", default="all", choices=["all", *GROUPS])
    parser.add_argument("--references", action="store_true")
    parser.add_argument("--split", default="development")
    parser.add_argument("--model", default="gpt-4.1-mini-2025-04-14")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--output", default="work/food-estimation/basics-run")
    args = parser.parse_args()
    prepare() if args.action == "prepare" else run(args)
