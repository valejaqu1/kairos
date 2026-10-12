# Mettre Kairos en route

Environ 15 minutes. Les étapes marquées « toi » se font à la main : Claude ne crée pas de comptes et ne manipule pas tes clés.

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

## 4. Page (toi)

Settings → Pages → Build and deployment → Source : **GitHub Actions**.

## 5. Vérifier les championnats

Actions → check-api → Run workflow. Le résumé doit afficher `OK` pour les quatre championnats. Un `ABSENT` se corrige dans `kairos/config.py` (clé du championnat chez The Odds API).

## 6. Environnement cloud et routine

1. Toi : connecte GitHub à https://claude.ai/code avec accès au dépôt `valejaqu1/kairos`.
2. Toi : sur https://claude.ai/code, crée un environnement cloud nommé `kairos`, sans variable d'environnement ni secret. L'accès réseau se règle dans les réglages de l'environnement : Edit environment → Network access → **Full**.
3. Claude crée la routine après ton accord. Elle utilise le dépôt `valejaqu1/kairos` et l'environnement `kairos`. Elle s'exécute tous les jours à 11:07 (Europe/Zurich), et non à 11:00 : les exécutions pile à l'heure peuvent partir avec quelques minutes de retard. Vérifie que le fuseau affiché est Europe/Zurich, car les heures de routine sont saisies dans le fuseau du compte. Elle n'a aucun connecteur : retire-les tous, ils sont inclus par défaut dans le formulaire. Sa consigne est : « Lis ROUTINE.md à la racine du dépôt et exécute-le pour la date du jour à Zurich. Pousse directement sur la branche main, jamais sur une branche claude/. »

## 7. Premier jour

Lance à la main Actions → prepare → Run workflow. Attends que `prepare` soit terminé (coche verte, et le commit « prepare » visible sur `main`) avant de lancer la routine (« Run now »). Puis vérifie : un fichier `decisions/<date>.json`, un commit « apply », le message Telegram et la page https://valejaqu1.github.io/kairos/.
