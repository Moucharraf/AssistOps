# AssistOps

Assistant IA pour la recherche documentaire et les opérations métier avec validation humaine.

## État actuel

Le **socle du MVP** est implémenté : FastAPI, configuration typée, logs JSON structlog,
correlation IDs, erreurs filtrées, sondes PostgreSQL/Qdrant, Docker Compose et workflow CI.
Aucune route métier n'accepte encore de demande. LangGraph, RAG, outils métier,
conversations persistées, approbations, HMAC, idempotence, rate limiting, n8n et
LangSmith constituent les jalons suivants. Aucun score RAG ni résultat E2E métier
n'est annoncé comme acquis.

## Démarrage local (PowerShell)

Prérequis : Python 3.12+ et Docker Desktop démarré pour les dépendances.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d postgres qdrant
.\.venv\Scripts\python.exe -m uvicorn assistops.main:create_app --factory --reload --no-access-log
```

L'API démarre aussi sans Docker : `/health/live` répond 200, tandis que
`/health/ready` répond 503 si les dépendances sont indisponibles.
Les variables applicatives sont préfixées par `ASSISTOPS_` (voir `.env.example`).
Les variables sans ce préfixe ne configurent pas ce socle.
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

Les tests Python simulent les dépendances externes. La CI ajoute un démarrage
Compose et vérifie `/health/ready` contre les vrais services. Ce contrôle
d'infrastructure ne constitue pas encore la suite E2E métier.
Les dépendances directes sont fixées ; le verrouillage transitif reste à ajouter.

## Structure

```text
src/assistops/     API, configuration, santé et observabilité
tests/            Tests automatisés du socle
docs/mvp.md       Contrat fonctionnel et critères d'acceptation
docs/adr/         Décisions d'architecture
.github/workflows/ci.yml
```

Voir le [contrat du MVP](docs/mvp.md) et la [décision d'architecture](docs/adr/0001-mvp.md).
Références : [tests FastAPI](https://fastapi.tiangolo.com/tutorial/testing/),
[ordre de démarrage Compose](https://docs.docker.com/compose/how-tos/startup-order/).
