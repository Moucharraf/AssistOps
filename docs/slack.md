# Préparer l’application Slack

Le connecteur reçoit les mentions du bot, transmet la demande au worker existant et
répond dans le fil Slack d’origine. Les tickets proposés restent soumis à validation
dans l’interface web ; la même réponse Slack est mise à jour après la décision et
la livraison Jira.

## Choix du transport local

Le premier raccordement utilise **Socket Mode** : le connecteur ouvre une connexion
sortante vers Slack. Aucun tunnel ni endpoint public ne sont nécessaires pour recevoir
les mentions sur la machine de développement. C’est un transport distinct des webhooks
n8n déjà présents ; leurs workflows restent disponibles.

Le manifeste demande uniquement `app_mentions:read` et `chat:write`. Le bot reçoit
les messages où il est mentionné dans une conversation à laquelle il appartient.
Il ne demande pas l’accès global à l’historique, aux e-mails ou à l’annuaire Slack.

## Créer et installer l’application

1. Ouvrir [la gestion des applications Slack](https://api.slack.com/apps).
2. Choisir **Create New App**, puis **From a manifest**, et sélectionner l’espace de test.
3. Dans l’onglet JSON, coller le contenu de
   [`integrations/slack/manifest.json`](../integrations/slack/manifest.json), puis créer l’application.
4. Dans **OAuth & Permissions**, choisir **Install to Workspace** et autoriser les
   permissions. Enregistrer le **Bot User OAuth Token** (`xoxb-…`) dans la variable
   d’environnement locale `SLACK_BOT_TOKEN`.
5. Dans **Basic Information → App-Level Tokens**, générer un jeton avec la portée
   `connections:write`. L’enregistrer dans `SLACK_APP_TOKEN` (`xapp-…`).
6. Dans le canal de test, saisir `/invite @AssistOps`.

Ne pas coller les jetons dans une conversation, un fichier versionné ou une commande
qui les afficherait. Le manifeste ne contient aucun secret. Les jetons serviront au
connecteur ; les fournir ne doit pas activer automatiquement l’envoi de messages.

## Informations pour le raccordement

Relever l’identifiant de l’espace (`T…`), du canal autorisé (`C…`, ou `G…` pour certains
canaux privés) et du membre qui utilisera le bot (`U…`). Le lien du canal contient
généralement l’espace et le canal : `app.slack.com/client/T…/C…`. L’identifiant du
membre est disponible via son profil et l’action de copie de l’identifiant.

Ces identifiants ne sont pas des secrets. Ils permettent de limiter le connecteur
au bon espace et au canal de test, et de relier explicitement le membre Slack à une
identité métier AssistOps. Le nom d’affichage d’une personne ou du canal ne constitue
pas une preuve d’identité. Aucun utilisateur ne doit recevoir un rôle sur la seule
base du texte de son message.

Le raccordement conserve les contrôles existants : déduplication des événements,
mémoire isolée par utilisateur et fil, validation humaine séparée et réponse dans
le fil d’origine. Les réponses postées dans un canal sont visibles par ses membres :
les premiers essais utiliseront uniquement les données synthétiques du projet.

## Configuration et démarrage

Les variables `SLACK_BOT_TOKEN` et `SLACK_APP_TOKEN` doivent être disponibles dans le
terminal qui lance Compose. Après leur ajout aux variables Windows, ouvrir un nouveau
terminal pour qu’il les hérite. Ne jamais afficher `docker compose config` sans
`--quiet`, car la configuration résolue contient les secrets.

Configurer également les valeurs suivantes dans `.env`, exclu de Git :

| Variable | Utilisation |
| --- | --- |
| `SLACK_TEAM_ID` | Identifiant `T…` de l’espace autorisé |
| `SLACK_CHANNEL_ID` | Identifiant `C…` ou `G…` du canal autorisé |
| `SLACK_USER_MAP` | JSON, par exemple `{"U0123456789":"user-001"}` |
| `SLACK_CONNECTOR_SECRET` | Secret aléatoire d’au moins 32 caractères, sans guillemets ni retours à la ligne |
| `SLACK_REVIEW_URL` | Adresse de l’interface, par défaut `http://localhost:8000/review` |

Le Compose Slack local représente le tenant `demo` et autorise `user-001`. Pour
ajouter des membres, modifier explicitement le mapping, l’allowlist du connecteur
et les droits métier/RAG. Deux membres ne peuvent pas partager la même identité
AssistOps. Aucun compte ne reçoit de droits sur la base de son nom Slack.

Ajouter **en dernier** `-f compose.slack.yaml` à la commande de démarrage existante,
après `compose.n8n.yaml`. Conserver tous les fichiers d’intégrations déjà activées.
Exemple pour Supervisor + n8n + Slack, sans activation de Jira :

```powershell
$env:ASSISTOPS_AI_PROCESSOR = 'supervisor'
docker compose -f compose.yaml -f compose.rag.yaml -f compose.n8n.yaml -f compose.slack.yaml up --build --wait --wait-timeout 240
```

Le service `slack` est un processus distinct, sans port entrant. L’API et le worker
ne reçoivent pas ses jetons Slack. La migration 010 ajoute son suivi de livraison.
Un premier contrôle peut être exécuté avec la même liste de fichiers Compose et
la commande `run --rm --no-deps slack python -m assistops.slack --check` après le build.
Il vérifie les deux jetons sans recevoir d’événements ni publier de message.

Le compte de validation doit être autorisé à examiner le connecteur `slack-demo`.
Pour le configurer via la commande d’administration (ce qui change le mot de passe
et révoque les sessions existantes) :

```shell
docker compose exec api python -m assistops.review.cli set-password reviewer --tenant demo --user reviewer-001 --connector demo --connector n8n-demo --connector slack-demo
```

L’adresse `localhost` convient au navigateur de la même machine ; pour une équipe,
configurer une adresse HTTPS accessible et l’authentification correspondante.

## Utilisation

Dans le canal autorisé, mentionner le bot :

> @AssistOps Quelle est la procédure pour contester une facture ?

Puis, dans le même fil, le mentionner de nouveau :

> @AssistOps Consulte ma facture INV-001 et prépare un ticket de test synthétique.

Le bot ne lit pas tout l’historique Slack : sa mémoire contient uniquement les
demandes qu’il a reçues. Les fichiers joints, messages modifiés, messages de bots,
messages directs et canaux Slack Connect ne sont pas pris en charge dans cette version.
Chaque demande doit mentionner le bot, y compris une relance dans un fil.

Une réponse documentaire contient les références sources. Une proposition de ticket
contient un bouton **Consulter la proposition** qui ouvre la bonne fiche après connexion.
Ce bouton n’approuve rien ; écrire « approuve » dans Slack ne remplace pas la décision
authentifiée dans l’interface. Le modèle actuel ne décide pas de remboursements.

La réponse originale est mise à jour lorsque la décision ou le résultat Jira change.
Le connecteur vérifie les changements toutes les 5 à 15 secondes. Une fois le ticket
créé, il ne suit pas les changements de statut ultérieurs effectués directement dans Jira.

## Fiabilité et sécurité

Le chemin est `Slack → Socket Mode → inbox PostgreSQL → worker Supervisor → réponse Slack`.
Socket Mode remplace ici le transport webhook ; n8n conserve ses propres workflows.
Le processus Slack est un adaptateur de confiance utilisant la même méthode
`EventStore.accept` que l’API, dans une transaction qui inclut la destination de réponse.
Il n’utilise pas les credentials publics de démonstration n8n pour attester une identité.

Le connecteur vérifie espace, canal, membre et mention du bot, applique la limitation
de débit partagée, puis persiste l’événement, le job, l’audit et le fil de réponse
**avant** d’accuser réception. Une nouvelle livraison de Slack retrouve le même événement.
Une panne de stockage ne reçoit pas d’accusé : Slack peut réessayer, dans les limites
de sa propre politique de livraison. Ce mécanisme ne garantit pas la récupération
de tous les événements pendant une longue indisponibilité.

Les réponses utilisent des blocs texte brut ; du texte issu du modèle ne peut pas
mentionner tout le canal ou fabriquer un bouton. Seuls les liens vers l’interface
configurée et le ticket Jira attendu sont générés. Les corps et jetons ne sont pas
journalisés. Les journaux du SDK sont masqués pour éviter les traces réseau contenant
des credentials ; le connecteur produit des logs JSON contrôlés.

Les publications Slack n’ont pas de retry réseau implicite. Un `429` est réessayé
au délai demandé, avec au maximum cinq tentatives. Une réponse perdue, un résultat
ambigu ou un arrêt après l’envoi passe en `uncertain` ; **aucun second message n’est
publié automatiquement**. Une erreur définitive passe en `failed`. Le traitement
métier et l’interface restent consultables indépendamment de la notification Slack.

Le diagnostic peut se faire sans afficher les corps des messages :

```shell
docker compose logs --tail 50 slack
docker compose exec postgres psql -U assistops -d assistops -c "SELECT event_id, state, error_code FROM slack_replies WHERE state IN ('failed', 'uncertain');"
```

Avant une reprise d’une notification incertaine, un opérateur doit vérifier le fil
Slack. Cette version ne fournit pas de renvoi automatique ni de rapprochement des
messages : il faudrait des permissions de lecture supplémentaires pour l’automatiser.
Ne pas recréer la demande métier pour réparer seulement une notification.

Les tests `tests/test_slack.py` couvrent l’isolation, les injections d’identité,
l’accusé après persistance, le rollback, les doublons, les erreurs réseau, les retries
bornés et le parcours proposition → décision → résultat Jira → mise à jour du même message.
Les scénarios de bout en bout vérifient les garanties suivantes :

| Situation | Résultat attendu |
| --- | --- |
| Même événement Slack livré plusieurs fois | Un seul traitement et une seule proposition. |
| Même approbation soumise plusieurs fois | Un seul envoi à Jira. |
| Proposition refusée | Aucun envoi à Jira ; le message Slack indique le refus. |
| Membre Slack non autorisé | Événement ignoré et acquitté, sans job ni réponse. |
| Timeout ou réponse HTTP 503 de Jira après envoi | Résultat incertain affiché dans Slack ; aucune répétition automatique de la création. |

Un résultat incertain ne prouve pas que Jira n’a rien créé : un opérateur doit vérifier
avant toute reprise. L’idempotence porte sur l’identifiant d’événement Slack ; deux
messages envoyés séparément constituent deux demandes, même si leur texte est identique.

Le modèle, Slack et Jira sont simulés dans ces parcours. PostgreSQL est réel, avec un
schéma isolé par test ; aucune clé externe ni création de ticket réel n’est nécessaire.
La CI les exécute dans son étape d’intégration PostgreSQL. Pour les relancer localement,
configurer `ASSISTOPS_TEST_DATABASE_URL`, puis exécuter :

```shell
python -m pytest tests/test_slack.py tests/test_jira.py -q
```

Références : [Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/),
[manifestes Slack](https://docs.slack.dev/reference/app-manifest/),
[portée connections:write](https://docs.slack.dev/reference/scopes/connections.write/).
