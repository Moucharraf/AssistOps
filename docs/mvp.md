# Périmètre du MVP

## Premier parcours

Un utilisateur signale un problème de facturation. AssistOps recherche la procédure
interne, consulte une facture autorisée et propose un ticket. Un approbateur habilité
confirme ou refuse. Une confirmation produit un seul ticket, même après un doublon
de webhook ou une reprise après incident. Les API métier seront d'abord simulées.

## Entrée implémentée

`POST /v1/events`, enveloppe JSON stricte :

```json
{
  "event_id": "evt-001",
  "tenant_id": "demo",
  "user_id": "user-001",
  "conversation_id": "conversation-001",
  "source": "webhook",
  "message": "Comment contester ma facture INV-001 ? Propose un ticket."
}
```

Le tenant et l'identité sont vérifiés auprès du connecteur authentifié. Une identité
dans le JSON ou suggérée par le modèle ne suffit pas. L'identifiant de conversation
ne donne aucun droit. La mémoire est privée au tenant, connecteur, source,
utilisateur et identifiant de conversation ; les conversations partagées ne sont
pas implémentées.

Headers : `X-AssistOps-Connector`, `X-AssistOps-Timestamp`, `X-AssistOps-Signature`,
`X-Correlation-ID` optionnel. Signature : `v1=` suivi du HMAC-SHA256 hexadécimal
de `timestamp + "." + corps brut`, avec secret par connecteur. Comparaison en temps
constant, horodatage accepté à ±300 secondes, corps limité à 64 Kio.

Une réponse `202` signifie que l'événement, le travail en attente et l'audit sont
persistés transactionnellement. Une contrainte unique `(tenant_id, source, event_id)`
empêche les doublons ; réutiliser un identifiant avec un contenu différent retourne `409`.
Le reçu est stable après redémarrage. Le worker traite les appels métier structurés
avec le Tools Agent ; les autres messages utilisent le processeur configuré :
démo, RAG ou Supervisor LangGraph.
Les opérations métier sont simulées. Le statut et le résultat sont accessibles via
`POST /v1/events/status`, avec une requête signée et limitée à l'identité d'origine.

## Agents et approbation

- Supervisor LangGraph : décide de la séquence documentaire/métier.
- RAG Agent : recherche des documents autorisés, cite ses sources et signale l'absence de preuve.
- Tools Agent : `get_user`, `get_invoice`, `create_ticket`. Le serveur valide droits et arguments.

Les documents et sorties d'outils sont des données non fiables : leurs instructions
ne peuvent pas autoriser une action ou modifier les règles d'approbation.

États cibles : `received → processing → awaiting_approval → completed`, avec
`rejected` et `failed` comme issues possibles. L'approbation authentifiée lie
l'approbateur, le tenant, l'action, les arguments exacts et une expiration.
Modifier la proposition invalide l'approbation. Les transitions et l'audit sont
persistés dans PostgreSQL. `create_ticket` reçoit une clé d'idempotence stable.
Le simulateur garantira l'idempotence ; un service réel devra accepter cette clé
ou offrir une réconciliation. Un appel réseau et une transaction locale ne suffisent
pas à garantir ensemble une exécution unique après crash.

## Critères E2E du parcours cible

Les cas documentaires, les reprises du worker et le parcours structuré avec
outils simulés et approbations sont testés. Le routage LangGraph est testé avec
un modèle simulé ; un contrôle OpenAI réel couvre lecture de facture et proposition
de ticket. Les adaptateurs métier réels restent à implémenter.

1. Une question documentaire obtient une réponse avec sources autorisées.
2. L'absence de source est signalée.
3. Une facture appartenant à l'utilisateur est consultable.
4. Une facture d'un autre tenant est inaccessible.
5. Une création s'arrête en attente d'approbation.
6. Une approbation valide crée un ticket et son audit.
7. Un refus ne crée aucun ticket.
8. Un doublon d'événement ou d'approbation ne crée aucun ticket supplémentaire.
9. Une interruption permet une reprise depuis l'état persisté.
10. Une instruction malveillante dans un document ne contourne pas les droits.

Les tests HMAC, concurrence, retries, timeouts et limites complètent ces critères.

## Jalons

1. **Socle livré** : configuration, API, santé, logs, Docker et CI.
2. **Réception durable livrée** : migrations, événements, HMAC, idempotence et audit.
   Le worker, les retries, la reprise par expiration de réservation et le statut
   authentifié sont livrés avec les processeurs démo, RAG et Supervisor. Le plan
   LangGraph et son contexte sont persistés ; les checkpoints par étape restent à implémenter.
3. **RAG** : corpus synthétique et benchmark de référence livrés et documentés.
   Ingestion, embeddings et recherche Qdrant filtrée livrés en CLI.
   RAG Agent avec citations vérifiées, abstention et connexion au worker livré.
   Configuration et limites : [guide RAG](rag-agent.md).
4. **Métier simulé livré** : Tools Agent, lectures autorisées, ticket après approbation
   persistée, expiration et idempotence. Le Supervisor LangGraph route les demandes
   documentaires, métier ou mixtes sur un parcours borné.
   La mémoire privée conserve un contexte borné entre messages et redémarrages.
5. **Intégration** : n8n, connecteurs réels, LangSmith, limites et E2E.

La clé OpenAI configure les embeddings et les réponses générées ; les modèles sont
définis dans la configuration. Le corpus actuel est entièrement synthétique, sans contenu
externe importé. Le jeu versionné contient 20 questions : 16 avec sources attendues,
2 sans réponse disponible et 2 demandes à refuser. Le Recall@5 documentaire est
calculé sur les 16 premières ; quatre d'entre elles nécessitent deux documents.
Les cas d'abstention et de refus sont évalués séparément, sans score de recall fictif.
Voir le [guide du corpus](synthetic-corpus.md) pour la formule et les limites.
Le [guide de recherche](retrieval.md) documente la mesure réelle du Recall@5,
les tokens des embeddings et leur coût estimé. Le RAG Agent mesure aussi les tokens,
la latence et le coût estimé de génération ; LangSmith reste à intégrer.
