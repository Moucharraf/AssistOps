# Comprendre le corpus documentaire synthétique

## 1. Ce que nous construisons

Un RAG retrouve des passages dans une bibliothèque documentaire, puis utilise ces
passages pour préparer une réponse. La qualité de cette bibliothèque est donc aussi
importante que le choix du modèle. Pour AssistOps, les textes doivent représenter
des demandes de support plausibles : règles précises, exceptions, responsabilités
et étapes de traitement.

Nous avons créé **Asteria Cloud**, une entreprise fictive, et son produit fictif
**AsterDesk**, un service SaaS de gestion des demandes client. Le tenant `demo`
constitue l'espace principal. `boreal` représente un autre client fictif avec une
convention distincte. Ces noms sont des éléments du scénario, sans prétention à
décrire des organisations réelles.

Les procédures décrivent les capacités et règles du produit fictif. Elles ne
signifient pas que toutes ces capacités sont déjà implémentées dans AssistOps :
notre worker utilise encore son processeur de démonstration.

## 2. Pourquoi du synthétique, et y a-t-il un mélange ?

**Cette version est entièrement synthétique, sans contenu réel mélangé.** Les
sources gratuites envisagées précédemment n'ont pas été incorporées. Nous avons
rédigé des documents originaux afin de :

- maîtriser les règles de bout en bout, pour les relier ensuite aux API simulées ;
- rendre les cas d'erreur reproductibles : ancienne version, autre tenant, rôle interdit ;
- éviter les données personnelles et les documents confidentiels ;
- préparer des réponses attendues dont on peut vérifier les preuves.

La provenance est déclarée à trois niveaux : fichier `provenance.json`, métadonnée
`origin = "synthetic"` et avertissement visible dans chaque document. Le benchmark
et les fixtures adversariales portent eux aussi cette indication.

Le corpus a été rédigé avec assistance IA. Les contrôles automatiques ne remplacent
pas une relecture métier : ils vérifient les formats et les références, mais ne
prouvent pas que toutes les règles sont parfaitement réalistes ou sans ambiguïté.
Le statut de relecture humaine est explicitement indiqué comme en attente.

Si nous ajoutons plus tard de vrais documents publics, il faudra enregistrer leur
URL, leur version ou date de collecte, leur licence et les transformations appliquées,
puis adapter le schéma de provenance. Le chargeur actuel accepte seulement l'origine
synthétique, ce qui empêche de présenter silencieusement un corpus mixte comme fictif.

## 3. Organisation des fichiers

```text
data/
  README.md                        Inventaire et explication de la provenance
  knowledge/
    manifest.json                  Liste explicite des documents
    provenance.json                Origine et limites de la version
    documents/
      current/                     20 documents principaux
      archive/                     2 versions obsolètes
      other-tenant/                1 document du tenant boreal
  evaluation/
    reference.json                 Questions, réponses et passages attendus
  adversarial/
    cases.json                     Spécifications des tests d'attaque
    fixtures/                      Textes hostiles fictifs
```

Le manifeste est la seule porte d'entrée du chargeur. Celui-ci refuse une entrée
qui sortirait de `knowledge/documents/`, même au moyen d'un chemin relatif ou d'un
lien symbolique. Il ne parcourt jamais le répertoire d'évaluation.

Cette séparation évite une **fuite du jeu d'évaluation** : si les réponses attendues
étaient indexées, le système pourrait les retrouver directement et afficher un
score trompeur. Les textes adversariaux doivent également rester hors du corpus
normal ; leur injection sera contrôlée par des tests spécifiques.

## 4. Comment lire un document

Ouvrir par exemple
[la procédure de contestation](../data/knowledge/documents/current/billing-disputes.v2.md).
Le bloc entre `+++` est du TOML, lu avec la bibliothèque standard Python. Le reste
est du Markdown destiné à la lecture et, plus tard, au découpage en passages.

| Métadonnée | Rôle |
| --- | --- |
| `document_id` et `version` | Citation stable, par exemple `billing-disputes@2` |
| `title`, `category`, `owner` | Comprendre le sujet et son responsable fictif |
| `tenant_id` | Organisation autorisée à consulter ce document |
| `allowed_roles` | Rôles autorisés, sans hiérarchie implicite |
| `status` | Document actif ou archivé |
| `effective_from`, `effective_until` | Début inclusif et fin exclusive de validité |
| `language` | Langue du document, ici `fr` |
| `origin`, `synthetic_reason`, `external_sources` | Origine, justification et absence de source externe |

Un document est éligible si le tenant correspond, si au moins un rôle est autorisé,
s'il est actif et si sa période couvre la date de recherche. Les archives sont
toujours exclues dans cette première version : la consultation historique n'est
pas encore prise en charge.

Les rôles du benchmark sont des **contextes de test**, pas des affirmations que
l'utilisateur pourra fournir pour obtenir des droits. Le futur endpoint RAG devra
recevoir son contexte d'autorisation d'une source serveur fiable. Le chargeur
implémente le prédicat local `visible_to`; les filtres Qdrant ne sont pas encore branchés.

## 5. Les règles structurantes du scénario

Ces valeurs sont inventées. Cette table sert à la relecture de cohérence ; les
documents associés sont les références du futur RAG.

