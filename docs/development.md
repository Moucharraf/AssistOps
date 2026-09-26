# Guide de développement

Les commandes ci-dessous s'exécutent depuis la racine du dépôt.
Voir le [README](../README.md) pour la présentation générale et le
[contrat du MVP](mvp.md) pour les jalons et critères d'acceptation.

## Démarrage local (PowerShell)

Prérequis : Python 3.12+ et Docker Desktop démarré pour les dépendances.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d postgres qdrant
.\.venv\Scripts\python.exe -m assistops.migrate
.\.venv\Scripts\python.exe -m uvicorn assistops.main:create_app --factory --reload --no-access-log
```

L'API démarre aussi sans Docker : `/health/live` répond 200, tandis que
`/health/ready` répond 503 si les dépendances sont indisponibles.
Les variables applicatives sont préfixées par `ASSISTOPS_` (voir `.env.example`).
Exception : `OPENAI_API_KEY` est aussi acceptée pour la recherche et le RAG Agent.
Pour un `.env` préexistant, ajouter `ASSISTOPS_WEBHOOK_CONNECTORS` depuis l'exemple
pour activer la réception locale. Ne pas remplacer les autres variables ou secrets.
Documentation locale : <http://localhost:8000/docs>.

Dans un second terminal, lancer le worker de démonstration :

```powershell
$env:ASSISTOPS_WORKER_PROCESSOR = 'demo'
.\.venv\Scripts\python.exe -m assistops.worker
```

Le mode par défaut est `disabled`. Le mode `demo` est interdit avec
`ASSISTOPS_ENVIRONMENT=production`. Le Compose active explicitement `demo`.
L'arrêt par Ctrl+C/SIGTERM termine le travail courant puis arrête les prises de
travaux. Une interruption brutale laisse une réservation récupérable après expiration.

```powershell
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
```

## Tout exécuter dans Docker

```powershell
docker compose up --build --wait
docker compose down
```

Les volumes conservent les données après `down`. Les volumes `assistops_mvp_postgres17_data` et
`assistops_mvp_qdrant115_data` isolent ce socle des anciennes données du projet.
Les ports sont exposés sur la boucle locale uniquement.
Les identifiants PostgreSQL sont publics et réservés au
développement. Ce Compose n'est pas une configuration de production. Le `.env`
n'est ni copié dans l'image ni injecté en bloc dans les conteneurs ; Compose
configure explicitement ses connexions internes.

## Vérification

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest
docker compose config --quiet
```

Pour vérifier le webhook dans Docker (identité publique locale de démonstration) :

```powershell
.\.venv\Scripts\python.exe scripts/send_demo_event.py --wait
```

Le script envoie deux fois un nouvel événement et vérifie que le reçu est identique.
Avec `--wait`, il attend aussi le résultat du worker (60 secondes maximum).
Les réponses `202` portent `receipt_id`, `event_id`, `status: received` et `duplicate`.
Erreurs : `401` signature absente/invalide/expirée, `403` identité non autorisée,
`408` délai de lecture du corps dépassé,
`409` identifiant réutilisé avec un autre contenu, `413` corps trop grand, `415`
format non supporté, `422` JSON/enveloppe invalide, `429` débit dépassé,
`503` configuration ou stockage indisponible. En cas de `429`, respecter
`Retry-After`. En cas de `503` ou timeout, retenter avec le même event_id et une
signature fraîche. L'accusé de réception ne signifie pas qu'un agent a exécuté la demande.

La signature utilise le secret du connecteur choisi dans `X-AssistOps-Connector` :
`v1=` + HMAC-SHA256 hexadécimal de `timestamp + "." + corps brut`.
`X-AssistOps-Timestamp` est un timestamp Unix en secondes (fenêtre de ±300 secondes).
Placer le résultat dans `X-AssistOps-Signature` et envoyer le corps exact signé
avec `Content-Type: application/json`. L'enveloppe est décrite dans le
[contrat du MVP](mvp.md) et la documentation interactive `/docs`.

## Limitation de débit

