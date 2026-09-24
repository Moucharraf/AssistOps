# ADR 0003 — Worker avec réservation expirante

Statut : accepté et implémenté. Complète l'ADR 0002.

## Décision

Un processus Python indépendant prend un travail à la fois dans PostgreSQL avec
`FOR UPDATE SKIP LOCKED`. Plusieurs workers peuvent consommer la même file.
La transaction de réservation incrémente le compteur de tentatives, attribue un
jeton UUID, fixe une expiration à partir de l'horloge PostgreSQL et écrit l'audit.
Elle se termine avant l'exécution du processeur : aucun verrou SQL n'est conservé
pendant un appel externe.

Le worker enregistre le résultat et l'audit dans une même transaction, à condition
que le jeton soit toujours courant et la réservation encore valide. Une réservation
expirée peut être reprise ; un ancien worker ne peut plus écrire de résultat ou
planifier de retry après avoir perdu son droit de traitement.

Les erreurs du processeur et les timeouts planifient des retries avec backoff
exponentiel borné. Le nombre de tentatives comprend les reprises après crash.
Au plafond, le travail passe en `failed`, y compris si chaque tentative s'est
interrompue sans enregistrer de résultat. Un événement stocké invalide échoue
définitivement. Les erreurs SQL laissent la réservation expirer lorsque le résultat
du commit est incertain ; elles ne provoquent pas d'acquittement en mémoire.

Ctrl+C/SIGTERM demande un arrêt après le travail courant. L'attente entre deux
lectures de la file peut être interrompue immédiatement. Les logs reprennent le
correlation ID d'origine et ne contiennent ni charge utile ni erreur brute.

## Processeur et garanties

La seule implémentation actuelle est `demo`, activée explicitement dans le Compose
local et refusée en environnement production. Elle confirme la prise en charge
technique sans appel IA ni action métier ; le résultat porte `processor: demo`
et `business_action_executed: false`. Les événements complétés ne sont pas réexécutés
automatiquement lorsque le processeur change.

L'interface est une coroutine recevant un événement validé. Le timeout repose sur
l'annulation coopérative asyncio : les futurs adaptateurs devront utiliser des
clients asynchrones avec leurs propres timeouts, sans bloquer la boucle ni ignorer
l'annulation. Les durées maximales sont bornées et inférieures au bail ; aucun
renouvellement de réservation n'est implémenté pour les tâches longues.

La file offre des **tentatives répétables**, pas une garantie universelle d'exécution
unique. Une action externe peut avoir réussi avant un crash ; le jeton ne peut pas
annuler cette action. Les futurs outils devront donc recevoir une clé d'idempotence
stable dérivée de l'événement et de l'action, indépendante du numéro de tentative.
Les checkpoints LangGraph et les approbations seront ajoutés séparément.

## Consultation

`POST /v1/events/status` utilise une enveloppe signée pour lier le reçu demandé,
le tenant, la source et l'utilisateur. La requête SQL exige aussi le connecteur
d'origine. Le résultat n'expose pas le message d'entrée. La réponse d'acceptation
`received` reste immuable ; les états de traitement se consultent sur cette route.

## Validation et limites

Tests PostgreSQL : concurrence, reprise avec un nouveau jeton après expiration,
limite des tentatives, backoff, rollback de l'audit de résultat et accès au statut.
Les tests simulent l'expiration en base sans attendre une minute. Les tests unitaires
couvrent timeout, annulation et arrêt du polling. La CI vérifie le trajet HTTP
jusqu'au résultat du worker de démonstration.

L'état de santé de l'API ne mesure pas le retard de la file ou la présence de workers.
Métriques de backlog, heartbeat opérationnel, équité entre tenants et pooling restent
à ajouter avant la mise en production.

Référence : [verrouillage et SKIP LOCKED dans PostgreSQL](https://www.postgresql.org/docs/17/sql-select.html).
