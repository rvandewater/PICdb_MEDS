# PICdb MEDS Extraction ETL

[![tests](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/tests.yaml/badge.svg)](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/tests.yaml)
[![code-quality](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/code-quality-main.yaml)
![python](https://img.shields.io/badge/-Python_3.11--3.13-blue?logo=python&logoColor=white)
[![MEDS-Extract 0.7](https://img.shields.io/badge/MEDS--Extract-0.7-blue)](https://github.com/mmcdermott/MEDS_extract)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](LICENSE)

This pipeline extracts the [Paediatric Intensive Care (PIC) database v1.1.0](https://physionet.org/content/picdb/1.1.0/)
from PhysioNet into the [MEDS format](https://medical-event-data-standard.github.io/). PIC holds 12,881
neonatal and paediatric patients and 13,449 hospital admissions from the Children's Hospital of Zhejiang
University School of Medicine (2010–2018). It was built from the
[ETL_MEDS_Template](https://github.com/Medical-Event-Data-Standard/ETL_MEDS_Template) and uses the
config-only layout introduced by [MEDS-Extract](https://github.com/mmcdermott/MEDS_extract) 0.7.

## Usage

PIC is a credentialed dataset. You need a PhysioNet account that has signed the PIC data use agreement.

```bash
pip install git+https://github.com/rvandewater/PICdb_MEDS.git
export DATASET_DOWNLOAD_USERNAME=$PHYSIONET_USERNAME
export DATASET_DOWNLOAD_PASSWORD=$PHYSIONET_PASSWORD
meds-extract-run spec=PICdb output_dir=$MEDS_OUTPUT_DIR
```

When you run this, the program will:

1. Download the v1.1.0 tables (`V1.1.0/*.csv`, about 1.2 GB) from PhysioNet into
    `$MEDS_OUTPUT_DIR/.meds_extract_run/raw_input`. Files that already exist and match their checksums
    are skipped, so an interrupted download resumes. Pass `download_dest_dir=$RAW_INPUT_DIR` to keep the
    raw data somewhere durable and reuse it across runs.
2. Build the MEDS cohort from those files and write it to `$MEDS_OUTPUT_DIR` (`data/` and `metadata/`).
    All transformations, joins and metadata extraction are declared in
    [`src/PICdb_MEDS/event_configs.yaml`](src/PICdb_MEDS/event_configs.yaml).

If you already have the PhysioNet release on disk, skip the download and point `input_dir` at the
release root, the directory that contains `V1.1.0/`:

```bash
meds-extract-run spec=PICdb output_dir=$MEDS_OUTPUT_DIR \
	do_download=false input_dir=/path/to/paediatric-intensive-care-database-1.1.0
```

To parallelize the stages, pass a runner file:

```bash
printf 'parallelize:\n  n_workers: 8\n  launcher: joblib\n' >runner.yaml
meds-extract-run spec=PICdb output_dir=$MEDS_OUTPUT_DIR stage_runner_fp=runner.yaml
```

Run `meds-extract-run --help` for every option.

## How this ETL is defined

The package contains no Python. The whole ETL is one MESSY (MEDS-Extract Specification Syntax YAML)
file, [`src/PICdb_MEDS/event_configs.yaml`](src/PICdb_MEDS/event_configs.yaml). It declares:

- **`sources:`**: where the raw data lives (the PhysioNet release, restricted to `V1.1.0/*.csv`).
- **`etl:`**: the dataset name and sharding options.
- **One block per raw table**: how each row becomes one or more MEDS events, and which dictionary
    tables describe the resulting codes.

`pyproject.toml` registers the file with MEDS-Extract's `MEDS_extract.pipelines` entry-point group under
the name `PICdb`. That registration is what makes `spec=PICdb` work. No pre-MEDS step is needed: every
PIC table already carries `SUBJECT_ID`, and every timestamp has the same format.

## Events

| Table                 | Event codes                                                                                                                            | Notes                                                                                   |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `PATIENTS`            | `GENDER//{gender}`, `MEDS_BIRTH`, `MEDS_DEATH`                                                                                         | Death time is the earliest `ADMISSIONS.DEATHTIME`, falling back to `DOD`.               |
| `ADMISSIONS`          | `HOSPITAL_ADMISSION//{dept}`, `HOSPITAL_DISCHARGE//{dept}`, `INSURANCE//…`, `ETHNICITY//…`, `ADMISSION_DIAGNOSIS//ICD10_CN//{code}`    | ED times equal admit/discharge times in every row, so there are no separate ED events.  |
| `ICUSTAYS`            | `ICU_ADMISSION//{careunit}`, `ICU_DISCHARGE//{careunit}`                                                                               |                                                                                         |
| `DIAGNOSES_ICD`       | `DIAGNOSIS//ICD10_CN//{code}`                                                                                                          | Placed at hospital discharge. `seq_num` and `diag_category` are kept as columns.        |
| `LABEVENTS`           | `LAB//{itemid}//{unit}`                                                                                                                | `numeric_value`, `text_value` and `flag` are kept.                                      |
| `CHARTEVENTS`         | `CHART//{itemid}//{unit}`                                                                                                              |                                                                                         |
| `INPUTEVENTS`         | `FLUID_INPUT//{unit}`                                                                                                                  | PIC records only fluid intake amounts here, with no item ID.                            |
| `OUTPUTEVENTS`        | `OUTPUT//{itemid}//{unit}`                                                                                                             |                                                                                         |
| `PRESCRIPTIONS`       | `MEDICATION//START//{drug}//{dose unit}`, `MEDICATION//END//{drug}`                                                                    | Uses the English drug name. The dose is the `numeric_value`.                            |
| `MICROBIOLOGYEVENTS`  | `MICROBIOLOGY//SPECIMEN//{spec_itemid}`, `MICROBIOLOGY//ORGANISM//{org_itemid}`, `MICROBIOLOGY//SUSCEPTIBILITY//{ab_itemid}//{S/I/R…}` | The MIC dilution is the `numeric_value`. Organism and specimen IDs are kept as columns. |
| `OR_EXAM_REPORTS`     | `EXAM//{type}//{item}`                                                                                                                 | Uses the exam time, or the report time when the exam time is missing.                   |
| `EMR_SYMPTOMS`        | `SYMPTOM//{symptom}//{+/-}`                                                                                                            | Symptoms extracted by NLP from clinical notes.                                          |
| `SURGERY_INFO`        | `SURGERY//START//{name}`, `SURGERY//END//{name}`, `ANESTHESIA//START//{method}`, `ANESTHESIA//END//{method}`                           |                                                                                         |
| `SURGERY_VITAL_SIGNS` | `SURGERY_VITAL//{itemid}`                                                                                                              | Intra-operative monitoring. Units are in the code metadata (`unit`).                    |

A missing unit or susceptibility interpretation becomes `UNK` in the code. A row with a missing
identifying component (for example, no organism) produces no event for that component.

### Code metadata

`metadata/codes.parquet` links codes to PIC's dictionary tables:

- **`description`**: the English label from `D_ITEMS`, `D_LABITEMS` or `D_ICD_DIAGNOSES`.
- **`parent_codes`**: `LOINC/…` for lab items with a well-formed LOINC code, and `ICD10/…` for
    diagnoses whose mapped code is a valid 3- or 4-character WHO ICD-10 code. PIC's own extended codes
    (7+ characters) have no parent.
- **Chinese source terms**: kept in their own columns (`title_cn`, `label_cn`, `drug_name_cn`,
    `org_name_cn`, `spec_type_desc_cn`, `ab_name_cn`, `symptom_name_cn`). Codes are always built from the
    English or ID columns.
- **Extra dictionary fields**: `fluid`, `category` and `unit`.

### Data notes

- **Shifted dates.** Dates are shifted 50–100 years into the future per patient. Years between 2049 and
    2119 are expected, and intervals within a patient are preserved.
- **Release layout.** The v1.1.0 release ships the current tables under `V1.1.0/`. The gzipped files at
    the release root are the superseded v1.0.0 tables, and this ETL does not read them.
- **Swapped column names.** In `PRESCRIPTIONS`, the CSV header `DRUG_NAME` holds the Chinese name and
    `DRUG_NAME_EN` the English one. The bundled SQL scripts name these columns differently.
- **Many-to-many microbiology IDs.** Item IDs and their Chinese names do not map one-to-one, so codes
    use the item IDs. Expect MEDS-Extract warnings that some codes have several `*_cn` values; those
    values are aggregated into lists.
- **Uninformative columns.** `LANGUAGE`, `RELIGION` and `MARITAL_STATUS` hold a single value across the
    release and are not extracted.

## Testing

PIC has no open demo release. Instead, `tests/e2e_synthetic_test.py` writes a few fully synthetic rows
with PIC's exact headers and layout, runs `meds-extract-run spec=PICdb` over them, and checks the
events, times, values and code metadata it produces.

```bash
uv sync --group dev
uv run pytest tests/ -v
uv run pre-commit run --all-files
```

## Citation

If you use this ETL, please cite the PIC database and its descriptor paper:

- Li, H., Zeng, X., & Yu, G. (2020). *Paediatric Intensive Care database* (version 1.1.0). PhysioNet.
    https://doi.org/10.13026/32x9-wv38
- Zeng, X., Yu, G., Lu, Y. et al. PIC, a paediatric-specific intensive care database. *Sci Data* 7, 14
    (2020). https://doi.org/10.1038/s41597-020-0355-4

See also [`CITATION.cff`](CITATION.cff).
