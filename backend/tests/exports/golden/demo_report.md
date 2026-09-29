# Data quality report: sales\_demo.csv

## Dataset summary

- File: sales\_demo.csv (csv)
- Size: 36521 bytes
- Content hash (SHA-256): `cef1513dfb14abb7eecc21e294bc7e0997c1a8d116bb792e5ed6006da5d1ea3c`
- Rows: 300
- Columns: 15
- Calculations covered: all 300 rows
- Analysis identifier: `demo-analysis`

## Trust assessment

- Assessment: **Not reliable for decision-making**
- Score: 0.0 / 100
- Findings considered: 22
- Highest finding priority score: 85.1
- The score is calculated deterministically; AI cannot alter it.

## Confirmed context

Context has not been inferred or confirmed for this analysis.

## Priority findings

Ordered by priority score, highest first.
Detector observations and example rows are omitted because they can quote dataset values; request bounded examples to include them.

- **Finding 15** (High, cross\_field) in quantity, unit\_price, discount\_pct, tax\_pct, line\_total: Line-total mismatch
  - Priority score: 85.1; affected rows: 2; review: Unreviewed
- **Finding 5** (High, completeness) in order\_id: Missing likely identifier
  - Priority score: 75.0; affected rows: 1; review: Unreviewed
- **Finding 4** (Medium, completeness) in notes: Excessive missing values
  - Priority score: 65.0; affected rows: 299; review: Unreviewed
- **Finding 3** (Medium, completeness) in line\_total: Excessive missing values
  - Priority score: 60.1; affected rows: 3; review: Unreviewed
- **Finding 9** (Medium, validity) in order\_date: Future dates
  - Priority score: 60.1; affected rows: 2; review: Unreviewed
- **Finding 2** (Medium, completeness) in quantity: Excessive missing values
  - Priority score: 50.1; affected rows: 3; review: Unreviewed
- **Finding 0** (Medium, structural) in dataset-level: Exact duplicate rows
  - Priority score: 50.1; affected rows: 2; review: Unreviewed
- **Finding 13** (Medium, validity) in discount\_pct: Invalid percentages
  - Priority score: 50.0; affected rows: 1; review: Unreviewed
- **Finding 14** (Medium, validity) in tax\_pct: Invalid percentages
  - Priority score: 50.0; affected rows: 1; review: Unreviewed
- **Finding 1** (Medium, structural) in empty\_col: Empty column
  - Priority score: 50.0; affected rows: 0; review: Unreviewed
- **Finding 16** (Medium, statistical) in constant\_col: Suspiciously constant column
  - Priority score: 50.0; affected rows: 0; review: Unreviewed
- **Finding 20** (Medium, statistical) in line\_total: Extreme outliers
  - Priority score: 45.5; affected rows: 10; review: Unreviewed
- **Finding 12** (Medium, validity) in line\_total: Negative likely non-negative values
  - Priority score: 45.1; affected rows: 3; review: Unreviewed
- **Finding 18** (Medium, statistical) in unit\_price: Extreme outliers
  - Priority score: 45.0; affected rows: 1; review: Unreviewed
- **Finding 10** (Medium, validity) in quantity: Negative likely non-negative values
  - Priority score: 35.1; affected rows: 2; review: Unreviewed
- **Finding 11** (Medium, validity) in tax\_pct: Negative likely non-negative values
  - Priority score: 35.0; affected rows: 1; review: Unreviewed
- **Finding 17** (Medium, statistical) in quantity: Extreme outliers
  - Priority score: 35.0; affected rows: 1; review: Unreviewed
- **Finding 19** (Medium, statistical) in discount\_pct: Extreme outliers
  - Priority score: 35.0; affected rows: 1; review: Unreviewed
- **Finding 7** (Low, consistency) in category: Inconsistent capitalization
  - Priority score: 27.4; affected rows: 48; review: Unreviewed
- **Finding 6** (Low, consistency) in category: Inconsistent capitalization
  - Priority score: 26.8; affected rows: 35; review: Unreviewed
- **Finding 8** (Low, consistency) in customer\_name: Leading/trailing whitespace
  - Priority score: 25.1; affected rows: 2; review: Unreviewed
- **Finding 21** (Low, ai\_processing\_security) in notes: Possible LLM prompt injection
  - Priority score: 18.8; affected rows: 1; review: Unreviewed

## Review decisions

- Unreviewed: 22
- Confirmed: 0
- Dismissed: 0
- Needs investigation: 0

## Recommendations

Review still pending for 22 finding(s): 15, 5, 4, 3, 9, 2, 0, 13, 14, 1, 16, 20, 12, 18, 10, 11, 17, 19, 7, 6, 8, 21.

## Validation rules

No validated rules are recorded for this analysis.

## AI-processing security

Detection pipeline (deterministic):
- No model provider was enabled for the detection pipeline.
- Dataset sample transmission to a model was not enabled.

Suspicious content:
- 1 possible prompt-injection finding detected, 0 dismissed by the reviewer.
  - Finding 21: Possible LLM prompt injection

Optional AI enrichment (explanations, context suggestions):
- Per-request AI enrichment is not recorded for this analysis.
- This report makes no statement about whether it was used.

## Methodology and limitations

- Findings come from deterministic detectors that calculate their own evidence.
- The trust assessment and finding priority scores are calculated deterministically.
- AI-generated text, where present, is advisory and never changes a finding or score.
- Reviewer decisions are recorded by people and are shown as recorded.
- Only the detectors in the catalogue were run; other quality problems can exist.

## Versions

- Application: 9.9.9
- Report schema: 1
- Detectors:
  - alpha.detector: 1
  - zeta.detector: 2
- Prompt version: prompt-v7
- Model: local-model-x
