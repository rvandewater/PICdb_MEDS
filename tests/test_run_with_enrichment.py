"""`meds-extract-run spec=PICdb` runs the ETL and then suMEDS enrichment, offline.

The spec declares suMEDS's `sumeds_enrich` post-stage with the rules this package registers in
suMEDS's `sumeds.rules` entry-point group under the same name, so the one command also enriches the
output. It runs over the synthetic release of `e2e_synthetic_test.py`, next to a plain build of the
same release (`skip_stages=[sumeds_enrich]`), so the enriched `metadata/codes.parquet` can be
compared with the one it replaced.

The ontology source is a tiny pack repository in suMEDS's `sumeds-ontologies/0.1` layout, built here
with a made-up title for the one LOINC code of the synthetic labs, so the test reads nothing over
the network and does not depend on the published packs. It reaches the stage as a pipeline override,
`"overrides=['++stage_cfg.ontology_source=DIR']"`. There is no WHO ICD-10 or ICD-O-3 pack (the
published packs have none either), so the `ICD10/` parents the ETL writes stay unnamed. Another
run points at an empty pack source, through `SUMEDS_ONTOLOGY_SOURCE`, which is how a site without
internet fails: the ETL still succeeds, unenriched, and `suMEDS-enrich` completes it later.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
from e2e_synthetic_test import SPEC, run_command, write_raw_release
from meds import CodeMetadataSchema, DatasetMetadataSchema
from polars.testing import assert_frame_equal

# vocabulary -> release -> code -> parent (None for a root). LOINC terms have no parents.
PACKS = {"LOINC": ("synthetic", {"2823-3": None})}


def title(vocabulary: str, code: str) -> str:
    return f"Synthetic {vocabulary} title {code}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def names(value) -> dict[str, str]:
    """A names map as a dict: Polars 2 reads `map<string, string>` as one, Polars 1 as key/value structs."""
    if value is None or isinstance(value, dict):
        return value or {}
    return {entry["key"]: entry["value"] for entry in value}


@pytest.fixture(scope="module")
def ontology_source(tmp_path_factory) -> Path:
    """A local `sumeds-ontologies/0.1` repository holding the synthetic LOINC pack."""
    root = tmp_path_factory.mktemp("ontologies")
    columns = ["code", "description", "parent"]
    vocabularies = {}
    for vocabulary, (release, rows) in PACKS.items():
        directory = root / vocabulary / release
        directory.mkdir(parents=True)
        by_shard: dict[str, list[list[str]]] = {}
        for code, parent in rows.items():
            by_shard.setdefault(code[:1], []).append([code, title(vocabulary, code), parent or ""])
        shards = {}
        for key, shard_rows in by_shard.items():
            buffer = io.StringIO()
            csv.writer(buffer, lineterminator="\n").writerows([columns, *shard_rows])
            data = buffer.getvalue().encode()
            (directory / f"{key}.csv").write_bytes(data)
            shards[key] = {
                "file": f"{key}.csv",
                "rows": len(shard_rows),
                "bytes": len(data),
                "sha256": _sha256(data),
            }
        manifest = {
            "schema": "sumeds-ontology-pack/0.1",
            "vocabulary": vocabulary,
            "release": release,
            "columns": columns,
            "fields": {"code": "code", "description": "description", "parent": "parent"},
            "shard_key_length": 1,
            "rows": len(rows),
            "bytes": sum(s["bytes"] for s in shards.values()),
            "shards": shards,
        }
        manifest_bytes = json.dumps(manifest).encode()
        (directory / "manifest.json").write_bytes(manifest_bytes)
        vocabularies[vocabulary] = {
            "manifest": f"{vocabulary}/{release}/manifest.json",
            "sha256": _sha256(manifest_bytes),
            "release": release,
            "rows": manifest["rows"],
            "bytes": manifest["bytes"],
        }
    index = {"schema": "sumeds-ontologies/0.1", "vocabularies": vocabularies}
    (root / "index.json").write_text(json.dumps(index))
    return root


@pytest.fixture(scope="module")
def raw(tmp_path_factory) -> Path:
    raw = tmp_path_factory.mktemp("picdb_raw")
    write_raw_release(raw)
    return raw


def etl_args(output_dir: Path, raw: Path) -> list[str]:
    return [f"spec={SPEC}", f"output_dir={output_dir}", "do_download=false", f"input_dir={raw}"]


def stage_options(**options: object) -> str:
    """Set `sumeds_enrich` options for one run.

    The override reaches every stage of the pipeline, so it adds the key (`++`) rather than setting one that
    only this stage declares.
    """
    values = ",".join(f"'++stage_cfg.{name}={value}'" for name, value in options.items())
    return f"overrides=[{values}]"


@pytest.fixture(scope="module")
def outputs(tmp_path_factory, raw: Path, ontology_source: Path) -> tuple[Path, Path]:
    """The plain and the enriched build of the synthetic release."""
    root = tmp_path_factory.mktemp("picdb_enriched")
    plain, enriched = root / "plain", root / "enriched"
    run_command("meds-extract-run", *etl_args(plain, raw), "skip_stages=[sumeds_enrich]")
    run_command("meds-extract-run", *etl_args(enriched, raw), stage_options(ontology_source=ontology_source))
    return plain, enriched


@pytest.fixture(scope="module")
def plain_codes(outputs) -> dict[str, dict]:
    return {row["code"]: row for row in pl.read_parquet(outputs[0] / "metadata" / "codes.parquet").to_dicts()}


@pytest.fixture(scope="module")
def enriched_codes(outputs) -> dict[str, dict]:
    return {row["code"]: row for row in pl.read_parquet(outputs[1] / "metadata" / "codes.parquet").to_dicts()}


def _dataset(output_dir: Path) -> dict:
    """`dataset.json`, checked to still be valid MEDS dataset metadata."""
    dataset = json.loads((output_dir / "metadata" / "dataset.json").read_text())
    DatasetMetadataSchema.validate(dataset)
    return dataset


def test_skip_stages_runs_the_plain_etl(outputs):
    """`skip_stages=[sumeds_enrich]` leaves the stage out: it never runs, and nothing is recorded."""
    plain = outputs[0]
    assert "sumeds_enrichment" not in _dataset(plain)
    assert not (plain / ".logs" / "sumeds_enrich.done").exists()
    assert "sumeds_enrich" not in (plain / ".meds_extract_run" / "pipeline.yaml").read_text()


def test_codes_parquet_is_replaced_by_valid_meds_metadata(outputs):
    plain, enriched = (out / "metadata" for out in outputs)
    CodeMetadataSchema.validate(pq.read_table(enriched / "codes.parquet"))
    # suMEDS stages the enriched table beside `codes.parquet`; nothing of it may be left behind.
    assert sorted(fp.name for fp in enriched.iterdir()) == sorted(fp.name for fp in plain.iterdir())


def test_data_matches_the_plain_etl(outputs):
    plain, enriched = (pl.read_parquet(out / "data" / "**" / "*.parquet") for out in outputs)
    assert_frame_equal(enriched.sort(enriched.columns), plain.sort(plain.columns))


def test_enrichment_keeps_what_the_etl_wrote(plain_codes, enriched_codes):
    """Every value the ETL wrote is kept, and `parent_codes` only gains entries at its end."""
    assert enriched_codes.keys() == plain_codes.keys()
    for code, before in plain_codes.items():
        after = enriched_codes[code]
        parents = before["parent_codes"] or []
        assert (after["parent_codes"] or [])[: len(parents)] == parents, code
        for column, value in before.items():
            if column != "parent_codes" and value is not None:
                assert after[column] == value, (code, column)


def test_enrichment_adds_the_rules_parents_and_pack_names(plain_codes, enriched_codes):
    # The prefix rule links an extended code to the shorter code of the same family, after the
    # parent the ETL wrote.
    extended = enriched_codes["DIAGNOSIS//ICD10_CN//J18.900x001"]
    assert extended["parent_codes"] == ["ICD10/J18.9", "DIAGNOSIS//ICD10_CN//J18.900"]
    assert extended["description"] == "Synthetic pneumonia subtype"
    # The same code in the other family has no such parent: the families are linked separately.
    assert enriched_codes["ADMISSION_DIAGNOSIS//ICD10_CN//J18.900"]["parent_codes"] == ["ICD10/J18.9"]

    # A Chinese-edition ICD-O-3 morphology code is tagged with its OMOP histology code.
    morphology = enriched_codes["DIAGNOSIS//ICD10_CN//M80000/3"]
    assert morphology["parent_codes"] == ["ICDO3//8000/3"]
    assert morphology["description"] == "Synthetic neoplasm entry"

    # The LOINC parent the ETL wrote is found in the pack: it keeps its spelling and place and gets
    # its LOINC name; the lab keeps the label PIC gives it.
    lab = enriched_codes["LAB//5001//mmol/L"]
    assert lab["parent_codes"] == ["LOINC/2823-3"]
    assert names(lab["parent_names"]) == {"LOINC/2823-3": title("LOINC", "2823-3")}
    assert (lab["description"], lab["vocabulary_id"], lab["concept_code"]) == ("Potassium", "LOINC", "2823-3")

    # Nothing else gains a parent.
    gained = {
        code
        for code, row in enriched_codes.items()
        if len(row["parent_codes"] or []) > len(plain_codes[code]["parent_codes"] or [])
    }
    assert gained == {"DIAGNOSIS//ICD10_CN//J18.900x001", "DIAGNOSIS//ICD10_CN//M80000/3"}


def test_dataset_json_records_the_enrichment(outputs, plain_codes, enriched_codes):
    """`metadata/dataset.json` says the build is enriched, with which rules, and what it added."""
    plain, dataset = (_dataset(out) for out in outputs)
    assert "sumeds_enrichment" not in plain
    assert set(dataset) == {*plain, "sumeds_enrichment"}
    record = dataset["sumeds_enrichment"]
    assert record["enriched"] is True
    assert record["rules"] == SPEC
    assert record["ontology_source"] == "local"
    assert record["athena"] is False

    def filled(rows: dict[str, dict], column: str) -> int:
        return sum(row.get(column) is not None for row in rows.values())

    assert record["coverage"] == {
        "codes": len(enriched_codes),
        "described": [filled(plain_codes, "description"), filled(enriched_codes, "description")],
        "with_parent_codes": [filled(plain_codes, "parent_codes"), filled(enriched_codes, "parent_codes")],
    }


def test_enrichment_soft_fails_and_suMEDS_enrich_completes_it_later(
    tmp_path: Path, raw: Path, ontology_source: Path, outputs
):
    """With no usable pack source (as on a site without internet), the ETL still succeeds: `codes.parquet` is
    left exactly as the plain ETL writes it, `dataset.json` records that it is not enriched and how to retry,
    and `suMEDS-enrich <OUT>` then gives the same table as a run that enriched directly.

    Running the ETL again does not retry: the stage succeeded, so MEDS-Extract skips it.
    """
    plain, enriched = outputs
    empty_source = tmp_path / "no_packs"
    empty_source.mkdir()
    output_dir = tmp_path / "MEDS_cohort"
    args = etl_args(output_dir, raw)
    run_command("meds-extract-run", *args, env={"SUMEDS_ONTOLOGY_SOURCE": str(empty_source)})

    # The stage's warning goes to the pipeline log, not to the console.
    log = (output_dir / ".logs" / "pipeline.log").read_text()
    assert "enrichment failed" in log
    assert f"suMEDS-enrich {output_dir}" in log

    codes = output_dir / "metadata" / "codes.parquet"
    assert codes.read_bytes() == (plain / "metadata" / "codes.parquet").read_bytes()
    record = _dataset(output_dir)["sumeds_enrichment"]
    assert record["enriched"] is False
    assert record["rules"] == SPEC
    assert record["error"].startswith("OntologyPackError")
    assert record["retry"] == "suMEDS-enrich <MEDS_ROOT>"

    run_command("meds-extract-run", *args, stage_options(ontology_source=ontology_source))
    assert _dataset(output_dir)["sumeds_enrichment"] == record

    run_command("suMEDS-enrich", str(output_dir), "--ontology-source", str(ontology_source))
    record = _dataset(output_dir)["sumeds_enrichment"]
    direct = _dataset(enriched)["sumeds_enrichment"]
    assert record["enriched"] is True
    assert {k: v for k, v in record.items() if k != "enriched_at"} == {
        k: v for k, v in direct.items() if k != "enriched_at"
    }
    assert pq.read_table(codes).equals(pq.read_table(enriched / "metadata" / "codes.parquet"))


def test_strict_makes_a_failed_enrichment_fail_the_run(tmp_path: Path, raw: Path):
    empty_source = tmp_path / "no_packs"
    empty_source.mkdir()
    output_dir = tmp_path / "MEDS_cohort"
    options = stage_options(ontology_source=empty_source, strict="true")
    run_command("meds-extract-run", *etl_args(output_dir, raw), options, ok=False)
    assert not (output_dir / ".logs" / "sumeds_enrich.done").exists()
    assert "sumeds_enrichment" not in _dataset(output_dir)
