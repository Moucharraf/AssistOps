+++
document_id = "incident-communication"
title = "Informer les clients pendant un incident"
version = 1
tenant_id = "demo"
language = "fr"
category = "support"
owner = "Opérations fictives"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["customer","billing_admin","support_agent","support_lead","finance","security","it_admin"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Informer les clients pendant un incident

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Objectif

Cette procédure encadre les messages destinés aux clients lorsqu’un incident a été confirmé. Elle ne constitue pas un tableau de bord en temps réel. Le fait de retrouver ce document ne signifie pas qu’un incident est actuellement ouvert.

## Contenu du premier message

Indiquer les fonctionnalités affectées, le périmètre connu, l’heure du début estimé et les contournements validés. Séparer les faits observés des hypothèses. Ne pas annoncer une cause racine avant confirmation technique ni publier des identifiants de clients touchés.

## Fréquence de suivi

Pour un incident confirmé, publier une mise à jour toutes les 30 minutes, même en l’absence de nouveau diagnostic. Une mise à jour peut préciser que l’investigation continue. Ne pas promettre une heure de rétablissement si l’équipe technique n’a pas fourni d’estimation validée.

Le statut actuel doit être consulté dans le service d’incidents autorisé. En son absence, expliquer que le corpus ne permet pas de vérifier la situation en direct.

## Clôture

Après confirmation du rétablissement, préciser ce qui a été vérifié et les limites restantes. Une amélioration partielle ne doit pas être annoncée comme une résolution totale. Les mesures correctives futures sont communiquées lorsqu’elles sont validées ; leur existence ne peut pas être déduite d’une procédure générique.

