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
Les variables sans ce préfixe ne configurent pas ce socle.
Pour un `.env` préexistant, ajouter `ASSISTOPS_WEBHOOK_CONNECTORS` depuis l'exemple
pour activer la réception locale. Ne pas remplacer les autres variables ou secrets.
Documentation locale : <http://localhost:8000/docs>.

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
.\.venv\Scripts\python.exe scripts/send_demo_event.py
```

Le script envoie deux fois un nouvel événement et vérifie que le reçu est identique.
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

Tests PostgreSQL réels, dans des schémas temporaires isolés supprimés après chaque test :

```powershell
$env:ASSISTOPS_TEST_DATABASE_URL = 'postgresql://assistops:assistops-local-only@localhost:5432/assistops'
.\.venv\Scripts\python.exe -m pytest -m integration
```

Les tests unitaires simulent les dépendances externes. Les tests d'intégration
vérifient concurrence, rollback et persistance sur PostgreSQL. La CI démarre Compose,
exécute ces tests et vérifie un webhook signé et son doublon par HTTP.
La suite E2E métier reste à implémenter.
Les dépendances directes sont fixées ; le verrouillage transitif reste à ajouter.

## Structure

```text
src/assistops/     API, configuration, santé et observabilité
tests/            Tests automatisés du socle
docs/mvp.md       Contrat fonctionnel et critères d'acceptation
docs/adr/         Décisions d'architecture
.github/workflows/ci.yml
```

Voir le [contrat du MVP](mvp.md) et la [décision d'architecture](adr/0001-mvp.md).
La [réception durable](adr/0002-durable-ingress.md) documente les garanties et limites.
Références : [tests FastAPI](https://fastapi.tiangolo.com/tutorial/testing/),
[ordre de démarrage Compose](https://docs.docker.com/compose/how-tos/startup-order/).
