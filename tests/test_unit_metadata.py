"""`picdb_unit_metadata`: unit siblings in codes.parquet get their stem as a parent and a row.

Synthetic codes.parquet files only; the full spec runs it in `test_run_with_enrichment.py`.
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from PICdb_MEDS.unit_metadata import (
    add_unit_sibling_parents,
    add_unit_sibling_rows,
    large_string_unit,
    link_unit_siblings_file,
)


def _write(path: Path, table: pa.Table) -> Path:
    pq.write_table(table, path)
    return path


def test_string_unit_is_written_as_large_string(tmp_path: Path):
    codes = pa.table(
        {
            "code": ["ONE", "NULL"],
            "description": ["a", "b"],
            "unit": pa.array(["mg/dL", None], pa.string()),
        }
    )
    path = _write(tmp_path / "codes.parquet", codes)
    link_unit_siblings_file(path)
    out = pq.read_table(path)
    assert out.schema.field("unit").type == pa.large_string()
    assert out.column("unit").to_pylist() == ["mg/dL", None]
    # Every other column is untouched.
    assert out.drop_columns(["unit"]).equals(codes.drop_columns(["unit"]))
    # A second run does not rewrite the file.
    before = path.read_bytes()
    link_unit_siblings_file(path)
    assert path.read_bytes() == before


def test_units_stay_as_recorded():
    codes = pa.table({"code": ["A", "B"], "unit": ["Geen", "None"]})
    assert large_string_unit(codes).column("unit").to_pylist() == ["Geen", "None"]


def test_large_string_unit_passes_through(tmp_path: Path):
    codes = pa.table({"code": ["A", "B"], "unit": pa.array(["mg", None], pa.large_string())})
    path = _write(tmp_path / "codes.parquet", codes)
    before = path.read_bytes()
    link_unit_siblings_file(path)
    assert path.read_bytes() == before
    assert large_string_unit(codes) is codes


def test_no_unit_column_is_a_no_op(tmp_path: Path):
    codes = pa.table({"code": ["A"], "description": ["a"]})
    path = _write(tmp_path / "codes.parquet", codes)
    before = path.read_bytes()
    link_unit_siblings_file(path)
    assert path.read_bytes() == before


def test_writes_to_another_file(tmp_path: Path):
    src = _write(tmp_path / "in.parquet", pa.table({"code": ["A"], "unit": ["mg"]}))
    dst = tmp_path / "out" / "codes.parquet"
    link_unit_siblings_file(src, dst)
    assert pq.read_table(dst).column("unit").to_pylist() == ["mg"]


def test_other_types_are_rejected():
    with pytest.raises(TypeError, match="must be a string"):
        large_string_unit(pa.table({"code": ["A"], "unit": [1]}))
    # A list, as MEDS-Extract < 0.9 wrote it.
    with pytest.raises(TypeError, match="must be a string"):
        large_string_unit(pa.table({"code": ["A"], "unit": [["mg"]]}))


SIBLINGS = pa.table(
    {
        "code": [
            "LAB//hb//g/dL",  # siblings: same item, unit as the last component
            "LAB//hb//mmol/L",
            "VITAL//hr///min",  # a lone unit-suffixed code: no sibling, no parent
            "LAB//crp//mg",  # last component is not its unit
            "LAB//crp//g",  # ... nor here, so these two are not siblings
            "WEIGHT",
        ],
        "unit": ["g/dL", "mmol/L", "/min", "mg/L", "g/L", "kg"],
        "parent_codes": pa.array([["LOINC//718-7"], None, None, None, None, None], pa.list_(pa.string())),
    }
)


def test_unit_siblings_get_their_stem_as_parent(tmp_path: Path):
    path = _write(tmp_path / "codes.parquet", SIBLINGS)
    link_unit_siblings_file(path)
    out = pq.read_table(path)
    # The SIBLINGS table is not sorted by code, so the stem row is appended.
    assert out.column("code").to_pylist() == [
        *SIBLINGS.column("code").to_pylist(),
        "LAB//hb",
    ]
    assert out.schema.field("parent_codes").type == pa.list_(pa.string())
    assert out.column("parent_codes").to_pylist() == [
        ["LOINC//718-7", "LAB//hb"],  # existing vocabulary parents stay first
        ["LAB//hb"],
        None,
        None,
        None,
        None,
        None,  # the stem row: no parent shared by both siblings
    ]
    # Running it again adds nothing.
    link_unit_siblings_file(path)
    assert pq.read_table(path).equals(out)


SORTED_SIBLINGS = pa.table(
    {
        "code": [
            "LAB//hb//g/dL",
            "LAB//hb//mmol/L",
            "MED//x//mcg",
            "MED//x//mg",
            "OTHER",
        ],
        "description": [
            "Hemoglobin",
            "Hemoglobin",
            "Drug x in mcg",
            "Drug x in mg",
            "o",
        ],
        "unit": ["g/dL", "mmol/L", "mcg", "mg", None],
        "parent_codes": [
            ["LOINC//718-7", "LOINC//0000-0"],
            ["LOINC//718-7"],
            ["ATC//X01"],
            ["ATC//X01"],
            None,
        ],
        "extra": [1, 2, 3, 4, 5],
    }
)


def test_stem_rows_are_added_with_what_the_siblings_share():
    out = add_unit_sibling_rows(add_unit_sibling_parents(SORTED_SIBLINGS))
    assert out.schema == SORTED_SIBLINGS.schema
    rows = {row["code"]: row for row in out.to_pylist()}
    assert out.column("code").to_pylist() == sorted(rows)  # sorted input stays sorted
    assert rows["LAB//hb"] == {
        "code": "LAB//hb",
        "description": "Hemoglobin",  # shared by both siblings
        "unit": None,
        "parent_codes": ["LOINC//718-7"],  # the parents both share, never the stem
        "extra": None,
    }
    assert rows["MED//x"]["description"] is None  # the siblings' descriptions differ
    assert rows["MED//x"]["parent_codes"] == ["ATC//X01"]
    assert out.num_rows == SORTED_SIBLINGS.num_rows + 2
    # A second run adds nothing.
    assert add_unit_sibling_rows(add_unit_sibling_parents(out)) is out


def test_an_existing_stem_row_is_left_alone():
    existing = pa.table(
        {
            "code": ["LAB//hb", "LAB//hb//g/dL", "LAB//hb//mmol/L"],
            "description": ["own", "Hemoglobin", "Hemoglobin"],
            "unit": [None, "g/dL", "mmol/L"],
        }
    )
    out = add_unit_sibling_rows(existing)
    assert out is existing


def test_parent_codes_is_added_when_missing():
    out = add_unit_sibling_parents(SIBLINGS.drop_columns(["parent_codes"]))
    assert out.schema.field("parent_codes").type == pa.list_(pa.string())
    assert out.column("parent_codes").to_pylist()[:3] == [
        ["LAB//hb"],
        ["LAB//hb"],
        None,
    ]


def test_no_siblings_leaves_parent_codes_alone():
    codes = SIBLINGS.slice(2)
    assert add_unit_sibling_parents(codes) is codes
    no_parents = codes.drop_columns(["parent_codes"])
    assert add_unit_sibling_parents(no_parents) is no_parents
