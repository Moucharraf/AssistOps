# Contrat du MVP — réception livrée, traitement métier à implémenter

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

Le tenant et l'identité seront vérifiés auprès du connecteur authentifié. Une identité
dans le JSON ou suggérée par le modèle ne suffit pas. Une conversation reste associée
à un tenant et à ses participants autorisés ; son identifiant ne donne aucun droit.

Headers : `X-AssistOps-Connector`, `X-AssistOps-Timestamp`, `X-AssistOps-Signature`,
`X-Correlation-ID` optionnel. Signature : `v1=` suivi du HMAC-SHA256 hexadécimal
de `timestamp + "." + corps brut`, avec secret par connecteur. Comparaison en temps
constant, horodatage accepté à ±300 secondes, corps limité à 64 Kio.

Une réponse `202` signifie que l'événement, le travail en attente et l'audit sont
persistés transactionnellement. Une contrainte unique `(tenant_id, source, event_id)`
empêche les doublons ; réutiliser un identifiant avec un contenu différent retourne `409`.
Le reçu est stable après redémarrage. Un worker exécute désormais un traitement
de démonstration sans action métier. Le statut et son résultat sont accessibles via
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

## Dix critères E2E à implémenter

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

Les tests HMAC, concurrence, retries, timeouts et limites s'y ajouteront.

## Jalons

1. **Socle livré** : configuration, API, santé, logs, Docker et CI.
2. **Réception durable livrée** : migrations, événements, HMAC, idempotence et audit.
   Le worker, les retries, la reprise par expiration de réservation et le statut
   authentifié sont livrés avec un processeur de démonstration. Les reprises des
   étapes internes LangGraph restent à implémenter avec les agents.
3. **RAG** : corpus synthétique, ingestion, embeddings, Qdrant et citations.
4. **Agents et métier** : LangGraph, outils simulés et approbations persistées.
5. **Intégration** : n8n, connecteurs réels, LangSmith, limites et E2E.

Les clés OpenAI et le choix du modèle seront nécessaires au jalon RAG. Le corpus
initial ne contiendra pas de données personnelles réelles. Un jeu versionné de
20 questions avec documents pertinents attendus permettra de mesurer le Recall@5
moyen : documents pertinents dans les cinq premiers résultats divisés par le nombre
de documents pertinents attendus, puis moyenne des questions. Avec une seule référence
par question, les résultats avancent par pas de 5 points : 83 % n'est pas possible
dans cette configuration. Latence, tokens et coût seront mesurés sur les appels réels.
