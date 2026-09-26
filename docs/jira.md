# Tickets Jira Cloud

Le backend Jira remplace uniquement la création du ticket. Les utilisateurs et les
factures restent synthétiques. Un ticket Jira est un objet **réel**, dont la
description signale explicitement l’origine fictive des données métier.

Cette intégration est désactivée par défaut. Elle reste en phase d’intégration :
le CRM synthétique empêche encore le déploiement du parcours complet en production.

## Configuration

Renseigner localement les variables suivantes, sans committer le token :

```dotenv
ASSISTOPS_JIRA_SITE=https://your-site.atlassian.net
ASSISTOPS_JIRA_PROJECT_KEY=OPS
ASSISTOPS_JIRA_TENANT_ID=demo
JIRA_EMAIL=your-atlassian-account@example.com
JIRA_API_TOKEN=your-local-secret
```

Le tenant fixe le périmètre AssistOps autorisé à envoyer vers ce projet. Le site,
le projet et le type de ticket sont configurés par l’administrateur, jamais par le
modèle ou les paramètres entrants. Cette version dessert un tenant/projet Jira.

Pour une intégration interne, utiliser un compte disposant des seuls droits
nécessaires au projet. Un token à scopes passe par le gateway Atlassian et nécessite
`ASSISTOPS_JIRA_CLOUD_ID`. Récupérer cet identifiant sans authentification :

```shell
python -m assistops.jira_cli --discover-cloud-id
```

Copier la valeur retournée dans `ASSISTOPS_JIRA_CLOUD_ID`. Les permissions du compte
et les scopes du token doivent permettre la lecture des métadonnées, la création
et la lecture des tickets et propriétés. Voir les [tokens Atlassian](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/).
Une intégration distribuée à des clients devra utiliser une application OAuth 2.0,
plutôt que collecter leurs tokens. Voir [l’authentification Atlassian](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/).

Vérifier les droits et lister les types de ticket, sans aucune création :

```shell
python -m assistops.jira_cli
```

Choisir l’identifiant d’un type standard, sans parent obligatoire, puis ajouter
`ASSISTOPS_JIRA_ISSUE_TYPE_ID`. Relancer la commande pour consulter les champs
obligatoires. Le payload actuel fournit projet, type, résumé et description au
format Atlassian Document Format. Les projets imposant d’autres champs sans valeur
par défaut nécessitent un mapping explicite avant activation. La commande indique
les nombres de champs retournés et disponibles ; elle ne prétend pas valider
des champs qui n’ont pas été récupérés.

Après cette vérification, ajouter l’override Jira à la commande habituelle :

```shell
docker compose -f compose.yaml -f compose.n8n.yaml -f compose.jira.yaml up --build --wait
```

Avec le Supervisor, ajouter également `-f compose.rag.yaml` et définir
`ASSISTOPS_AI_PROCESSOR=supervisor`. L’override Jira active les écritures externes
après approbation. L’API reçoit la destination ; **seul le worker reçoit le token**.
Pour lancer les processus hors Docker, définir aussi `ASSISTOPS_TICKET_BACKEND=jira`.

## Approbation et envoi

1. La proposition contient les arguments métier et `ticket_target`, dont le site,
   l’identifiant Cloud, le projet et le type de ticket. Le hash d’approbation lie
   l’ensemble à la demande, au demandeur et au connecteur.
2. `/v1/approvals/decide` vérifie l’approbateur distinct, les droits, l’expiration et
   ce hash. La décision et l’envoi en attente sont enregistrés dans une transaction.
   Aucun appel réseau Jira n’a lieu dans la requête d’approbation.
3. Le worker vérifie encore les droits et la destination, enregistre `sending`,
   puis appelle Jira. La clé `OPS-123` et son lien sont conservés en base.

Le mécanisme existant d’approbation utilise le même connecteur que la proposition.
Le connecteur n8n local atteste uniquement `user-001` : pour approuver ses demandes,
un canal de revue de confiance doit signer avec ce connecteur et un approbateur
ajouté à sa liste d’identités autorisées. Le webhook n8n conserve son identité fixe ;
ne jamais y accepter un `user_id` fourni par le client. Le connecteur local `demo`
possède déjà `reviewer-001` pour les tests directs de l’API.

Les scripts `check_business_flow.py` simulent une approbation automatiquement :
**ne pas les lancer contre un environnement Jira actif**. Ils sont réservés au
backend synthétique. L’activation Jira exige une revue humaine du ticket proposé.

## Erreurs et doublons

Une seule ligne d’envoi existe par proposition. Le verrou PostgreSQL empêche deux
workers d’envoyer cette ligne simultanément ; rejouer l’approbation ne la duplique
pas. Un HTTP 429 planifie une reprise après `Retry-After`, avec trois tentatives au
maximum. Un refus explicite (400, 401, 403, 404, 422) termine l’envoi en échec.

Un timeout, une erreur serveur, une réponse de succès illisible ou une interruption
après `sending` peut masquer une création réussie. AssistOps passe alors en
`delivery_uncertain`, sans répéter le POST. Un envoi interrompu est détecté après
deux minutes. `business_action_executed` vaut `null` lorsque l’effet est inconnu.
Ce choix évite les reprises aveugles, sans promettre une transaction atomique entre
PostgreSQL et Jira. Les nouvelles propositions pour la même facture dans la même
conversation sont bloquées tant que l’envoi est en attente ou incertain.

Un opérateur recherche la référence AssistOps inscrite dans la description du ticket
sur Jira. S’il retrouve le ticket, il peut rapprocher les deux états :

```shell
python -m assistops.jira_cli --reconcile PROPOSAL_UUID --issue OPS-123
```

Cette commande lit le ticket et sa propriété `assistops.proposal`, vérifie projet,
type, identifiant de proposition et hash, puis journalise le rapprochement. Elle
ne crée aucun ticket. Les propriétés Jira sont modifiables par les utilisateurs
autorisés dans Jira : ce contrôle suppose un espace de confiance, ce n’est pas une
preuve cryptographique indépendante. Si aucun ticket n’est retrouvé, l’état reste
incertain jusqu’à investigation ; aucun bouton de renvoi automatique n’est fourni.

Le suivi expose `awaiting_delivery`, `completed`, `failed` ou `delivery_uncertain`.
Une approbation réussie signifie « envoi autorisé », pas « ticket déjà créé ».

## Vérification

Les tests `tests/test_jira.py` utilisent PostgreSQL réel et un transport HTTP Jira
simulé : concurrence, révocation, destination, timeout, reprise sur 429,
redirections et rapprochement. Ils tournent en CI sans secret ni création externe.
Le test réel de création doit être effectué séparément après configuration et
approbation humaine ; une vérification de métadonnées seule ne le remplace pas.
