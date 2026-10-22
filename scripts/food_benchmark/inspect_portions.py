"""Normalize SimpleFood45's published labels for local inspection, not training."""

import csv
import hashlib
import json
import math
from pathlib import Path

from PIL import Image

from scripts.food_benchmark.acquire import DATA, ROOT, digest, save_json
from scripts.food_benchmark.prepare import write_jsonl


def main():
    folder = DATA / "raw" / "simplefood45" / "ordered_dataset"
    images = {
        p.name: p
        for p in folder.iterdir()
        if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    }
    source = list(csv.DictReader((folder / "labels.csv").open(encoding="utf-8-sig")))
    rows, rejected = [], []
    for row in source:
        try:
            name = Path(row["image"]).name
            path = images[name]
            weight, volume, energy = (
                float(row[k]) for k in ("weight", "volume", "energy")
            )
            if (
                not all(math.isfinite(v) and v >= 0 for v in (weight, volume, energy))
                or weight == 0
                or volume == 0
            ):
                raise ValueError("Invalid quantity")
            with Image.open(path) as image:
                image.verify()
            group = hashlib.sha256(
                json.dumps([row["label"], weight, volume, energy]).encode()
            ).hexdigest()[:16]
            rows.append(
                {
                    "dataset": "simplefood45",
                    "image": str(path.relative_to(ROOT)),
                    "image_sha256": digest(path),
                    "group_id": "simplefood45:" + group,
                    "food_label": row["label"],
                    "mass_g": weight,
                    "volume_ml": volume,
                    "kcal": energy,
                    "split": "local_inspection_only_pending_license",
                    "license": "No explicit dataset license located",
                    "unit_provenance": "Author paper describes weight g, volume mL, energy kcal",
                    "grouping_note": "Conservative grouping by identical food label/measurements; no source object ID available",
                }
            )
        except (ValueError, KeyError, OSError) as error:
            rejected.append({"image": row.get("image"), "reason": type(error).__name__})
    write_jsonl(DATA / "labels" / "simplefood45-provisional.jsonl", rows)
    save_json(
        DATA / "audit" / "simplefood45.json",
        {
            "archive_images": len(images),
            "published_label_rows": len(source),
            "verified_labeled_images": len(rows),
            "conservative_groups": len({r["group_id"] for r in rows}),
            "images_without_label_row": len(
                set(images) - {Path(r["image"]).name for r in source}
            ),
            "rejected": rejected,
            "policy": "Local inspection only; excluded from model training, reference retrieval, distribution and scored benchmark pending license clarification.",
        },
    )
    print(
        json.dumps(
            json.loads((DATA / "audit" / "simplefood45.json").read_text()), indent=2
        )
    )


if __name__ == "__main__":
    main()