| Sujet | Règle fictive actuelle | Source |
| --- | --- | --- |
| Échéance | 15 jours calendaires après émission | `billing-cycle@1` |
| Contestation | 30 jours calendaires ; pas de suspension automatique du paiement | `billing-disputes@2` |
| Remboursement | 5 à 10 jours ouvrés bancaires après validation | `refund-policy@1` |
| Validation interne | Jusqu'à 100 EUR : responsable support ; au-delà : finance | `refund-approvals@1`, restreint |
| Impayé | Relances J+1/J+5 ; lecture seule J+10 après échéance | `payment-failures@1` |
| Starter / Pro | 19 EUR / 49 EUR HT mensuels ; 5 / 20 membres actifs | `plans@1` |
| P1 | Première réponse en 1 heure, 24/7 ; pas une garantie de résolution | `support-priorities@2` |
| Ticket | Confirmation humaine obligatoire avant création | `ticket-creation@1` |
| Export | Préparation sous 72 heures ; lien valide 24 heures | `data-export@1` |
| Conservation | Tickets clos : 30 jours Starter, 90 jours Pro | `retention@1` |

L'archive de contestation indique intentionnellement **15 jours** ; celle de P1
indique **2 heures**. Le document de `boreal` indique **45 jours** pour ce tenant.
Ces différences sont des pièges contrôlés de version et d'autorisation, pas des
contradictions dans les règles actives du tenant demo.

## 6. Les 20 questions de référence

[reference.json](../data/evaluation/reference.json) contient :

- **16 questions avec réponse** : 12 à source unique et 4 nécessitant deux documents ;
- **2 questions sans réponse disponible** : montant actuel d'une facture et prix Enterprise non défini ;
- **2 demandes à refuser** : matrice interne pour un client et document d'un autre tenant.

Chaque cas précise le tenant, les rôles et la date fictive de recherche, fixée au
**1er septembre 2026**. Cette date rend le jeu reproductible même lorsque le calendrier
réel avance. Les dates de création et de validité ont des significations distinctes.

Pour les questions auxquelles on peut répondre, nous conservons les clés des documents
pertinents, une réponse attendue et des citations exactes de preuve. Le validateur
vérifie que ces passages existent et que les sources sont accessibles dans le contexte
du cas. Une réponse attendue sert à la comparaison, jamais à l'ingestion documentaire.

Le jeu est un **jeu de référence visible pour le développement**, et non un test
aveugle indépendant : questions et réponses ont été écrites en connaissant les
documents. Il faudra un second jeu inédit et une relecture humaine avant de
généraliser les résultats à un contexte réel.

## 7. Comment mesurer le Recall@5

Nous choisissons une mesure **au niveau document versionné**, pas au niveau passage.
Pour chaque question avec réponse :

```text
Recall@5 = nombre de documents pertinents dans les 5 premiers résultats
           / nombre total de documents pertinents attendus
```

Exemple : une question exige deux documents ; un seul est retrouvé parmi les cinq
premiers. Son recall vaut 1/2, soit 50 %. Le score global est la moyenne des recalls
des **16 questions avec réponse**. Les 4 autres n'ont pas de dénominateur pertinent
et sont exclues du recall, sans leur attribuer artificiellement 0 ou 1.

Le programme accepte une liste ordonnée de documents distincts par question. Quand
nous aurons des chunks, il faudra définir et documenter leur agrégation en classement
de documents avant d'utiliser ce programme. Ce score ne sera pas un Recall@5 des chunks.

Le programme signale également les résultats inéligibles parmi les cinq premiers :
archive, date, rôle ou tenant incompatible. Il ne les supprime pas pour masquer
une erreur de filtrage. Un recall élevé ne suffit donc pas à valider la sécurité.

Le refus approprié, l'absence d'invention et la qualité de réponse restent à évaluer
avec un générateur de réponses. Ce calcul de ranking ne les mesure pas. Les fixtures
adversariales sont pour l'instant des scénarios spécifiés, pas des tests d'agents réussis.

## 8. Exécuter les contrôles

Depuis la racine du dépôt :

```powershell
.\.venv\Scripts\python.exe -m assistops.corpus
.\.venv\Scripts\python.exe -m pytest tests/test_corpus.py tests/test_retrieval_eval.py -q
```

Sortie attendue du validateur : 23 documents, 20 questions, 16 `answer`, 2 `abstain`
et 2 `deny`. Aucune clé OpenAI, aucun Docker et aucun appel réseau ne sont nécessaires.

Pour scorer un futur fichier de résultats de recherche :

```powershell
.\.venv\Scripts\python.exe -m assistops.retrieval_eval chemin/vers/rankings.json
```

Le fichier doit contenir `corpus_id: "asterdesk-fr-v1"` et un tableau `rankings`
avec exactement une entrée pour chacun des identifiants Q01 à Q20. Chaque entrée
contient `question_id` et `documents`, la liste ordonnée des clés retournées.
Une liste vide est autorisée. Les clés inconnues, doublons et résultats partiels
sont refusés. Aucun fichier de résultats prétendument réels n'est fourni à ce stade.

## 9. Ce qui est livré et ce qui suit

Livré : documents, provenance explicite, benchmark avec preuves, chargeur contrôlé,
filtres locaux, validateur et calcul du recall testé sur des cas construits.

À venir : découpage en passages, embeddings, indexation Qdrant avec filtres serveur,
recherche réelle, citations dans les réponses et intégration du RAG au worker.
Nous n'avons encore ni entraîné ni évalué un modèle sur ce corpus. Les tests du
calcul de métrique vérifient une formule ; ils ne constituent pas un score RAG.
