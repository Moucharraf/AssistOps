+++
document_id = "invoice-access"
title = "Consulter et télécharger une facture"
version = 1
tenant_id = "demo"
language = "fr"
category = "billing"
owner = "Finance fictive"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["customer","billing_admin","support_agent","support_lead","finance","security","it_admin"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Consulter et télécharger une facture

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Accès individuel et accès d’équipe

Un utilisateur authentifié peut consulter les factures qui lui sont explicitement attribuées. Un administrateur de facturation peut consulter les factures de son tenant. Le service métier vérifie ces droits à chaque requête ; l’assistant ne les déduit pas de l’historique de conversation.

Un agent support utilise un périmètre de consultation délégué et audité. Le simple fait d’avoir le rôle support ne lui donne pas un accès global à tous les tenants. Aucun exemple de facture réelle n’est inclus dans cette documentation.

## Demande de copie

Le téléchargement d’une facture se fait depuis la rubrique Facturation du portail sécurisé. Le lien de téléchargement individuel expire après 24 heures. Le support peut expliquer ce parcours, mais ne doit pas créer un lien fictif ni publier un document comptable dans un canal partagé.

## Facture introuvable

Si la référence n’est pas trouvée dans le périmètre autorisé, signaler qu’elle n’est pas accessible avec le compte courant. Vérifier avec l’utilisateur le bon espace et la bonne période, sans confirmer l’existence d’une facture appartenant à une autre organisation.

## Données actuelles

La documentation décrit la procédure, pas les montants ni les états des factures. Pour connaître le solde de INV-001 ou son statut de paiement, un appel au service de facturation est nécessaire. Aucun montant par défaut ne doit être inventé.

