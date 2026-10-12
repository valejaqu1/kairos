# Kairos — spécification

Date : 2026-10-12 · Statut : validée en brainstorming, à planifier

## 1. En une phrase

Kairos est un agent IA autonome qui vit d'une cagnotte fictive de 100 CHF : chaque jour il paie sa « faim », analyse des matchs de foot, parie en simulation sur de vraies cotes, apprend de ses résultats, et meurt quand il ne peut plus placer la mise minimale (cagnotte sous 40 CHF, aucun pari en cours). On l'observe sur une page web et il envoie un message quotidien sur Telegram.

## 2. Cadre et limites

- **Simulation uniquement.** Aucun argent réel, aucun compte de paris. Le passage à l'argent réel (semi-automatique sur Jouez Sport, l'utilisateur valide chaque ticket à la main) est un projet séparé, envisagé seulement si Kairos décroche son diplôme.
- **Pas de lecture de Jouez Sport.** Le site jeux.loro.ch bloque les navigateurs automatisés (403 constaté le 2026-10-12). On ne contourne pas cette protection. Les cotes viennent de The Odds API (bookmakers européens), avec une décote prudente.
- **Légalité.** Seule plateforme légale pour l'utilisateur (Suisse romande) : Jouez Sport. Les plateformes étrangères (Polymarket, bookmakers étrangers) sont bloquées en Suisse et ne sont pas utilisées.
- **Sport couvert :** football, pari « 1X2 classique » en temps réglementaire (victoire domicile / nul / victoire extérieur), avant-match uniquement.
- **Fidélité à Jouez Sport** (règlement 17e édition, septembre 2024) : mise minimale d'un pari Single en ligne 2 CHF (art. 9), cote minimale 1,10 (art. 7), le 1X2 classique fait partie des paris autorisés (annexe 1, art. 1). Les championnats suivis sont l'intersection de l'offre football réelle de Jouez Sport, de The Odds API et de football-data.co.uk, relevée par l'utilisateur à la mise en route. Relevé du 2026-10-12 (site public, sans connexion) : une trentaine de pays et régions en football, dont l'Angleterre sur 4 divisions, l'Espagne, l'Italie, l'Allemagne, la France, le Portugal et les coupes d'Europe ; marchés 1X2, double chance, plus/moins de buts, les deux équipes marquent, 1X2 handicap ; aucun match de football suisse affiché ce jour-là (pause internationale probable). Championnats par défaut : Premier League, LaLiga, Serie A, Bundesliga. Exemple de marge : Coventry–Newcastle à 3,00 / 3,65 / 2,10, soit une marge d'environ 8 %. Limite connue : Jouez Sport peut réserver certains 1X2 aux paris combinés (art. 5.2) ; la simulation ne peut pas le savoir et suppose que le pari Single est disponible.

## 3. Règles du jeu

| Paramètre | Valeur |
|---|---|
| Cagnotte de départ | 100,00 CHF fictifs |
| Faim | 0,25 CHF par jour calendaire, jours manqués rattrapés |
| Décote des cotes | cote simulée = cote médiane UE × 0,95 (plancher 1,01), facteur recalé à la mise en route sur de vraies cotes Jouez Sport |
| Seuil de valeur | proba de Kairos × cote simulée − 1 ≥ 0,05 |
| Mise | ¼ de Kelly, plafond 5 % de l'avoir, arrondi à 0,10 CHF, minimum 2,00 CHF (sinon pas de pari) |
| Cote minimale | 1,10 (en dessous, pas de pari) |
| Paris par jour | 3 au maximum |
| Exposition | mises en cours ≤ 15 % de la cagnotte |
| Mort | cagnotte < 40,00 CHF (5 % de l'avoir n'atteignent plus la mise minimale de 2,00 CHF, donc plus de mise possible) et aucun pari en cours |
| Diplôme | au jour 56 : vivant, cagnotte ≥ 100,00 CHF, prévisions meilleures que le marché en moyenne (score de compétence > 0) et CLV positive sur ≥ 55 % des paris, jugée sur au moins 5 paris dont la cote de clôture est connue (en dessous : « manqué ») |

