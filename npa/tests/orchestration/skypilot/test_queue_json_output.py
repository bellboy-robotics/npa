"""Protect exact queue reconciliation from native diagnostics and ambiguous JSON."""

import json
import subprocess

import pytest

from npa.orchestration.skypilot.json_output import (
    is_verified_empty_queue_result,
    queue_rows_from_output,
    verified_structured_queue_rows,
)
from npa.orchestration.skypilot.workflow import lookup_managed_job


WARNING = (
    'The following keys (["allowed_clouds"]) have different values in the client '
    "SkyPilot config with the server and will be ignored. Remove these keys to "
    "disable this warning. If you want to specify it, please modify it on server "
    "side or contact your administrator.\n"
)
ROWS = [{"job_id": 1, "job_name": "exact-run", "task_id": 0, "status": "STARTING"}]


@pytest.mark.parametrize(
    "warning", [WARNING, "\x1b[33m" + WARNING.rstrip() + "\x1b[0m\n"]
)
@pytest.mark.parametrize("payload", [ROWS, {"jobs": ROWS}])
def test_native_config_warning_preserves_queue_rows(warning, payload):
    result = subprocess.CompletedProcess([], 0, warning + json.dumps(payload), "")
    assert queue_rows_from_output(result.stdout) == ROWS
    assert verified_structured_queue_rows(result) == ROWS
    assert not is_verified_empty_queue_result(result)


def test_exact_job_reconciliation_with_native_warning(monkeypatch, tmp_path):
    sky = tmp_path / "sky"
    sky.write_text("#!/bin/sh\n")
    sky.chmod(0o755)
    monkeypatch.setattr(
        "npa.orchestration.skypilot.workflow.ensure_skypilot_version",
        lambda value: value,
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, WARNING + json.dumps(ROWS), ""
        ),
    )
    evidence = lookup_managed_job("exact-run", sky_bin=sky)
    assert evidence.outcome == "found"
    assert evidence.job_id == "1"
    assert evidence.status == "STARTING"
    assert evidence.task_rows[0]["status"] == "STARTING"


@pytest.mark.parametrize(
    "stdout,stderr",
    [
        (WARNING + "[]", ""),
        ("[]", WARNING),
        (WARNING + "No in-progress managed jobs.\n", ""),
    ],
)
def test_warning_alone_does_not_contradict_proven_empty_queue(stdout, stderr):
    assert is_verified_empty_queue_result(
        subprocess.CompletedProcess([], 0, stdout, stderr)
    )


@pytest.mark.parametrize(
    "prefix,suffix",
    [
        (WARNING + "[]\n", ""),
        (WARNING, "\n[]"),
        ('Unknown warning ["allowed_clouds"]\n', ""),
        (WARNING.replace('["allowed_clouds"]', '[{"job_id": 2}]'), ""),
        (WARNING.replace("ignored.", "ignored. []"), ""),
        ("", "\n["),
    ],
)
def test_config_warning_exception_preserves_ambiguity_rejection(prefix, suffix):
    output = prefix + json.dumps(ROWS) + suffix
    assert queue_rows_from_output(output) is None
    assert (
        verified_structured_queue_rows(subprocess.CompletedProcess([], 0, output, ""))
        is None
    )


@pytest.mark.parametrize("diagnostic", ["Error: access denied", "job_id 2 RUNNING"])
def test_warning_does_not_hide_conflicting_diagnostics(diagnostic):
    result = subprocess.CompletedProcess([], 0, WARNING + "[]\n" + diagnostic, "")
    assert verified_structured_queue_rows(result) is None
    assert not is_verified_empty_queue_result(result)
