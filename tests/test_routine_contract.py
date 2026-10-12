import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from kairos.cli import cmd_check_decisions

ROOT = Path(__file__).resolve().parent.parent


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


EXAMPLE = ROOT / "tests" / "fixtures" / "decisions_example.json"
HEAVY_MODULES = ("pandas", "penaltyblog", "numpy", "requests")


def test_check_decisions_needs_no_heavy_dependency():
    # La routine n'installe pas les dépendances du paquet : la vérification doit s'en passer.
    script = (
        "import json, sys\n"
        "from datetime import date\n"
        "from kairos.cli import cmd_check_decisions\n"
        f"rc = cmd_check_decisions({str(EXAMPLE)!r}, date(2026, 10, 17))\n"
        f"loaded = [m for m in {HEAVY_MODULES!r} if m in sys.modules]\n"
        "print(json.dumps({'rc': rc, 'loaded': loaded}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout.splitlines()[-1])
    assert report["rc"] == 0, proc.stdout
    assert report["loaded"] == [], f"modules lourds chargés : {report['loaded']}"


def test_routine_pulls_before_push_and_stays_on_main():
    text = (ROOT / "ROUTINE.md").read_text()
    assert "git pull --rebase origin main" in text
    assert "jamais sur une branche `claude/`" in text