Après le jour 56, la simulation continue jusqu'à la mort ; le diplôme est un jalon, obtenu ou non une seule fois. Pas de résurrection. Une « génération 2 » éventuelle repartirait de zéro avec le carnet de leçons de la génération 1 (hors périmètre de cette spec).

## 4. Architecture

Principe : **l'IA propose, le code décide.** Tout ce qui touche à l'argent, aux clés et aux règles est du code déterministe ; l'IA ne fait que réfléchir et écrire des propositions.

```
                 GitHub (dépôt public valejaqu1/kairos)
  ┌──────────────────────────────────────────────────────────────────┐
  │ Actions « prepare »  (cron ~10:15 Zurich)                        │
  │   cotes 48 h → data/odds/   modèle stats → data/model/           │
  │   résultats → règlement des paris, faim → state/                 │
  │                                                                  │
  │ Routine Claude (11:00 Zurich, cloud, sans clé ni connecteur)     │
  │   lit state/ data/ memory/ → recherche web → écrit decisions/    │
  │   puis push                                                      │
  │                                                                  │
  │ Actions « apply »  (sur push de decisions/, secours à 15:00)     │
  │   valide et applique les règles → state/   métriques → memory/   │
  │   construit site/ → GitHub Pages     message → Telegram          │
  │                                                                  │
  │ Actions « closing »  (toutes les 30 min, 9h–23h)                 │
  │   cote juste avant le coup d'envoi des paris en cours → CLV      │
  └──────────────────────────────────────────────────────────────────┘
```

