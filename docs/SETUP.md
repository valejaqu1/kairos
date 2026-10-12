# Mettre Kairos en route

Environ 20 minutes. Les étapes marquées « toi » se font à la main : Claude ne crée pas de comptes et ne manipule pas tes clés.

**Ordre à respecter.** Les clés, la variable du verrou de code et la page doivent exister **avant** que le code arrive sur `main` (étape 7). Kairos naît au premier workflow lancé après ce moment, et un workflow sans clé ou sans variable s'arrête ou travaille à vide.

## 1. Clé The Odds API (toi)

1. Crée un compte gratuit sur https://the-odds-api.com (offre gratuite : 500 crédits par mois).
2. Copie ta clé API depuis l'e-mail de bienvenue ou ton tableau de bord.

## 2. Bot Telegram (toi)

1. Dans Telegram, ouvre @BotFather, envoie `/newbot`, choisis un nom (par exemple « Kairos ») et un identifiant finissant par `bot`.
2. Copie le jeton que BotFather te donne.
3. Ouvre la conversation avec ton nouveau bot et envoie-lui « bonjour ».
4. Dans ton navigateur, ouvre `https://api.telegram.org/bot<TON_JETON>/getUpdates` et note le nombre dans `"chat":{"id": …}`. C'est ton identifiant de conversation.

## 3. Secrets GitHub (toi)

Dans le dépôt `valejaqu1/kairos` : Settings → Secrets and variables → Actions → New repository secret. Crée :

- `ODDS_API_KEY` : la clé de l'étape 1
- `TELEGRAM_BOT_TOKEN` : le jeton de l'étape 2
- `TELEGRAM_CHAT_ID` : l'identifiant de l'étape 2

## 4. Variable du verrou de code (toi, avec la valeur de Claude)

La routine peut pousser sur `main`. Sans précaution, une routine piégée par une page web pourrait modifier le code que les workflows exécutent avec tes clés. Chaque workflow qui porte une clé commence donc par une étape « Verrou du code » : elle calcule l'empreinte de tout le dépôt sauf les dossiers de données (`state/`, `decisions/`, `journal/`, `memory/`, `site/`, `data/odds/`, `data/model/`) et refuse de continuer si elle ne correspond pas à la variable `KAIROS_CODE_FINGERPRINT`, que la routine ne peut pas modifier. Elle refuse aussi tout fichier de `site/` autre que `index.html` et `data.json`.

1. Claude lance `scripts/empreinte-code.sh` sur la branche qui partira sur `main` et te donne la valeur (64 caractères hexadécimaux).
2. Dans le dépôt : Settings → Secrets and variables → Actions → onglet **Variables** → New repository variable. Nom : `KAIROS_CODE_FINGERPRINT`, valeur : celle de Claude, collée telle quelle.

**Chaque mise à jour du code exige une nouvelle valeur**, c'est-à-dire tout changement d'un fichier du dépôt hors des dossiers de données, documentation et tests compris : après avoir relu le changement, Claude relance `scripts/empreinte-code.sh` et tu mets la variable à jour. Si un workflow s'arrête avec « Code non validé : empreinte A, attendue B », le code a changé depuis ta dernière validation : relis le changement, puis mets A dans la variable.

## 5. Page (toi)

Settings → Pages → Build and deployment → Source : **GitHub Actions**.

## 6. Intégration GitHub de Claude (toi)

Vérifie que l'intégration GitHub de Claude ne peut pas modifier les workflows : dans GitHub, Settings → Applications → Installed GitHub Apps → Claude, la permission « Workflows » (écriture sur `.github/workflows`) ne doit pas être accordée au dépôt ; sinon une routine piégée pourrait retirer le verrou de l'étape 4.

## 7. Mettre le code sur `main` (Claude, avec ton accord)

Quand les étapes 1 à 6 sont faites, dis à Claude de fusionner la branche `construction` dans `main` et de la pousser. Claude ne le fait qu'après ton accord explicite. Il vérifie ensuite que `scripts/empreinte-code.sh` donne sur `main` la valeur de la variable.

Kairos naît (jour 1) au premier `prepare` ou `apply` lancé après ce push. Le premier `prepare` planifié part à 08:15 UTC ; si tu fusionnes le soir, il naît le lendemain matin.

## 8. Vérifier les championnats

Actions → check-api → Run workflow. Le résumé doit afficher `OK` pour les quatre championnats. Un `ABSENT` se corrige dans `kairos/config.py` (clé du championnat chez The Odds API) ; ce changement de code demande une nouvelle empreinte (étape 4).

## 9. Environnement cloud et routine

1. Toi : connecte GitHub à https://claude.ai/code avec accès au dépôt `valejaqu1/kairos`.
2. Toi : sur https://claude.ai/code, crée un environnement cloud nommé `kairos`, sans variable d'environnement ni secret. L'accès réseau se règle dans les réglages de l'environnement : Edit environment → Network access → **Full**.
3. Claude crée la routine après ton accord. Elle utilise le dépôt `valejaqu1/kairos` et l'environnement `kairos`. Elle s'exécute tous les jours à 11:07 (Europe/Zurich), et non à 11:00 : les exécutions pile à l'heure peuvent partir avec quelques minutes de retard. Vérifie que le fuseau affiché est Europe/Zurich, car les heures de routine sont saisies dans le fuseau du compte. Elle n'a aucun connecteur : retire-les tous, ils sont inclus par défaut dans le formulaire. Sa consigne est : « Lis ROUTINE.md à la racine du dépôt et exécute-le pour la date du jour à Zurich. Pousse directement sur la branche main, jamais sur une branche claude/. »

## 10. Premier jour

Lance à la main Actions → prepare → Run workflow. Attends que `prepare` soit terminé (coche verte, et le commit « prepare » visible sur `main`) avant de lancer la routine (« Run now »). Puis vérifie : un fichier `decisions/<date>.json`, un commit « apply », le message Telegram et la page https://valejaqu1.github.io/kairos/.

## À savoir ensuite

**Horaires.** Les heures des workflows sont en UTC. `prepare` part à 08:15 UTC (10:15 à Zurich en été, 09:15 en hiver), toujours avant la routine de 11:07. L'`apply` de secours part à 13:10 UTC, soit 15:10 à Zurich en été et 14:10 en hiver. `closing` part à :07 et :37 de 07 h à 21 h UTC.

**Budget de crédits.** Compte environ 12 à 15 crédits par jour sur les 500 par mois de l'offre gratuite. Sous 50 crédits restants, le code saute d'abord les captures de cotes de clôture, puis les championnats sans pari ouvert.

**Pannes.** Après 3 jours sans `prepare`, les résultats ne peuvent plus être récupérés (`daysFrom=3` chez The Odds API) : les paris ouverts sont alors remboursés et les prévisions en attente annulées.