Les quatre endpoints signés (`/v1/events`, `/v1/events/status`,
`/v1/approvals/status` et `/v1/approvals/decide`) partagent une capacité par
**connecteur, tenant et source**. Elle est consommée après vérification HMAC,
avant le décodage JSON et l'exécution métier. Changer d'utilisateur, d'adresse IP
ou d'endpoint ne crée pas une capacité supplémentaire pour le même connecteur.
Un connecteur différent dispose de sa propre capacité.

Le limiteur utilise un réservoir de jetons (*token bucket*) :

| Variable | Défaut | Signification |
| --- | --- | --- |
| `ASSISTOPS_API_RATE_LIMIT_REQUESTS` | `120` | Capacité maximale du réservoir et taille de rafale |
| `ASSISTOPS_API_RATE_LIMIT_PERIOD_SECONDS` | `60` | Durée nécessaire pour reconstituer cette capacité |

Ces valeurs autorisent une rafale de 120 requêtes, puis reconstituent deux jetons
par seconde. **Ce n'est pas un plafond strict de 120 requêtes sur chaque minute** :
le réservoir se recharge pendant le trafic. Les seuils doivent être dimensionnés
selon le polling, le trafic des connecteurs et la capacité réelle du déploiement.
La configuration s'applique à tous les connecteurs ; les instances de l'API
doivent utiliser les mêmes valeurs et la même base PostgreSQL.

La migration 007 crée `connector_rate_limits`, avec une ligne par identité de
connecteur. Une transaction verrouille uniquement sa ligne, calcule la recharge
avec l'horloge PostgreSQL et consomme un jeton. Le solde survit aux redémarrages.
Les demandes concurrentes ne peuvent pas consommer le même jeton. Aucun secret,
corps de requête ou identifiant utilisateur n'est conservé dans cette table.

Un réservoir vide produit `429`, le code JSON `rate_limited`, un `Retry-After`
entier en secondes et `Cache-Control: no-store`. Aucune réception d'événement ni
action métier n'a alors lieu. Le délai indique le temps de recharge nécessaire ;
un autre appel concurrent peut consommer le jeton entre-temps.

Le client doit attendre ce délai et renvoyer **le même événement avec une signature
fraîche**. Les doublons authentifiés consomment eux aussi un jeton, puis retrouvent
leur reçu grâce à l'idempotence existante. Une requête signée dont le JSON ou
l'identité est invalide consomme sa capacité : le connecteur est déjà authentifié.
Une signature invalide ne consomme aucun jeton et ne crée aucune ligne.

Les scripts de démonstration respectent `Retry-After` avec au maximum cinq essais
et une fenêtre d'attente de 30 secondes ; ils renouvellent la signature sans
changer le corps. Au-delà, ils signalent l'erreur au lieu de réessayer indéfiniment.

Si PostgreSQL échoue ou si l'attente d'un verrou dépasse le timeout, l'API retourne
`503`, le code `rate_limit_unavailable` et `Retry-After: 1`. Elle ne poursuit pas
le traitement avec un compteur local. Une admission déjà consommée n'est pas
remboursée si le traitement suivant échoue. Les logs exposent le statut, le délai
et le correlation ID, sans corps ni signature.

Les endpoints de santé restent accessibles sans consommer cette capacité. Ce
limiteur protège les opérations authentifiées ; la limitation du trafic anonyme,
des connexions et des attaques volumétriques doit être assurée par le reverse
proxy ou la passerelle en amont. Il ne limite pas la taille de la file du worker.
Les lignes des anciens connecteurs restent en base après leur retrait de la
configuration ; leur nettoyage relève de la maintenance du déploiement.

Le Compose expose les deux variables. Après modification dans l'environnement,
recréer l'API avec `docker compose up -d api`. Vérification HTTP sur le Compose
local avec les valeurs par défaut, également exécutée en CI :

```powershell
.\.venv\Scripts\python.exe scripts/check_rate_limit.py
```

Ce script envoie une rafale de consultations d'un reçu inexistant avec le compte
de démonstration. Il ne crée aucun job et n'appelle aucun modèle. Il consomme
temporairement la capacité de `demo` ; exécuter les autres tests HTTP avant lui.
Les tests PostgreSQL couvrent la concurrence, la recharge, l'isolation et la
reprise dans une nouvelle instance d'API. Les tests HTTP couvrent les réponses
`429`/`503`, les signatures invalides et le rejeu après recharge.

