# AssistOps

**Assistant IA multi-agents pour l’automatisation des opérations.**

AssistOps vise à réunir la recherche documentaire et l’exécution d’actions métier
au sein d’une même conversation. À partir d’une demande reçue par webhook, Slack
ou e-mail, il doit retrouver les procédures utiles, consulter les données métier
et demander une validation humaine avant les actions sensibles.

Le projet est développé progressivement autour de trois priorités : fiabilité,
traçabilité et contrôle des accès.

## Cas d’usage

- Retrouver une procédure interne et répondre avec des sources vérifiables.
- Consulter les informations d’un utilisateur ou d’une facture autorisée.
- Proposer un ticket de support, puis le créer après approbation.
- Conserver le contexte d’une demande et reprendre un traitement interrompu.

Exemple de parcours cible : « Comment contester ma facture ? » → recherche de la
procédure → consultation de la facture → proposition de ticket → validation humaine.

## Architecture

```mermaid
flowchart LR
    Channels[Slack / E-mail / Webhook] --> N8N[n8n]
    N8N --> API[FastAPI]
    API --> PG[(PostgreSQL)]
    PG --> Worker[Worker]
    Worker --> Supervisor[Supervisor LangGraph]
    Supervisor --> RAG[RAG Agent]
    Supervisor --> Tools[Tools Agent]
    RAG --> Qdrant[(Qdrant)]
    Tools --> Business[CRM / Facturation / Tickets]
    Tools --> Approval[Validation humaine]
    Approval --> PG
    Supervisor --> PG
```

Cette architecture décrit la cible du projet. n8n prend en charge les connecteurs
et l’enrichissement des événements ; FastAPI vérifie et persiste les demandes ;
LangGraph orchestre les agents. PostgreSQL porte les événements et les états de
traitement, tandis que Qdrant sert à la recherche documentaire.

## Fonctionnalités

| Domaine | Capacité | Disponibilité |
| --- | --- | --- |
| Réception | Webhooks HMAC-SHA256, contrôle des identités, validation des entrées | Implémenté |
| Fiabilité | Persistance transactionnelle, idempotence et audit de réception | Implémenté |
| Observabilité | Logs JSON, correlation IDs, contrôles de santé | Implémenté |
| Développement | Docker Compose, migrations, tests et workflow GitHub Actions | Implémenté |
| Traitement | Worker, retries, reprise après interruption et statut authentifié | Implémenté, processeur démo |
| Orchestration | Supervisor LangGraph, RAG Agent et Tools Agent | Prévu |
| Connaissances | Corpus synthétique réaliste, provenance et questions de référence | Disponible |
| Recherche | Ingestion, embeddings, recherche Qdrant et citations | Prévu |
| Actions | Outils CRM/facturation/tickets et approbations humaines | Prévu |
| Mémoire | Conversations persistées entre sessions | Prévu |
| Intégrations | n8n, Slack, e-mail et API métier réelles | Prévu |
| Évaluation | LangSmith, latence/tokens/coût, évaluation RAG et E2E métier | Prévu |

Le worker exécute actuellement un processeur de démonstration et conserve son résultat
dans PostgreSQL. Ce résultat confirme le fonctionnement du traitement asynchrone ;
il ne répond pas encore à la demande métier et n'exécute aucune action externe.

## Stack technique

**Socle :** Python · FastAPI · PostgreSQL · Qdrant · Docker · pytest · structlog · GitHub Actions.

**Intégrations prévues :** LangGraph · LangChain · OpenAI · n8n · LangSmith.

## Démarrage rapide

Prérequis : Docker avec Docker Compose. Depuis la racine du dépôt :

```shell
docker compose up --build --wait
```

Compose démarre PostgreSQL et Qdrant, applique les migrations puis lance l’API et le worker.

- Documentation interactive : [localhost:8000/docs](http://localhost:8000/docs)
- Disponibilité des dépendances : [localhost:8000/health/ready](http://localhost:8000/health/ready)
- Disponibilité de l’API : [localhost:8000/health/live](http://localhost:8000/health/live)

Cet environnement utilise des identifiants publics de démonstration et des ports
limités à la machine locale. Il est destiné au développement.

Pour arrêter les services en conservant les données :

```shell
docker compose down
```

Le [guide de développement](docs/development.md) détaille l’installation Python,
la configuration, l’envoi d’un webhook signé et l’exécution des tests.

## Qualité et sécurité

Les tests couvrent l’authentification des webhooks, les entrées invalides,
l’isolation des identités, l’idempotence concurrente et les transactions PostgreSQL,
ainsi que les reprises après expiration, les retries et le rejet des résultats obsolètes.
Le workflow CI inclut les contrôles de code, les tests et une vérification HTTP
sur la stack conteneurisée.

Les signatures et corps de requête ne sont pas journalisés. Les secrets sont
fournis par configuration ; `.env` est exclu de Git et des images Docker.
Le rate limiting, les politiques de rétention, la rotation des secrets et les
contrôles métier complémentaires font partie des travaux de préparation à la production.

Les objectifs de Recall@5 et les scénarios E2E métier seront évalués sur des jeux
versionnés. Aucun score de performance non mesuré n’est présenté comme résultat acquis.

Le corpus de démonstration est **100 % synthétique** : politiques, FAQ et procédures
originales pour une entreprise fictive, avec versions et droits d'accès explicites.
Il ne contient aucun document réel importé ni aucune donnée client. Les questions
et réponses de référence sont séparées des documents de recherche pour éviter de
fausser l'évaluation. Voir le [guide du corpus](docs/synthetic-corpus.md).

## Documentation

- [Guide de développement et de vérification](docs/development.md)
- [Corpus synthétique : démarche, lecture et évaluation](docs/synthetic-corpus.md)
- [Inventaire et provenance des données](data/README.md)
- [Contrat du MVP et critères d’acceptation](docs/mvp.md)
- [Architecture et responsabilités](docs/adr/0001-mvp.md)
- [Réception durable : garanties et limites](docs/adr/0002-durable-ingress.md)
- [Worker : réservations, retries et reprise](docs/adr/0003-worker.md)

## Organisation du dépôt

```text
src/assistops/       API, sécurité des webhooks, persistance et observabilité
src/assistops/migrations/
                    Migrations SQL versionnées
scripts/            Démonstrations et vérifications locales
data/               Documents synthétiques et jeux de référence séparés
tests/              Tests unitaires et d’intégration
docs/               Guides, contrat fonctionnel et décisions d’architecture
.github/workflows/  Intégration continue
```
