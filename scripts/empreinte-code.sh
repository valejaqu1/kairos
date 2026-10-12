#!/usr/bin/env bash
# Affiche l'empreinte du code qui tourne avec les clés (workflows « Verrou du code »).
# Colle-la dans Settings > Secrets and variables > Actions > Variables > KAIROS_CODE_FINGERPRINT.
# Elle porte sur le dernier commit (HEAD) : lance-la sur la branche qui part sur main.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git ls-tree -r HEAD -- kairos site_template pyproject.toml .github ROUTINE.md .claude data/team_aliases.json | sha256sum | cut -d' ' -f1
