# ADR 0002 — Réception authentifiée et transactionnelle

Statut : accepté et implémenté pour l'entrée des événements.

## Décision

Chaque connecteur est identifié par `X-AssistOps-Connector`. Sa configuration lie
un secret HMAC d'au moins 32 caractères, un tenant, une source et une liste d'utilisateurs
autorisés. Le connecteur est responsable de vérifier l'identité à l'origine de la
demande ; le serveur refuse toute identité hors de cette liste. Les secrets doivent
être distincts par connecteur. Il s'agit d'un contrat de service à service, pas d'une
authentification utilisateur final. Les ACL documentaires, conversations et factures
seront vérifiées indépendamment lors de l'implémentation des agents.

La signature porte sur `timestamp + "." + corps brut`, avec fenêtre de ±300 secondes.
Un corps trop volumineux est interrompu à 64 Kio, y compris sans Content-Length.
La lecture du corps est limitée à 10 secondes par défaut. Le JSON doit être UTF-8,
sans champs inconnus ni clés dupliquées. L'identité n'est contrôlée qu'après signature.

Une transaction PostgreSQL en isolation Read Committed écrit l'événement, un travail
`pending` et l'audit d'acceptation. Le commit précède la réponse `202`.
Une contrainte unique `(tenant_id, source, event_id)` arbitre les accès concurrents.
Après un conflit d'insertion, une requête distincte lit le gagnant validé.
Un hash du JSON canonique validé permet de tolérer les changements d'espaces et
d'ordre des clés, mais un contenu différent renvoie `409`.

Le reçu expose un état d'acceptation `received`, pas l'état futur du traitement.
Un doublon exact retourne `202`, le même reçu et `duplicate: true` sans créer
de travail ou d'audit d'acceptation supplémentaire. Les logs de requête tracent
chaque livraison avec un correlation ID, sans corps ni signature.

Les migrations SQL sont versionnées et embarquées dans le paquet. Un verrou
transactionnel sérialise leur exécution ; la migration et sa version sont validées
ensemble. Compose exécute un service de migration avant l'API. La readiness vérifie
la version du schéma. Les anciennes données et les volumes ne sont pas supprimés.

## Limites et suites

Le travail `pending` est durable, mais aucun worker ne l'exécute encore. Les leases,
retries, reprises de travaux en cours et transitions métier seront ajoutés avec
le worker. Une panne après commit avant réponse se résout par une nouvelle livraison
signée avec le même event_id. Après une réponse 503 ou un timeout, le connecteur doit
retenter avec backoff et la même identité d'événement, sans supposer un rollback.

Les journaux SQL d'audit ne sont pas inviolables face à un administrateur de base.
Rôles SQL restreints, rétention, chiffrement au repos, pooling, rate limiting et
gestion/rotation des secrets restent à définir avant exposition de production.
Le Compose utilise explicitement une identité publique de démonstration sur loopback.
L'API hors Compose refuse les webhooks tant qu'aucun connecteur n'est configuré.

Références : [transactions Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html),
[isolation PostgreSQL](https://www.postgresql.org/docs/17/transaction-iso.html).
