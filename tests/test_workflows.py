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


SECRET_REF = re.compile(r"secrets(?:\.(?P<dot>\w+)|\[\s*['\"](?P<key>\w+)['\"]\s*\])?", re.IGNORECASE)


def string_values(node, path=()):
    """Yield (path, text) for every string value in a parsed YAML tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from string_values(value, path + (key,))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from string_values(value, path + (i,))
    elif isinstance(node, str):
        yield path, node


def is_cli_step_env(data, path):
    """True when path is one entry of the env of a step that runs the kairos CLI."""
    if len(path) != 6 or path[0] != "jobs" or path[2] != "steps" or path[4] != "env":
        return False
    step = data["jobs"][path[1]]["steps"][path[3]]
    return "python -m kairos.cli" in step.get("run", "")


def test_each_secret_is_used_only_by_the_workflows_that_need_it():
    for name, expected in SECRETS.items():
        data, _ = load(name)
        used = set()
        for _, text in string_values(data):
            names = [m.group("dot") or m.group("key") for m in SECRET_REF.finditer(text)]
            assert None not in names, (name, text)  # dynamic secrets[...] cannot be audited
            used.update(names)
        assert used == expected, name


def test_secrets_appear_only_in_the_env_of_the_cli_step():
    for name in sorted(EXPECTED_FILES):
        data, _ = load(name)
        for path, text in string_values(data):
            if SECRET_REF.search(text):
                assert is_cli_step_env(data, path), (name, path)


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


def test_state_commit_pulls_before_push():
    for name, job in STATE_JOBS.items():
        data, _ = load(name)
        steps = data["jobs"][job]["steps"]
        (commit,) = [s for s in steps if s.get("name") == "Commit"]
        script = commit["run"]
        pull = script.find("git pull --rebase")
        push = script.find("git push")
        assert pull != -1 and push != -1 and pull < push, name


CHECKOUT_JOBS = (("prepare.yml", "prepare"), ("apply.yml", "apply"), ("closing.yml", "closing"), ("apply.yml", "deploy"))


def checkout_steps(name, job):
    data, _ = load(name)
    return [s for s in data["jobs"][job]["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]


def test_state_jobs_and_deploy_check_out_the_latest_main():
    # Un run en file d'attente garde le SHA de son déclencheur : sans ref, il lirait un état périmé.
    for name, job in CHECKOUT_JOBS:
        (checkout,) = checkout_steps(name, job)
        assert (checkout.get("with") or {}).get("ref") == "main", (name, job)


def test_crons_are_offset_from_the_hour_and_the_half_hour():
    expected = {"prepare.yml": "15 8 * * *", "apply.yml": "10 13 * * *", "closing.yml": "7,37 7-21 * * *"}
    for name, cron in expected.items():
        _, on = load(name)
        assert [s["cron"] for s in on["schedule"]] == [cron], name


# --- Verrou du code : les workflows qui portent des clés refusent de tourner si le code a changé ---

import hashlib
import os
import shutil
import subprocess

import pytest

SCRIPT = WF.parent.parent / "scripts" / "empreinte-code.sh"
LOCKED_PATHS = ["kairos", "site_template", "pyproject.toml", ".github", "ROUTINE.md", ".claude", "data/team_aliases.json"]
FINGERPRINT_COMMAND = "git ls-tree -r HEAD -- " + " ".join(LOCKED_PATHS) + " | sha256sum | cut -d' ' -f1"
LOCKED_FILES = ["kairos/x.txt", "site_template/x.txt", "pyproject.toml", ".github/x.txt", "ROUTINE.md", ".claude/x.txt", "data/team_aliases.json"]
LOCKED_JOBS = {"prepare.yml": "prepare", "apply.yml": "apply", "closing.yml": "closing", "check.yml": "check"}
LOCK_NAME = "Verrou du code"


def lock_step(name):
    data, _ = load(name)
    steps = data["jobs"][LOCKED_JOBS[name]]["steps"]
    (step,) = [s for s in steps if s.get("name") == LOCK_NAME]
    return steps, step


def test_lock_step_follows_checkout_and_precedes_setup_and_install():
    for name in LOCKED_JOBS:
        steps, lock = lock_step(name)
        checkout = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/checkout"))
        setup = next(i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith("actions/setup-python"))
        install = next(i for i, s in enumerate(steps) if s.get("run", "").startswith("pip install"))
        position = steps.index(lock)
        assert position == checkout + 1 < setup < install, name


def test_lock_step_reads_the_repository_variable_and_holds_no_secret():
    for name in LOCKED_JOBS:
        _, lock = lock_step(name)
        assert lock["env"] == {"KAIROS_CODE_FINGERPRINT": "${{ vars.KAIROS_CODE_FINGERPRINT }}"}, name
        assert set(lock) == {"name", "env", "run"}, name
        for _, text in string_values(lock):
            assert not SECRET_REF.search(text), (name, text)


def test_lock_step_is_the_same_in_the_four_workflows_and_names_the_mismatch():
    runs = {name: lock_step(name)[1]["run"] for name in LOCKED_JOBS}
    assert len(set(runs.values())) == 1
    run = runs["prepare.yml"]
    assert "Code non validé : empreinte $actual, attendue ${KAIROS_CODE_FINGERPRINT:-(vide)}" in run
    assert run.rstrip().endswith("exit 1\nfi")


def test_fingerprint_command_is_identical_in_the_workflows_and_the_script():
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.count(FINGERPRINT_COMMAND) == 1
    for name in LOCKED_JOBS:
        assert lock_step(name)[1]["run"].count(FINGERPRINT_COMMAND) == 1, name


def test_locked_path_list_is_exactly_the_code_that_runs_with_the_keys():
    pattern = re.compile(r"git ls-tree -r HEAD -- (?P<paths>.+?) \| sha256sum")
    texts = [lock_step(name)[1]["run"] for name in LOCKED_JOBS] + [SCRIPT.read_text(encoding="utf-8")]
    for text in texts:
        (match,) = pattern.finditer(text)
        assert match.group("paths").split(" ") == LOCKED_PATHS


def test_script_is_an_executable_bash_script_with_strict_mode():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n") and "\nset -euo pipefail\n" in text
    assert os.access(SCRIPT, os.X_OK)


def git(repo, *args):
    config = ["-c", "user.email=t@example.org", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "-C", str(repo), *config, *args], check=True, capture_output=True)


def locked_repo(tmp_path):
    repo = tmp_path / "repo"
    for rel in [*LOCKED_FILES, "state/kairos.json", "decisions/2026-10-17.json", "data/odds/2026-10-17.json"]:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel, encoding="utf-8")
    (repo / "scripts").mkdir()
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def independent_fingerprint(repo):
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "HEAD", "--", *LOCKED_PATHS], check=True, capture_output=True).stdout
    return hashlib.sha256(listing).hexdigest()


def run_lock(repo, value, workflow="prepare.yml"):
    env = {**os.environ, "KAIROS_CODE_FINGERPRINT": value}
    return subprocess.run(["bash", "-eo", "pipefail", "-c", lock_step(workflow)[1]["run"]], cwd=repo, env=env, capture_output=True, text=True)


needs_sha256sum = pytest.mark.skipif(shutil.which("sha256sum") is None, reason="sha256sum absent")


@needs_sha256sum
@pytest.mark.parametrize("workflow", sorted(LOCKED_JOBS))
def test_lock_step_passes_only_on_the_exact_fingerprint(tmp_path, workflow):
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)
    done = run_lock(repo, good, workflow)
    assert (done.returncode, done.stdout) == (0, "")
    wrong = run_lock(repo, "0" * 64, workflow)
    assert wrong.returncode == 1 and wrong.stdout == f"Code non validé : empreinte {good}, attendue {'0' * 64}\n"
    empty = run_lock(repo, "", workflow)
    assert empty.returncode == 1 and empty.stdout == f"Code non validé : empreinte {good}, attendue (vide)\n"
    assert run_lock(repo, good.upper(), workflow).returncode == 1


@needs_sha256sum
@pytest.mark.parametrize("workflow", sorted(LOCKED_JOBS))
def test_lock_follows_locked_paths_and_ignores_state_files(tmp_path, workflow):
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)
    for rel in ("state/kairos.json", "decisions/2026-10-17.json", "data/odds/2026-10-17.json"):
        (repo / rel).write_text("changé", encoding="utf-8")
        git(repo, "commit", "-q", "-am", f"état {rel}")
        assert run_lock(repo, good, workflow).returncode == 0, rel
    for rel in LOCKED_FILES:
        (repo / rel).write_text("changé", encoding="utf-8")
        git(repo, "commit", "-q", "-am", f"code {rel}")
        assert run_lock(repo, good, workflow).returncode == 1, rel
        good = independent_fingerprint(repo)  # la nouvelle empreinte validée par l'utilisateur
        assert run_lock(repo, good, workflow).returncode == 0, rel


@needs_sha256sum
def test_script_prints_the_fingerprint_the_lock_expects(tmp_path):
    repo = locked_repo(tmp_path)
    done = subprocess.run([str(repo / "scripts" / SCRIPT.name)], cwd=tmp_path, capture_output=True, text=True)  # lancé de n'importe où
    assert done.returncode == 0 and done.stdout == independent_fingerprint(repo) + "\n" and done.stderr == ""


def test_secret_ref_catches_names_case_and_bare_contexts():
    names = lambda text: [m.group("dot") or m.group("key") for m in SECRET_REF.finditer(text)]
    assert names("${{ secrets.ODDS_API_KEY }}") == ["ODDS_API_KEY"]
    assert names("${{ SECRETS.odds_api_key }} ${{ Secrets['TOKEN'] }}") == ["odds_api_key", "TOKEN"]
    assert names('${{ secrets["A"] }}') == ["A"]
    assert names("${{ toJSON(secrets) }}") == [None]
    assert names("${{ toJSON(SECRETS) }}") == [None]
    assert names("${{ secrets[format('{0}', 'A')] }}") == [None]
    assert names("${{ vars.KAIROS_CODE_FINGERPRINT }} ${{ github.token }}") == []
