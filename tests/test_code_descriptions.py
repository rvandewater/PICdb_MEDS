"""Every code the event config emits declares a description, and parents name OMOP vocabularies.

These checks read only `event_configs.yaml`; `e2e_synthetic_test.py` checks the descriptions the ETL
actually writes.
"""

import re
from pathlib import Path

import yaml

CONFIG_FP = Path(__file__).parents[1] / "src" / "PICdb_MEDS" / "event_configs.yaml"
# MEDS-reserved literal codes. MEDS-Extract 0.7 attaches no metadata to a code without components.
MEDS_LITERALS = {"MEDS_BIRTH", "MEDS_DEATH"}
# OMOP `vocabulary_id`s that `parent_codes` may point into: codes PIC's own dictionaries carry. Other
# vocabularies (ICD-O-3 morphology) are tagged by suMEDS through `sumeds_rules.yaml`.
PARENT_VOCABULARIES = {"ICD10", "LOINC"}
COLUMN = re.compile(r"\$(\w+)")


def _events():
    cfg = yaml.safe_load(CONFIG_FP.read_text())
    for table, body in cfg.items():
        if table in ("etl", "_defaults", "sources"):
            continue
        for name, event in body.items():
            if name != "_table":
                yield f"{table}/{name}", body.get("_table", {}), event


def test_every_event_declares_exactly_one_description():
    """Two description sources for one code would be concatenated by MEDS-Extract."""
    for block, _table_cfg, event in _events():
        if str(event["code"]) in MEDS_LITERALS:
            assert "_metadata" not in event, block
            continue
        sources = [prefix for prefix, meta in event.get("_metadata", {}).items() if "description" in meta]
        assert len(sources) == 1, f"{block}: description sources {sources}"


def test_self_descriptions_depend_only_on_the_code():
    """A `_self` template may read the code's components, and columns joined in on a component.

    Anything else could vary between rows of one code and give that code several descriptions.
    """
    for block, table_cfg, event in _events():
        template = event.get("_metadata", {}).get("_self", {}).get("description")
        if template is None:
            continue
        allowed = set(COLUMN.findall(str(event["code"])))
        for join in table_cfg.get("join", {}).values():
            left_on = join.get("left_on", join.get("key"))
            left_on = {left_on} if isinstance(left_on, str) else set(left_on)
            if left_on <= allowed and isinstance(join["cols"], list):
                allowed |= set(join["cols"])
        extra = set(COLUMN.findall(template)) - allowed
        assert not extra, f"{block}: description reads non-code columns {sorted(extra)}"


def test_parent_codes_use_omop_vocabulary_prefixes():
    n_blocks = 0
    for block, _table_cfg, event in _events():
        for meta in event.get("_metadata", {}).values():
            if "parent_codes" in meta:
                n_blocks += 1
                vocabularies = set(re.findall(r'f"(\w+)/', meta["parent_codes"]))
                assert vocabularies, block
                assert vocabularies <= PARENT_VOCABULARIES, f"{block}: {sorted(vocabularies)}"
    assert n_blocks == 3
