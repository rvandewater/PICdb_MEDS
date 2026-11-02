"""`sumeds_rules.yaml` loads in suMEDS and its rules match this ETL's codes.

suMEDS validates the rules file itself (`sumeds.load_rules`) and resolves codes with the rule objects its
enrichment uses, so these tests only state what PIC's codes must resolve to. The codes are synthetic,
built from the code templates in `event_configs.yaml`.
"""

import fnmatch
import json
import re
import tomllib
from pathlib import Path

import polars as pl
import pytest
import yaml
from sumeds import EnrichmentConfig, OntologyRules, enrich_metadata, load_rules
from sumeds.ontology import INDEX_SCHEMA

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "PICdb_MEDS"
RULES_FP = PACKAGE / "sumeds_rules.yaml"
CONFIG = yaml.safe_load((PACKAGE / "event_configs.yaml").read_text())

# Diagnosis codes for the hierarchy rules, written into both diagnosis families.
HIERARCHY_EXAMPLES = [
    "J18.900",
    "J18.9",
    "J18",
    "P07.300x001",
    "P07.300",
    "A18.000+",
    "A18.000",
    "M80000/3",
    "M80",
]
# The parent suMEDS adds to each example code from the other example codes of the same family. No other
# code gets one: the nearest shorter code must exist, and M80000/3 is not truncated, so it cannot fall
# under ICD-10 M80.
EXPECTED_PARENTS = {
    "J18.900": "J18.9",
    "J18.9": "J18",
    "P07.300x001": "P07.300",
    # A dagger-marked code falls under the unmarked code.
    "A18.000+": "A18.000",
}


def code(table: str, event: str, **values: str) -> str:
    """Build a code from the event's `f"..."` code template, substituting synthetic column values."""
    template = CONFIG[table][event]["code"].strip()
    assert template.startswith('f"') and template.endswith('"'), template
    return re.sub(r"\{\$(\w+)[^}]*\}", lambda m: values[m.group(1)], template[2:-1])


def diagnosis(value: str) -> str:
    return code("V1.1.0/DIAGNOSES_ICD", "diagnosis", ICD10_CODE_CN=value)


def admission_diagnosis(value: str) -> str:
    return code("V1.1.0/ADMISSIONS", "admission_diagnosis", ICD10_CODE_CN=value)


@pytest.fixture(scope="module")
def rules() -> dict:
    loaded = load_rules(RULES_FP)
    return {rule.id: rule for rule in (*loaded.vocabulary_rules, *loaded.hierarchy)}


@pytest.fixture(scope="module")
def ontology_source(tmp_path_factory) -> str:
    """An empty local ontology source, so the enrichment below reads no ontology data."""
    source = tmp_path_factory.mktemp("ontologies")
    (source / "index.json").write_text(json.dumps({"schema": INDEX_SCHEMA, "vocabularies": {}}))
    return str(source)


def test_rules_load_in_sumeds():
    """`sumeds.load_rules` rejects any malformed rule; each pattern must also span a whole code."""
    loaded = load_rules(RULES_FP)
    for rule in (*loaded.vocabulary_rules, *loaded.hierarchy):
        if rule.pattern is not None:
            assert rule.pattern.pattern.startswith("^"), rule.id
            assert rule.pattern.pattern.endswith("$"), rule.id


def test_rules_file_is_package_data():
    """`importlib.resources.files("PICdb_MEDS")` finds the rules file in an installed wheel too."""
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    assert any(fnmatch.fnmatch("sumeds_rules.yaml", glob) for glob in package_data["PICdb_MEDS"])


@pytest.mark.parametrize("build", [diagnosis, admission_diagnosis])
def test_icdo3_rule_tags_morphology_codes_only(rules, build):
    rule = rules["picdb-icdo3-morphology"]
    assert rule.vocabulary == "ICDO3"
    assert rule.validate == "none"
    # Chinese-edition morphology codes: the fifth digit is dropped, the behaviour digit kept.
    assert rule.resolve(build("M80000/3")) == "8000/3"
    assert rule.resolve(build("M81403/3")) == "8140/3"
    assert rule.resolve(build("M95900/1")) == "9590/1"
    # ICD-10 codes, including chapter M codes and dagger-marked codes, are not morphology codes.
    for value in ("J18.900", "P07.300x001", "M79.300", "M80.000", "A18.000+", "M8000/3"):
        assert rule.resolve(build(value)) is None, value


@pytest.mark.parametrize(
    ("rule_id", "build"),
    [
        ("picdb-diagnosis-prefix", diagnosis),
        ("picdb-admission-diagnosis-prefix", admission_diagnosis),
    ],
)
def test_prefix_hierarchy_stays_within_the_family(rules, ontology_source, rule_id, build):
    """Run suMEDS's own enrichment, offline, with one hierarchy rule over both diagnosis families."""
    rule = rules[rule_id]
    # Codes such as J18.900 fall under J18.90, J18.9 and J18 (the dot is skipped, never a trailing dot).
    assert rule.candidates(build("J18.900"))[:3] == [build("J18.90"), build("J18.9"), build("J18")]

    examples = [family(value) for family in (diagnosis, admission_diagnosis) for value in HIERARCHY_EXAMPLES]
    enriched = enrich_metadata(
        pl.LazyFrame({"code": examples}),
        EnrichmentConfig(rules=OntologyRules(hierarchy=(rule,)), ontology_source=ontology_source),
    ).collect()
    parents = {
        row["code"]: row["parent_codes"]
        for row in enriched.select("code", "parent_codes").to_dicts()
        if row["parent_codes"]
    }
    # Only codes of the rule's own family get a parent, and only from that family.
    assert parents == {build(child): [build(parent)] for child, parent in EXPECTED_PARENTS.items()}
