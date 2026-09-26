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
| Protection API | Limitation de débit par connecteur, partagée via PostgreSQL | Implémenté |
| Fiabilité | Persistance transactionnelle, idempotence et audit de réception | Implémenté |
| Observabilité | Logs JSON, correlation IDs, contrôles de santé | Implémenté |
| Développement | Docker Compose, migrations, tests et workflow GitHub Actions | Implémenté |
| Traitement | Worker, retries, reprise après interruption et statut authentifié | Implémenté, modes démo, RAG et Supervisor |
| Orchestration | Supervisor LangGraph et routage en langage naturel | Implémenté, parcours bornés |
| Réponses | RAG Agent, citations vérifiées et abstention | Implémenté |
| Connaissances | Corpus synthétique réaliste, provenance et questions de référence | Disponible |
| Recherche | Ingestion OpenAI, recherche Qdrant filtrée et passages sourcés | Implémenté en CLI |
| Actions | Tools Agent : utilisateur, facture, proposition de ticket | Implémenté, services simulés |
| Approbations | Décision signée, expiration, audit et création idempotente | Implémenté, tickets simulés |
| Mémoire | Contexte privé entre messages et redémarrages | Implémenté, historique borné |
| Intégrations | Webhooks n8n authentifiés, signature et suivi du résultat | Implémenté, environnement local |
| Connecteurs externes | Slack, e-mail et API métier réelles | Prévu |
| Évaluation | Recall documentaire, tokens/coût estimé et latence RAG | Implémenté |
| Tracing | Export des traces vers LangSmith | Prévu |

Le Supervisor analyse une demande en langage naturel et peut enchaîner une recherche
documentaire, une lecture métier et une proposition de ticket. Son plan est validé
et conservé dans PostgreSQL avant l'exécution. Les modes démo et RAG direct restent
disponibles. Voir le [fonctionnement du Supervisor](docs/development.md#supervisor-langgraph)
et le [guide du RAG Agent](docs/rag-agent.md).

Avec le même identifiant de conversation, « Consulte INV-001 » peut être suivi de
« Prépare un ticket pour cette facture ». La mémoire conserve un contexte limité,
isolé par utilisateur et connecteur. Les données métier et documentaires sont
relues avec les droits actuels ; une confirmation en langage naturel ne remplace
jamais l'approbation signée. Voir la [mémoire conversationnelle](docs/development.md#mémoire-conversationnelle).

Les demandes structurées `tool_call` passent par le Tools Agent. La création d'un
ticket simulé attend une décision signée d'un autre utilisateur habilité. Les
données CRM et de facturation sont fictives ; aucun service métier externe n'est
connecté. Le [guide de développement](docs/development.md#outils-métier-simulés-et-approbations)
décrit les appels et le parcours d'approbation.

## Stack technique

**Socle :** Python · LangGraph · LangChain Core · FastAPI · OpenAI · PostgreSQL · Qdrant · Docker · pytest · structlog · GitHub Actions.

**Intégrations :** n8n. **Prévu :** LangSmith (export des traces).

Le [guide n8n](docs/n8n.md) décrit le démarrage du workflow, le contrat HTTP,
la gestion des identités et les limites du déploiement local.

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
Le débit des endpoints signés est limité par connecteur authentifié, avec réponses
`429` et `Retry-After`. Les politiques de rétention, la rotation des secrets et les
contrôles métier complémentaires font partie des travaux de préparation à la production.

La recherche obtient un Recall@5 documentaire de **96,875 %** sur les 16 questions
répondables du petit corpus synthétique de référence. Ce résultat ne mesure ni
la qualité de réponses générées ni une performance générale en production.
Les parcours HTTP métier simulés sont vérifiés en CI, avec approbation et rejeu.
Voir le [rapport](retrieval-reports/baseline.json)
et le [guide de recherche](docs/retrieval.md).

Le parcours RAG est également vérifié sur trois cas réels : réponse sourcée,
information absente et demande hors droits. Les [résultats](retrieval-reports/rag-smoke.json)
sont des contrôles ponctuels sur données synthétiques, pas un benchmark de production.

Le corpus de démonstration est **100 % synthétique** : politiques, FAQ et procédures
originales pour une entreprise fictive, avec versions et droits d'accès explicites.
Il ne contient aucun document réel importé ni aucune donnée client. Les questions
et réponses de référence sont séparées des documents de recherche pour éviter de
fausser l'évaluation. Voir le [guide du corpus](docs/synthetic-corpus.md).

## Documentation

- [RAG Agent : réponses sourcées, configuration et limites](docs/rag-agent.md)
- [Recherche documentaire : fonctionnement, coût et commandes](docs/retrieval.md)
- [Guide de développement et de vérification](docs/development.md)
- [Corpus synthétique : démarche, lecture et évaluation](docs/synthetic-corpus.md)
- [Inventaire et provenance des données](data/README.md)
- [Contrat du MVP et critères d’acceptation](docs/mvp.md)

## Organisation du dépôt

```text
src/assistops/       API, sécurité des webhooks, persistance et observabilité
src/assistops/migrations/
                    Migrations SQL versionnées
scripts/            Démonstrations et vérifications locales
data/               Documents synthétiques et jeux de référence séparés
tests/              Tests unitaires et d’intégration
docs/               Guides de développement, corpus, RAG et périmètre fonctionnel
.github/workflows/  Intégration continue
```
