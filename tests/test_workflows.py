import re
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"
ALLOWED = {"schedule", "push", "workflow_dispatch"}


def load(name):
    data = yaml.safe_load((WF / name).read_text())
    return data, data.get("on", data.get(True))


def test_state_workflows_share_concurrency_and_safe_triggers():
    for name in ("prepare.yml", "apply.yml", "closing.yml"):
        data, on = load(name)
        assert set(on) <= ALLOWED, name
        assert data["concurrency"]["group"] == "kairos-state"
        assert data["concurrency"]["cancel-in-progress"] is False


def test_no_pull_request_target_anywhere():
    for f in WF.glob("*.yml"):
        assert "pull_request_target" not in f.read_text()


def test_apply_triggers_on_decisions_and_deploys_pages():
    data, on = load("apply.yml")
    assert on["push"]["paths"] == ["decisions/**"]
    assert "deploy" in data["jobs"]
    assert data["permissions"]["pages"] == "write"


EXPECTED_FILES = {"tests.yml", "prepare.yml", "apply.yml", "closing.yml", "check.yml"}
STATE_JOBS = {"prepare.yml": "prepare", "apply.yml": "apply", "closing.yml": "closing"}
CLI_COMMAND = {
    "prepare.yml": "prepare",
    "apply.yml": "apply",
    "closing.yml": "closing",
    "check.yml": "check-api",
}
SECRETS = {
    "tests.yml": set(),
    "prepare.yml": {"ODDS_API_KEY"},
    "apply.yml": {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
    "closing.yml": {"ODDS_API_KEY"},
    "check.yml": {"ODDS_API_KEY"},
}


def test_expected_workflow_files_exist():
    assert {f.name for f in WF.glob("*.yml")} == EXPECTED_FILES


def test_every_workflow_has_allowed_triggers_and_pushes_only_to_main():
    for name in sorted(EXPECTED_FILES):
        _, on = load(name)
        assert set(on) <= ALLOWED, name
        if "push" in on:
            assert on["push"]["branches"] == ["main"], name


def test_each_secret_is_used_only_by_the_workflows_that_need_it():
    for name, expected in SECRETS.items():
        used = set(re.findall(r"secrets\.([A-Z_]+)", (WF / name).read_text()))
        assert used == expected, name


def test_each_state_workflow_runs_its_own_cli_command():
    for name, command in CLI_COMMAND.items():
        data, _ = load(name)
        called = [
            cmd
            for job in data["jobs"].values()
            for step in job["steps"]
            for cmd in re.findall(r"python -m kairos\.cli (\S+)", step.get("run", ""))
        ]
        assert called == [command], name


def test_state_commit_runs_after_install_and_cli():
    for name, job in STATE_JOBS.items():
        data, _ = load(name)
        steps = data["jobs"][job]["steps"]
        install = next(i for i, s in enumerate(steps) if s.get("run", "").startswith("pip install"))
        cli = next(i for i, s in enumerate(steps) if "python -m kairos.cli" in s.get("run", ""))
        commit = next(i for i, s in enumerate(steps) if s.get("name") == "Commit")
        assert install < cli < commit, name
