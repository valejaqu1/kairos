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
# L'empreinte couvre tout le dépôt suivi par git SAUF les dossiers de données que les workflows et la routine écrivent.

import hashlib
import os
import shutil
import subprocess
import sys

import pytest

SCRIPT = WF.parent.parent / "scripts" / "empreinte-code.sh"
DATA_DIRS = ["state", "decisions", "journal", "memory", "site", "data/odds", "data/model"]
FINGERPRINT_COMMAND = (r"""git ls-tree -r --full-tree HEAD | awk -F'\t' '$2 !~ /^(state|decisions|journal|memory|site|data\/odds|data\/model)\//'"""
                       r""" | sha256sum | cut -d' ' -f1""")
LOCKED_JOBS = {"prepare.yml": "prepare", "apply.yml": "apply", "closing.yml": "closing", "check.yml": "check"}
LOCK_NAME = "Verrou du code"
# Un fichier suivi dans chaque dossier ou à la racine : tous verrouillés, sauf ceux des dossiers de données.
LOCKED_FILES = ["kairos/x.txt", "tests/x.txt", "docs/x.md", "scripts/x.sh", "site_template/x.txt", ".github/x.txt", ".claude/x.txt",
                "pyproject.toml", "ROUTINE.md", "README.md", ".gitignore", "data/team_aliases.json"]
DATA_FILES = ["state/kairos.json", "decisions/2026-10-17.json", "journal/2026-10-17.md", "memory/lessons.md", "site/index.html",
              "site/data.json", "data/odds/2026-10-17.json", "data/model/2026-10-17.json"]
PAGE = "<!doctype html><title>Kairos</title>\n"  # le gabarit ; apply publie site/index.html en le copiant tel quel


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


def test_locked_workflows_restore_no_dependency_cache():
    # setup-python restaure ~/.cache/pip APRÈS le verrou, dans un espace partagé avec tests.yml (sans verrou) :
    # ce que « pip install -e . » consommerait échapperait à l'empreinte. Les workflows à clés n'ont donc aucun cache.
    for name in LOCKED_JOBS:
        steps, _ = lock_step(name)
        (setup,) = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python")]
        assert not [key for key in setup.get("with", {}) if key.startswith("cache")], name
        assert not [s for s in steps if str(s.get("uses", "")).startswith("actions/cache")], name


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
    assert "Code non validé : site/ ne doit contenir que index.html et data.json, trouvé :" in run
    assert "if [ -e site/index.html ] && ! cmp -s site/index.html site_template/index.html; then\n" in run
    assert 'echo "Page non conforme au gabarit"\n' in run
    assert run.count("exit 1") == 3 and run.rstrip().endswith("exit 1\nfi")


def test_fingerprint_command_is_identical_in_the_workflows_and_the_script():
    script = SCRIPT.read_text(encoding="utf-8")
    assert script.count(FINGERPRINT_COMMAND) == 1
    for name in LOCKED_JOBS:
        assert lock_step(name)[1]["run"].count(FINGERPRINT_COMMAND) == 1, name


def test_the_excluded_set_is_exactly_the_data_the_workflows_and_the_routine_write():
    pattern = re.compile(r"awk -F'\\t' '\$2 !~ /\^\((?P<dirs>[^)]+)\)\\//'")
    texts = [lock_step(name)[1]["run"] for name in LOCKED_JOBS] + [SCRIPT.read_text(encoding="utf-8")]
    for text in texts:
        (match,) = pattern.finditer(text)
        assert match.group("dirs").replace("\\/", "/").split("|") == DATA_DIRS


def test_script_is_an_executable_bash_script_with_strict_mode():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n") and "\nset -euo pipefail\n" in text
    assert os.access(SCRIPT, os.X_OK)


def git(repo, *args):
    config = ["-c", "user.email=t@example.org", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "-C", str(repo), *config, *args], check=True, capture_output=True)


def locked_repo(tmp_path):
    repo = tmp_path / "repo"
    for rel in [*LOCKED_FILES, *DATA_FILES]:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel, encoding="utf-8")
    shutil.copy2(SCRIPT, repo / "scripts" / SCRIPT.name)
    for rel in ("site_template/index.html", "site/index.html"):  # la page publiée est celle du gabarit
        (repo / rel).write_text(PAGE, encoding="utf-8")
    git(repo.parent, "init", "-q", str(repo))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def independent_fingerprint(repo):
    # Calculé en Python (re, hashlib), pas avec le pipeline awk | sha256sum qu'on teste.
    listing = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--full-tree", "HEAD"], check=True, capture_output=True, text=True).stdout
    excluded = re.compile("^(" + "|".join(DATA_DIRS) + ")/")
    kept = [line for line in listing.splitlines(keepends=True) if not excluded.match(line.split("\t", 1)[1])]
    return hashlib.sha256("".join(kept).encode()).hexdigest()


