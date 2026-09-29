import sys
from pathlib import Path

import json

import pytest


# Ensure src is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from geodiff_models import Change, GeodiffEntryDict, GeodiffFile, validate_examples_from_strings  # noqa: E402 (because nee to import after path insert)
# JSON example fixtures moved to tests/conftest.py as pytest fixtures:
# - geodiff_delete_json
# - geodiff_update_json
# - geodiff_insert_json


def test_parse_delete(geodiff_delete_json):
    g = GeodiffFile.from_json_text(geodiff_delete_json)
    assert len(g.geodiff) == 1
    entry = g.geodiff[0]
    assert entry.type == "delete"
    assert entry.table == "simple"
    assert len(entry.changes) == 4
    assert entry.changes[0].column == 0
    assert entry.changes[0].old == 2


def test_parse_update(geodiff_update_json):
    g = GeodiffFile.from_json_text(geodiff_update_json)
    entry = g.geodiff[0]
    assert entry.type == "update"
    # second change has both old and new
    change1 = entry.changes[1]
    assert change1.old == "R1AAAeYQAAABAQAAAPBDGq/kSde/+HS2Feb94T8="
    assert change1.new == "R1AAAeYQAAABAQAAAMp+uos0te2/hISLbYZyzj8="
    # third change numeric update
    change2 = entry.changes[2]
    assert change2.old == 2
    assert change2.new == 9999


def test_parse_insert(geodiff_insert_json):
    g = GeodiffFile.from_json_text(geodiff_insert_json)
    entry = g.geodiff[0]
    assert entry.type == "insert"
    assert entry.changes[0].new == -4
    assert entry.changes[2].new == 401  # road_id (column 2)


def test_write_entry_type_schemas_and_validate(tmp_path):
    # write schemas to tmp_path
    GeodiffFile.write_entry_type_schemas(tmp_path)
    # ensure files exist
    for t in ("delete", "update", "insert"):
        p = tmp_path / f"geodiff_entry_{t}_schema.json"
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        # top-level title includes the type
        assert data.get("title") == "GeodiffEntry"


def test_validate_examples_from_strings(geodiff_delete_json, geodiff_update_json, geodiff_insert_json):
    results = validate_examples_from_strings(
        {"delete": geodiff_delete_json, "update": geodiff_update_json, "insert": geodiff_insert_json}
    )
    assert all(results.values())


def test_roundtrip_to_json(geodiff_insert_json):
    g = GeodiffFile.from_json_text(geodiff_insert_json)
    s = g.to_json()
    g2 = GeodiffFile.from_json_text(s)
    assert g.model_dump() == g2.model_dump()


def test_from_path_and_from_json_text(tmp_path, geodiff_insert_json):
    p = tmp_path / "example.json"
    p.write_text(geodiff_insert_json, encoding="utf-8")
    g = GeodiffFile.from_path(p)
    assert isinstance(g, GeodiffFile)
    assert g.geodiff[0].type == "insert"


def test_write_json_schema(tmp_path):
    out = tmp_path / "geodiff_file_schema.json"
    GeodiffFile.write_json_schema(out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "geodiff" in data.get("properties", {})


def test_json_schema_for_entry_type():
    schema = GeodiffFile.json_schema_for_entry_type("update")
    assert schema.get("title") == "GeodiffEntry"
    props = schema.get("properties", {})
    assert props.get("type", {}).get("const") == "update"


def test_validate_examples_invalid():
    results = validate_examples_from_strings({"bad": "{not: json"})
    assert results.get("bad") is False


def test_entry_dict_from_entry(geodiff_insert_json, geodiff_schema_json):
    entry = GeodiffFile.from_json_text(geodiff_insert_json).geodiff[0]

    d = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))

    assert set(d.to_dict()) == {"PROGRESSIVO_ACCESSO", "geom", "ODONIMO", "PROGRESSIVO_NAZIONALE", "CIVICO"}
    assert d.to_dict()["PROGRESSIVO_ACCESSO"] == Change(column=0, new=-4)
    assert d.to_dict()["ODONIMO"].new == "my new point A"
    assert d.to_dict()["PROGRESSIVO_NAZIONALE"].new == 401


def test_entry_dict_keeps_old_and_new(geodiff_real_coord_update_json, geodiff_schema_json):
    entry = GeodiffFile.from_json_text(geodiff_real_coord_update_json).geodiff[0]

    geom = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json)).to_dict()["geom"]

    assert geom.old == "R1AAAQAAAAABAQAAAObiXKWtwitAXt3+bojzREA="
    assert geom.new == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="


def test_entry_dict_uses_schema_positions(geodiff_real_schema_json):
    entry = GeodiffFile.from_json_text(
        json.dumps({"geodiff": [{"table": "t", "type": "insert", "changes": [{"column": 10, "new": "VIA ROMA"}]}]})
    ).geodiff[0]

    d = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_real_schema_json))

    assert d.to_dict() == {"ODONIMO": Change(column=10, new="VIA ROMA")}


def test_entry_dict_empty_changes(geodiff_schema_json):
    entry = GeodiffFile.from_json_text(
        json.dumps({"geodiff": [{"table": "t", "type": "delete", "changes": []}]})
    ).geodiff[0]

    assert GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json)).to_dict() == {}


def test_entry_dict_unknown_column_raises(geodiff_schema_json):
    entry = GeodiffFile.from_json_text(
        json.dumps({"geodiff": [{"table": "t", "type": "insert", "changes": [{"column": 99, "new": 1}]}]})
    ).geodiff[0]

    with pytest.raises(ValueError, match="Column 99"):
        GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))


def test_entry_dict_serializes_as_plain_dict(geodiff_insert_json, geodiff_schema_json):
    entry = GeodiffFile.from_json_text(geodiff_insert_json).geodiff[0]

    d = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))

    dumped = d.model_dump()
    assert dumped["table"] == "simple"
    assert dumped["type"] == "insert"
    assert dumped["changes"]["PROGRESSIVO_ACCESSO"] == {"column": 0, "old": None, "new": -4}


def test_entry_dict_keeps_table_and_type(geodiff_delete_json, geodiff_schema_json):
    entry = GeodiffFile.from_json_text(geodiff_delete_json).geodiff[0]

    d = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))

    assert d.table == entry.table
    assert d.type == "delete"
    assert len(d.changes) == len(entry.changes)


def test_entry_dict_value(geodiff_real_coord_update_json, geodiff_schema_json):
    entry = GeodiffFile.from_json_text(geodiff_real_coord_update_json).geodiff[0]

    d = GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))

    assert d.value("PROGRESSIVO_ACCESSO") == 28671616  # only old
    assert d.value("geom") == "R1AAAQAAAAABAQAAAAAAAICcwitAAAAAwInzREA="  # new wins over old
    assert d.value("ODONIMO") is None  # not in the entry


def test_entry_dict_rejects_unknown_type(geodiff_schema_json):
    from types import SimpleNamespace

    entry = SimpleNamespace(table="t", type="upsert", changes=[])

    with pytest.raises(ValueError):
        GeodiffEntryDict.from_entry(entry, json.loads(geodiff_schema_json))
