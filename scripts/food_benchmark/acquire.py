"""Acquire food-estimation benchmark data. Never reads account credentials or calls MFP."""

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import random
import tarfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import requests
import truststore
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "food-estimation"
GCS = "https://storage.googleapis.com/nutrition5k_dataset/"
SEED = 20261015


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def download(url, path, expected_md5=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (not expected_md5 or digest(path, "md5") == expected_md5):
        return
    temporary = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            with requests.get(url, stream=True, timeout=(15, 90)) as response:
                response.raise_for_status()
                with temporary.open("wb") as stream:
                    for block in response.iter_content(2**20):
                        stream.write(block)
            if expected_md5 and digest(temporary, "md5") != expected_md5:
                raise ValueError("Publisher checksum mismatch")
            temporary.replace(path)
            return
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def list_gcs(prefix):
    values, token = [], None
    while True:
        response = requests.get(
            "https://storage.googleapis.com/storage/v1/b/nutrition5k_dataset/o",
            params={
                "prefix": "nutrition5k_dataset/" + prefix,
                "maxResults": 1000,
                **({"pageToken": token} if token else {}),
            },
            timeout=45,
        )
        response.raise_for_status()
        page = response.json()
        values.extend(page.get("items", []))
        token = page.get("nextPageToken")
        if not token:
            return values


def stratified(rows, count):
    bins = defaultdict(list)
    for row in rows:
        mass_bin = sum(row["mass_g"] > edge for edge in (100, 250, 500))
        count_bin = min(len(row["ingredients"]), 4)
        bins[(mass_bin, count_bin, row["cafe"])].append(row)
    rng = random.Random(SEED)
    for bucket in bins.values():
        rng.shuffle(bucket)
    chosen = []
    while len(chosen) < count and any(bins.values()):
        for key in sorted(bins):
            if bins[key] and len(chosen) < count:
                chosen.append(bins[key].pop())
    rng.shuffle(chosen)
    return chosen


def nutrition5k():
    folder = DATA / "raw" / "nutrition5k"
    for obj in list_gcs("metadata/") + list_gcs("dish_ids/splits/"):
        relative = obj["name"].removeprefix("nutrition5k_dataset/")
        download(GCS + obj["name"], folder / relative)
    imagery = [
        obj
        for obj in list_gcs("imagery/realsense_overhead/")
        if obj["name"].endswith("/rgb.png")
    ]
    save_json(DATA / "provenance" / "nutrition5k-image-index.json", imagery)
    available = {Path(obj["name"]).parent.name: obj["name"] for obj in imagery}
    official = {}
    for split in ("train", "test"):
        ids = (
            (folder / "dish_ids" / "splits" / f"rgb_{split}_ids.txt")
            .read_text()
            .split()
        )
        for dish_id in ids:
            if dish_id in official and official[dish_id] != split:
                raise ValueError("Official split overlap")
            official[dish_id] = split
    rows, rejected = [], []
    for path in sorted((folder / "metadata").glob("dish_metadata*.csv")):
        for raw in csv.reader(path.open(encoding="utf-8", newline="")):
            while raw and raw[-1] == "":
                raw.pop()
            try:
                # Actual release is six dish fields + seven fields/ingredient.
                if (len(raw) - 6) % 7:
                    raise ValueError("Unexpected metadata schema")
                row = dict(
                    zip(
                        (
                            "dish_id",
                            "kcal",
                            "mass_g",
                            "fat_g",
                            "carbohydrate_g",
                            "protein_g",
                        ),
                        raw[:6],
                    )
                )
                for key in ("kcal", "mass_g", "fat_g", "carbohydrate_g", "protein_g"):
                    row[key] = float(row[key])
                if (
                    not all(
                        math.isfinite(row[k])
                        for k in (
                            "mass_g",
                            "kcal",
                            "fat_g",
                            "carbohydrate_g",
                            "protein_g",
                        )
                    )
                    or row["mass_g"] <= 0
                    or any(
                        row[k] < 0
                        for k in ("kcal", "fat_g", "carbohydrate_g", "protein_g")
                    )
                ):
                    raise ValueError("Nonpositive mass or negative nutrient")
                row["ingredients"] = [
                    {
                        "id": raw[i],
                        "name": raw[i + 1],
                        "mass_g": float(raw[i + 2]),
                        "kcal": float(raw[i + 3]),
                        "fat_g": float(raw[i + 4]),
                        "carbohydrate_g": float(raw[i + 5]),
                        "protein_g": float(raw[i + 6]),
                    }
                    for i in range(6, len(raw), 7)
                ]
                if any(ing["mass_g"] < 0 for ing in row["ingredients"]):
                    raise ValueError("Negative ingredient mass")
                row["cafe"] = path.stem
                row["official_split"] = official.get(row["dish_id"])
                if row["dish_id"] not in available or not row["official_split"]:
                    continue
                row["ingredient_mass_residual_g"] = round(
                    row["mass_g"] - sum(i["mass_g"] for i in row["ingredients"]), 3
                )
                rows.append(row)
            except (ValueError, IndexError) as error:
                rejected.append(
                    {"dish_id": raw[0] if raw else None, "reason": str(error)}
                )
    if len({r["dish_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate dish metadata IDs")
    selected = stratified(
        [r for r in rows if r["official_split"] == "train"], 700
    ) + stratified([r for r in rows if r["official_split"] == "test"], 300)
    print(f"nutrition5k: selected {len(selected)} distinct dish records", flush=True)

    def get_image(row):
        relative = Path("imagery") / row["dish_id"] / "rgb.png"
        path = folder / relative
        download(GCS + available[row["dish_id"]], path)
        with Image.open(path) as image:
            image.verify()
        row.update(
            dataset="nutrition5k",
            image=str(path.relative_to(ROOT)),
            group_id=row["dish_id"],
            split="development" if row["official_split"] == "train" else "locked_test",
            image_sha256=digest(path),
            mass_basis="measured ingredient/dish mass",
            nutrition_basis="USDA ingredient composition calculation",
            license="CC-BY-4.0",
        )
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for index, row in enumerate(pool.map(get_image, selected), 1):
            if index % 100 == 0:
                print(
                    f"nutrition5k: {index}/{len(selected)} verified images", flush=True
                )
    labels = DATA / "labels" / "nutrition5k.jsonl"
    labels.parent.mkdir(parents=True, exist_ok=True)
    labels.write_text(
        "".join(json.dumps(row) + "\n" for row in selected), encoding="utf-8"
    )
    save_json(
        DATA / "audit" / "nutrition5k.json",
        {
            "metadata_eligible_with_rgb": len(rows),
            "selected": len(selected),
            "rejected": rejected,
            "development": sum(r["split"] == "development" for r in selected),
            "locked_test": sum(r["split"] == "locked_test" for r in selected),
            "nonzero_ingredient_mass_residuals": sum(
                abs(r["ingredient_mass_residual_g"]) > 1 for r in selected
            ),
            "split_policy": "Official RGB train/test membership preserved; all views/increments follow publisher split. No new image-level split.",
        },
    )
    return {"status": "acquired", "count": len(selected)}


def extract_archive(path, destination):
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if not (root / member.filename).resolve().is_relative_to(root):
                    raise ValueError("Unsafe archive path")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive symlink rejected")
            if sum(m.file_size for m in archive.infolist()) > 20 * 2**30:
                raise ValueError("Archive extraction exceeds 20 GiB")
            archive.extractall(root)
    else:
        with tarfile.open(path) as archive:
            members = archive.getmembers()
            for member in members:
                if not (root / member.name).resolve().is_relative_to(root):
                    raise ValueError("Unsafe archive member")
            if sum(m.size for m in members) > 20 * 2**30:
                raise ValueError("Archive extraction exceeds 20 GiB")
            regular = [m for m in members if m.isfile() or m.isdir()]
            # SNAPMe includes thousands of redundant organizational symlinks.
            # Extract physical files only; never create archive-controlled links.
            archive.extractall(root, members=regular, filter="data")
            save_json(
                destination / "extraction-audit.json",
                {
                    "regular_files": sum(m.isfile() for m in regular),
                    "omitted_link_shortcuts": sum(
                        m.issym() or m.islnk() for m in members
                    ),
                },
            )


def large_dataset(name):
    archives = DATA / "archives"
    if name == "simplefood45":
        url = "https://lorenz.ecn.purdue.edu/~gvinod/simplefood45/simple_food_45.zip"
        path = archives / "simple_food_45.zip"
        expected = None
        license = "No explicit license found; local research inspection only; excluded from training/distribution pending clarification"
    elif name == "nutritionverse-real":
        url = "https://www.kaggle.com/api/v1/datasets/download/nutritionverse/nutritionverse-real"
        path = archives / "nutritionverse-real.zip"
        expected = None
        license = "CC-BY-NC-SA-4.0"
    else:
        source = requests.get(
            "https://api.figshare.com/v2/articles/24856449", timeout=45
        ).json()
        save_json(DATA / "provenance" / "snapme-source.json", source)
        file = source["files"][0]
        url, expected = file["download_url"], file["computed_md5"]
        path = archives / file["name"]
        license = "CC-BY-SA-4.0; publisher evaluation-only guidance"
    print(name + ": downloading archive", flush=True)
    download(url, path, expected)
    extract_archive(path, DATA / "raw" / name)
    result = {
        "status": "acquired",
        "archive_bytes": path.stat().st_size,
        "archive_sha256": digest(path),
        "license": license,
        "source": url,
    }
    save_json(DATA / "provenance" / (name + ".json"), result)
    print(name + ": extracted and checksummed", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "dataset",
        choices=["all", "nutrition5k", "nutritionverse-real", "snapme", "simplefood45"],
        default="all",
        nargs="?",
    )
    args = parser.parse_args()
    truststore.inject_into_ssl()
    targets = (
        ["nutrition5k", "nutritionverse-real", "snapme", "simplefood45"]
        if args.dataset == "all"
        else [args.dataset]
    )
    status_path = DATA / "acquisition-status.json"
    results = json.loads(status_path.read_text()) if status_path.exists() else {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        pending = {
            pool.submit(
                nutrition5k if name == "nutrition5k" else large_dataset,
                *([] if name == "nutrition5k" else [name]),
            ): name
            for name in targets
        }
        for future in concurrent.futures.as_completed(pending):
            name = pending[future]
            try:
                results[name] = future.result()
            except Exception as error:
                results[name] = {
                    "status": "blocked",
                    "error": type(error).__name__,
                    "detail": str(error)[:500],
                }
                print(name + ": " + str(results[name]), flush=True)
            save_json(DATA / "acquisition-status.json", results)
    print("Acquisition finished", flush=True)


if __name__ == "__main__":
    main()
