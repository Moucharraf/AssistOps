+++
document_id = "payment-failures"
title = "Paiement échoué et restriction progressive du service"
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

# Paiement échoué et restriction progressive du service

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Déclenchement

Cette procédure commence lorsque la facture atteint son échéance sans paiement confirmé. Un échec de prélèvement avant l’échéance déclenche une notification informative, mais pas immédiatement une restriction. Le statut réel doit être vérifié dans l’API de facturation.

## Calendrier des relances

Une première relance est envoyée à J+1 et une seconde à J+5 après l’échéance impayée. À J+10, l’espace passe en lecture seule si le paiement n’est toujours pas confirmé. Les jours de ce calendrier sont des jours calendaires.

Le mode lecture seule conserve la consultation des demandes existantes, mais bloque leur création et leur modification. Une contestation en cours ne neutralise pas ce calendrier sans suspension écrite de la finance.

## Régularisation

Le client met à jour son moyen de paiement depuis le portail sécurisé. Il ne transmet jamais ses données de carte dans un ticket. Après confirmation du règlement par le prestataire, le support vérifie la levée de la restriction. Aucun délai automatique de déblocage n’est garanti par cette procédure.

## Gestion d’un doute

Si le client dispose d’une preuve de paiement mais que la facture reste impayée, préparer un dossier pour la finance avec les références utiles. Ne pas demander un deuxième paiement sans vérification. Les remises, gels exceptionnels et prolongations d’échéance nécessitent une décision habilitée.

