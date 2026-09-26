# RAG Agent : des passages à une réponse sourcée

Le RAG Agent répond aux questions documentaires à partir de Qdrant. Il peut être
appelé en CLI ou par le worker qui traite les webhooks signés. Son implémentation
est indépendante de LangGraph : le Supervisor pourra l'appeler à l'étape suivante.

Le corpus demeure **100 % synthétique** : procédures et politiques fictives pour
tester sans exposer de données clients. Les exemples décrivent cette entreprise
fictive, pas des règles juridiques réelles. Aucun document externe n'a été ajouté.

## Parcours d'une demande

1. FastAPI vérifie la signature et l'identité, puis persiste l'événement et le job.
2. Le worker réserve le job avec son mécanisme existant de lease.
3. Le RAG résout les rôles par `(tenant_id, user_id)` dans la configuration serveur.
   Un rôle écrit dans la question ne change jamais ces permissions.
4. PostgreSQL réserve une tentative dans le compteur quotidien partagé.
5. La recherche utilise une collection Qdrant déterminée pour cette demande et
   filtre les documents par tenant, rôles, statut et date UTC courante.
6. Jusqu'à cinq documents et deux passages par document sont envisagés. Le contexte
   effectivement envoyé est limité à 6 000 octets UTF-8 ; les passages qui dépassent
   ce volume sont omis, sans découper les preuves au milieu d'une phrase.
7. `gpt-4.1-mini-2025-04-14` produit une réponse structurée avec au maximum trois
   affirmations, chacune accompagnée d'un identifiant de passage et d'un extrait exact.
8. Python vérifie le schéma, l'existence du passage et la présence exacte de la
   citation dans le contexte envoyé. Il construit lui-même les références et
   conserve le résultat dans PostgreSQL via le worker.

Les titres, versions, chemins et origines des citations viennent du moteur de
recherche ; le modèle ne choisit pas une URL arbitraire pour les références.
Les citations ne prouvent toutefois pas automatiquement que chaque reformulation
est correcte : la fidélité sémantique doit encore être évaluée humainement.

## Résultats et erreurs

`result.processor` vaut `rag`. Le champ `result.outcome` distingue :

| Valeur | Signification |
| --- | --- |
| `answered` | Réponse avec références et extraits vérifiés |
| `abstained` | Sources insuffisantes, citation invalide, refus fournisseur ou sortie incomplète |
| `denied` | Aucun rôle documentaire configuré pour l'identité |
| `rejected` | Question supérieure à 4 000 octets UTF-8 |
| `budget_exhausted` | Quota quotidien de tentatives atteint |
| `unavailable` | Clé absente ou échec de dépendance |

Un job `completed` signifie que le traitement a terminé ; consulter `outcome` pour
savoir si une réponse a été produite. `business_action_executed` reste `false`.
Le RAG ne peut pas créer un ticket, modifier une facture ni obtenir des informations
de compte en temps réel. Il peut expliquer une procédure décrite dans les sources.

Les erreurs de fournisseur sont retournées comme résultats terminaux `unavailable`
pour éviter les retries payants automatiques. Les retries du worker demeurent
applicables aux timeouts globaux et aux erreurs de persistance. Un crash après un
appel fournisseur mais avant la sauvegarde peut donc provoquer un nouvel appel.
L'idempotence d'un webhook déjà terminé empêche son retraitement normal ; elle ne
garantit pas une facturation exactement une fois lors d'un crash.

## Configuration et démarrage

La clé est héritée de `OPENAI_API_KEY` dans l'environnement. L'alias
`ASSISTOPS_OPENAI_API_KEY` reste accepté par Python. Ne pas afficher la configuration
Compose résolue : elle contient la clé injectée dans le worker. `config --quiet`
permet de vérifier la syntaxe sans afficher les valeurs.

Le Compose de base conserve le processeur démo pour la CI. Pour le mode RAG local :

```powershell
docker compose -f compose.yaml -f compose.rag.yaml up --build --wait
.\.venv\Scripts\python.exe scripts/send_demo_event.py --wait --processor rag
```

L'override configure uniquement `demo/user-001` avec le rôle `customer`, transmet
la clé au worker et conserve le cache des embeddings dans un volume dédié.
Les documents doivent déjà être indexés selon le [guide de recherche](retrieval.md).
La migration 003 ajoute le compteur de budget sans supprimer les données existantes.

Pour appeler le RAG en CLI depuis la racine, sans worker :

```powershell
$env:ASSISTOPS_RAG_USER_ROLES = '{"demo":{"user-001":["customer"]}}'
.\.venv\Scripts\python.exe -m assistops.migrate
.\.venv\Scripts\python.exe -m assistops.answer_cli "Quel est le délai pour contester une facture ?" --tenant demo --user user-001
```

Cette CLI est un outil d'opérateur de confiance, pas une authentification utilisateur.
Elle utilise PostgreSQL pour partager le quota avec le worker. Ne pas lancer en
parallèle un worker démo et un worker RAG sur la même file : chacun peut prendre
n'importe quel job. L'override remplace le worker du Compose de base.

