# Model Card — Seniority Classifier

## What it does

Classifies a job listing into one of three seniority levels: `junior`, `senior`, `senior_plus`.
Input: job title + description concatenated as plain text.
Output: a single label.

```python
from apps.intelligence.ml_service import predict_seniority
label = predict_seniority(title, description)  # → 'junior' | 'senior' | 'senior_plus'
```

## Training data

- 611 job listings scraped from Remotive and Arbeitnow (591 Arbeitnow, 20 Remotive)
- Date range: ingested during Week 3 pipeline run
- Train/test split: 491 train / 120 test, group-aware (near-duplicate listings kept on the same side), stratified by class

Class distribution:

| Label | Count | % |
|---|---|---|
| senior_plus | 250 | 40.9 |
| senior | 207 | 33.9 |
| junior | 154 | 25.2 |

## Model

TF-IDF (10k features, bigrams, sublinear_tf=True) + Logistic Regression (class_weight=None, max_iter=1000).
Serialised to `apps/intelligence/ml/seniority_classifier.joblib`.

## Metrics (test set, n=120)

| | Precision | Recall | F1 |
|---|---|---|---|
| junior | 0.82 | 0.90 | 0.86 |
| senior | 0.78 | 0.71 | 0.74 |
| senior_plus | 0.80 | 0.81 | 0.80 |
| **macro avg** | **0.80** | **0.81** | **0.80** |
| accuracy | | | 0.80 |

Confusion matrix:

```
                  pred:junior  pred:senior  pred:senior_plus
true:junior                28            1                 2
true:senior                 4           29                 8
true:senior_plus            2            7                39
```

Most common error: `senior` ↔ `senior_plus` confusion (15 cases out of 24 total errors).
This boundary is genuinely fuzzy — a "Senior Principal Engineer" is legitimately ambiguous.

## Label provenance and accuracy

Labels come from two sources applied in order:

1. **Regex on job title** (`backfill_seniority`) — high precision where it fires, but only covers titles with explicit keywords (senior, junior, lead, etc.)
2. **This model itself** (`backfill_seniority_ml`) — used to label the `not_stated` remainder

**Important:** the LLM extraction pipeline (used in Week 3) measured `seniority_acc` of 0.526 on a 20-job hand-labelled eval set. The regex labels are likely more reliable than LLM labels for titles with clear keywords, but the ML-backfilled labels have no independent ground truth.

### What this means for the reported metrics

The test set labels are not perfectly accurate. If label accuracy is ~0.53–0.80 (LLM lower bound to regex upper bound), then:

- The model's **true accuracy ceiling is the label accuracy** — a perfect model trained on noisy labels cannot exceed the noise floor
- Reported test macro F1 of 0.80 should be read as: *"0.80 agreement with the training labels"*, not *"0.80 agreement with ground truth"*
- The true macro F1 against a clean hand-labelled set is unknown and likely lower

## Known weaknesses

- **German-language titles** are misclassified at higher rates — the TF-IDF vocabulary is dominated by English. Example: `Fachplaner*in Versorgungstechnik HLS (m/w/d)` predicted `junior` with 0.68 confidence (true: `senior`).
- **Ambiguous seniority markers** in titles like `(Senior)` or `Senior/Principal` confuse the model — it sees both signals and picks inconsistently.
- **Remotive is underrepresented** (20 jobs, 3.3% of data). The model has not been validated on Remotive listings independently.
- **`senior` recall is lowest** (0.71) — 12 senior jobs are misclassified, mostly as `senior_plus`. The senior/senior_plus boundary is the weakest point.
- **No temporal validation** — the model has not been tested on listings from a different time period. Job title conventions drift.

## When not to use it

- As a hard filter in candidate matching — a misclassified `junior` job shown to a senior candidate is a bad experience
- On non-English job boards without retraining or language detection
- As a substitute for human review on high-stakes decisions
- When label provenance matters and must be auditable — this model's training labels have no per-row source tracking

## Baseline comparison

| Model | Accuracy | Macro F1 |
|---|---|---|
| Majority class | 0.40 | 0.19 |
| Keyword rule (title) | 0.52 | 0.41 |
| **This model** | **0.80** | **0.80** |
