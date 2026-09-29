---
name: campagne-marketing-automation
description: Construire un scénario marketing automatisé sur mesure dans Odoo (marketing.campaign + marketing.activity) — modèle de données, procédure et pièges. Odoo 19 Enterprise.
---

# Construire un scénario Marketing Automation

## La règle d'or

**Tu construis, l'humain lance.** Une campagne en `running` envoie de vrais
emails, en boucle, sans repasser par personne. Le serveur refuse d'écrire
`marketing.campaign.state` et aucune action de workflow n'est autorisée sur ce
modèle — c'est volontaire, n'essaie pas de contourner. Quand le scénario est
prêt, dis à ton interlocuteur d'ouvrir Odoo → Marketing Automation → sa
campagne → **Start**.

## Les deux modèles

### `marketing.campaign` — le scénario

| Champ | Type | À savoir |
|---|---|---|
| `name` | char | Délégué à `utm.campaign` (`_inherits`). La campagne UTM est créée toute seule. |
| `model_id` | many2one `ir.model` | **Obligatoire.** La cible. Doit avoir `is_mail_thread = True`. |
| `enroll_domain` | char | Le filtre d'inscription. **Une chaîne** contenant un domaine, pas une liste. |
| `enroll_unique_field_id` | many2one `ir.model.fields` | Optionnel. Évite d'inscrire deux fois le même email. |
| `state` | selection | `draft` / `running` / `stopped`. **Gelé en écriture.** |
| `mailing_filter_ids` | many2many `mailing.filter` | Filtres favoris réutilisables. |

### `marketing.activity` — une étape

| Champ | Type | À savoir |
|---|---|---|
| `name` | char | Le libellé de l'étape. |
| `campaign_id` | many2one | **Obligatoire.** |
| `activity_type` | selection | `email` ou `action`. Pas de SMS (module non installé). |
| `mass_mailing_id` | many2one `mailing.mailing` | Le mail envoyé, si `activity_type = "email"`. |
| `server_action_id` | many2one `ir.actions.server` | Si `activity_type = "action"`. **Lecture seule** : branche une action existante, n'en crée jamais. |
| `parent_id` | many2one `marketing.activity` | L'étape dont celle-ci dépend. Vide pour la première. |
| `trigger_type` | selection | Voir ci-dessous. Défaut `begin`. |
| `interval_number` + `interval_type` | int + selection | Le délai **après le déclencheur**. `hours` / `days` / `weeks` / `months`. |
| `activity_domain` | char | Filtre supplémentaire sur cette branche. **C'est ce champ qu'on écrit.** |
| `domain` | char | **Calculé, en lecture seule.** Ne l'écris jamais. |

### Les déclencheurs (`trigger_type`)

`begin` (départ du scénario) · `activity` (le parent est exécuté) ·
`mail_open` · `mail_not_open` · `mail_click` · `mail_not_click` ·
`mail_reply` · `mail_not_reply` · `mail_bounce`

Les déclencheurs `mail_*` n'ont de sens que si l'activité parente est de type
`email`.

## Procédure

1. **Clarifie** avant de créer quoi que ce soit : quelle cible, quelle
   audience, quelle séquence d'étapes, quels délais, quelles conditions.
   Reformule le scénario en toutes lettres et fais-le valider.

2. **Résous le modèle cible** :
   `search("ir.model", [["model", "=", "mailing.contact"]], ["id", "name", "is_mail_thread"])`.
   Si `is_mail_thread` est faux, le modèle ne peut pas être ciblé — dis-le.

3. **Crée la campagne** :
   ```
   create("marketing.campaign", {
     "name": "Bienvenue abonnés",
     "model_id": 512,
     "enroll_domain": "[('list_ids', 'in', [3])]"
   })
   ```

4. **Crée un mailing brouillon par étape email**. Ton interlocuteur écrira le
   contenu lui-même dans Odoo — ne rédige pas le corps, crée la coquille :
   ```
   create("mailing.mailing", {
     "subject": "Bienvenue chez MaGin",
     "mailing_model_id": 512,
     "use_in_marketing_automation": true,
     "mailing_type": "mail"
   })
   ```
   `use_in_marketing_automation` est ce qui rend le mailing sélectionnable dans
   un scénario. `mailing_model_id` doit être le **même** que `model_id` de la
   campagne. `source_id` se remplit tout seul, ne le fournis pas.

5. **Crée les activités, de la racine vers les feuilles** — il faut l'`id` du
   parent avant de créer l'enfant. Étape de départ :
   ```
   create("marketing.activity", {
     "name": "Mail de bienvenue", "campaign_id": 7,
     "activity_type": "email", "mass_mailing_id": 41,
     "trigger_type": "begin", "interval_number": 0, "interval_type": "hours"
   })
   ```
   Relance conditionnelle :
   ```
   create("marketing.activity", {
     "name": "Relance si non ouvert", "campaign_id": 7,
     "activity_type": "email", "mass_mailing_id": 42,
     "parent_id": 88, "trigger_type": "mail_not_open",
     "interval_number": 3, "interval_type": "days"
   })
   ```

6. **Relis et montre l'arbre.** Recharge les activités
   (`search("marketing.activity", [["campaign_id", "=", 7]], [...])`) et
   présente le scénario sous forme d'arborescence lisible, avec les délais et
   les conditions. C'est le moment où une erreur se voit.

7. **Passe la main.** Rappelle : écrire le contenu des mails, puis **Start**
   dans Odoo. Précise le nombre de destinataires attendus
   (`count` sur le modèle cible avec le `enroll_domain`) — c'est le chiffre qui
   fait réfléchir avant de lancer.

## Pièges

- **`domain` vs `activity_domain`** : `domain` est calculé, toute écriture est
  perdue ou refusée. Écris `activity_domain`.
- **Les domaines sont des chaînes**, pas des listes JSON : `"[('x', '=', 1)]"`.
- **Crée `activity_type` dans le même appel** que `mass_mailing_id` ou
  `server_action_id`. Ces deux champs sont calculés et se vident tout seuls si
  le type ne correspond pas — les renseigner par un `update` séparé après coup
  ne marche pas de façon fiable.
- **`ir.actions.server` est en lecture seule.** Si le scénario a besoin d'une
  action qui n'existe pas, décris-la et demande qu'elle soit créée dans Odoo.
- **Changer `model_id` d'une campagne qui a déjà des activités les invalide.**
  Fixe la cible d'abord.
- **Pas de SMS** sur cette base : `activity_type` n'offre que `email` et
  `action`.

## Juger une campagne passée

`marketing.participant` (qui est inscrit, où il en est) et `marketing.trace`
(ce qui a été fait, ouvert, cliqué, rebondi) sont **en lecture seule** — ce
sont des résultats produits par Odoo. Les compteurs agrégés sont directement
sur `marketing.activity` : `processed`, `total_sent`, `total_open`,
`total_click`, `total_reply`, `total_bounce`, `rejected`.