Pour revenir au processeur démo sans effacer les volumes :

```powershell
docker compose up -d worker
```

Pour un worker lancé directement en Python, définir `ASSISTOPS_WORKER_PROCESSOR=rag`,
`ASSISTOPS_WORKER_TIMEOUT_SECONDS=45` et `ASSISTOPS_WORKER_LEASE_SECONDS=90` avant
`python -m assistops.worker`, ainsi que les connexions et rôles nécessaires.

## Coût et observabilité

Le modèle est fixé à une version pour rendre les changements de comportement
explicites. Le [tarif officiel](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
consulté le 25 septembre 2026 est de 0,40 $ par million de tokens entrants et 1,60 $
par million de tokens sortants. Le suivi utilise ces tarifs sans réduction de cache.

Les limites sont de 16 000 octets pour le corps JSON complet de génération et
600 tokens sortants. Le modèle ne reçoit ni outil métier ni outil de navigation.
Une tentative effectue au maximum un appel d'embedding et un appel de génération ;
le cache peut éviter l'embedding. Les appels de génération utilisent `store=false`.
Ce paramètre ne constitue pas une garantie de rétention nulle côté fournisseur.

`ASSISTOPS_RAG_DAILY_ATTEMPTS=5` par défaut autorise cinq tentatives par jour UTC,
partagées entre processus utilisant la même base et le même schéma. Chaque tentative
réserve conventionnellement 0,01 $, une marge prudente pour les limites ci-dessus.
Le compteur est atomique et persiste après redémarrage. Les réservations ne sont
pas remboursées après une erreur ou une abstention. La valeur peut être configurée
de 0 à 20 ; 0 désactive les appels payants du RAG.

Ce mécanisme limite **ce parcours RAG**, pas le compte OpenAI : l'ingestion et les
autres applications utilisant la clé ne sont pas comptabilisées. Le compteur ne
consulte pas le solde réel et doit être réévalué si les tarifs ou limites changent.

`result.usage` et le log `rag_completed` contiennent modèle, version du prompt,
collection, tokens, latence et coût estimé. Les logs ne contiennent ni question ni
passage ni clé. Le résultat conservé en base contient la réponse et les citations,
donc devra suivre la politique de rétention de l'application.
Les coûts estimés proviennent des usages reçus ; une réponse fournisseur perdue
peut être facturée sans apparaître dans ces usages. Sa réservation reste consommée.

## Tests et limites avant production

La CI ne nécessite aucune clé OpenAI. Elle vérifie les réponses structurées avec
des doublures, les citations inventées, l'absence de sources, les permissions,
l'annulation, le quota concurrent et le parcours webhook → worker → résultat
persisté avec rejeu. Les tests Qdrant existants vérifient les filtres réels.

Vérification locale du 25 septembre 2026 : **109 tests réussis**, ainsi que le
parcours HTTP sur les conteneurs avec une vraie réponse OpenAI et un doublon
sans second traitement. Le [rapport de trois cas réels](../retrieval-reports/rag-smoke.json)
conserve également Q01 (réponse avec source), Q17 (abstention sur les données de
facture absentes) et Q19 (abstention sur les seuils internes interdits au client).
Ces trois cas passent. Le coût estimé cumulé de ces trois appels est de 0,00223918 $.
Il s'agit d'une vérification ponctuelle, pas d'un score général de qualité.
Le cas Q19 vérifie une non-divulgation par abstention ; la distinction conversationnelle
entre refus explicite et absence de preuve reste à affiner.

Pour répéter volontairement ces appels payants, avec le worker RAG actif :

```powershell
.\.venv\Scripts\python.exe scripts/check_rag_live.py --live
```

Le script écrit son rapport dans `.cache/rag-live.json` et consomme trois tentatives
du quota partagé. Il n'est pas exécuté en CI. Les rôles et la date de recherche
sont ceux du worker ; le benchmark sert uniquement de source des questions.

Les documents et questions sont des entrées non fiables dans le prompt. Les
tests adversariaux vérifient notamment qu'ils ne modifient pas les rôles ni les
outils disponibles ; ils ne démontrent pas une résistance universelle aux injections.

Avant une mise en production, il reste notamment à valider :

- La fidélité des réponses, les abstentions et les injections sur un jeu indépendant.
- La gestion centralisée des identités, la révocation des droits et l'accès aux
  réponses historiques après un changement de permissions.
- Le rate limiting, la rétention, les sauvegardes et les alertes opérationnelles.
- Les dépendances verrouillées transitivement et la gestion des secrets déployés.
- LangGraph, mémoire conversationnelle, API métier réelles et tracing LangSmith.
  Les outils simulés et la validation humaine via API sont décrits dans le
  [guide de développement](development.md#outils-métier-simulés-et-approbations).

Les timeouts HTTP bornent les opérations réseau. La génération est asynchrone et
annulable ; une recherche synchrone déjà lancée dans un thread peut finir après
l'annulation du worker, mais ne déclenche alors aucune génération. Une réservation
conservée couvre cette incertitude. Le timeout de traitement et la durée de lease
doivent rester cohérents lors du déploiement.

Référence du format : [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
