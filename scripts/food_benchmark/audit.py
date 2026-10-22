"""Audit normalization, duplicates and evaluation-only SNAPMe records."""

import base64
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from scripts.food_benchmark.acquire import DATA, ROOT, digest, save_json
from scripts.food_benchmark.prepare import write_jsonl


def dhash(path):
    with Image.open(path) as original:
        original.draft("L", (512, 512))
        image = original.convert("L")
        w, h = image.size
        image = image.crop((w // 10, h // 10, w * 9 // 10, h * 9 // 10)).resize((9, 8))
        pixels = list(image.get_flattened_data())
        return sum(
            (pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
            for y in range(8)
            for x in range(8)
        )


def audit_snapme():
    folder = DATA / "raw" / "snapme" / "snapme_db_09Dec2022"
    records = list(
        csv.DictReader(
            (folder / "snapme_cs_db" / "master_SNAPME_linkfile.csv").open(
                encoding="utf-8-sig", errors="replace"
            )
        )
    )
    images = {
        p.name: p
        for p in (folder / "snapme_nut_db").rglob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    }
    by_image = defaultdict(list)
    for row in records:
        by_image[row["filename"]].append(row)
    rows, missing, rejected = [], [], []
    for name, path in images.items():
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as error:
            rejected.append({"file_name": name, "reason": type(error).__name__})
            continue
        linked = by_image.get(name, [])
        references = []
        for entry in linked:
            nutrients = {}
            for key, source in (
                ("kcal", "KCAL"),
                ("protein_g", "PROT"),
                ("carbohydrate_g", "CARB"),
                ("fat_g", "TFAT"),
            ):
                try:
                    value = float(entry[source])
                    if math.isfinite(value) and value >= 0:
                        nutrients[key] = value
                except (ValueError, TypeError):
                    pass
            references.append(
                {
                    "food_description": entry["Food_Description"],
                    "food_code": entry["FoodCode"],
                    "reported_food_amount": entry.get("FoodAmt"),
                    "amount_unit": "not independently confirmed",
                    "reported_consumed_nutrients": nutrients,
                }
            )
        participant = path.parent.parent.name
        rows.append(
            {
                "dataset": "snapme",
                "image": str(path.relative_to(ROOT)),
                "image_sha256": digest(path),
                "group_id": "snapme:"
                + hashlib.sha256(participant.encode()).hexdigest()[:12],
                "split": "external_evaluation_only",
                "license": "CC-BY-SA-4.0",
                "photo_type": next(
                    (
                        kind
                        for kind in ("before", "after", "front", "ingredients")
                        if kind in name
                    ),
                    "unknown",
                ),
                "reference_records": references,
                "ground_truth_class": "reported dietary recall, not scale-measured food mass",
                "weight_scoring_eligible": False,
                "warning": "Consumed-food recall is not automatically the mass or nutrition visible before/after eating. Paired-image review is required.",
            }
        )
        if not linked:
            missing.append(name)
    write_jsonl(DATA / "labels" / "snapme-evaluation-references.jsonl", rows)
    save_json(
        DATA / "audit" / "snapme.json",
        {
            "physical_unique_photo_filenames": len(images),
            "verified_readable_photos": len(rows),
            "rejected_photos": rejected,
            "master_link_rows": len(records),
            "linked_photo_filenames": len(by_image),
            "photos_with_direct_master_link": len(rows) - len(missing),
            "photos_without_direct_master_link": len(missing),
            "photo_types": dict(Counter(r["photo_type"] for r in rows)),
            "policy": "Evaluation only, never training or calibration. Excluded from measured-weight scoring.",
            "omitted_shortcuts": json.loads(
                (folder.parent / "extraction-audit.json").read_text()
            ),
        },
    )


def main():
    rows = [
        json.loads(line)
        for line in (DATA / "labels" / "all-ground-truth.jsonl")
        .read_text()
        .splitlines()
    ]
    for row in rows:
        if not all(
            math.isfinite(row[k]) and row[k] >= 0
            for k in ("mass_g", "kcal", "protein_g", "carbohydrate_g", "fat_g")
        ):
            raise ValueError("Invalid normalized nutrient value")
        if row["mass_g"] <= 0:
            raise ValueError("Invalid normalized mass")
    index = json.loads(
        (DATA / "provenance" / "nutrition5k-image-index.json").read_text()
    )
    publisher_md5 = {
        Path(obj["name"]).parent.name: base64.b64decode(obj["md5Hash"]).hex()
        for obj in index
        if obj.get("md5Hash")
    }
    for row in rows:
        if row["dataset"] == "nutrition5k":
            if digest(ROOT / row["image"], "md5") != publisher_md5[row["dish_id"]]:
                raise ValueError("Nutrition5k publisher image checksum mismatch")
    hashes = [(r, dhash(ROOT / r["image"])) for r in rows]
    development = [(r, h) for r, h in hashes if r["split"] == "development"]
    candidates = []
    for row, h in hashes:
        if row["split"] == "development":
            continue
        matches = [
            (other["dataset"], other["dish_id"], (h ^ other_h).bit_count())
            for other, other_h in development
            if (h ^ other_h).bit_count() <= 1
        ]
        if matches:
            candidates.append(
                {
                    "dataset": row["dataset"],
                    "dish_id": row["dish_id"],
                    "image": row["image"],
                    "original_split": row["split"],
                    "matches": matches,
                }
            )
    flagged_groups = {(r["dataset"], r["dish_id"]) for r in candidates}
    # Conservative quarantine is by complete dish group, including all its views.
    manifest = []
    for row in rows:
        record = {
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
        if (row["dataset"], row["dish_id"]) in flagged_groups:
            record["original_split"] = record["split"]
            record["split"] = "quarantined_similarity"
        manifest.append(record)
    write_jsonl(DATA / "manifest.jsonl", manifest)
    save_json(
        DATA / "audit" / "near-duplicates.json",
        {
            "method": "64-bit center-crop dHash, Hamming distance <= 1 against development",
            "limitations": "Heuristic candidates may be different foods or portions; conservative quarantine is not a claim of identity.",
            "candidate_images": candidates,
            "quarantined_dish_groups": len(flagged_groups),
            "effective_splits": dict(Counter(r["split"] for r in manifest)),
        },
    )
    audit_snapme()
    # Recover complete acquisition receipts even after individual dataset reruns.
    sources = {}
    for dataset in ("nutritionverse-real", "snapme", "simplefood45"):
        if not (DATA / "provenance" / (dataset + ".json")).exists():
            continue
        sources[dataset] = json.loads(
            (DATA / "provenance" / (dataset + ".json")).read_text()
        )
    sources["nutrition5k"] = {
        "status": "acquired",
        "count": sum(r["dataset"] == "nutrition5k" for r in rows),
    }
    save_json(DATA / "acquisition-status.json", sources)
    print(
        json.dumps(
            {
                "effective_splits": dict(Counter(r["split"] for r in manifest)),
                "quarantined_groups": len(flagged_groups),
                "snapme": json.loads((DATA / "audit" / "snapme.json").read_text()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
