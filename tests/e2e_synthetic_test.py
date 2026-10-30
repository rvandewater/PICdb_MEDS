"""End-to-end run of the shipped ETL over a small synthetic PIC release.

PIC is credentialed and has no open demo release, so this test writes a handful of fully synthetic
rows -- with the exact headers, file layout (`V1.1.0/*.csv`), CRLF line endings and timestamp format
of the real v1.1.0 release -- and runs `meds-extract-run spec=PICdb` over them with downloading
disabled. Driving it through the registered name rather than a path makes this test cover the
entry-point registration too.

None of the values below come from the real database.
"""

import csv
import json
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
from meds import CodeMetadataSchema

SPEC = "PICdb"
RAW_RELEASE = "1.1.0"

TABLES: dict[str, list[dict[str, str]]] = {
    "PATIENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "GENDER": "M",
            "DOB": "2080-01-01 00:00:00",
            "DOD": "2081-03-04 05:06:07",
            "EXPIRE_FLAG": "1",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "2",
            "GENDER": "F",
            "DOB": "2090-06-15 12:30:00",
            "DOD": "",
            "EXPIRE_FLAG": "0",
        },
        # Dies in hospital but has no `DOD`: the death time must come from `ADMISSIONS.DEATHTIME`.
        {
            "ROW_ID": "3",
            "SUBJECT_ID": "3",
            "GENDER": "F",
            "DOB": "2100-02-02 00:00:00",
            "DOD": "",
            "EXPIRE_FLAG": "1",
        },
    ],
    "ADMISSIONS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ADMITTIME": "2081-03-01 08:00:00",
            "DISCHTIME": "2081-03-04 05:06:07",
            "DEATHTIME": "2081-03-04 05:06:07",
            "ADMISSION_DEPARTMENT": "PICU",
            "DISCHARGE_DEPARTMENT": "PICU",
            "INSURANCE": "Self-pay",
            "LANGUAGE": "Chi",
            "RELIGION": "Not specified",
            "MARITAL_STATUS": "Single",
            "ETHNICITY": "Han",
            "EDREGTIME": "2081-03-01 08:00:00",
            "EDOUTTIME": "2081-03-04 05:06:07",
            "DIAGNOSIS": "",
            "ICD10_CODE_CN": "J18.900",
            "HOSPITAL_EXPIRE_FLAG": "1",
            "HAS_CHARTEVENTS_DATA": "1",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "2",
            "HADM_ID": "201",
            "ADMITTIME": "2091-01-10 10:00:00",
            "DISCHTIME": "2091-01-20 10:00:00",
            "DEATHTIME": "",
            "ADMISSION_DEPARTMENT": "Neonatology",
            "DISCHARGE_DEPARTMENT": "General Surgery",
            "INSURANCE": "Insured",
            "LANGUAGE": "Chi",
            "RELIGION": "Not specified",
            "MARITAL_STATUS": "Single",
            "ETHNICITY": "Han",
            "EDREGTIME": "2091-01-10 10:00:00",
            "EDOUTTIME": "2091-01-20 10:00:00",
            "DIAGNOSIS": "",
            "ICD10_CODE_CN": "",
            "HOSPITAL_EXPIRE_FLAG": "0",
            "HAS_CHARTEVENTS_DATA": "0",
        },
        {
            "ROW_ID": "3",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "ADMITTIME": "2101-05-05 05:05:05",
            "DISCHTIME": "2101-05-09 09:09:09",
            "DEATHTIME": "2101-05-09 09:09:09",
            "ADMISSION_DEPARTMENT": "CICU",
            "DISCHARGE_DEPARTMENT": "CICU",
            "INSURANCE": "Self-pay",
            "LANGUAGE": "Chi",
            "RELIGION": "Not specified",
            "MARITAL_STATUS": "Single",
            "ETHNICITY": "Other",
            "EDREGTIME": "2101-05-05 05:05:05",
            "EDOUTTIME": "2101-05-09 09:09:09",
            "DIAGNOSIS": "",
            "ICD10_CODE_CN": "Q21.000",
            "HOSPITAL_EXPIRE_FLAG": "1",
            "HAS_CHARTEVENTS_DATA": "1",
        },
    ],
    "ICUSTAYS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ICUSTAY_ID": "1001",
            "FIRST_CAREUNIT": "PICU",
            "LAST_CAREUNIT": "PICU",
            "FIRST_WARDID": "1",
            "LAST_WARDID": "1",
            "INTIME": "2081-03-01 09:00:00",
            "OUTTIME": "2081-03-04 05:06:07",
            "LOS": "2.84",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "ICUSTAY_ID": "3001",
            "FIRST_CAREUNIT": "CICU",
            "LAST_CAREUNIT": "CICU",
            "FIRST_WARDID": "2",
            "LAST_WARDID": "2",
            "INTIME": "2101-05-05 06:00:00",
            "OUTTIME": "2101-05-09 09:09:09",
            "LOS": "4.13",
        },
    ],
    "DIAGNOSES_ICD": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "SEQ_NUM": "1",
            "ICD10_CODE_CN": "J18.900",
            "Diag_Category": "Primary",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "2",
            "HADM_ID": "201",
            "SEQ_NUM": "1",
            "ICD10_CODE_CN": "P07.300x001",
            "Diag_Category": "Primary",
        },
        {
            "ROW_ID": "3",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "SEQ_NUM": "1",
            "ICD10_CODE_CN": "Q21.000",
            "Diag_Category": "Primary",
        },
        # A diagnosis whose mapped code is an ICD-O-3 morphology code.
        {
            "ROW_ID": "4",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "SEQ_NUM": "2",
            "ICD10_CODE_CN": "M80000/3",
            "Diag_Category": "Other",
        },
    ],
    "D_ICD_DIAGNOSES": [
        {
            "ROW_ID": "1",
            "ICD10_CODE_CN": "J18.900",
            "ICD10_CODE": "J18.9",
            "TITLE_CN": "肺炎",
            "TITLE": "Pneumonia, unspecified",
        },
        {
            "ROW_ID": "2",
            "ICD10_CODE_CN": "P07.300x001",
            "ICD10_CODE": "P07.30",
            "TITLE_CN": "早产儿",
            "TITLE": "Preterm newborn",
        },
        {
            "ROW_ID": "3",
            "ICD10_CODE_CN": "Q21.000",
            "ICD10_CODE": "Q21.0",
            "TITLE_CN": "室间隔缺损",
            "TITLE": "Ventricular septal defect",
        },
        {
            "ROW_ID": "4",
            "ICD10_CODE_CN": "M80000/3",
            "ICD10_CODE": "8000/3",
            "TITLE_CN": "测试",
            "TITLE": "Synthetic neoplasm entry",
        },
    ],
    "D_ITEMS": [
        {
            "ROW_ID": "1",
            "ITEMID": "1001",
            "LABEL_CN": "心率",
            "LABEL": "Heart Rate",
            "LINKSTO": "chartevents",
            "CATEGORY": "Vital Signs",
            "UNITNAME": "",
        },
        {
            "ROW_ID": "2",
            "ITEMID": "2001",
            "LABEL_CN": "尿量",
            "LABEL": "Urine",
            "LINKSTO": "outputevents",
            "CATEGORY": "Output",
            "UNITNAME": "",
        },
        {
            "ROW_ID": "3",
            "ITEMID": "SV1",
            "LABEL_CN": "心率",
            "LABEL": "Heart Rate",
            "LINKSTO": "surgery_vital_signs",
            "CATEGORY": "Vital Signs",
            "UNITNAME": "bpm",
        },
        {
            "ROW_ID": "4",
            "ITEMID": "B1",
            "LABEL_CN": "血",
            "LABEL": "Blood",
            "LINKSTO": "microbiologyevents",
            "CATEGORY": "SPECIMEN",
            "UNITNAME": "",
        },
        {
            "ROW_ID": "5",
            "ITEMID": "O1",
            "LABEL_CN": "金黄色葡萄球菌",
            "LABEL": "Staphylococcus aureus",
            "LINKSTO": "microbiologyevents",
            "CATEGORY": "ORGANISM",
            "UNITNAME": "",
        },
        {
            "ROW_ID": "6",
            "ITEMID": "A1",
            "LABEL_CN": "万古霉素",
            "LABEL": "Vancomycin",
            "LINKSTO": "microbiologyevents",
            "CATEGORY": "ANTIBACTERIUM",
            "UNITNAME": "",
        },
    ],
    "D_LABITEMS": [
        {
            "ROW_ID": "1",
            "ITEMID": "5001",
            "LABEL_CN": "钾",
            "LABEL": "Potassium",
            "FLUID": "Blood",
            "CATEGORY": "Chemistry",
            "LOINC_CODE": "2823-3",
        },
        {
            "ROW_ID": "2",
            "ITEMID": "5002",
            "LABEL_CN": "血培养",
            "LABEL": "Culture",
            "FLUID": "Blood",
            "CATEGORY": "Microbiology",
            "LOINC_CODE": "600",
        },
    ],
    "LABEVENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ITEMID": "5001",
            "CHARTTIME": "2081-03-01 10:00:00",
            "VALUE": "4.1",
            "VALUENUM": "4.1",
            "VALUEUOM": "mmol/L",
            "FLAG": "",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ITEMID": "5001",
            "CHARTTIME": "2081-03-02 10:00:00",
            "VALUE": "5.9",
            "VALUENUM": "5.9",
            "VALUEUOM": "mmol/L",
            "FLAG": "H",
        },
        {
            "ROW_ID": "3",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "ITEMID": "5002",
            "CHARTTIME": "2101-05-06 10:00:00",
            "VALUE": "Negative",
            "VALUENUM": "",
            "VALUEUOM": "",
            "FLAG": "",
        },
    ],
    "CHARTEVENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ICUSTAY_ID": "1001",
            "ITEMID": "1001",
            "CHARTTIME": "2081-03-01 09:30:00",
            "STORETIME": "2081-03-01 09:30:00",
            "VALUE": "130",
            "VALUENUM": "130",
            "VALUEUOM": "bpm",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "ICUSTAY_ID": "",
            "ITEMID": "1001",
            "CHARTTIME": "2101-05-05 07:00:00",
            "STORETIME": "2101-05-05 07:00:00",
            "VALUE": "150",
            "VALUENUM": "150",
            "VALUEUOM": "bpm",
        },
    ],
    "INPUTEVENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ICUSTAY_ID": "1001",
            "CHARTTIME": "2081-03-01 12:00:00",
            "AMOUNT": "50",
            "AMOUNTUOM": "ml",
            "STORETIME": "2081-03-01 12:00:00",
        },
    ],
    "OUTPUTEVENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ICUSTAY_ID": "",
            "CHARTTIME": "2081-03-01 13:00:00",
            "ITEMID": "2001",
            "VALUE": "35",
            "VALUEUOM": "ml",
            "STORETIME": "2081-03-01 13:00:00",
        },
    ],
    "PRESCRIPTIONS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "ICUSTAY_ID": "1001",
            "STARTDATE": "2081-03-01 11:00:00",
            "ENDDATE": "2081-03-03 11:00:00",
            "DRUG_NAME": "万古霉素",
            "DRUG_NAME_EN": "Vancomycin Injection",
            "PROD_STRENGTH": "0.5g",
            "DRUG_NAME_GENERIC": "",
            "DOSE_VAL_RX": "150",
            "DOSE_UNIT_RX": "mg",
            "DRUG_FORM": "Injection",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "2",
            "HADM_ID": "201",
            "ICUSTAY_ID": "",
            "STARTDATE": "2091-01-11 08:00:00",
            "ENDDATE": "",
            "DRUG_NAME": "维生素K1",
            "DRUG_NAME_EN": "Vitamin K1 Injection",
            "PROD_STRENGTH": "10mg",
            "DRUG_NAME_GENERIC": "",
            "DOSE_VAL_RX": "1",
            "DOSE_UNIT_RX": "",
            "DRUG_FORM": "Injection",
        },
    ],
    "MICROBIOLOGYEVENTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "CHARTTIME": "2081-03-01 15:00:00",
            "SPEC_ITEMID": "B1",
            "SPEC_TYPE_DESC": "血",
            "ORG_ITEMID": "O1",
            "ORG_NAME": "金黄色葡萄球菌",
            "AB_ITEMID": "A1",
            "AB_NAME": "万古霉素",
            "DILUTION_TEXT": "1",
            "DILUTION_COMPARISON": "<=",
            "DILUTION_VALUE": "1",
            "INTERPRETATION": "S",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "CHARTTIME": "2101-05-06 15:00:00",
            "SPEC_ITEMID": "B1",
            "SPEC_TYPE_DESC": "血",
            "ORG_ITEMID": "",
            "ORG_NAME": "",
            "AB_ITEMID": "",
            "AB_NAME": "",
            "DILUTION_TEXT": "",
            "DILUTION_COMPARISON": "",
            "DILUTION_VALUE": "",
            "INTERPRETATION": "",
        },
        # A specimen ID that `D_ITEMS` does not list.
        {
            "ROW_ID": "3",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "CHARTTIME": "2081-03-02 15:00:00",
            "SPEC_ITEMID": "S900",
            "SPEC_TYPE_DESC": "痰",
            "ORG_ITEMID": "",
            "ORG_NAME": "",
            "AB_ITEMID": "",
            "AB_NAME": "",
            "DILUTION_TEXT": "",
            "DILUTION_COMPARISON": "",
            "DILUTION_VALUE": "",
            "INTERPRETATION": "",
        },
    ],
    "OR_EXAM_REPORTS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "EXAMTIME": "2081-03-01 16:00:00",
            "REPORTTIME": "2081-03-01 18:00:00",
            "EXAM_ITEM_TYPE_NAME": "X-ray",
            "EXAM_ITEM_NAME": "Chest X-ray",
            "EXAM_PART_NAME": "Chest",
        },
        # No exam time: the event must fall back to the report time.
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "EXAMTIME": "",
            "REPORTTIME": "2101-05-07 18:00:00",
            "EXAM_ITEM_TYPE_NAME": "Ultrasound",
            "EXAM_ITEM_NAME": "Echocardiography",
            "EXAM_PART_NAME": "",
        },
    ],
    "EMR_SYMPTOMS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "EMR_ID": "9001",
            "RECORDTIME": "2081-03-01 20:00:00",
            "SYMPTOM_NAME_CN": "发热",
            "SYMPTOM_NAME": "fever",
            "SYMPTOM_ATTRIBUTE": "+",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "1",
            "HADM_ID": "101",
            "EMR_ID": "9001",
            "RECORDTIME": "2081-03-01 20:00:00",
            "SYMPTOM_NAME_CN": "咳嗽",
            "SYMPTOM_NAME": "cough",
            "SYMPTOM_ATTRIBUTE": "-",
        },
    ],
    "SURGERY_INFO": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "VISIT_ID": "1",
            "OPER_ID": "1",
            "ANES_START_TIME": "2101-05-06 08:00:00",
            "ANES_END_TIME": "2101-05-06 12:00:00",
            "SURGERY_BEGIN_TIME": "2101-05-06 08:30:00",
            "SURGERY_END_TIME": "2101-05-06 11:30:00",
            "SURGERY_NAME": "VSD repair",
            "ANES_METHOD": "General anesthesia",
            "SURGERY_POSITION": "Supine",
        },
    ],
    "SURGERY_VITAL_SIGNS": [
        {
            "ROW_ID": "1",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "VISIT_ID": "1",
            "OPER_ID": "1",
            "ITEM_NO": "1",
            "MONITOR_TIME": "2101-05-06 08:35:00",
            "ITEMID": "SV1",
            "VALUE": "140",
        },
        {
            "ROW_ID": "2",
            "SUBJECT_ID": "3",
            "HADM_ID": "301",
            "VISIT_ID": "1",
            "OPER_ID": "1",
            "ITEM_NO": "2",
            "MONITOR_TIME": "2101-05-06 08:40:00",
            "ITEMID": "SV1",
            "VALUE": "138",
        },
    ],
}


