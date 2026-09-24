# Données de démonstration AssistOps

**Tout le contenu de ce répertoire est synthétique. Aucun document externe n'a été
importé, copié ou adapté pour cette version.** Les entreprises, le produit, les
montants, les délais et les politiques sont inventés pour les besoins du projet.

Lire d'abord le [guide du corpus](../docs/synthetic-corpus.md), qui explique les
choix, les métadonnées, les permissions et l'évaluation étape par étape.

| Répertoire | Contenu | Peut alimenter la recherche ? |
| --- | --- | --- |
| `knowledge/documents/current/` | 20 documents du tenant fictif `demo` | Oui, selon les permissions et dates |
| `knowledge/documents/archive/` | 2 anciennes versions aux règles différentes | Non dans le mode actuel |
| `knowledge/documents/other-tenant/` | 1 document du tenant fictif `boreal` | Seulement pour un contexte `boreal` autorisé |
| `evaluation/` | 20 questions, réponses attendues et passages justificatifs | **Non** |
| `adversarial/` | 2 textes hostiles fictifs et leurs scénarios attendus | **Non**, tests dédiés uniquement |

Le [manifeste](knowledge/manifest.json) énumère les 23 documents. Le chargeur utilise
cette liste explicite, puis les métadonnées déterminent quels documents sont
éligibles pour un contexte. Un parcours récursif de tout `data/` est interdit pour
l'ingestion : il exposerait les réponses de référence et les attaques de test.

## Provenance

Voir [provenance.json](knowledge/provenance.json). Le corpus a été rédigé avec
assistance IA à partir du scénario original du projet. Il est soumis à des
contrôles automatiques de structure et de références ; sa relecture humaine
métier reste à réaliser. Il ne représente aucune politique d'entreprise réelle.

## Inventaire des documents principaux

Les identifiants de citation incluent la version : `document_id@version`.

| Identifiant | Sujet | Public dans le tenant demo |
| --- | --- | --- |
| `billing-cycle@1` | Cycle mensuel, échéance et lecture d'une facture | Tous les rôles de démonstration |
| `billing-disputes@2` | Contestation et effet sur le paiement | Tous |
| `refund-policy@1` | Remboursement validé | Tous |
| `refund-approvals@1` | Seuils internes de validation | Finance, responsable support |
| `payment-failures@1` | Relances et lecture seule | Tous |
| `subscription-changes@1` | Changement d'offre et prorata | Tous |
| `plans@1` | Catalogue et limites d'offres | Tous |
| `ticket-creation@1` | Proposition, approbation et création de ticket | Tous |
| `support-priorities@2` | Priorités et première réponse | Tous |
| `support-escalation@1` | Escalade et astreinte | Support, responsable support, sécurité |
| `identity-verification@1` | Identité et vérification des permissions | Tous |
| `invoice-access@1` | Accès individuel et téléchargement | Tous |
| `password-reset@1` | Réinitialisation et récupération MFA | Tous |
| `onboarding@1` | Arrivée et attribution des rôles | Support, responsable support, IT |
| `offboarding@1` | Départ et révocation des accès | IT, sécurité |
| `data-export@1` | Formats, préparation et durée des liens | Tous |
| `retention@1` | Conservation des tickets clos | Tous |
| `incident-communication@1` | Information pendant un incident | Tous |
| `integration-webhooks@1` | Livraison, doublons et diagnostic | Tous |
| `service-cancellation@1` | Résiliation et préparation de la clôture | Tous |

« Tous » signifie les rôles explicitement listés dans le document, pas un accès
public inter-tenant. Aucun rôle n'implique automatiquement tous les autres.

## Contrôle local

Depuis la racine du dépôt, sans Docker, sans clé API et sans appel réseau :

```powershell
.\.venv\Scripts\python.exe -m assistops.corpus
.\.venv\Scripts\python.exe -m pytest tests/test_corpus.py tests/test_retrieval_eval.py -q
```

Le résultat de validation indique les nombres de documents et de questions.
Il ne constitue pas un résultat de recherche ni une mesure de performance.