def run_lock(repo, value, workflow="prepare.yml"):
    env = {**os.environ, "KAIROS_CODE_FINGERPRINT": value}
    return subprocess.run(["bash", "-eo", "pipefail", "-c", lock_step(workflow)[1]["run"]], cwd=repo, env=env, capture_output=True, text=True)


def commit_file(repo, rel, content="changé"):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"change {rel}")


def lock_codes(repo, value, workflows=("prepare.yml",)):
    """Code de sortie de l'étape de verrou. Les boucles n'exécutent que prepare.yml (les quatre étapes sont identiques,
    un autre test le vérifie) ; `workflows=ALL` les exécute toutes aux points de contrôle."""
    return {workflow: run_lock(repo, value, workflow).returncode for workflow in workflows}


ALL = tuple(sorted(LOCKED_JOBS))


def passes(repo, value, workflows=("prepare.yml",)):
    return set(lock_codes(repo, value, workflows).values()) == {0}


def fails(repo, value, workflows=("prepare.yml",)):
    return set(lock_codes(repo, value, workflows).values()) == {1}


needs_sha256sum = pytest.mark.skipif(shutil.which("sha256sum") is None, reason="sha256sum absent")
EVERY_WORKFLOW = pytest.mark.parametrize("workflow", sorted(LOCKED_JOBS))


@needs_sha256sum
@EVERY_WORKFLOW
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
def test_lock_covers_every_tracked_file_except_the_data_dirs(tmp_path):
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)
    for rel in DATA_FILES:
        if rel == "site/index.html":
            continue  # hors empreinte aussi, mais son contenu doit être celui du gabarit : test dédié plus bas
        commit_file(repo, rel)
        assert passes(repo, good), rel
    assert passes(repo, good, ALL)
    for rel in LOCKED_FILES:
        commit_file(repo, rel)
        assert fails(repo, good), rel
        good = independent_fingerprint(repo)  # la nouvelle empreinte validée par l'utilisateur
        assert passes(repo, good), rel
    commit_file(repo, "kairos/x.txt", "encore")
    assert fails(repo, good, ALL)


@needs_sha256sum
def test_a_new_root_file_is_locked_but_a_new_data_file_is_not(tmp_path):
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)
    for rel in ("state/new.json", "decisions/new.json", "journal/new.md", "memory/new.md", "data/odds/new.json", "data/model/new.json",
                "state/deep/er/new.json"):
        commit_file(repo, rel)
    assert passes(repo, good, ALL)
    # fichiers hors exclusion : une ressemblance de nom ne suffit pas (ancrage au début et frontière du dossier)
    for rel in ("requests.py", "json.py", "sitecustomize.py", "setup.py", "conftest.py", "data/other.json", "data/odds.py",
                "data/modelling/x.json", "statefile", "kairos/state/x.py", "docs/memory/x.md", "tests/journal/x.md"):
        commit_file(repo, rel)
        assert fails(repo, good), rel
        assert independent_fingerprint(repo) != good, rel
        good = independent_fingerprint(repo)
        assert passes(repo, good), rel
    commit_file(repo, "requests.py", "encore")
    assert fails(repo, good, ALL)


@needs_sha256sum
def test_lock_refuses_anything_in_site_but_index_and_data_json(tmp_path):
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)  # site/ est hors empreinte : seul le contrôle de contenu peut réagir
    for rel in ("site/evil.js", "site/sub/page.html", "site/index.htm", "site/data.json.bak", "site/.nojekyll", "site/CNAME"):
        commit_file(repo, rel)
        assert independent_fingerprint(repo) == good, rel
        done = run_lock(repo, good)
        assert done.returncode == 1, rel
        assert done.stdout.startswith("Code non validé : site/ ne doit contenir que index.html et data.json, trouvé : ") and rel in done.stdout
        git(repo, "rm", "-q", "-f", rel)
        git(repo, "commit", "-q", "-m", f"retire {rel}")
        assert passes(repo, good), rel
    git(repo, "rm", "-q", "-f", "site/index.html", "site/data.json")
    git(repo, "commit", "-q", "-m", "site vide")
    assert passes(repo, good, ALL)  # site/ absent : rien d'inattendu
    commit_file(repo, "site/data.json")
    assert passes(repo, good, ALL)
    commit_file(repo, "site/evil.js")
    assert fails(repo, good, ALL)


