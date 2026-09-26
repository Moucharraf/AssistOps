# Traces LangSmith

AssistOps exporte des traces explicites du traitement des événements :

```text
worker
└── supervisor
    ├── route
    │   └── generation
    ├── rag
    │   ├── retrieve
    │   └── generation
    └── tools
```

Les branches dépendent de la demande. Une opération structurée passe directement
de `worker` à `tools`. Un plan de routage réutilisé ne crée pas une fausse trace
d’appel au modèle. Chaque tentative possède son arbre ; l’identifiant interne de
l’événement permet de retrouver ses différentes tentatives.

## Ce qui est exporté

- Noms fixes des opérations, relations parent/enfant et dates de début/fin.
- Identifiant UUID interne de l’événement et numéro de tentative.
- `correlation_ref`, empreinte SHA-256 du correlation ID des logs. La valeur brute
  vient du client et pourrait contenir des données personnelles ; elle est exclue.
- Statuts appartenant à une liste fermée, réutilisation du plan et nombre de tours.
- Modèle, fournisseur et compteurs de tokens des appels de génération.
- Compteurs de tokens d’embedding et coût RAG estimé, dans les métadonnées du RAG.

Le coût RAG est un diagnostic global, à ne pas additionner aux coûts des appels
de génération. LangSmith peut calculer ceux-ci à partir du modèle et des compteurs
`usage_metadata`. Les tarifs et coûts calculés par le serveur peuvent différer des
estimations locales ; ils ne constituent pas une facture. Une réponse perdue peut
avoir été facturée sans que les compteurs soient disponibles.

Les entrées et sorties des traces sont vides. Aucune question, réponse, citation,
pièce documentaire, adresse e-mail, identité métier, facture, contenu de ticket,
clé API ou stack trace n’est exportée. Les métadonnées d’environnement automatiques
du SDK sont désactivées. Les identifiants techniques et compteurs restent des
données opérationnelles : l’accès et la rétention doivent être définis sur le serveur.

Le graphe LangGraph reste sous `tracing_context(enabled=False)` : son état contient
des données brutes. Les spans AssistOps utilisent un contexte séparé et une liste
de valeurs autorisées. Activer seulement `LANGSMITH_TRACING=true` n’active donc pas
l’export automatique du graphe.

## Configuration cloud

Dans `.env` ou l’environnement du processus :

```dotenv
ASSISTOPS_LANGSMITH_ENABLED=true
ASSISTOPS_LANGSMITH_ENDPOINT=https://api.smith.langchain.com
ASSISTOPS_LANGSMITH_PROJECT=assistops
LANGSMITH_API_KEY=your-local-secret
```

Pour un projet hébergé en UE, utiliser `https://eu.api.smith.langchain.com`.
Créer la clé depuis les paramètres LangSmith et utiliser une clé du workspace cible.
Le projet peut être nommé `assistops`. Ces paramètres activent l’export ; aucune
image Docker LangSmith n’est nécessaire avec le service cloud.

Pour une installation auto-hébergée, utiliser **l’URL réelle de l’API**, avec son préfixe,
et pas nécessairement l’URL de son interface web. La clé est facultative uniquement
si l’installation auto-hébergée accepte les appels sans authentification. HTTPS est
obligatoire en environnement `production` ; HTTP est accepté pour un serveur de test.

Ajouter `-f compose.langsmith.yaml` à la commande Compose habituelle. Conserver les
autres overrides déjà utilisés, notamment `compose.rag.yaml` et `compose.jira.yaml`
si ces fonctions sont actives. Seul le worker reçoit la configuration LangSmith.
Sur Docker Desktop, une API accessible sur le poste via `localhost` se joint depuis
le worker avec `host.docker.internal`, ou via le nom du service sur un réseau commun.
L’override n’installe aucun serveur LangSmith et n’ajoute aucune image Docker.

Le worker ouvre la session de tracing automatiquement. Pour un appel direct en Python,
encadrer les processeurs avec `tracing_session(settings)` ; hors de cette session,
les décorateurs ne créent aucun client ni export.

## Fiabilité et diagnostic

Les spans terminés passent dans une file en mémoire de 256 éléments, puis sont
envoyés par un thread dédié. Le chemin métier n’attend pas le réseau LangSmith.
Une file pleine abandonne les nouvelles traces ; une panne d’export ne provoque
ni échec métier ni reprise d’un appel au modèle. La télémétrie peut être incomplète
après un crash ou une panne réseau. PostgreSQL reste la référence de l’audit métier.

Les logs locaux signalent `tracing_initialization_failed`, `tracing_export_failed`,
`tracing_queue_full` et `tracing_flush_incomplete`, sans corps d’erreur du serveur.
L’arrêt accorde au thread un délai de trois secondes. Les enfants peuvent parvenir
au serveur avant leur parent, grâce aux identifiants de trace et à `dotted_order`.
Le log `trace_queued` fournit le `trace_id` pour relier les logs locaux à LangSmith ;
il confirme la mise en file, pas encore la réception par le serveur.

Cette première intégration couvre le traitement Worker/Supervisor/RAG/Tools.
L’approbation humaine et l’envoi Jira différé restent suivis par les logs et l’audit
PostgreSQL ; ils ne sont pas présentés comme faisant partie du même appel synchrone.

## Tests

`tests/test_tracing.py` vérifie la sérialisation du SDK réel avec transport simulé,
la suppression des données sensibles, la propagation async/thread, l’isolation des
requêtes concurrentes, les annulations, la panne réseau et la saturation de la file.
Les tests tournent sans serveur LangSmith ni appel payant. La réception effective
doit aussi être vérifiée sur le serveur configuré avant de déclarer l’export actif.

Après activation sur le worker, la vérification réelle lit une facture synthétique
et contrôle les traces reçues, sans créer de ticket :

```shell
python scripts/check_langsmith_flow.py --live
```

Ajouter `--natural` pour vérifier le routage Supervisor, ou `--rag` pour une question
documentaire. Ces deux options effectuent des appels OpenAI facturés. Le script
contrôle l’arbre, la politique de filtrage et l’absence d’entrées/sorties brutes,
puis affiche le lien de la trace. Il utilise les credentials locaux, jamais la CI.

Références : [instrumentation manuelle](https://docs.langchain.com/langsmith/log-llm-trace),
[compteurs et coûts](https://docs.langchain.com/langsmith/cost-tracking).