def write_raw_release(root: Path) -> None:
    out = root / f"V{RAW_RELEASE}"
    out.mkdir(parents=True)
    for table, rows in TABLES.items():
        with (out / f"{table}.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\r\n")
            writer.writeheader()
            writer.writerows(rows)


@pytest.fixture(scope="module")
def cohort(tmp_path_factory) -> Path:
    # Resolve the runner against `sysconfig`'s script dir rather than the ambient PATH, so the test
    # behaves the same under `uv run pytest` and a bare `pytest`. The dir is also prepended to the
    # child's PATH, because the runner spawns stages by bare name.
    scripts = Path(sysconfig.get_path("scripts"))
    runner = scripts / "meds-extract-run"
    assert runner.exists(), f"meds-extract-run is not installed in this environment ({sys.executable})."
    env = os.environ | {"PATH": f"{scripts}{os.pathsep}{os.environ.get('PATH', '')}"}

    root = tmp_path_factory.mktemp("picdb")
    raw = root / "raw"
    write_raw_release(raw)
    out = root / "MEDS_cohort"

    command = [str(runner), f"spec={SPEC}", f"output_dir={out}", "do_download=false", f"input_dir={raw}"]
    result = subprocess.run(command, capture_output=True, check=False, env=env)
    assert result.returncode == 0, (
        f"{' '.join(command)} failed with return code {result.returncode}.\n"
        f"stdout:\n{result.stdout.decode()}\nstderr:\n{result.stderr.decode()}"
    )
    return out


