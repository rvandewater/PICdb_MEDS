"""`sumeds_rules.yaml` is a well-formed `sumeds-rules/0.1` file whose rules match this ETL's codes.

suMEDS is not a dependency of this package, so the checks below mirror the rules format (strict keys,
compiled patterns, required named groups) and apply each rule to synthetic codes built from the code
templates in `event_configs.yaml`, the way suMEDS does (`re.search`, ordered `re.sub` normalization,
`mode: prefix` truncation).
"""

import fnmatch
import re
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "PICdb_MEDS"
RULES = yaml.safe_load((PACKAGE / "sumeds_rules.yaml").read_text())
CONFIG = yaml.safe_load((PACKAGE / "event_configs.yaml").read_text())

KEYS = {
    "ontology": {"id", "pattern", "vocabulary", "normalize", "validate"},
    "crosswalk": {
        "id",
        "pattern",
        "table",
        "key_column",
        "code_column",
        "vocabulary",
        "where",
        "normalize",
        "validate",
    },
    "hierarchy": {
        "id",
        "pattern",
        "group",
        "mode",
        "separator",
        "ignore",
        "nearest_only",
        "from_ontology",
        "rules",
    },
}
REQUIRED_GROUP = {"ontology": "code", "crosswalk": "key"}
GROUP_REFERENCE = re.compile(r"\\(?:g<([^>]*)>|(\d{1,2}))")


def code(table: str, event: str, **values: str) -> str:
    """Build a code from the event's `f"..."` code template, substituting synthetic column values."""
    template = CONFIG[table][event]["code"].strip()
    assert template.startswith('f"') and template.endswith('"'), template
    return re.sub(r"\{\$(\w+)[^}]*\}", lambda m: values[m.group(1)], template[2:-1])


def diagnosis(value: str) -> str:
    return code("V1.1.0/DIAGNOSES_ICD", "diagnosis", ICD10_CODE_CN=value)


def admission_diagnosis(value: str) -> str:
    return code("V1.1.0/ADMISSIONS", "admission_diagnosis", ICD10_CODE_CN=value)


def rules(kind: str) -> dict[str, dict]:
    return {rule["id"]: rule for rule in RULES.get(kind) or []}


def resolve(rule: dict, value: str) -> str | None:
    """The vocabulary code an ontology rule assigns to `value`, as suMEDS computes it."""
    match = re.search(rule["pattern"], value)
    if match is None:
        return None
    result = match.group("code")
    for step in rule.get("normalize") or []:
        result = re.sub(step["pattern"], step["replace"], result)
    return result


def prefix_candidates(rule: dict, value: str) -> list[str]:
    """Possible same-dataset parents of `value` under a `mode: prefix` rule, nearest first."""
    match = re.search(rule["pattern"], value)
    if match is None:
        return []
    start, end = match.span(rule["group"])
    ignore = rule.get("ignore", "")
    stem, stems = match.group(rule["group"]).rstrip(ignore), []
    while len(stem) > 1:
        stem = stem[:-1].rstrip(ignore)
        if stem:
            stems.append(stem)
    return [value[:start] + s + value[end:] for s in stems]


def test_rules_file_is_well_formed():
    assert RULES["schema"] == "sumeds-rules/0.1"
    assert set(RULES) <= {"schema", "ontology", "crosswalk", "hierarchy"}
    ids = [rule["id"] for kind in KEYS for rule in RULES.get(kind) or []]
    assert len(ids) == len(set(ids)), "rule ids must be unique"
    for kind, allowed in KEYS.items():
        for rule in RULES.get(kind) or []:
            assert set(rule) <= allowed, (rule["id"], set(rule) - allowed)
            if kind == "hierarchy" and rule.get("from_ontology"):
                continue
            pattern = re.compile(rule["pattern"])
            assert rule["pattern"].startswith("^") and rule["pattern"].endswith("$"), rule["id"]
            if kind in REQUIRED_GROUP:
                assert REQUIRED_GROUP[kind] in pattern.groupindex, rule["id"]
                assert rule.get("validate", "pack") in {"pack", "athena", "none"}, rule["id"]
                assert "/" not in rule["vocabulary"], rule["id"]
                for step in rule.get("normalize") or []:
                    assert set(step) == {"pattern", "replace"}, rule["id"]
                    step_pattern = re.compile(step["pattern"])
                    for name, number in GROUP_REFERENCE.findall(step["replace"]):
                        ref = name or number
                        known = (
                            int(ref) <= step_pattern.groups
                            if ref.isdigit()
                            else ref in step_pattern.groupindex
                        )
                        assert known, (rule["id"], ref)
            else:
                assert rule["group"] in pattern.groupindex, rule["id"]
                assert rule.get("mode", "separator" if "separator" in rule else None) == "prefix", rule["id"]


def test_rules_file_is_package_data():
    """`importlib.resources.files("PICdb_MEDS")` finds the rules file in an installed wheel too."""
    package_data = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]
    assert any(fnmatch.fnmatch("sumeds_rules.yaml", glob) for glob in package_data["PICdb_MEDS"])


@pytest.mark.parametrize("build", [diagnosis, admission_diagnosis])
def test_icdo3_rule_tags_morphology_codes_only(build):
    rule = rules("ontology")["picdb-icdo3-morphology"]
    assert rule["vocabulary"] == "ICDO3"
    assert rule["validate"] == "none"
    # Chinese-edition morphology codes: the fifth digit is dropped, the behaviour digit kept.
    assert resolve(rule, build("M80000/3")) == "8000/3"
    assert resolve(rule, build("M81403/3")) == "8140/3"
    assert resolve(rule, build("M95900/1")) == "9590/1"
    # ICD-10 codes, including chapter M codes and dagger-marked codes, are not morphology codes.
    for value in ("J18.900", "P07.300x001", "M79.300", "M80.000", "A18.000+", "M8000/3"):
        assert resolve(rule, build(value)) is None, value


@pytest.mark.parametrize(
    ("rule_id", "build", "other"),
    [
        ("picdb-diagnosis-prefix", diagnosis, admission_diagnosis),
        ("picdb-admission-diagnosis-prefix", admission_diagnosis, diagnosis),
    ],
)
def test_prefix_hierarchy_stays_within_the_family(rule_id, build, other):
    rule = rules("hierarchy")[rule_id]
    # Codes such as J18.900 fall under J18.90, J18.9 and J18 (the dot is skipped, never a trailing dot).
    assert prefix_candidates(rule, build("J18.900"))[:4] == [
        build("J18.90"),
        build("J18.9"),
        build("J18"),
        build("J1"),
    ]
    assert prefix_candidates(rule, build("P07.300x001"))[3] == build("P07.300")
    # A dagger-marked code falls under the unmarked code.
    assert prefix_candidates(rule, build("A18.000+"))[0] == build("A18.000")
    # Morphology codes are not truncated, so M80000/3 cannot fall under ICD-10 M80.
    assert prefix_candidates(rule, build("M80000/3")) == []
    # The rule never proposes a parent from the other diagnosis family.
    assert prefix_candidates(rule, other("J18.900")) == []
