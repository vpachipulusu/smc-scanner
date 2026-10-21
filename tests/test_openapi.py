"""The committed OpenAPI schema (the frontend client's input) must match the running API."""

import json
from pathlib import Path
from typing import get_args

from smc_scanner.api import Frequency
from smc_scanner.openapi_export import DEFAULT_OUTPUT, export_schema, is_current, main, schema_text
from smc_scanner.schedule.timing import FREQUENCIES


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
        "list_schedules",
        "create_schedule",
        "get_schedule",
        "update_schedule",
        "delete_schedule",
        "run_schedule_now",
        "list_schedule_logs",
        "send_telegram_test",
        "list_journal",
        "create_journal_entry",
        "journal_stats",
        "get_journal_entry",
        "update_journal_entry",
        "delete_journal_entry",
        "get_calendar",
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


def test_schedule_endpoints_document_their_errors_and_limits() -> None:
    schema = json.loads(schema_text())
    paths = schema["paths"]
    assert set(paths["/schedules"]["post"]["responses"]) >= {"201", "401", "409", "422"}
    assert set(paths["/schedules/{schedule_id}/run"]["post"]["responses"]) >= {
        "200",
        "404",
        "409",
    }
    assert set(paths["/telegram/test"]["post"]["responses"]) >= {"200", "502", "503"}
    limit = next(
        p
        for p in paths["/schedules/{schedule_id}/logs"]["get"]["parameters"]
        if p["name"] == "limit"
    )
    assert limit["schema"]["maximum"] == 100
    assert "errors" not in schema["components"]["schemas"]["RunOut"]["properties"]


def test_frequency_literal_matches_the_scheduler_frequencies() -> None:
    assert get_args(Frequency) == FREQUENCIES


def test_schedule_update_is_nullable_only_for_the_chat_id() -> None:
    props = json.loads(schema_text())["components"]["schemas"]["ScheduleUpdate"]["properties"]
    nullable = {
        name
        for name, prop in props.items()
        if "anyOf" in prop and {"type": "null"} in prop["anyOf"]
    }
    assert nullable == {"telegram_chat_id"}


def test_run_now_documents_the_failed_run_and_the_cooldown() -> None:
    schema = json.loads(schema_text())
    run = schema["paths"]["/schedules/{schedule_id}/run"]["post"]
    assert "status" in run["description"]
    assert "failed" in run["description"]
    assert "Retry-After" in run["responses"]["429"]["headers"]


def test_telegram_test_is_tagged_and_documents_422() -> None:
    post = json.loads(schema_text())["paths"]["/telegram/test"]["post"]
    assert post["tags"] == ["telegram"]
    assert set(post["responses"]) >= {"200", "422", "429", "502", "503"}
