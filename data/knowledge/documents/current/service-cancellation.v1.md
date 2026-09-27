+++
document_id = "service-cancellation"
title = "Résilier un abonnement et préparer la clôture"
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

# Résilier un abonnement et préparer la clôture

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Demande de résiliation

Seul l’administrateur de facturation du tenant peut confirmer la résiliation d’un abonnement. L’assistant présente d’abord le périmètre et les conséquences. Une question sur le prix d’une offre ou une demande d’export ne constitue pas un ordre de résiliation.

## Date d’effet

La résiliation prend effet à la fin de la période mensuelle en cours. Elle empêche le renouvellement suivant, sans remboursement automatique du temps restant. Un remboursement éventuel relève de la politique dédiée et d’une décision distincte.

Le client peut annuler sa demande de résiliation avant cette date d’effet, sous réserve de confirmation par le service métier. L’assistant ne peut pas confirmer un changement d’état sur la seule base d’une explication documentaire.

## Préparer les données

L’administrateur doit demander l’export souhaité avant la date d’effet de la résiliation. Les formats, délais de préparation et durées des liens sont décrits dans la procédure d’export. Il faut tenir compte de ce délai pour éviter une demande trop tardive.

## Après clôture

Le corpus ne définit pas de délai universel de suppression de toutes les données après résiliation. Les obligations contractuelles et les catégories de données peuvent différer. Ne pas annoncer une suppression immédiate des factures ou des traces d’audit en appliquant la règle des tickets clos. Toute demande de suppression suit un examen spécifique.

