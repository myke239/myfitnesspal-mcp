"""Audit sources, normalize labels and produce a blinded DEVELOPMENT-only pilot."""

import csv
import json
import random
import re
from collections import Counter, defaultdict

from PIL import Image, ImageDraw, ImageOps

from scripts.food_benchmark.acquire import DATA, ROOT, SEED, digest, save_json


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def normalize_nutritionverse():
    folder = DATA / "raw" / "nutritionverse-real"
    metadata = {
        r["dish_id"]: r
        for r in csv.DictReader(
            (folder / "nutritionverse_dish_metadata3.csv").open(encoding="utf-8-sig")
        )
    }
    split_file = next(folder.rglob("updated-manual-dataset-splits.csv"))
    source_splits = list(csv.DictReader(split_file.open(encoding="utf-8-sig")))
    by_name = {p.name: p for p in folder.rglob("*.jpg")}
    rows, rejected = [], []
    split_groups = defaultdict(set)
    for record in source_splits:
        name = record["file_name"]
        match = re.search(r"dish_(\d+)_", name)
        if not match or match[1] not in metadata or name not in by_name:
            rejected.append(
                {
                    "file_name": name,
                    "reason": "Missing image/metadata/parseable dish ID",
                }
            )
            continue
        dish = metadata[match[1]]
        values = {
            k: float(dish[v])
            for k, v in {
                "mass_g": "total_food_weight",
                "kcal": "total_calories",
                "fat_g": "total_fats",
                "carbohydrate_g": "total_carbohydrates",
                "protein_g": "total_protein",
            }.items()
        }
        if values["mass_g"] <= 0 or any(v < 0 for v in values.values()):
            rejected.append({"file_name": name, "reason": "Invalid mass/nutrients"})
            continue
        path = by_name[name]
        with Image.open(path) as image:
            image.verify()
        ingredients = [
            {
                "name": dish[f"food_item_type_{i}"],
                "mass_g": float(dish[f"food_weight_g_{i}"]),
            }
            for i in range(1, 8)
            if (dish.get(f"food_item_type_{i}") or "").strip()
            and (dish.get(f"food_weight_g_{i}") or "").strip()
        ]
        rows.append(
            {
                "dataset": "nutritionverse-real",
                "dish_id": match[1],
                "group_id": "nutritionverse-real:" + match[1],
                "image": str(path.relative_to(ROOT)),
                "image_sha256": digest(path),
                "split": "external_locked_test",
                "publisher_split": record["category"],
                **values,
                "ingredients": ingredients,
                "license": "CC-BY-NC-SA-4.0",
                "mass_basis": "weighed ingredients",
                "nutrition_basis": "food packaging/Canadian Nutrient File",
            }
        )
        split_groups[match[1]].add(record["category"])
    write_jsonl(DATA / "labels" / "nutritionverse-real.jsonl", rows)
    annotation = json.loads(next(folder.rglob("_annotations.coco.json")).read_text())
    save_json(
        DATA / "audit" / "nutritionverse-real.json",
        {
            "publisher_split_rows": len(source_splits),
            "disk_images": len(by_name),
            "annotation_image_records": len(annotation["images"]),
            "usable_images": len(rows),
            "distinct_dishes": len({r["group_id"] for r in rows}),
            "source_split_dishes_in_multiple_categories": sum(
                len(v) > 1 for v in split_groups.values()
            ),
            "excluded_annotation_only_images": sorted(
                {r["file_name"] for r in annotation["images"]}
                - {r["file_name"] for r in source_splits}
            ),
            "rejected": rejected,
            "policy": "Entire real dataset is external evaluation only. Publisher Train/Val labels do not grant development access.",
        },
    )
    return rows


