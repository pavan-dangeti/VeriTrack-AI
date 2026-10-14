# OCR benchmark

How accurately and how safely the timesheet reader turns a screenshot into hours, measured on 440 generated
sheets with controlled degradations, on x86-64 (the architecture production runs on).

## Scope

The reader is built for **screenshots and digital exports** of one timesheet layout. Everything here is
synthetic: sheets are rendered by `scripts/gen_synthetic_timesheets.py` and degraded by
`scripts/bench_ocr.py`. The `simulated_photo` group imitates a phone photo of a printed page; **no real
photographs were tested**, and the app does not claim photo support.

## Method

**Sheets.** Realistic variants of the regression-test sheets: decimal hours (7.5, 3.5), notes, longer task
names that wrap, up to nine rows, four fonts, 80–150 % zoom, 28–31-day months.

**Degradations.** Each sheet gets exactly one, at low, medium or high severity (20 sheets per group):

| Group | Low / medium / high |
|---|---|
| clean | none |
| blur | Gaussian σ 0.6 / 1.0 / 1.4 px |
| skew | rotation 0.8° / 1.8° / 3.0° |
| noise | Gaussian noise σ 6 / 12 / 20 grey levels |
| jpeg | quality 60 / 40 / 25 |
| shadow | uneven lighting, darkest point 75 % / 60 % / 45 % of full brightness |
| lowres | downscaled to 70 % / 55 % / 45 % |
| stamp | a red "APPROVED"-style stamp over the table, opacity 0.3 / 0.45 / 0.6 |
| pen | 2 / 5 / 9 pen marks (ticks, circles, underlines, initials) — not data |
| correction | 1 / 1 / 2 day values struck through with a different number written beside them |
| simulated_photo | page on a desk at an angle (2 / 4 / 7 % corner shift), curled, warm light, noise, defocus, JPEG |

**Two sets.** The **development set** (seed 7) was used while fixing the reader. The **held-out set** (seed
4729) was fixed on 2026-10-13 before any of its sheets existed, and read once, at commit `1838480`, after
the fixes were final. Both come from the same generator, so the held-out set shows whether the fixes
overfit the development sheets; it does not show how the reader handles other kinds of input.

**Fields.** *Checked* fields are the ones the leave check depends on: every day's hours, row and sheet
totals, the number of rows, the employee ID, the period, the hour type and each row's leave flag (whether its
task reads as *Out Of Office*). *Unchecked* fields are shown and exported but neither covered by any total
nor used by the leave check: employee name, client, role, task title, project and task codes.

**Outcomes per sheet.**

| Outcome | Meaning |
|---|---|
| Exact | verified, and every checked and unchecked field matches the ground truth |
| Verified, unchecked field wrong | verified, every checked field right, an unchecked field differs |
| Flagged | marked *Needs review*, or refused as not a timesheet — safe, nothing is acted on |
| **Verified but wrong** | verified while a checked field is wrong: the outcome that must not happen |

A handwritten correction changes a value on paper that the printed totals still agree with, so for those
sheets the only safe outcome is *flagged*; verifying one counts as *verified but wrong*.

**What "verified" means.** Every day's hours agree with the printed row and sheet totals, the employee ID
and period were read (and every row that shows the ID agrees on it), and every row's task was read clearly
enough to tell leave from work. Project and task codes, names, roles and task titles are not cross-checked.

## Headline results — held-out set, x86-64

| Engine | Exact | Flagged | **Verified but wrong** | Verified, unchecked field wrong | Field accuracy | Cell accuracy | Median time per sheet |
|---|---|---|---|---|---|---|---|
| RapidOCR (PP-OCRv4), production | **96 / 220 (43.6 %)** | 114 | **1** | 9 | 93.1 % | 98.4 % | 5.8 s |
| Tesseract 5 | 27 / 220 (12.3 %) | 181 | **0** | 12 | 86.5 % | 98.1 % | 17.9 s |

RapidOCR by group (held-out): clean 18/20 exact, skew 17/20, shadow 17/20, noise 13/20, blur 11/20, jpeg
10/20, lowres 7/20, stamp 3/20; every pen-marked, corrected and simulated-photo sheet was flagged except one
corrected sheet (below). Full reports: [RapidOCR](benchmarks/heldout-rapid.md),
[Tesseract](benchmarks/heldout-tesseract.md).

**The one verified-but-wrong sheet** (`218_correction_medium`): a struck-through day value was not detected
as handwriting; the struck cell was misread, and the totals arithmetic repaired it back to the printed value,
so the sheet was marked *auto-corrected* instead of flagged. It is reported as found; the held-out set is not
used to tune the reader.

## Development set (used for tuning), x86-64