@pytest.fixture(scope="module")
def data(cohort: Path) -> pl.DataFrame:
    return pl.read_parquet(cohort / "data" / "**" / "*.parquet")


@pytest.fixture(scope="module")
def codes(cohort: Path) -> pl.DataFrame:
    return pl.read_parquet(cohort / "metadata" / "codes.parquet")


def test_layout_and_identity(cohort: Path):
    metadata = cohort / "metadata"
    for fname in ("dataset.json", "codes.parquet", "subject_splits.parquet"):
        assert (metadata / fname).exists(), f"{fname} missing from {metadata}"

    dataset_json = json.loads((metadata / "dataset.json").read_text())
    assert dataset_json["dataset_name"] == SPEC
    assert dataset_json["dataset_version"].startswith(f"{RAW_RELEASE}:")

    splits = pl.read_parquet(metadata / "subject_splits.parquet")
    assert sorted(splits["subject_id"].to_list()) == [1, 2, 3]


def test_every_event_block_produces_events(data: pl.DataFrame):
    want = {
        "V1.1.0/PATIENTS/gender", "V1.1.0/PATIENTS/dob", "V1.1.0/PATIENTS/death",
        "V1.1.0/ADMISSIONS/admission", "V1.1.0/ADMISSIONS/insurance", "V1.1.0/ADMISSIONS/ethnicity",
        "V1.1.0/ADMISSIONS/admission_diagnosis", "V1.1.0/ADMISSIONS/discharge",
        "V1.1.0/ICUSTAYS/icu_admission", "V1.1.0/ICUSTAYS/icu_discharge",
        "V1.1.0/DIAGNOSES_ICD/diagnosis", "V1.1.0/LABEVENTS/lab", "V1.1.0/CHARTEVENTS/chart",
        "V1.1.0/INPUTEVENTS/fluid_input", "V1.1.0/OUTPUTEVENTS/output",
        "V1.1.0/PRESCRIPTIONS/medication_start", "V1.1.0/PRESCRIPTIONS/medication_end",
        "V1.1.0/MICROBIOLOGYEVENTS/specimen", "V1.1.0/MICROBIOLOGYEVENTS/organism",
        "V1.1.0/MICROBIOLOGYEVENTS/susceptibility", "V1.1.0/OR_EXAM_REPORTS/exam",
        "V1.1.0/EMR_SYMPTOMS/symptom", "V1.1.0/SURGERY_INFO/surgery_start",
        "V1.1.0/SURGERY_INFO/surgery_end", "V1.1.0/SURGERY_INFO/anesthesia_start",
        "V1.1.0/SURGERY_INFO/anesthesia_end", "V1.1.0/SURGERY_VITAL_SIGNS/surgery_vital",
    }  # fmt: skip
    got = set(data["source_block"].unique().to_list())
    assert want == got, f"missing: {sorted(want - got)}; unexpected: {sorted(got - want)}"