def make_pilot(rows):
    development = [
        r for r in rows if r["dataset"] == "nutrition5k" and r["split"] == "development"
    ]
    rng = random.Random(SEED + 1)
    chosen = rng.sample(development, min(30, len(development)))
    folder = DATA / "pilot"
    folder.mkdir(parents=True, exist_ok=True)
    prompts, keys = [], []
    for index, row in enumerate(chosen, 1):
        sample_id = f"P{index:02d}"
        target = folder / "images" / (sample_id + ".jpg")
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(ROOT / row["image"]) as original:
            image = original.convert("RGB")
            image.thumbnail((1024, 1024))
            image.save(target, quality=95)  # Strip source filenames and image metadata.
        prompts.append(
            {
                "sample_id": sample_id,
                "image": str(target.relative_to(ROOT)),
                "condition": "photo_only",
                "split": "development_pilot",
                "prompt": "Identify visible food and estimate TOTAL edible food mass in grams. No plate dimensions or scale reference are known. Return mass_g, lower_g, upper_g and food_description. Do not infer a standard plate diameter. The interval is subjective, not calibrated.",
            }
        )
        keys.append(
            {
                "sample_id": sample_id,
                "dataset": row["dataset"],
                "dish_id": row["dish_id"],
                "mass_g": row["mass_g"],
                "kcal": row["kcal"],
                "protein_g": row["protein_g"],
                "fat_g": row["fat_g"],
                "carbohydrate_g": row["carbohydrate_g"],
                "image_sha256": row["image_sha256"],
            }
        )
    write_jsonl(folder / "prompts.jsonl", prompts)
    write_jsonl(DATA / "labels" / "pilot-answer-key.jsonl", keys)
    for start in range(0, len(prompts), 6):
        sheet = Image.new("RGB", (1050, 740), "white")
        draw = ImageDraw.Draw(sheet)
        for j, row in enumerate(prompts[start : start + 6]):
            with Image.open(ROOT / row["image"]) as image:
                tile = ImageOps.contain(image.convert("RGB"), (340, 330))
            x, y = (j % 3) * 350, (j // 3) * 370
            sheet.paste(tile, (x + (340 - tile.width) // 2, y + 30))
            draw.text((x + 10, y + 8), row["sample_id"] + " | photo only", fill="black")
        sheet.save(folder / f"sheet-{start // 6 + 1}.jpg", quality=95)
    save_json(
        folder / "protocol.json",
        {
            "seed": SEED + 1,
            "sample_count": len(prompts),
            "role": "development pilot only, never a held-out performance claim",
            "blindness": "Do not view labels/pilot-answer-key.jsonl until predictions.jsonl is saved.",
            "label_visibility": "No ground-truth labels or source IDs in model input.",
            "model": "Current assistant in this conversation; exact backend model ID not available",
            "automated_model_api": "not configured; no OPENAI_API_KEY present; no API purchase attempted",
        },
    )


def main():
    rows = [
        json.loads(line)
        for line in (DATA / "labels" / "nutrition5k.jsonl").read_text().splitlines()
    ]
    rows += normalize_nutritionverse()
    groups, hashes = defaultdict(set), defaultdict(set)
    for row in rows:
        group = row["dataset"] + ":" + row["dish_id"]
        groups[group].add(row["split"])
        hashes[row["image_sha256"]].add(row["split"])
    cross_groups = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    cross_hashes = {k: sorted(v) for k, v in hashes.items() if len(v) > 1}
    if cross_groups or cross_hashes:
        raise ValueError(
            "Split leakage detected: group or exact image crosses partitions"
        )
    write_jsonl(DATA / "labels" / "all-ground-truth.jsonl", rows)
    manifest = [
        {
            k: row[k]
            for k in (
                "dataset",
                "dish_id",
                "group_id",
                "image",
                "image_sha256",
                "split",
                "license",
            )
        }
        for row in rows
    ]
    write_jsonl(DATA / "manifest.jsonl", manifest)
    save_json(
        DATA / "audit" / "split-integrity.json",
        {
            "image_count": len(rows),
            "unique_dish_records": len(groups),
            "splits": dict(Counter(r["split"] for r in rows)),
            "cross_split_groups": cross_groups,
            "cross_split_exact_hashes": cross_hashes,
            "limitations": [
                "Publisher official Nutrition5k groups are trusted; no new image-level split was created.",
                "No claim that public benchmark images were absent from foundation-model pretraining.",
                "Near-duplicate image audit is separate from exact hash checks.",
            ],
        },
    )
    make_pilot(rows)
    print("Prepared labels, split audit and blinded development pilot", flush=True)


if __name__ == "__main__":
    main()
