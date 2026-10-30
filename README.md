# PICdb MEDS Extraction ETL

<!-- Placeholders until available: the PyPI badges resolve once PICdb-MEDS is published; replace
CODECOV_TOKEN_PLACEHOLDER with the repo's Codecov badge token and zenodo.XXXXXXX with its Zenodo DOI. -->

[![PyPI - Version](https://img.shields.io/pypi/v/PICdb-MEDS)](https://pypi.org/project/PICdb-MEDS/)
[![codecov](https://codecov.io/gh/rvandewater/PICdb_MEDS/graph/badge.svg?token=CODECOV_TOKEN_PLACEHOLDER)](https://codecov.io/gh/rvandewater/PICdb_MEDS)
[![tests](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/synthetic-etl.yaml/badge.svg)](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/synthetic-etl.yaml)
[![code-quality](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/rvandewater/PICdb_MEDS/actions/workflows/code-quality-main.yaml)
![python](https://img.shields.io/badge/python-%3E%3D3.11.4%2C%20%3C3.14-blue?logo=python&logoColor=white)
![Static Badge](https://img.shields.io/badge/MEDS-0.4.1-blue)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/rvandewater/PICdb_MEDS#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/rvandewater/PICdb_MEDS/pulls)
[![contributors](https://img.shields.io/github/contributors/rvandewater/PICdb_MEDS.svg)](https://github.com/rvandewater/PICdb_MEDS/graphs/contributors)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23676598.svg)](https://doi.org/10.5281/zenodo.23676598)

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

`metadata/codes.parquet` describes every code except `MEDS_BIRTH` and `MEDS_DEATH`, and links codes to
PIC's dictionary tables:

- **`description`**: one English description per code, from one of two routes.
    - **PIC dictionaries**: the English label from `D_LABITEMS` (labs), `D_ICD_DIAGNOSES` (diagnoses) or
        `D_ITEMS` (chart, output and intra-operative vital items, organisms, antibiotics, and the specimen
        IDs `D_ITEMS` lists). These are joined when the ETL runs; nothing from them is copied into this
        repository.
    - **Templates**: every other code gets a `_self` template in the event config. The template
        restates the code's parts in words and names the PIC column they come from, for example
        `ICU admission; first care unit: PICU, paediatric ICU (PIC ICUSTAYS.FIRST_CAREUNIT)`. The
        wording follows the [PhysioNet PIC documentation](https://physionet.org/content/picdb/1.1.0/) and
        the PIC paper ([Zeng et al. 2020](https://doi.org/10.1038/s41597-020-0355-4), CC BY 4.0). The paper
        names the five ICUs and says what `INPUTEVENTS` holds. The PhysioNet page explains the `+`/`-`
        symptom attribute and the "Other" ethnicity group. A specimen ID that `D_ITEMS` does not list
        gets a description saying so; its Chinese name is in `spec_type_desc_cn`.
    - `MEDS_BIRTH` and `MEDS_DEATH` have no description. MEDS-Extract 0.7 attaches no metadata to a
        literal code, and the MEDS standard defines what these two mean.
- **`parent_codes`**: OMOP-style `vocabulary_id/code` parents:
    - `LOINC/…` for lab items with a well-formed LOINC code;
    - `ICD10/…` for diagnoses whose mapped code is a valid 3- or 4-character WHO ICD-10 code. PIC's own
        extended codes (7+ characters) have no parent;
    - `ICDO3/…` for diagnoses coded as ICD-O-3 morphology (`dddd/d`, for example `ICDO3/8000/3`). The
        PIC paper notes that diagnoses use both ICD-10 and ICD-O-3.
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
- **Local diagnosis codes.** Diagnoses use PIC's extended Chinese ICD-10 codes (`ICD10_CN`), so they do
    not yet line up with standard ICD-10 codes in other datasets. Valid standard codes are attached as
    `parent_codes`. Mapping equivalent codes to standard ICD-10 needs a MEDS-Extract feature; see
    [#1](https://github.com/rvandewater/PICdb_MEDS/issues/1).

## Testing

PIC has no open demo release. Instead, `tests/e2e_synthetic_test.py` writes a few fully synthetic rows
with PIC's exact headers and layout, runs `meds-extract-run spec=PICdb` over them, and checks the
events, times, values and code metadata it produces. That includes checking that the output validates
against `meds.CodeMetadataSchema`. `tests/test_code_descriptions.py` checks the config itself: every
event block declares exactly one description, a `_self` description reads only the code's own parts,
and parents use OMOP vocabulary prefixes.

```bash
uv sync --group dev
uv run pytest tests/ -v
uv run pre-commit run --all-files
```

## Citation

If you use this ETL, please cite the PIC database and its descriptor paper:

```bibtex
@article{PhysioNet-picdb-1.1.0,
  author = {Li, Haomin and Zeng, Xian and Yu, Gang},
  title = {{Paediatric Intensive Care database}},
  journal = {{PhysioNet}},
  year = {2020},
  month = nov,
  note = {Version 1.1.0},
  doi = {10.13026/32x9-wv38},
  url = {https://doi.org/10.13026/32x9-wv38}
}
@article{zengPICPaediatricspecificIntensive2020,
  title = {{{PIC}}, a Paediatric-Specific Intensive Care Database},
  author = {Zeng, Xian and Yu, Gang and Lu, Yang and Tan, Linhua and Wu, Xiujing and Shi, Shanshan and Duan, Huilong and Shu, Qiang and Li, Haomin},
  year = 2020,
  month = jan,
  journal = {Scientific Data},
  volume = {7},
  number = {1},
  pages = {14},
  publisher = {Nature Publishing Group},
  issn = {2052-4463},
  doi = {10.1038/s41597-020-0355-4},
  copyright = {2020 The Author(s)},
  langid = {english},
}
```

See also [`CITATION.cff`](CITATION.cff).