def test_death_prefers_deathtime_and_falls_back(data: pl.DataFrame):
    deaths = data.filter(pl.col("code") == "MEDS_DEATH").sort("subject_id")
    assert deaths["subject_id"].to_list() == [1, 3]
    assert [str(t) for t in deaths["time"].to_list()] == ["2081-03-04 05:06:07", "2101-05-09 09:09:09"]


def test_codes(data: pl.DataFrame):
    got = set(data["code"].unique().to_list())
    for code in [
        "GENDER//F",
        "HOSPITAL_ADMISSION//PICU",
        "ADMISSION_DIAGNOSIS//ICD10_CN//J18.900",
        "DIAGNOSIS//ICD10_CN//P07.300x001",
        "LAB//5001//mmol/L",
        "LAB//5002//UNK",
        "CHART//1001//bpm",
        "FLUID_INPUT//ml",
        "OUTPUT//2001//ml",
        "MEDICATION//START//Vancomycin Injection//mg",
        "MEDICATION//START//Vitamin K1 Injection//UNK",
        "MEDICATION//END//Vancomycin Injection",
        "MICROBIOLOGY//SPECIMEN//B1",
        "MICROBIOLOGY//ORGANISM//O1",
        "MICROBIOLOGY//SUSCEPTIBILITY//A1//S",
        "EXAM//Ultrasound//Echocardiography",
        "SYMPTOM//cough//-",
        "SURGERY//START//VSD repair",
        "ANESTHESIA//END//General anesthesia",
        "SURGERY_VITAL//SV1",
    ]:
        assert code in got, f"{code} not extracted; got {sorted(got)}"
    # A culture with no growth has no organism or susceptibility rows to emit.
    assert data.filter(pl.col("code").str.starts_with("MICROBIOLOGY//") & (pl.col("subject_id") == 3))[
        "code"
    ].to_list() == ["MICROBIOLOGY//SPECIMEN//B1"]