| Engine | Reader | Exact | Flagged | **Verified but wrong** | Verified, unchecked field wrong | Field accuracy | Cell accuracy |
|---|---|---|---|---|---|---|---|
| RapidOCR | before the fixes (`6e90ae5`) | 16 / 220 (7.3 %) | 202 | **1** | 1 | 80.7 % | 96.0 % |
| RapidOCR | final (`f107e8d`) | 86 / 220 (39.1 %) | 126 | **0** | 8 | 90.5 % | 98.0 % |
| Tesseract | before the fixes (`6e90ae5`) | 4 / 220 (1.8 %) | 212 | **1** | 3 | 74.8 % | 95.9 % |
| Tesseract | final (`1838480`) | 31 / 220 (14.1 %) | 179 | **0** | 10 | 84.8 % | 97.9 % |

Reports: [RapidOCR before](benchmarks/baseline-dev-rapid.md), [RapidOCR final](benchmarks/final-dev-rapid.md),
[Tesseract before](benchmarks/baseline-dev-tesseract.md), [Tesseract final](benchmarks/final-dev-tesseract.md).
Before the fixes, every shadowed and simulated-photo sheet was refused and every half-hour value was
unreadable; the verification rules below did not exist, which is why "before" verified fewer sheets *and*
verified one wrongly.

## What changed in the reader, and why

Each fix came from a measured failure and has a test that failed before it:

| Measured on the development set | Fix |
|---|---|
| A misread totals label ('ALNB', 'ISIT') matched no row, nothing was compared and the sheet verified | a totals row for every hour type used, the grand total row, readable zeros for unused hour types |
| A partial grid (21 of February's 28 days, 1 of 5 rows) verified | the day columns must match the month |
| An empty employee ID, or a stamp turning '100410' into '1004' on some rows, verified | the ID must be readable and every row must agree on it |
| A wrapped *Out Of Office* cell split into 'Payments Out Of' / 'Office'; the leave row was missed | a task that could be leave or work (similarity 0.4–0.85), empty, or read as an hour type blocks verification |
| '3.5' reached the recogniser as '35' (the decimal point was erased as noise) | a speck on the digits' baseline between two digits is kept as a decimal point |
| Shadowed sheets were refused: dim paper looked like ink | uneven lighting is flattened before the grid is located |
| Skewed sheets were all flagged: tilted rows drifted across row boundaries | the rotation is estimated from long near-horizontal lines and undone |
| 9 of 20 handwritten corrections verified on the printed value | a connected blue pen stroke, or a long diagonal stroke of dark unsaturated ink among the day boxes, blocks verification |

Evenly lit, level screenshots pass through the lighting and rotation steps unchanged.

## Engine comparison

On identical inputs and the same reader, RapidOCR reads 3.6× as many held-out sheets exactly as Tesseract
(96 vs 27) and is about 3× faster (5.8 s vs 17.9 s median on a GitHub-hosted x86-64 runner). Neither engine
produced more than one verified-but-wrong sheet in any final run; the safety comes from the verification
rules, not the engine. Tesseract is a benchmark option only (`read_timesheet(engine="tesseract")`).

## OCR output differs between processor architectures

The same code and images give different results on x86-64 and on ARM (Apple silicon). On the development set
the final reader read **86** sheets exactly on x86-64 (CI) and **94** on an ARM Mac (`python -m scripts.bench_ocr
run` locally), with groups moving in both directions (blur 5 vs 8, low resolution 6 vs 12, noise 13 vs 9). Two
reading errors appeared only on x86-64 and were fixed at the root:

- *Migration* was read as **'M ig ration'**: the wide gaps around an 'i' in that rendering were taken for word
  spaces.
- A wrapped *Out Of Office* cell was read as **'office'**: the detector missed the first line, and the box of
  the second line touched it by 1 px, which hid it from missed-text recovery.

Production runs on x86-64, so published numbers come from x86-64 CI runs only.

## Limitations

- Real phone photos have not been tested; simulated photos are all refused (no grid found). Page detection
  and perspective correction were not built, because the only evidence would have been this simulation.
- The handwriting check missed 1 of 20 held-out corrections (described above).
- The employee ID is required to be readable and identical on every row that shows it, but is not checked
  against anything else; project and task codes, names, roles and task titles are not cross-checked at all.
- Pen marks that are not data (ticks, circles) also block verification: 0 of 20 annotated sheets were read
  exactly, by design.
- Both sets come from one generator and one layout; other layouts go through the generic table reader.

## Reproduce

```bash
# locally (results differ by architecture, see above)
python -m scripts.bench_ocr generate --out bench-data --seed 7        # development set; --seed 4729 for held-out
python -m scripts.bench_ocr run --data bench-data --out bench-out [--engine tesseract]
python -m scripts.bench_ocr report bench-out

# on x86-64, as published (GitHub Actions, about 100 runner-minutes per run)
gh workflow run ocr-benchmark.yml --ref main -f engine=rapid -f seed=4729
gh workflow run ocr-benchmark.yml --ref main -f engine=tesseract -f seed=4729
```
