> Historical dataset-preparation report. See the [current accuracy investigation](food-estimation-accuracy.md) for later API experiments, additional datasets and the unmet 20% chicken target.

# Food estimation: dataset preparation and baseline report



Status: acquisition, audit, split preparation, and a blinded development pilot completed on October 15, 2026. Validation: 75 tests passed, lint passed, and wheel/source builds passed. Both distributions were inspected and contain no dataset images, archives or answer keys. `data/food-estimation/benchmark-lock.json` pins the effective manifests and pilot files by SHA-256. No estimation skill, correction model, or production plugin tool was implemented. Existing MyFitnessPal and Garmin services were not restarted or changed.



## Acquired and audited



| Source | Local result | Role and restrictions |

| --- | --- | --- |

| [Nutrition5k](https://github.com/google-research-datasets/Nutrition5k) | 1,000 RGB images with ingredient/dish mass, kcal, protein, carbohydrate and fat | CC BY 4.0. 700 development; 299 held-out; one similarity quarantine. Official train/test membership preserved. All 1,000 source image MD5s checked against publisher metadata. |

| [NutritionVerse-Real](https://www.kaggle.com/datasets/nutritionverse/nutritionverse-real) | 889 verified images matching nutrition/mass metadata; 225 photographed dish IDs | CC BY-NC-SA 4.0, confirmed through Kaggle metadata. Entire set external evaluation only; excluded from distributable assets and commercial use. |

| [SNAPMe](https://agdatacommons.nal.usda.gov/articles/dataset/SNAPMe_A_Benchmark_Dataset_of_Food_Photos_with_Food_Records_for_Evaluation_of_Computer_Vision_Algorithms_in_the_Context_of_Dietary_Assessment/24856449) | Archive verified against publisher MD5; 3,366 readable unique photo filenames; 1,658 readable photos directly linked to the master food-record table | CC BY-SA 4.0 and publisher evaluation-only guidance. Never training/calibration. Dietary recall is not measured plate mass; excluded from mass-scoring benchmark. |

| [SimpleFood45](https://lorenz.ecn.purdue.edu/~gvinod/simplefood45/) | 513 images; 420 supplied and matched weight/volume/energy labels, grouped conservatively into 38 measurement groups | Downloaded from the author's direct public download for local inspection. No explicit dataset license located. Excluded from training, retrieval, scored benchmark, publication and package distribution pending clarification. |



The mass/nutrition benchmark has 1,889 image-label records across 1,225 dish IDs before quarantine; 1,888 usable records remain after the one-image quarantine. Multiple viewpoints are not counted as independent dishes.



Raw archives, photos, label keys and dataset receipts live under `data/food-estimation` in this project. They are ignored by Git and explicitly excluded from distribution builds. No assets or labeled examples were uploaded to a model API. The current assistant viewed only the development pilot's blinded contact sheets.



## Quality findings



- **Nutrition5k:** the actual CSV release contains six dish fields followed by seven fields per ingredient. Its README describes a different layout. The importer parses the released schema and audits malformed/negative records. The official split is used instead of creating a split across camera views. Image hashes found no exact cross-partition duplicate; a center-crop perceptual-hash audit identified one potential near-duplicate and quarantined the complete affected test group. This heuristic can flag similar but distinct foods, so it is conservative, not proof of identical images.

- **NutritionVerse:** the metadata contains 251 dishes, but the 889 downloaded photographs cover 225 dish IDs. COCO lists 905 image records, 16 more than are present in the supplied split/image set. Missing annotation-only images are recorded, not fabricated. No dish crosses the supplied Train/Val categories, but we reserve both categories entirely for external evaluation.

- **SNAPMe:** the archive includes 3,312 organizational symlinks. Only physical files/directories were extracted; no archive links were created. Of 3,408 unique candidate photo filenames, 42 were unreadable or non-image artifacts and were excluded. The remaining 3,366 include 1,708 images without a direct master-table link (including after/label photos). Reported consumed nutrient references are preserved separately and are not assigned as the visible nutrition or mass of a before/after photograph. The archive counts differ from the publication's 3,311-photo summary; the local audit records actual files.

- **SimpleFood45:** 93 archive images have no row in labels.csv. The 420 available rows have usable image, food label, weight, volume and energy values. Food/object group IDs were not supplied, so identical label/measurement tuples are conservatively grouped. Published units are grams, milliliters and kcal; these are dataset annotations, not independently remeasured values.

- **Optional sources:** [MetaFood3D](https://lorenz.ecn.purdue.edu/~food3d/) is CC BY-NC 4.0 and requires an access request/password; no request was submitted. [ECUSTFD](https://github.com/Liang-yc/ECUSTFD-resized-) has no license returned by GitHub's license endpoint; no ECUST image collection was acquired. Neither is needed for the initial benchmark.



## Blinded baseline pilot



Thirty Nutrition5k development images were selected deterministically. New image files and contact sheets use P01–P30 and strip source metadata. The current assistant produced visual food descriptions, mass point estimates and subjective ranges. Predictions were saved and SHA-256 committed before the answer key was read. The commit still matches the evaluated prediction file.



| Weight-only pilot metric | Result |

| --- | ---: |

| Predictions / expected | 30 / 30 |

| Mean absolute weight error | 59.17 g |

| Median absolute percentage error | 21.66% |

| Mean absolute percentage error | 22.86% |

| Weighted absolute percentage error | 25.54% |

| Mean signed error | -45.70 g (underestimation) |

| Predictions above actual mass | 20.00% |

| Actual mass inside subjective interval | 86.67% |

| Mean interval width | 196.17 g |

| Errors above 50% | 3 / 30 |



These are exploratory development results, not held-out or production accuracy. Intervals are subjective, wide and uncalibrated. There were no scale references or known plate dimensions. Food-identification accuracy was not independently graded. No calorie/macro predictions were made, so those scores are explicitly absent rather than inferred from weight error. The exact backend model ID is unavailable; provenance identifies the current conversation assistant. Public dataset pretraining contamination cannot be ruled out.



The signed error is the opposite direction to the user's earlier chicken example. This is additional evidence against applying a universal correction factor from one or a few meals. No correction factors were fitted.



## Reproduce



From `D:\developer\myfitnesspal-mcp`:



```powershell

.\.venv\Scripts\python.exe -m pip install -e '.[benchmark,dev]'

.\.venv\Scripts\python.exe -m scripts.food_benchmark.acquire all

.\.venv\Scripts\python.exe -m scripts.food_benchmark.prepare

.\.venv\Scripts\python.exe -m scripts.food_benchmark.audit

.\.venv\Scripts\python.exe -m scripts.food_benchmark.inspect_portions

.\.venv\Scripts\python.exe -m scripts.food_benchmark.evaluate --predictions data/food-estimation/pilot/predictions.jsonl --truth data/food-estimation/labels/pilot-answer-key.jsonl --output data/food-estimation/reports/photo-only-pilot.json

.\.venv\Scripts\python.exe -m pytest

```



Acquisition can also take one dataset name. It downloads only a stratified RGB subset for Nutrition5k, not the 181 GB archive. Archives are checksummed, extracted with path checks, and publisher symlink shortcuts are omitted. Use the effective `manifest.jsonl` after `audit`, not the original split report, to honor quarantine. Predictions and label keys stay separate; do not show either locked-test partition's labels to an estimator. Rerunning preparation recreates the development pilot but never runs a model or overwrites predictions.



The scorer rejects invalid quantities, unknown/duplicate prediction IDs, modified committed predictions and incomplete runs by default. It computes optional calorie/protein/carbohydrate/fat metrics when predictions include those fields, with explicit coverage counts. Missing predictions are never filled with zeros. Full measured-weight labels and detailed audit receipts remain local, not in distributed package files.



## Gate before estimation implementation



Data acquisition and a small photo-only baseline are complete. The next design should be evaluated on these fixed partitions before claims of improved accuracy. In particular:



1. Compare photo-only estimates with estimates given measured dimensions/reference objects, keeping reference-aware datasets separate.

2. Use independently weighed local meals for a genuinely new evaluation set. Public benchmark performance cannot establish that samples were unseen in pretraining.

3. Grade food identity, preparation state and hidden fats separately from portion mass. Add calorie/macro predictions to the scorer instead of treating weight accuracy as nutrition accuracy.

4. Compare future calibration only on held-out data, retain uncertainty and refusals, and report bias by food and portion size. Do not derive a universal chicken correction from one example.

5. Resolve SimpleFood45 terms before using it beyond local inspection. Keep NutritionVerse's noncommercial terms and SNAPMe's evaluation-only guidance attached to records.

6. An automated 30-image development pilot is now complete; a full held-out model evaluation has not been performed. See the API pilot report below.



The current data phase does not enable automatic logging or add any production estimation behavior. Future estimation/logging must preserve measured-versus-estimated provenance and verify actual MyFitnessPal entries after authorized writes.



## Automated API development pilot (October 15, 2026)

The encrypted local key works. The new `scripts/food_benchmark/infer.py` reads it in memory through PowerShell 7 and sends image-only prompts to the OpenAI Responses endpoint with response storage disabled. It rejects redirects, makes no automatic retries and permits only 1-30 development pilot samples. Labels are never opened during inference. The existing manual predictions and locked test partitions remain untouched.

Completed run: `work/food-estimation/api-pilot-03/`. Model: `gpt-4.1-mini-2025-04-14`; high image detail; maximum 1,000 output tokens per request; all 30 requests completed. Input hashes, predictions committed before scoring, model/token receipts and the scored report are saved together. Usage: 19,650 input tokens, 2,539 output tokens. Dollar charges were not independently checked. Earlier api-pilot-01/02 directories are failed local setup attempts with no API calls.

| Metric | Result |
| --- | ---: |
| Weight MAE | 92.3 g |
| Median absolute weight percentage error | 30.8% |
| Mean signed weight error | -83.5 g |
| Subjective interval coverage | 16.7% |
| Errors above 50% | 7 / 30 |
| Calories MAE | 68.1 kcal |
| Protein MAE | 7.17 g |
| Fat MAE | 5.34 g |
| Carbohydrate MAE | 8.28 g |

The baseline underestimates portions and gives narrow ranges with poor coverage. These are uncalibrated subjective ranges, not confidence guarantees. This is the same development sample as the manual pilot; differing models, presentation and nutrition prompts prevent causal comparison. Identification remains ungraded and public-data pretraining contamination unknown. No production estimation or automatic logging has been enabled. Next work should improve the development protocol, then compare reference-aware images and independently weighed meals before locked evaluation.

Reproduce using a fresh output directory:

```powershell
.\.venv\Scripts\python.exe -m scripts.food_benchmark.infer --model gpt-4.1-mini-2025-04-14 --limit 30 --output work/food-estimation/api-pilot-next
.\.venv\Scripts\python.exe -m scripts.food_benchmark.evaluate --predictions work/food-estimation/api-pilot-next/predictions.jsonl --truth data/food-estimation/labels/pilot-answer-key.jsonl --output work/food-estimation/api-pilot-next/report.json
```

Implemented against official OpenAI vision and structured output documentation:
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/structured-outputs
