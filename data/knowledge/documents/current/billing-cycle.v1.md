+++
document_id = "billing-cycle"
title = "Calendrier de facturation et lecture d’une facture"
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

# Calendrier de facturation et lecture d’une facture

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Objet et périmètre

Asteria Cloud est l’entreprise fictive qui édite AsterDesk, un service de gestion des demandes client. Cette procédure explique les factures d’abonnement mensuel. Elle ne permet pas de connaître le solde réel d’un compte : cette information doit venir du service de facturation autorisé.

## Cycle et échéance

La facture mensuelle est émise le jour anniversaire de l’abonnement, à 00:00 UTC. Si ce jour n’existe pas dans le mois, le dernier jour du mois est utilisé. La période facturée et la date d’échéance apparaissent séparément sur le document.

Le paiement est exigible 15 jours calendaires après la date d’émission. Les prix du catalogue sont exprimés en euros hors taxes ; les taxes éventuelles sont détaillées sur la facture. Aucune règle fiscale nationale n’est définie dans ce corpus.

## Contrôles avant réponse

Vérifier le tenant, l’utilisateur autorisé, la devise, la période et le statut du paiement dans l’API métier. Le numéro d’une facture ne prouve pas que son demandeur peut la consulter. Une ligne de prorata doit être rapprochée d’un changement d’abonnement ; sa présence seule ne prouve pas une erreur.

## Exemple fictif

Une facture émise le 3 septembre 2026 arrive à échéance le 18 septembre 2026. Pour une contestation, suivre la procédure dédiée. Ne jamais remplacer une donnée de facture absente par un montant estimé à partir du tarif catalogue.