def test_values_and_times(data: pl.DataFrame):
    labs = data.filter(pl.col("code") == "LAB//5001//mmol/L").sort("time")
    assert labs["numeric_value"].to_list() == pytest.approx([4.1, 5.9])
    text_lab = data.filter(pl.col("code") == "LAB//5002//UNK")
    assert text_lab["text_value"].to_list() == ["Negative"]
    exam = data.filter(pl.col("code") == "EXAM//Ultrasound//Echocardiography")
    assert [str(t) for t in exam["time"].to_list()] == ["2101-05-07 18:00:00"]
    dx = data.filter(pl.col("code") == "DIAGNOSIS//ICD10_CN//Q21.000")
    assert [str(t) for t in dx["time"].to_list()] == ["2101-05-09 09:09:09"]


def test_code_metadata(codes: pl.DataFrame):
    by_code = {row["code"]: row for row in codes.to_dicts()}

    assert by_code["LAB//5001//mmol/L"]["description"] == "Potassium"
    assert by_code["LAB//5001//mmol/L"]["parent_codes"] == ["LOINC/2823-3"]
    # "600" is not a well-formed LOINC code, so it yields no parent.
    assert not by_code["LAB//5002//UNK"]["parent_codes"]

    assert by_code["DIAGNOSIS//ICD10_CN//Q21.000"]["description"] == "Ventricular septal defect"
    assert by_code["DIAGNOSIS//ICD10_CN//Q21.000"]["parent_codes"] == ["ICD10/Q21.0"]
    assert by_code["DIAGNOSIS//ICD10_CN//Q21.000"]["title_cn"] == ["室间隔缺损"]
    # P07.30 is a PIC extension of WHO ICD-10, so it yields no parent.
    assert not by_code["DIAGNOSIS//ICD10_CN//P07.300x001"]["parent_codes"]
    assert by_code["ADMISSION_DIAGNOSIS//ICD10_CN//J18.900"]["parent_codes"] == ["ICD10/J18.9"]

    assert by_code["CHART//1001//bpm"]["description"] == "Heart Rate"
    assert by_code["SURGERY_VITAL//SV1"]["unit"] == ["bpm"]
    assert by_code["MICROBIOLOGY//ORGANISM//O1"]["description"] == "Staphylococcus aureus"
    assert by_code["MICROBIOLOGY//ORGANISM//O1"]["org_name_cn"] == ["金黄色葡萄球菌"]
    assert by_code["MICROBIOLOGY//SUSCEPTIBILITY//A1//S"]["description"] == "Vancomycin"
    assert by_code["MEDICATION//START//Vancomycin Injection//mg"]["drug_name_cn"] == ["万古霉素"]
    assert by_code["SYMPTOM//fever//+"]["symptom_name_cn"] == ["发热"]

    # ICD-O-3 morphology codes get an ICDO3 parent.
    assert by_code["DIAGNOSIS//ICD10_CN//M80000/3"]["parent_codes"] == ["ICDO3/8000/3"]


