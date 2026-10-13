#!/usr/bin/env bash
# Affiche l'empreinte du code qui tourne avec les clés (étape « Verrou du code » des workflows).
# Elle couvre tout le dépôt suivi par git SAUF les dossiers de données que les workflows et la routine écrivent :
# state/, decisions/, journal/, memory/, site/, data/odds/ et data/model/.
# git entoure de guillemets les chemins non ASCII ("memory/le\303\247ons.md") : le guillemet initial de l'exclusion est facultatif.
# Colle-la dans Settings > Secrets and variables > Actions > Variables > KAIROS_CODE_FINGERPRINT.
# Elle porte sur le dernier commit (HEAD) : lance-la sur la branche qui part sur main.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
git ls-tree -r --full-tree HEAD | awk -F'\t' '$2 !~ /^"?(state|decisions|journal|memory|site|data\/odds|data\/model)\//' | sha256sum | cut -d' ' -f1