@needs_sha256sum
def test_lock_refuses_a_published_page_that_differs_from_the_template(tmp_path):
    # Après l'annonce de la mort, apply n'écrit rien et le déploiement publie le site/ de main tel quel.
    repo = locked_repo(tmp_path)
    good = independent_fingerprint(repo)
    assert passes(repo, good, ALL)  # page conforme au gabarit
    refused = "Page non conforme au gabarit\n"
    for content in ("<script>fetch('https://evil.example')</script>\n", PAGE.rstrip("\n"), PAGE + "\n", ""):
        commit_file(repo, "site/index.html", content)
        assert independent_fingerprint(repo) == good  # site/ est hors empreinte : seul le contrôle de la page peut réagir
        done = run_lock(repo, good)
        assert (done.returncode, done.stdout) == (1, refused), repr(content)
        assert fails(repo, good, ALL)
        wrong = run_lock(repo, "0" * 64)  # l'empreinte reste contrôlée en premier
        assert wrong.stdout.startswith("Code non validé : empreinte ")
        commit_file(repo, "site/index.html", PAGE)
        assert passes(repo, good), repr(content)
    # l'ordre des contrôles : le nom des fichiers de site/ est vérifié avant le contenu de la page
    commit_file(repo, "site/index.html", "autre")
    commit_file(repo, "site/evil.js")
    done = run_lock(repo, good)
    assert done.returncode == 1 and done.stdout.startswith("Code non validé : site/ ne doit contenir que ")
    git(repo, "rm", "-q", "-f", "site/evil.js")
    commit_file(repo, "site/index.html", PAGE)
    assert passes(repo, good, ALL)
    # absente : avant le premier apply, site/ est vide
    git(repo, "rm", "-q", "-f", "site/index.html")
    git(repo, "commit", "-q", "-m", "site vide")
    assert passes(repo, good, ALL)
    commit_file(repo, "site/data.json")
    assert passes(repo, good, ALL)
    # la référence est le gabarit du dépôt, pas un contenu figé : quand le gabarit change, l'ancienne page est refusée
    commit_file(repo, "site_template/index.html", "<!doctype html><title>Kairos 2</title>\n")
    good = independent_fingerprint(repo)
    assert passes(repo, good, ALL)  # toujours pas de page
    commit_file(repo, "site/index.html", PAGE)
    done = run_lock(repo, good)
    assert (done.returncode, done.stdout) == (1, refused)
    commit_file(repo, "site/index.html", "<!doctype html><title>Kairos 2</title>\n")
    assert passes(repo, good, ALL)


@needs_sha256sum
def test_script_prints_the_fingerprint_the_lock_expects(tmp_path):
    repo = locked_repo(tmp_path)
    done = subprocess.run([str(repo / "scripts" / SCRIPT.name)], cwd=tmp_path, capture_output=True, text=True)  # lancé de n'importe où
    assert done.returncode == 0 and done.stdout == independent_fingerprint(repo) + "\n" and done.stderr == ""


def test_every_cli_step_runs_with_the_working_directory_off_the_import_path():
    for name in LOCKED_JOBS:
        data, _ = load(name)
        cli_steps = [s for job in data["jobs"].values() for s in job["steps"] if "python -m kairos.cli" in s.get("run", "")]
        assert len(cli_steps) == 1, name
        assert cli_steps[0]["env"]["PYTHONSAFEPATH"] == "1", name


def test_pythonsafepath_keeps_a_root_module_from_shadowing_the_standard_library(tmp_path):
    # Un fichier posé à la racine du dépôt (json.py, requests.py…) serait importé avant la bibliothèque, car « python -m »
    # place le répertoire courant en tête de sys.path. Avec PYTHONSAFEPATH=1, le paquet reste importable (installation éditable).
    (tmp_path / "json.py").write_text("raise SystemExit('json.py du dépôt importé')\n", encoding="utf-8")
    probe = [sys.executable, "-c", "import kairos"]
    safe = {**os.environ, "PYTHONSAFEPATH": "1"}
    if subprocess.run(probe, cwd=tmp_path, env=safe, capture_output=True).returncode != 0:
        pytest.skip("kairos n'est pas installé en mode éditable dans cet environnement")
    command = [sys.executable, "-m", "kairos.cli", "check-decisions", str(tmp_path / "absent.json")]
    unsafe = subprocess.run(command, cwd=tmp_path, env={k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}, capture_output=True, text=True)
    assert unsafe.returncode != 0 and "json.py du dépôt importé" in unsafe.stderr
    done = subprocess.run(command, cwd=tmp_path, env=safe, capture_output=True, text=True)
    assert done.returncode == 1 and done.stdout.startswith("illisible : ") and "json.py" not in done.stderr


def test_secret_ref_catches_names_case_and_bare_contexts():
    names = lambda text: [m.group("dot") or m.group("key") for m in SECRET_REF.finditer(text)]
    assert names("${{ secrets.ODDS_API_KEY }}") == ["ODDS_API_KEY"]
    assert names("${{ SECRETS.odds_api_key }} ${{ Secrets['TOKEN'] }}") == ["odds_api_key", "TOKEN"]
    assert names('${{ secrets["A"] }}') == ["A"]
    assert names("${{ toJSON(secrets) }}") == [None]
    assert names("${{ toJSON(SECRETS) }}") == [None]
    assert names("${{ secrets[format('{0}', 'A')] }}") == [None]
    assert names("${{ vars.KAIROS_CODE_FINGERPRINT }} ${{ github.token }}") == []