def test_code_descriptions(codes: pl.DataFrame):
    by_code = dict(zip(codes["code"], codes["description"], strict=True))

    # Every code is described except the MEDS-reserved literal codes, to which MEDS-Extract 0.7
    # attaches no metadata.
    assert sorted(code for code, desc in by_code.items() if desc is None) == ["MEDS_BIRTH", "MEDS_DEATH"]

    assert by_code["GENDER//F"] == "Patient gender: female (PIC PATIENTS.GENDER)"
    assert by_code["ICU_ADMISSION//PICU"] == (
        "ICU admission; first care unit: PICU, paediatric ICU (PIC ICUSTAYS.FIRST_CAREUNIT)"
    )
    assert by_code["HOSPITAL_DISCHARGE//General Surgery"] == (
        "Hospital discharge; discharging department: General Surgery (PIC ADMISSIONS.DISCHARGE_DEPARTMENT)"
    )
    assert by_code["MEDICATION//START//Vitamin K1 Injection//UNK"].startswith(
        "Prescription start: Vitamin K1 Injection; dose unit UNK ("
    )
    assert by_code["SYMPTOM//cough//-"].startswith("Symptom cough, absent (-), extracted by NLP")
    assert by_code["SURGERY//START//VSD repair"].startswith("Surgery start: VSD repair (")
    # A specimen ID listed in `D_ITEMS` keeps exactly its label; an unlisted one gets a fallback.
    assert by_code["MICROBIOLOGY//SPECIMEN//B1"] == "Blood"
    assert by_code["MICROBIOLOGY//SPECIMEN//S900"].startswith(
        "Microbiology specimen, PIC item S900, which has"
    )


def test_codes_parquet_is_valid_meds_code_metadata(cohort: Path):
    CodeMetadataSchema.validate(pq.read_table(cohort / "metadata" / "codes.parquet"))
