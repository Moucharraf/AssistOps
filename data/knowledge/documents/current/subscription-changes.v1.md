+++
document_id = "subscription-changes"
title = "Changer d’offre et comprendre le prorata"
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

# Changer d’offre et comprendre le prorata

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Demande autorisée

Seul un administrateur de facturation du tenant peut demander un changement d’offre. Un agent support peut expliquer les conséquences, mais ne se substitue pas à cet administrateur. L’offre actuelle et la date de renouvellement proviennent du service métier.

## Passage à une offre supérieure

Une montée en gamme prend effet immédiatement après confirmation. Le prorata correspond à la différence des tarifs mensuels multipliée par les jours calendaires restants, divisée par les jours de la période de facturation. Le service de facturation produit le montant définitif et son arrondi ; l’assistant peut expliquer la formule sans créer une nouvelle facture.

## Passage à une offre inférieure

Une baisse d’offre prend effet au prochain renouvellement, sans remboursement automatique de la période en cours. Avant confirmation, vérifier que le nombre de membres et les besoins de conservation respectent les limites de la future offre.

Si le nombre de membres dépasse la capacité cible, l’administrateur doit choisir les accès à retirer. L’assistant ne choisit pas les personnes à désactiver. Les règles de conservation ne doivent pas être modifiées rétroactivement par une réponse conversationnelle.

## Confirmation

Présenter un récapitulatif de l’offre demandée, de la date d’effet et des conséquences. Une demande de conseil n’est pas un ordre de modification. Les changements effectifs nécessiteront un outil métier et son contrôle d’autorisation.

