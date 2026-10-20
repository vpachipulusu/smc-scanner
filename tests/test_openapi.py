"""The committed OpenAPI schema (the frontend client's input) must match the running API."""

import json
from pathlib import Path

from smc_scanner.openapi_export import DEFAULT_OUTPUT, export_schema, is_current, main, schema_text


def test_committed_schema_is_current() -> None:
    assert DEFAULT_OUTPUT.is_file(), "run: uv run python -m smc_scanner.openapi_export"
    assert is_current(), "nextjs-frontend/openapi.json is stale; re-run the export"


def test_operation_ids_are_plain_function_names() -> None:
    schema = json.loads(schema_text())
    operation_ids = {
        operation["operationId"] for path in schema["paths"].values() for operation in path.values()
    }
    assert operation_ids == {
        "health",
        "config",
        "scan",
        "analyse",
        "list_analyses",
        "get_analysis",
    }


def test_error_bodies_are_documented_with_the_envelope() -> None:
    schema = json.loads(schema_text())
    scan = schema["paths"]["/scan"]["get"]["responses"]
    assert set(scan) >= {"200", "401", "422", "503"}
    error_schema = schema["components"]["schemas"]["ErrorResponse"]
    assert set(error_schema["properties"]) == {"success", "error"}


def test_analyses_endpoints_document_their_errors_and_limits() -> None:
    schema = json.loads(schema_text())
    paths = schema["paths"]
    assert set(paths["/analyse"]["post"]["responses"]) >= {"200", "401", "422", "502", "503"}
    assert set(paths["/analyses/{analysis_id}"]["get"]["responses"]) >= {"200", "404"}
    limit = next(p for p in paths["/analyses"]["get"]["parameters"] if p["name"] == "limit")
    assert limit["schema"]["maximum"] == 200
    models = schema["components"]["schemas"]
    assert models["AiResultOut"]["properties"]["note"]["maxLength"] > 0
    assert models["AiVerdict"]["properties"]["summary"]["maxLength"] > 0
    assert models["AnalyseRequest"]["properties"]["provider"]["anyOf"][0]["const"] == "claude"


def test_export_writes_lf_json(tmp_path: Path) -> None:
    out = export_schema(tmp_path / "nested" / "openapi.json")

    raw = out.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"}\n")
    assert json.loads(raw)["info"]["title"] == "SMC scanner"
    assert is_current(out)


def test_main_check_and_usage() -> None:
    assert main(["--bogus"]) == 2
    assert main(["--check"]) == (0 if is_current() else 1)
