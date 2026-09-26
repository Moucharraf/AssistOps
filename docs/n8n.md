# Connecteur n8n

Ce parcours relie un client HTTP à AssistOps via n8n. Il reçoit une demande,
construit son identité autorisée, signe son contenu et transmet le reçu de l’API.
Un second webhook consulte le résultat. Le worker reste responsable du traitement
durable : n8n n’attend pas la réponse du modèle dans une connexion HTTP ouverte.

## Démarrer

```shell
docker compose -f compose.yaml -f compose.n8n.yaml up --build --wait --wait-timeout 240
python scripts/check_n8n_flow.py
```

L’interface est accessible sur <http://localhost:5678>. Créer le compte propriétaire
à la première ouverture. Le service `n8n-init` importe les credentials et publie
le workflow une seule fois. Les redémarrages préservent les modifications faites
dans l’interface ; ils ne réimportent pas les fichiers du dépôt.

`n8n` et `n8n-init` utilisent la même image `assistops-n8n:local`. Le second est
un conteneur ponctuel qui s’arrête après l’initialisation ; il ne consomme ensuite
plus de RAM. L’image officielle versionnée sert de base, avec des couches Docker
partagées, et ne correspond pas à un service supplémentaire.

Pour conserver un worker Supervisor déjà configuré, inclure aussi `compose.rag.yaml`
avant `compose.n8n.yaml` et définir `ASSISTOPS_AI_PROCESSOR=supervisor`, comme décrit
dans le [guide de développement](development.md#supervisor-langgraph).

## Contrat HTTP

Les deux endpoints sont des `POST` JSON, authentifiés par le header
`X-AssistOps-Ingress-Key`. La valeur **publique, réservée au développement** est
`assistops-n8n-local-ingress-only`.

Soumettre à `http://localhost:5678/webhook/assistops/events` :

```json
{
  "event_id": "example-001",
  "conversation_id": "conversation-001",
  "message": "Consulte ma facture INV-001.",
  "tool_call": {"name": "get_invoice", "invoice_id": "INV-001"}
}
```

`tool_call` est facultatif : une demande en langage naturel exige le worker
Supervisor. L’exemple structuré fonctionne sans appel au modèle. `event_id` doit
venir de l’événement d’origine et rester identique lors de chaque nouvelle tentative.
`conversation_id` identifie la conversation privée à reprendre.

Le HTTP 202 contient `receipt_id`, `event_id`, `status` et `duplicate`.
Consulter `http://localhost:5678/webhook/assistops/status` avec :

```json
{"receipt_id": "remplacer-par-le-reçu"}
```

Les codes de l’API sont transmis : 409 si un identifiant est réutilisé avec un
contenu différent, 404 si le reçu n’est pas accessible, 429 en cas de limitation.
Le client doit respecter `Retry-After`, conserver le même contenu et le même
`event_id` pour réessayer, y compris après un timeout ou un 502. Chaque appel
recalcule la signature ; aucune nouvelle tentative silencieuse ne crée un autre
événement. Le polling doit être espacé et borné côté client.

## Identité et secrets

Le credential `assistOpsApi` fixe l’URL, le connecteur, le tenant et l’utilisateur.
Le workflow local représente exclusivement `demo/user-001`, via `n8n-demo`.
Un champ entrant `user_id`, `tenant_id`, `source` ou tout champ inconnu est rejeté.
La clé d’entrée authentifie donc **un seul utilisateur**, pas tous les utilisateurs
d’une organisation. Un futur connecteur Slack/e-mail devra vérifier la provenance
et mapper l’identité authentifiée avant d’attester son identité auprès de l’API.

Le petit node `AssistOps` est nécessaire pour signer les octets exacts du JSON avec
HMAC-SHA256 tout en lisant la clé dans un credential n8n. Il n’utilise ni clé dans
les expressions du workflow ni accès aux variables d’environnement. Il refuse
les redirections, limite la taille des requêtes et borne l’appel API à dix secondes.
L’API vérifie de nouveau les droits et valide les paramètres métier.

Les credentials importés sont chiffrés par n8n avec sa clé persistée dans le volume.
Les fixtures contiennent uniquement des secrets publics de démonstration. Les
exports de workflow ne contiennent que des références aux credentials. Les corps
des exécutions ne sont pas conservés dans l’historique n8n ; AssistOps conserve ses
propres événements et son audit. L’identifiant de corrélation est généré pour chaque
appel à l’API, tandis que `event_id` assure la continuité entre les tentatives.

Aucun chemin de ce workflow ne permet d’approuver une action. Un ticket reste en
`awaiting_approval` jusqu’à une décision séparée d’un utilisateur habilité.

## Données et limites du déploiement

Les factures, utilisateurs et tickets utilisés par le test sont **synthétiques** :
ils vérifient le routage et les contrôles sans consulter de données client ni appeler
un CRM réel. Aucun message Slack ou e-mail n’est envoyé.

Ce Compose est local : port lié à `127.0.0.1`, HTTP, secrets publics, SQLite dans
`assistops_n8n_v2_data` pour la configuration n8n. Les événements AssistOps restent
dans PostgreSQL. Ne pas exposer ce Compose tel quel. Un déploiement partagé exige
des secrets distincts, HTTPS et cookies sécurisés, une clé de chiffrement sauvegardée,
un contrôle d’accès à l’éditeur et une configuration PostgreSQL n8n dédiée. Les
éditeurs autorisés à modifier un workflow sont dans le périmètre de confiance.

Les tests JavaScript (`node --test integrations/n8n/assistops.test.js`) vérifient
signature, identité, erreurs et limitation de débit. Le test HTTP est exécuté en
CI avec les vrais conteneurs n8n, API et worker, sans clé OpenAI.
