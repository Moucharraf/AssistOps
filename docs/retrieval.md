# Recherche documentaire : ingestion et évaluation

Cette étape implémente la recherche sémantique en ligne de commande. Elle retourne
des passages et leurs sources. Le [RAG Agent](rag-agent.md) les utilise maintenant
pour générer des réponses sourcées via le worker, directement ou depuis le
[Supervisor LangGraph](development.md#supervisor-langgraph).

## Données et fonctionnement

Le corpus est **100 % synthétique**, rédigé pour une entreprise fictive. Il permet
de tester versions, procédures et permissions sans exposer de données clients.
Aucun contenu public réel n'est mélangé aux documents. La provenance est décrite
dans le [guide du corpus](synthetic-corpus.md).

1. Le chargeur valide les 23 documents listés dans le manifeste.
2. Chaque section Markdown `##` est découpée en fenêtres de 180 mots avec un
   chevauchement de 30 mots. Le titre et le nom de section accompagnent le texte
   envoyé au modèle. Le préambule du corpus (titre et mention synthétique) est
   exclu. Ce découpage est spécifique à ce format, pas un parseur Markdown général.
3. OpenAI transforme les 95 passages en vecteurs de 1 536 dimensions avec
   `text-embedding-3-small`. Un vecteur représente le sens du texte pour comparer
   une question aux passages par similarité cosinus.
4. Qdrant reçoit une nouvelle collection complète. L'alias `assistops_knowledge`
   bascule atomiquement vers elle après tous les envois. Une erreur d'envoi ne
   publie pas d'index partiel. Les anciennes collections sont conservées ; leur
   nettoyage et celui des collections incomplètes restent manuels.
5. La question est vectorisée avec le même modèle. Qdrant applique les filtres
   tenant, rôle, statut actif et dates **avant** de sélectionner les résultats.
   Les documents sont classés par leur meilleur passage, avec deux passages au
   maximum par document et cinq documents par défaut.

Les identifiants des passages sont déterministes. Les métadonnées conservent la
version du document, le chemin source et l'origine synthétique. Les résultats sont
revérifiés côté Python avant de retourner leur texte. Les rôles n'ont pas de
hiérarchie implicite : au moins un rôle doit correspondre aux droits du document.
La date de début est inclusive et la date de fin exclusive. Les archives restent
exclues, même pour une recherche datée dans le passé.

La CLI est réservée à un opérateur de confiance : ses arguments de tenant et rôle
ne sont pas un mécanisme d'authentification. Une future API devra dériver ces
valeurs de l'identité authentifiée. Aucun endpoint public de recherche n'est ajouté.

## Coût et clé

La clé existante `OPENAI_API_KEY` est acceptée depuis l'environnement ou `.env`.
`ASSISTOPS_OPENAI_API_KEY` est prioritaire si les deux sont définies. Ne jamais
commiter la clé. Le `.env` existant n'est pas remplacé et Compose n'injecte pas
automatiquement cette clé dans les conteneurs.

Le [tarif officiel de text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small)
consulté pour cette implémentation est de **0,02 $ par million de tokens**.
Le coût estimé se calcule par `tokens_used / 1_000_000 × 0.02` ; il ne constitue
pas une lecture du solde ou de la facture du compte.

- Cache local dans `.cache/embeddings`, exclu de Git : clé par modèle, dimensions
  et empreinte du texte ; fichiers contenant les vecteurs, pas le texte source.
- Lots de 32 passages et trois tentatives maximum sur erreurs temporaires.
- Plafond de 100 000 octets UTF-8 envoyés par instance, retries compris. Il limite
  le volume d'une commande, **pas les dépenses cumulées du compte**.
- `tokens_used` additionne les usages rapportés par les réponses réussies. Une
  réponse perdue peut avoir été facturée sans apparaître dans ce compteur.
- Aucun modèle de génération n'est appelé ; les tests et la CI n'utilisent pas
  l'API OpenAI payante.

Conserver le cache évite de repayer les textes identiques. Changer les dimensions
nécessite une réingestion complète. Les vecteurs nommés empêchent de mélanger des
dimensions ou modèles incompatibles. Le texte synthétique est envoyé à OpenAI ;
Qdrant conserve localement les passages et leurs vecteurs.

## Commandes PowerShell

Depuis la racine du dépôt, avec l'environnement Python installé :

```powershell
docker compose up -d qdrant
# Inspect the input volume without calling OpenAI or Qdrant.
.\.venv\Scripts\python.exe -m assistops.rag_cli plan
.\.venv\Scripts\python.exe -m assistops.rag_cli ingest --output .cache/ingestion.json
.\.venv\Scripts\python.exe -m assistops.rag_cli search --query "Comment contester ma facture ?" --tenant demo --roles customer --as-of 2026-09-01
.\.venv\Scripts\python.exe -m assistops.rag_cli evaluate --output .cache/evaluation.json
```

Les rapports sont aussi affichés en JSON. `search` utilise la date du jour si
`--as-of` est omis. `evaluate` utilise les dates et identités du benchmark, résout
l'alias une fois puis garde la même collection pendant les 20 recherches. Seule
la question est vectorisée ; les réponses de référence ne sont jamais indexées.
Réingérer le corpus après une modification avant de lancer son évaluation.

Le Recall@5 est calculé sur les **16 questions avec sources attendues**. Les quatre
autres cas ne mesurent pas encore une capacité d'abstention ou de refus : le moteur
retourne des voisins même lorsqu'aucun passage ne répond vraiment à la question.
Ces comportements devront être testés sur le futur agent. Un bon recall sur ce
petit corpus synthétique ne démontre pas une qualité générale en production.

### Première mesure réelle

Le [rapport versionné](../retrieval-reports/baseline.json) conserve les classements,
l'empreinte du corpus, la collection et les usages retournés par OpenAI :

| Mesure | Résultat |
| --- | --- |
| Recall@5 macro sur 16 questions répondables | 96,875 % |
| Questions avec une source hors droits | 0 sur 20 |
| Tokens d'ingestion | 9 133 |
| Tokens pour les 20 recherches | 423 |
| Coût estimé total des embeddings | 0,00019112 $ |

Q15 retrouve un seul des deux documents attendus ; les 15 autres questions
répondables retrouvent toutes leurs sources. Le jeu a servi au développement et
n'est pas un jeu de test indépendant. Les cas de refus et d'abstention sont exclus
du recall. Aucun score de réponse générée n'est revendiqué.

## Vérifications

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -m 'not integration'
$env:ASSISTOPS_TEST_QDRANT_URL = 'http://localhost:6333'
.\.venv\Scripts\python.exe -m pytest tests/test_retrieval.py -m integration
```

Les tests unitaires simulent OpenAI et vérifient notamment cache, plafond de volume
et masquage des erreurs fournisseur. Le test Qdrant utilise des vecteurs fictifs
déterministes pour vérifier les droits et le remplacement d'un index. Il crée et
supprime uniquement ses collections de test ; il ne mesure pas la pertinence.
La CI exécute ce test sur le service Qdrant du Compose.

Le code est réparti entre `embeddings.py` (appels et cache), `retrieval.py`
(passages, index et recherche) et `rag_cli.py` (commandes et évaluation).
Références : [embeddings OpenAI](https://developers.openai.com/api/docs/guides/embeddings),
[recherche groupée Qdrant](https://api.qdrant.tech/api-reference/search/query-points-groups).