Références : [HTTP 429 (RFC 6585)](https://www.rfc-editor.org/rfc/rfc6585#section-4),
[verrous PostgreSQL](https://www.postgresql.org/docs/17/explicit-locking.html).

## Consulter le traitement

`POST /v1/events/status` utilise les mêmes headers HMAC, calculés sur ce corps :

```json
{
  "receipt_id": "00000000-0000-0000-0000-000000000000",
  "tenant_id": "demo",
  "user_id": "user-001",
  "source": "webhook"
}
```

Remplacer `receipt_id` par le reçu de l'envoi initial. La réponse expose `status`
(`pending`, `processing`, `awaiting_approval`, `completed`, `failed`), `attempts`, `result` et `last_error`.
Un reçu absent ou appartenant à un autre utilisateur/connecteur retourne `404`.
Le statut `completed` signifie que le traitement a terminé ; `result.outcome`
indique s'il a répondu, refusé ou rencontré une erreur. Le processeur de
démonstration produit `business_action_executed: false`.
Les événements déjà terminés en démonstration ne seront pas rejoués automatiquement
lors du branchement des agents ; envoyer de nouveaux événements pour les tester.

Valeurs par défaut : polling 1 s, traitement 20 s maximum, réservation 60 s,
3 tentatives, backoff initial 2 s puis exponentiel (plafond 60 s). Voir les variables
`ASSISTOPS_WORKER_*` dans `.env.example`. La réservation doit dépasser le timeout
d'au moins 15 s. Les erreurs retournées sont des codes filtrés, pas les exceptions brutes.
La readiness de l'API contrôle les dépendances et le schéma, pas la disponibilité du worker.

## Garanties du traitement

Le connecteur atteste l'identité de l'utilisateur auprès de l'API : la signature
HMAC authentifie le connecteur, pas directement l'utilisateur final. Chaque
connecteur doit avoir son propre secret et vérifier l'identité à la source.

L'événement, le job et l'audit sont enregistrés dans une même transaction avant
la réponse `202`. L'unicité `(tenant_id, source, event_id)` empêche les doublons
concurrents. Après une réponse perdue, renvoyer le même événement signé permet
de retrouver son reçu sans créer un second job.

Le worker utilise `FOR UPDATE SKIP LOCKED` pour réserver un job sans bloquer les
autres workers. La transaction se termine avant le traitement externe. Un jeton
et une expiration empêchent un worker ayant perdu sa réservation d'enregistrer
un résultat obsolète. Le résultat et son audit sont validés ensemble.

Après un crash, un appel externe peut être répété si son résultat n'a pas été
enregistré. Les futurs outils métier devront donc gérer leur propre idempotence.
Les particularités du RAG, notamment ses erreurs terminales et ses limites de
contexte, sont décrites dans le [guide RAG](rag-agent.md).

Les migrations sont sérialisées par un verrou PostgreSQL ; chaque migration et
son numéro de version sont validés ensemble. Les audits en base restent modifiables
par un administrateur : ils ne constituent pas un journal inviolable.

## Tests d'intégration

Tests PostgreSQL réels, dans des schémas temporaires isolés supprimés après chaque test :

```powershell
$env:ASSISTOPS_TEST_DATABASE_URL = 'postgresql://assistops:assistops-local-only@localhost:5432/assistops'
.\.venv\Scripts\python.exe -m pytest -m integration
```

Les tests unitaires simulent les dépendances externes. Les tests d'intégration
vérifient concurrence, rollback et persistance sur PostgreSQL. La CI démarre Compose,
exécute ces tests et vérifie un webhook signé, son doublon et le résultat du worker par HTTP.
Le parcours HTTP métier simulé vérifie aussi les approbations et les doublons.
Les dépendances directes sont fixées ; le verrouillage transitif reste à ajouter.

## Corpus synthétique et évaluation documentaire

Le [guide dédié](synthetic-corpus.md) explique les documents, leur origine entièrement
synthétique et la distinction entre tests du calcul de métrique et performance RAG.
Depuis la racine, sans services externes :

```powershell
.\.venv\Scripts\python.exe -m assistops.corpus
.\.venv\Scripts\python.exe -m pytest tests/test_corpus.py tests/test_retrieval_eval.py -q
```

La validation est également exécutée en CI. Elle vérifie notamment les références
de preuve, les droits des sources attendues et la séparation de l'évaluation.
L'ingestion OpenAI et la recherche Qdrant sont disponibles en CLI : voir le
[guide détaillé](retrieval.md). Le [RAG Agent](rag-agent.md) ajoute les réponses sourcées et le mode worker `rag`.
Pour les tests Qdrant, définir `ASSISTOPS_TEST_QDRANT_URL=http://localhost:6333`.
Ces tests utilisent des vecteurs fictifs et ne consomment aucun crédit OpenAI.

## Supervisor LangGraph

Le mode `supervisor` traite les messages sans `tool_call`. Un appel à
`gpt-4.1-mini-2025-04-14` propose un plan JSON strict, puis Python valide les
arguments. Le modèle reçoit le texte de la demande et un court contexte privé
des échanges précédents. Il ne choisit
ni l'identité, ni le tenant, ni les droits, ni la décision d'approbation.

```text
Message → plan validé et persisté → RAG éventuel → lecture éventuelle
        → proposition éventuelle → résultat / attente d'approbation
```

Le graphe autorise au maximum une question documentaire, une lecture (`get_user`
ou `get_invoice`) et une proposition de ticket. Les identifiants doivent figurer
dans le message ou le contexte autorisé. Sans historique, la question documentaire
doit être un extrait exact du message ; avec historique, elle peut être reformulée
pour résoudre une référence, puis elle est recherchée à nouveau dans Qdrant. Chaque
agent applique ses propres contrôles d'accès. Un refus, une abstention ou une
indisponibilité arrête les étapes suivantes. Il n'existe pas de boucle autonome
qui invente des tâches supplémentaires.

Pour activer ce mode dans Docker, avec la clé OpenAI dans l'environnement et
le corpus déjà indexé selon le [guide de recherche](retrieval.md) :

```powershell
$env:ASSISTOPS_AI_PROCESSOR = 'supervisor'
docker compose -f compose.yaml -f compose.rag.yaml up --build --wait
```

`ASSISTOPS_AI_PROCESSOR` sélectionne le mode dans cet override Compose ; sa valeur
par défaut est `rag`. Pour revenir au RAG direct, définir cette variable à `rag`
et relancer la même commande. Pour un worker Python, utiliser
`ASSISTOPS_WORKER_PROCESSOR=supervisor`, un timeout de 60 secondes et une lease
de 90 secondes, avec les connexions et permissions nécessaires.

Envoyer un événement signé habituel, sans `tool_call`, avec par exemple :

- « Quel est le délai pour contester une facture ? » : recherche documentaire.
- « Consulte le montant et le statut de la facture INV-001. » : lecture métier.
- « Quel est le délai pour contester une facture ? Consulte INV-001 puis prépare
  un ticket pour contester une ligne incorrecte. » : parcours mixte.

Une demande ambiguë ou sans identifiant nécessaire peut retourner
`clarification_required`. Envoyer alors un **nouvel événement dans la même
conversation** avec la précision demandée, par exemple « INV-001 ».
Le routage sémantique dépend du modèle ; sa précision générale reste à évaluer.

Le résultat porte `processor: supervisor`. `result.supervisor.steps` décrit les
étapes exécutées ; `routing_usage` contient tokens, latence et coût estimé du
routage. `context_turns` indique combien de tours précédents ont été utilisés.
`document_answer` et `read_result` conservent les résultats intermédiaires
lorsqu'ils existent, y compris après la décision humaine. Le ticket reste soumis
aux [approbations signées](#outils-métier-simulés-et-approbations).

La migration 005 ajoute `supervisor_plans`. Le premier plan enregistré pour un
événement est immuable et réutilisé après une interruption. La migration 006
y ajoute le contexte exact utilisé pour ce plan. Un changement des
rôles configurés invalide sa reprise. Cette persistance **n'est pas un checkpoint
LangGraph de chaque étape** : une lecture ou un appel RAG peut être répété après
un crash. Les propositions de ticket restent idempotentes. Un crash avant la
sauvegarde du plan peut aussi provoquer un nouvel appel de routage.

Une demande documentaire via le Supervisor nécessite un appel de routage, puis
une recherche et une génération RAG. Une demande métier seule utilise un appel
de routage ; un `tool_call` explicite n'appelle pas le modèle. Le routeur limite
sa sortie à 450 tokens. Aucun appel supplémentaire ne reformule les résultats.
L'export LangSmith est explicitement désactivé autour du graphe, même si des
variables de tracing existent : la politique de masquage reste à implémenter.

Vérification volontairement payante, avec le Supervisor actif :

```powershell
.\.venv\Scripts\python.exe scripts/check_business_flow.py --natural-ticket
```

Ce test demande en langage naturel la lecture de `INV-001` puis un ticket. Il
vérifie l'attente, simule la décision du compte fictif `reviewer-001` et vérifie
le rejeu sans second ticket. Toutes les données et actions métier sont
**synthétiques**, pour tester le parcours sans système client réel. Il écrit
`.cache/supervisor-smoke.json` et ne tourne pas en CI.
Ce contrôle ponctuel ne mesure pas la qualité générale du routage.

Les tests automatisés simulent OpenAI et couvrent les trois types de demandes,
les plans invalides, les identifiants inventés, les refus, la concurrence
des plans et la reprise sur PostgreSQL. Le scénario mixte est testé avec des
doublures du modèle ; le test payant ci-dessus couvre lecture et proposition.

Implémentation : `supervisor.py` porte le graphe et le plan ; `generation.py`
mutualise le transport OpenAI borné avec le RAG. Références :
[routage LangGraph](https://docs.langchain.com/oss/python/langgraph/workflows-agents),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Mémoire conversationnelle

La mémoire est active avec le mode `supervisor`. Elle utilise les événements,
plans et résultats déjà présents dans PostgreSQL ; aucun service ni modèle
supplémentaire n'est nécessaire. Une nouvelle instance du worker retrouve le
contexte depuis la base.

Pour continuer un échange, garder le même `conversation_id`, la même identité et
le même connecteur, mais utiliser un **nouvel `event_id` pour chaque message**.
Un identifiant d'événement déjà utilisé reste réservé au rejeu du même contenu.
Exemple, après réception du résultat de chaque message :

| Message | Comportement attendu |
| --- | --- |
| « Consulte le montant de la facture INV-001. » | Lecture de la facture autorisée |
| « Prépare un ticket pour cette facture : une ligne est incorrecte. » | Proposition pour INV-001, en attente de validation |
| « Oui. » | Orientation vers le canal d'approbation, aucun ticket créé |
| Décision signée par `reviewer-001` via l'API d'approbation | Création du ticket simulé |

Le contexte est strictement privé à la combinaison **tenant, connecteur, source,
utilisateur et conversation**. Réutiliser le nom d'une conversation depuis un
autre utilisateur ou canal ne permet pas de lire son historique. Il n'existe pas
encore de conversation partagée entre plusieurs participants.

Le routeur reçoit au maximum **quatre tours précédents et 4 000 octets UTF-8 de
contexte JSON**. Chaque tour contient le message utilisateur, l'issue du traitement
et les références du plan utiles au suivi : facture, utilisateur, question
documentaire ou clarification. Les tours sont conservés entiers, du plus récent
vers le plus ancien jusqu'à atteindre une limite, puis présentés chronologiquement.
Un tour trop volumineux peut donc laisser un contexte vide.

Les réponses générées, extraits documentaires, montants et profils retournés par
les outils ne sont pas réinjectés dans le modèle. Une nouvelle question provoque
une nouvelle recherche ou lecture avec les droits actuels. Le texte saisi par
l'utilisateur peut toutefois contenir des informations personnelles : il fait
partie du contexte envoyé à OpenAI. L'historique reste une entrée non fiable et
ne peut attribuer des droits ni autoriser une approbation.

Le serveur bloque aussi une nouvelle proposition pour la même facture dans la
même conversation privée tant qu'une proposition non expirée attend une décision.
Cette règle s'applique même si le modèle interprète mal « oui » et demande un
nouveau ticket. Un verrou transactionnel protège également les appels concurrents ;
le rejeu du même événement conserve sa proposition d'origine.

Seuls les tours du Supervisor terminés ou en attente d'approbation sont retenus.
Une issue non réutilisable (refus, erreur, abstention) ou une empreinte de rôles
différente coupe la remontée dans cet historique. Les appels `tool_call` directs
et le mode RAG seul n'alimentent pas cette mémoire. Le modèle peut encore mal
interpréter une référence ambiguë ; préciser l'identifiant reste possible.

Les workers Supervisor prennent les messages d'une même conversation privée dans
l'ordre de réception en base. Un traitement en cours ou en attente de retry
bloque les suivants ; une attente d'approbation ne les bloque pas. Les autres
conversations peuvent avancer en parallèle. Tous les workers d'une même file
doivent utiliser le même mode ; attendre le résultat avant d'envoyer une précision
reste le parcours client recommandé.

Le plan et son contexte sont enregistrés ensemble, avec une seule version gagnante
en cas de concurrence. Une reprise réutilise cet instantané ; les étapes métier
conservent leurs contrôles et leur idempotence. Il ne s'agit toujours pas de
checkpoints LangGraph par étape.

Changer de `conversation_id` commence un échange sans contexte. Cela **ne supprime
pas les données déjà persistées**. La fenêtre de quatre tours limite les données
envoyées au modèle, pas leur rétention en base ; la purge et la politique de
rétention restent à implémenter.

Le suivi utilise le même appel de routage que les demandes autonomes ;
le volume de tokens entrants augmente avec le contexte.
Vérification HTTP payante sur les données entièrement synthétiques du Compose :

```powershell
.\.venv\Scripts\python.exe scripts/check_business_flow.py --memory
```

Le script effectue trois appels de routage pour le parcours du tableau, puis
simule explicitement la décision du compte d'approbation de test. Il vérifie
aussi les doublons et écrit `.cache/memory-smoke.json`. Il ne tourne pas en CI.
Les tests de `test_memory.py`, exécutés en CI sans OpenAI réel, couvrent notamment
l'isolation, les limites de contexte, les références inventées, une nouvelle
instance de worker, la reprise après crash, les droits actuels et la concurrence.

Le contexte est géré par l'application avec `store=false`, selon le principe de
[gestion explicite de l'état conversationnel](https://developers.openai.com/api/docs/guides/conversation-state).
Le transport conserve son plafond global de 16 000 octets par appel.

## Outils métier simulés et approbations

Les événements contenant `tool_call` sont traités par le Tools Agent avant le
processeur démo, RAG ou Supervisor. Ce composant est déterministe : il valide et
exécute un appel structuré. Le Supervisor choisit les appels depuis un message
en langage naturel ; fournir directement `tool_call` évite cet appel OpenAI.

Le Compose local active `ASSISTOPS_BUSINESS_BACKEND=synthetic`. Hors Compose,
le backend est désactivé par défaut ; son activation est interdite avec
`ASSISTOPS_ENVIRONMENT=production`. Les rôles proviennent exclusivement de
`ASSISTOPS_BUSINESS_USER_ROLES`, configuré de façon identique pour l'API et le worker.

| Rôle | Droits |
| --- | --- |
| `customer` | Lire son profil et ses factures ; proposer un ticket pour sa facture |
| `support_agent` | Lire les profils et factures du tenant ; proposer un ticket |
| `ticket_approver` | Examiner et décider les propositions du tenant et du connecteur |

Un approbateur ne peut jamais approuver sa propre demande, même s'il possède
plusieurs rôles. Ces rôles sont distincts des rôles documentaires du RAG.
Une facture inaccessible et une facture inexistante produisent le même refus.

Exemple de corps pour `POST /v1/events`, à signer comme les autres webhooks :

```json
{
  "event_id": "ticket-demo-001",
  "tenant_id": "demo",
  "user_id": "user-001",
  "conversation_id": "conversation-demo",
  "source": "webhook",
  "message": "Je souhaite contester une ligne de ma facture.",
  "tool_call": {
    "name": "create_ticket",
    "invoice_id": "INV-001",
    "subject": "Contestation de facture",
    "description": "Le montant d'une ligne semble incorrect."
  }
}
```

Les autres appels sont `{"name":"get_user"}` (profil du demandeur) et
`{"name":"get_invoice","invoice_id":"INV-001"}`. Un agent support peut fournir
`target_user_id` à `get_user`. Ni le texte de la demande ni les arguments ne peuvent
attribuer un rôle, changer de tenant ou approuver une action.

Pour une création, le statut du job devient `awaiting_approval`. Son résultat
contient `proposal.id`, les arguments exacts, leur empreinte `arguments_hash` et
`expires_at`. **Aucun ticket n'existe à ce stade.** Les arguments ne sont pas
modifiables ; une correction nécessite un nouvel événement et une nouvelle décision.

L'approbateur consulte `POST /v1/approvals/status` avec un corps signé contenant
`tenant_id`, `user_id`, `source` et `proposal_id`. Il décide ensuite via
`POST /v1/approvals/decide` avec le même contexte, l'empreinte affichée et :

```json
{
  "tenant_id": "demo",
  "user_id": "reviewer-001",
  "source": "webhook",
  "proposal_id": "UUID de la proposition examinée",
  "arguments_hash": "empreinte de 64 caractères retournée lors de la consultation",
  "decision": "approved"
}
```

`decision` accepte `approved` ou `rejected`. Le connecteur et la source doivent
être ceux de la demande initiale. La signature atteste l'identité transmise par le
connecteur ; ce dernier doit authentifier la personne qui prend la décision.
Les identifiants publics du Compose servent uniquement aux tests locaux. Il n'y
a pas encore d'interface utilisateur ou de bouton Slack pour cette validation.

La validité est de 15 minutes par défaut (`ASSISTOPS_APPROVAL_TTL_SECONDS`). Une
proposition périmée devient `expired` lors de sa consultation ou d'une tentative
de décision, sans création de ticket. Sans consultation, le job peut encore
afficher `awaiting_approval` : il n'existe pas de tâche de nettoyage périodique.

La décision verrouille la proposition et vérifie de nouveau les droits du
demandeur. Le ticket simulé, la décision, le résultat du job et l'audit sont
enregistrés dans une seule transaction PostgreSQL. Une décision répétée retourne
le même ticket ; une décision contradictoire renvoie `409`. Une empreinte différente
renvoie également `409`. Un refus et une expiration terminent le job avec un
résultat explicite, sans ticket. Une reprise après crash réutilise la proposition
existante sans prolonger sa validité.

Les résultats portent `origin: synthetic` et `business_action_executed: false`.
Après création locale, `simulated_action_executed: true` et `ticket_id` désignent
le ticket dans `synthetic_tickets`. Aucun CRM, service de facturation ou logiciel
de support externe n'est appelé. La garantie transactionnelle du simulateur ne
s'étend pas à un futur fournisseur distant : son adaptateur devra gérer les
clés d'idempotence, les timeouts et la réconciliation.

Vérification HTTP automatisée, également exécutée en CI :

```powershell
.\.venv\Scripts\python.exe scripts/check_business_flow.py
```

Le script utilise les comptes fictifs `user-001` et `reviewer-001`. **Il simule
explicitement la décision humaine pour le test** ; le worker ne s'auto-approuve
jamais. Il vérifie les lectures autorisées, le refus d'une autre facture, l'attente,
l'approbation, le rejet et les doublons. Les tests PostgreSQL vérifient aussi la
concurrence, l'expiration, la révocation des droits et le rollback de l'audit.

## Structure du dépôt

```text
src/assistops/     API, configuration, santé et observabilité
tests/            Tests automatisés du socle
docs/mvp.md       Contrat fonctionnel et critères d'acceptation
.github/workflows/ci.yml
```

Voir le [contrat du MVP](mvp.md) pour le périmètre livré et les fonctions prévues.
Références : [tests FastAPI](https://fastapi.tiangolo.com/tutorial/testing/),
[ordre de démarrage Compose](https://docs.docker.com/compose/how-tos/startup-order/).
