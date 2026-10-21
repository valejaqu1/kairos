---
name: kairos-analyste
description: Méthode d'analyste de Kairos pour estimer les probabilités d'un match de football (1X2), repérer la valeur face aux cotes et éviter les biais. À utiliser pendant la routine quotidienne de Kairos.
---

# Méthode d'analyste de Kairos

Méthode adaptée au football de sports-betting-claude (licence MIT, © 2024 Sports Betting Claude Contributors).

## 1. Le marché est ton point de départ

`p_market` est la probabilité implicite des bookmakers, marge retirée. Le marché a souvent raison : il agrège beaucoup d'information. Tu ne t'en écartes que pour une raison précise et vérifiable.

- Écart de moins de 3 points : normal, c'est du bruit.
- Écart de 3 à 8 points : il faut une information concrète (absence d'un titulaire clé, rotation annoncée, contexte particulier).
- Écart de plus de 8 points : exceptionnel. Vérifie deux fois ; le plus souvent, c'est toi qui te trompes.

## 2. Le modèle donne un deuxième avis

`p_model` (Dixon-Coles) ne connaît que les buts marqués et encaissés. S'il diverge fortement du marché, cherche pourquoi (transfert, blessure longue, changement d'entraîneur) avant de le suivre.

## 3. Ce qui fait bouger une probabilité

Par ordre d'importance : absences confirmées de joueurs clés (gardien, buteur, meneur), compositions probables, enjeu (maintien, qualification, match sans enjeu), fatigue (match européen trois jours avant), conditions exceptionnelles. La forme récente compte peu : le marché l'intègre déjà.

## 4. Valeur

Valeur = ta probabilité × cote simulée − 1. Elle doit atteindre 0,05. Une forte valeur sur un outsider vient presque toujours d'une erreur d'estimation : demande-toi ce que le marché sait et que tu ignores.

## 5. Liste des biais à vérifier avant chaque pari

- Récence : un gros score la semaine dernière ne change pas la force d'une équipe.
- Récit : « ils sont en mission » n'est pas une information.
- Grande équipe : la notoriété n'est pas une probabilité.
- Confirmation : cherche activement ce qui contredit ton idée.
- Tilt : après des pertes, ne cherche pas à te refaire ; le code limite tes mises, pas ton jugement.
- Petit échantillon : 3 cas ne font pas une règle.

## 6. Discipline des sources

Cite seulement ce que tu as réellement utilisé. Préfère les sources primaires (communiqués des clubs, conférences de presse, journalistes accrédités) aux forums et aux pronostiqueurs. Une source jetée ne revient pas. Une nouvelle source par jour au maximum.

## 7. Quand ne pas parier

Pas d'information nouvelle, doute sur une absence, écart avec le marché que tu ne sais pas expliquer, ou valeur juste au-dessus du seuil sans conviction : tu donnes ta prévision et tu ne paries pas.

## 8. Pari d'apprentissage

Les jours sans pari de valeur, tu places un pari de 2 CHF sur ta meilleure conviction, à condition que ta probabilité dépasse celle du marché. Ce pari ne cherche pas à gagner : il mesure si ton jugement bat la cote de clôture. Choisis l'issue où ton information est la plus solide, pas celle qui paie le plus. Une cote élevée donne un résultat bruité qui ne t'apprend rien.
