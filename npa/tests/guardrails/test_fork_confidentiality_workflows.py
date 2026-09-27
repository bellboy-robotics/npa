"""Execute the fork's CI confidentiality steps against real synthetic Git diffs."""

from pathlib import Path
import os
import shlex
import subprocess
import sys

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = ("security-regression.yml", "confidentiality-scan.yml")
SYNTHETIC_INFRA = "project: project-" + "u00" + "z" * 16


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def scan_repository(tmp_path: Path) -> tuple[Path, str]:
    """Create a Git baseline and a launcher for the real scanner.

    Args:
        tmp_path: Isolated test directory.
    Returns:
        Repository directory and baseline commit.
    Raises:
        subprocess.CalledProcessError: Git setup failed.
    """
    _git(tmp_path, "init", "--quiet")
    (tmp_path / "baseline.txt").write_text("existing-customer-fixture\n")
    _git(tmp_path, "add", "baseline.txt")
    _git(tmp_path, "commit", "--quiet", "-m", "Baseline")
    launcher = tmp_path / "npa/.venv/bin/python"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    launcher.chmod(0o755)
    (tmp_path / "runner").mkdir(mode=0o700)
    return tmp_path, _git(tmp_path, "rev-parse", "HEAD")


def _scan_script(workflow: str, baseline: str) -> str:
    path = REPO_ROOT / ".github/workflows" / workflow
    definition = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    step = next(
        step
        for step in definition["jobs"]["scan"]["steps"]
        if step["name"] in ("Reject confidential data", "Run confidentiality scans")
    )
    return (
        step["run"]
        .replace("${{ github.event_name }}", "push")
        .replace("${{ github.event.before }}", baseline)
        .replace("${{ github.event.pull_request.base.sha }}", baseline)
    )


def _run_scan(scan_repository, workflow, content="public", **settings):
    root, baseline = scan_repository
    (root / "addition.txt").write_text(content + "\n")
    _git(root, "add", "addition.txt")
    _git(root, "commit", "--quiet", "-m", "Candidate")
    environment = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT / "npa/src"),
        "GITHUB_REPOSITORY": "bellboy-robotics/npa",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_EVENT_PATH": str(root / "absent-event.json"),
        "RUNNER_TEMP": str(root / "runner"),
        "BASE_SHA": baseline,
        "MERGE_BASE": baseline,
        "CUSTOMER_DENYLIST": "",
        "INFRA_DENYLIST": "",
        "CUSTOMER_DENYLIST_FILE": str(root / "absent-customer.regex"),
        "INFRA_DENYLIST_FILE": str(root / "absent-infra.regex"),
        **settings,
    }
    return subprocess.run(
        ["bash", "-c", _scan_script(workflow, environment["BASE_SHA"])],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize(
    "content,customer,infra,expected",
    [
        ("public", "", "", 0),
        ("public", "customer-private", "", 0),
        ("customer-private", "customer-private", "", 1),
        ("public", "[", "", 2),
        ("OPERATOR-PRIVATE", "", "operator-private", 1),
        ("public", "", "[", 2),
        (SYNTHETIC_INFRA, "", "", 1),
        (SYNTHETIC_INFRA, "customer-private", "", 1),
        ("public", "existing-customer-fixture", "", 1),
    ],
)
def test_fork_confidentiality_enforces_available_policies(
    scan_repository, workflow, content, customer, infra, expected
):
    """Require real public scanning and every configured private policy.

    Args:
        scan_repository: Isolated repository and baseline commit.
        workflow: PR or main-push workflow.
        content: Synthetic addition to scan.
        customer: Optional customer regex.
        infra: Optional operator regex.
        expected: Required scanner exit status.
    Returns:
        None.
    Raises:
        AssertionError: The real workflow accepted a leak or rejected public input.
    """
    result = _run_scan(
        scan_repository,
        workflow,
        content,
        CUSTOMER_DENYLIST=customer,
        INFRA_DENYLIST=infra,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if expected == 1:
        assert "confidentiality scan failed;" in result.stderr
        assert "unresolved=0" not in result.stderr
        assert content not in result.stderr


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("repository", ["nebius/nebius-physical-ai", "other/fork", ""])
def test_other_repositories_still_require_customer_policy(
    scan_repository, workflow, repository
):
    """Keep the customer-policy exception scoped to the approved fork.

    Args:
        scan_repository: Isolated repository and baseline commit.
        workflow: PR or main-push workflow.
        repository: Repository outside the approved exception.
    Returns:
        None.
    Raises:
        AssertionError: A missing customer policy was silently accepted.
    """
    result = _run_scan(scan_repository, workflow, GITHUB_REPOSITORY=repository)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "CUSTOMER_DENYLIST is empty" in result.stderr


@pytest.mark.parametrize("workflow", WORKFLOWS)
@pytest.mark.parametrize("baseline", ["", "invalid-baseline", "0" * 40])
def test_fork_confidentiality_rejects_missing_diff_baseline(
    scan_repository, workflow, baseline
):
    """Refuse to pass without a valid range of additions to scan.

    Args:
        scan_repository: Isolated repository and baseline commit.
        workflow: PR or main-push workflow.
        baseline: Unresolvable or initial-push baseline.
    Returns:
        None.
    Raises:
        AssertionError: The workflow passed without inspecting a valid diff.
    """
    result = _run_scan(scan_repository, workflow, BASE_SHA=baseline)
    assert result.returncode != 0
