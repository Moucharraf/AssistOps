+++
document_id = "refund-approvals"
title = "Circuit interne d’approbation des remboursements"
version = 1
tenant_id = "demo"
language = "fr"
category = "billing"
owner = "Finance fictive"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["support_lead","finance"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Circuit interne d’approbation des remboursements

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Diffusion restreinte

Cette procédure est réservée aux responsables support et à la finance du tenant demo. Elle détaille une répartition interne des pouvoirs de validation. Le client peut recevoir l’état de son dossier, mais pas cette matrice interne. Un agent ne doit pas déduire un droit d’accès de la formulation de sa question.

## Seuils de validation

Un remboursement inférieur ou égal à 100 EUR peut être validé par un responsable support habilité. Au-delà de 100 EUR, la validation de la finance est obligatoire. Le seuil s’applique au montant total à rembourser pour un même incident, après regroupement des demandes liées.

Il est interdit de fractionner un dossier pour éviter le seuil. En cas de devise différente, transmettre à la finance plutôt que d’appliquer un taux de change inventé. Le demandeur initial ne peut pas approuver sa propre demande de remboursement.

## Pièces nécessaires

Le dossier contient la facture, la preuve du paiement, le motif vérifié et le montant exact. La validation doit identifier l’approbateur, l’horodatage et les arguments approuvés. Toute modification du montant ou du bénéficiaire impose une nouvelle validation.

## Exécution et audit

Seul le système de paiement habilité exécute le remboursement. L’audit conserve les références de validation et d’exécution, sans numéro de carte complet. Ces règles fictives servent à tester les autorisations documentaires ; elles n’activent pas une fonction de paiement dans AssistOps.

