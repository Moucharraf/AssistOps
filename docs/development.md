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
format non supporté, `422` JSON/enveloppe invalide, `503` configuration ou stockage
indisponible. En cas de `503` ou timeout, retenter avec le même event_id et une
signature fraîche. L'accusé de réception ne signifie pas qu'un agent a exécuté la demande.

La signature utilise le secret du connecteur choisi dans `X-AssistOps-Connector` :
`v1=` + HMAC-SHA256 hexadécimal de `timestamp + "." + corps brut`.
`X-AssistOps-Timestamp` est un timestamp Unix en secondes (fenêtre de ±300 secondes).
Placer le résultat dans `X-AssistOps-Signature` et envoyer le corps exact signé
avec `Content-Type: application/json`. L'enveloppe est décrite dans le
[contrat du MVP](mvp.md) et la documentation interactive `/docs`.

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
(`pending`, `processing`, `completed`, `failed`), `attempts`, `result` et `last_error`.
Un reçu absent ou appartenant à un autre utilisateur/connecteur retourne `404`.
Le statut `completed` signifie ici que le **processeur de démonstration** a terminé,
pas qu'une opération métier a eu lieu. Il produit `business_action_executed: false`.
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
Les particularités du RAG, notamment ses erreurs terminales et les réservations
de budget, sont décrites dans le [guide RAG](rag-agent.md).

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
La suite E2E métier reste à implémenter.
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
