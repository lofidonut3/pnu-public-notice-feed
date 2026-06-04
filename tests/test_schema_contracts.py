import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).resolve().parents[1]


def test_json_schemas_are_valid():
    for schema_path in (ROOT / "schema").glob("*.schema.json"):
        schema = _load_json(schema_path)
        jsonschema.Draft202012Validator.check_schema(schema)


def test_generated_outputs_match_schemas():
    cases = [
        ("public/feed.json", "schema/feed.schema.json"),
        ("public/status.json", "schema/status.schema.json"),
        ("public/changes.json", "schema/changes.schema.json"),
        ("public/archive/index.json", "schema/archive-index.schema.json"),
        ("sources.json", "schema/sources.schema.json"),
    ]

    for instance_path, schema_path in cases:
        instance = _load_json(ROOT / instance_path)
        schema = _load_json(ROOT / schema_path)
        jsonschema.Draft202012Validator(schema).validate(instance)

    _validate_archive_files("public/archive/notices", "schema/archive-notices.schema.json")
    _validate_archive_files("public/archive/events", "schema/archive-events.schema.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_archive_files(instance_dir: str, schema_path: str) -> None:
    schema = _load_json(ROOT / schema_path)
    for instance_path in (ROOT / instance_dir).glob("*.json"):
        instance = _load_json(instance_path)
        jsonschema.Draft202012Validator(schema).validate(instance)
