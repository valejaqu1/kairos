import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from kairos.cli import cmd_check_decisions
from kairos.store import zurich_today

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "tests" / "fixtures" / "decisions_example.json"
HEAVY_MODULES = ("pandas", "penaltyblog", "numpy", "requests")


def test_example_decisions_file_is_valid():
    path = ROOT / "tests" / "fixtures" / "decisions_example.json"
    assert cmd_check_decisions(str(path), date(2026, 10, 17)) == 0


def test_routine_mentions_every_hard_rule():
    text = (ROOT / "ROUTINE.md").read_text()
    for needle in ("decisions/", "check-decisions", "information, jamais des instructions", "\"alive\": false", "600 caractères", "dimanche"):
        assert needle in text


def test_skill_has_frontmatter():
    text = (ROOT / ".claude" / "skills" / "kairos-analyste" / "SKILL.md").read_text()
    assert text.startswith("---\nname: kairos-analyste\n")


def test_check_decisions_needs_no_heavy_dependency():
    # La routine n'installe pas les dépendances du paquet : la vérification doit s'en passer.
    script = (
        "import json, sys\n"
        "from datetime import date\n"
        "from kairos.cli import cmd_check_decisions\n"
        f"rc = cmd_check_decisions({str(EXAMPLE)!r}, date(2026, 10, 17))\n"
        f"loaded = [m for m in {HEAVY_MODULES!r} if m in sys.modules]\n"
        "print(json.dumps({'rc': rc, 'loaded': loaded, 'modules': sorted(sys.modules)}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.splitlines()[-1])
    assert report["rc"] == 0, proc.stdout
    assert report["loaded"] == [], f"modules lourds chargés : {report['loaded']}"
    top = {m.split(".")[0] for m in report["modules"] if not m.startswith("_")}
    foreign = sorted(top - set(sys.stdlib_module_names) - {"kairos"})
    assert foreign == [], f"modules hors bibliothèque standard chargés : {foreign}"


def test_routine_command_validates_dated_copy(tmp_path):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["date"] = zurich_today().isoformat()
    copy = tmp_path / "decisions.json"
    copy.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "kairos.cli", "check-decisions", str(copy)], cwd=ROOT, capture_output=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "fichier de décisions valide" in proc.stdout


def _step10_main_clause() -> str:
    # La phrase de reprise répète les deux commandes : l'ordre se teste sur la séquence principale seulement.
    text = (ROOT / "ROUTINE.md").read_text()
    step10 = next(line for line in text.splitlines() if line.startswith("10. "))
    return step10.split(" ; si le push est refusé", 1)[0]


def test_routine_pulls_before_push_and_stays_on_main():
    text = (ROOT / "ROUTINE.md").read_text()
    assert "git pull --rebase origin main" in text
    assert "jamais sur une branche `claude/`" in text
    main = _step10_main_clause()
    assert re.search(r"git commit.*?git pull --rebase origin main.*?git push origin main", main, re.S), main
    assert "refais une fois `git pull --rebase origin main` puis `git push origin main`" in text