- Les trois workflows partagent un groupe de concurrence `kairos-state` (un seul à la fois) et font `git pull --rebase` avant de commiter.
- Déclencheurs autorisés : `schedule`, `push` sur `main`, `workflow_dispatch`. Jamais `pull_request_target` (dépôt public).
- Secrets GitHub Actions : `ODDS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. La routine Claude n'en voit aucun.

## 5. Données (fichiers du dépôt)

```
state/kairos.json        état vivant : cagnotte, jour, vivant/mort, génération, dates clés
state/bets.json          tous les paris (ouverts et réglés), cote de clôture comprise (champ closing_odds)
state/forecasts.json     toutes les prévisions (pariées ou non), avec score une fois le match joué
data/odds/AAAA-MM-JJ.json    instantané des cotes (médiane UE par issue, cote simulée)
data/model/AAAA-MM-JJ.json   probabilités du modèle statistique par match
data/team_aliases.json   correspondances de noms d'équipes entre The Odds API et football-data
decisions/AAAA-MM-JJ.json    sortie de la routine (schéma §7)
memory/sources.json      sources avec utilisations, score et statut (gardée / en test / jetée)
memory/lessons.md        carnet de leçons, 15 règles au maximum
journal/AAAA-MM-JJ.md    journal du jour lisible (décisions, rejets, résultats, message)
site/                    page publiée (HTML + data.json)
```

## 6. Composants déterministes (Python 3.12, paquet `kairos/`)

1. **odds** : appelle The Odds API (`regions=eu`, `markets=h2h`) pour 4 championnats, garde les matchs des 48 h suivantes, calcule la médiane par issue et la cote simulée. Lit l'en-tête de crédits restants ; sous 50 crédits, saute les appels non essentiels (closing d'abord, puis championnats sans pari en cours).
2. **model** : modèle Dixon-Coles (`penaltyblog`) ajusté sur les résultats des deux dernières saisons (football-data.co.uk), donne P(1), P(X), P(2) par match.
3. **market** : probabilités du marché sans marge (`penaltyblog.implied`) à partir des cotes médianes.
4. **settle** : récupère les scores des championnats avec paris ou prévisions en attente, règle les paris (gagné : mise × cote simulée ; perdu : 0 ; annulé ou reporté de plus de 3 jours : remboursé) et note les prévisions.
5. **hunger** : retire 0,25 CHF × jours écoulés depuis la dernière faim payée ; déclare la mort selon §3.
6. **rules** : valide chaque proposition (match connu, coup d'envoi futur, probabilités cohérentes, seuil de valeur), calcule la mise, applique les plafonds, place les paris acceptés, journalise les rejets avec leur raison.
7. **metrics** : RPS (ranked probability score) de Kairos, du marché et du modèle sur chaque prévision réglée ; CLV par pari = cote prise / cote de clôture − 1 (cotes brutes, sans décote) ; score des sources ; rang ; trophées ; état du diplôme.
8. **site** : construit `site/data.json` et la page à partir de la maquette validée (`maquette-kairos.html`), y compris l'état « mort ».
9. **notify** : envoie sur Telegram le message de Kairos suivi d'une ligne automatique (cagnotte, faim, paris du jour).

Chaque composant est une fonction pure testable plus une fine couche d'entrées-sorties. Les montants sont en centimes entiers dans le code.

## 7. Contrat de la routine Claude

**Entrées lues :** `state/`, `data/odds/` et `data/model/` du jour, `memory/`, les 7 derniers `journal/`.

**Travail :**
1. Choisir jusqu'à 10 matchs à analyser parmi ceux des 48 h.
2. Pour chacun, chercher l'actu (compositions, blessures, contexte) sur le web, partir du modèle et du marché, et donner ses propres P(1), P(X), P(2), avec les sources utilisées.
3. Proposer au plus 3 paris parmi ces matchs.
4. Essayer au plus une nouvelle source par jour.
5. Le dimanche : relire la semaine (scores et CLV calculés par le code), ajouter au plus 2 leçons, retirer celles que les résultats contredisent, sans dépasser 15.
6. Écrire son message du jour, à la première personne, 600 caractères au maximum.

**Sortie :** un seul fichier `decisions/AAAA-MM-JJ.json`, puis commit et push sur `main`.

```json
{
  "date": "2026-10-12",
  "forecasts": [
    {"event_id": "…", "p": [0.49, 0.27, 0.24], "sources": ["compos-probables", "presse-locale-ch"], "note": "…"}
  ],
  "bets": [
    {"event_id": "…", "selection": "1", "reasoning": "…"}
  ],
  "new_source": {"id": "presse-locale-ch", "description": "…", "url": "…"},
  "lessons": {"add": ["…"], "remove": ["…"]},
  "message": "…"
}
```

Kairos ne fixe pas ses mises : le code les calcule à partir de sa probabilité. Une proposition invalide est rejetée et journalisée, sans bloquer le reste.

**Configuration de la routine :** dépôt `valejaqu1/kairos` uniquement, aucun connecteur (liste vidée explicitement après création), environnement cloud dédié « kairos » avec accès réseau complet (nécessaire pour découvrir des sources) et sans variable secrète. Compétence d'analyste dans `.claude/skills/kairos-analyste/` (méthode adaptée de sports-betting-claude, MIT : détection de valeur, liste de biais, discipline des sources).

**Rayon d'action si une page web piège Kairos :** écrire des fichiers dans son propre dépôt public. Pas de clé à voler, pas de compte connecté, et ses mises restent bornées par le code.

## 8. Apprentissage

- **Prévisions sur tous les matchs analysés** (environ 10 par jour), pas seulement les paris : environ 300 points de mesure par mois.
- **Score de compétence** = RPS du marché − RPS de Kairos, moyenné. Positif : il voit mieux que le marché.
- **Sources** : score = score de compétence moyen des prévisions qui la citent. Statut calculé par le code : « gardée » si ≥ 10 utilisations et score > 0 ; « jetée » si ≥ 10 utilisations et score < 0 ; sinon « en test ». Kairos n'utilise plus une source jetée.
- **Leçons** : rédigées par Kairos le dimanche, chacune avec le nombre de cas qui l'appuient ; plafond de 15 imposé par la validation.
- **Rang** : r = 0,5 × (part des 30 dernières prévisions qui battent le marché) + 0,5 × (part des 20 derniers paris à CLV positive). Bronze < 0,45 ≤ Argent < 0,55 ≤ Or < 0,62 ≤ Platine ; chaque palier sauf Platine est coupé en I, II, III par tiers.
- **Trophées** : premier pari gagné ; séries de 3 et de 5 ; première source gardée ; 10 paris à CLV positive ; 4 semaines de survie ; diplômé.
- **Ensemble de CLV** : la page, le trophée « 10 paris à CLV positive » et le diplôme calculent la CLV sur le même ensemble, les paris non annulés dont la cote de clôture est connue (les paris en cours en font partie, car la CLV est connue au coup d'envoi). Le diplôme juge la CLV sur au moins 5 de ces paris (`DIPLOMA_MIN_CLV_BETS`) : en dessous, il est « manqué ». La moyenne du score de compétence du diplôme est calculée en fractions exactes, et le diplôme est décidé avant les trophées pour que « diplômé » porte la date du jour 56.

## 9. Page et message

- Page publique sur GitHub Pages, fidèle à la maquette validée : entité lumineuse (couleur et rythme selon la santé), cagnotte, signes vitaux, message du jour, courbe, fiche de joueur (rang, progression, stats), cartes de match avec CLV, leçons et sources, trophées. État « mort » : entité éteinte, dernier message, date.
- Données lues dans `site/data.json`, régénéré par « apply ».
- Telegram : un message par jour après « apply » ; un message de mort ; un message de diplôme au jour 56.

## 10. Erreurs et cas limites

| Cas | Comportement |
|---|---|
| The Odds API indisponible | « prepare » réessaie 2 fois, sinon pas de nouvelles cotes ; la routine n'a rien à analyser et le dit dans son message |
| Routine absente ou en échec | « apply » de secours à 15:00 : faim appliquée, aucun pari, message « Kairos n'a pas donné signe de vie aujourd'hui » |
| Fichier de décisions invalide | rejeté en entier, journalisé ; même traitement que l'absence |
| Match reporté | pari en attente ; remboursé après 3 jours |
| Jours sans aucun run | faim rattrapée au run suivant |
| Crédits API presque épuisés | voir composant odds |
| Conflit de push | concurrence `kairos-state` + rebase ; un seul écrivain à la fois |

## 11. Tests

- Tests unitaires (pytest) pour rules, hunger, settle, metrics (RPS, CLV, rang, sources), validation du fichier de décisions.
- Réponses de The Odds API et de football-data enregistrées en fixtures ; aucun appel réseau dans les tests.
- Test de bout en bout avec un faux client API : prepare → décisions d'exemple → apply → closing → prepare du surlendemain, sans réseau, sans Telegram ni push.
- Avant la mise en route : une journée complète en dry-run, puis un premier jour réel surveillé.

## 12. Ce que l'utilisateur fait lui-même

Créer le compte gratuit The Odds API et sa clé ; créer le bot Telegram (BotFather) et lui écrire une fois pour obtenir l'identifiant de conversation ; coller les trois secrets dans GitHub ; valider la création du dépôt public, de l'environnement cloud et de la routine. Claude ne crée pas de comptes et ne manipule pas les clés.

## 13. Hors périmètre

Argent réel et Jouez Sport ; autres sports et marchés ; paris en direct ; génération 2 ; notifications autres que Telegram.

## 14. Points à confirmer au début du plan

- Clés de championnats disponibles chez The Odds API (Super League suisse incluse ?) et coût exact en crédits des appels odds, scores et cotes par match.
- Format des fichiers football-data.co.uk pour la Suisse (fichiers « nouvelles ligues ») et fonction de chargement de `penaltyblog`.
- Fuseau horaire accepté par la planification des routines.
- Offre football réelle de Jouez Sport et décote réelle : l'utilisateur relève la liste des championnats et une quinzaine de cotes 1X2 un jour donné ; on recale la décote et la liste des championnats.
