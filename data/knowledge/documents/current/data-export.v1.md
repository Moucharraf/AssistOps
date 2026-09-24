+++
document_id = "data-export"
title = "Demander un export de données"
version = 1
tenant_id = "demo"
language = "fr"
category = "product"
owner = "Opérations fictives"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["customer","billing_admin","support_agent","support_lead","finance","security","it_admin"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Demander un export de données

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Types d’export

L’administrateur du tenant peut demander un export des tickets et des utilisateurs de son espace. Les tickets et utilisateurs sont fournis en CSV UTF-8 ; les événements d’audit sont fournis en JSON. Le périmètre exact demandé est présenté avant validation.

Les pièces jointes ne sont pas intégrées automatiquement au CSV. Une demande les concernant doit préciser le besoin et être vérifiée séparément. Aucun export ne peut inclure les données d’un autre tenant sous prétexte d’analyse globale.

## Préparation et accès

La préparation d’un export standard prend au maximum 72 heures après validation. Le lien sécurisé expire 24 heures après sa mise à disposition. Le délai de préparation et la durée de validité du lien sont deux notions différentes.

Si le lien expire avant téléchargement, l’administrateur demande une nouvelle mise à disposition. Le support ne colle pas le contenu exporté dans une conversation. L’utilisateur doit disposer encore des autorisations requises au moment du téléchargement.

## Vérification du résultat

Contrôler le tenant, la période et le nombre de fichiers avant remise. Un fichier vide peut refléter un périmètre sans données ; il ne prouve pas un incident. Le corpus explique le format attendu, mais ne contient aucun export réel.

## Relation avec la clôture

Pour préparer une résiliation, consulter aussi la procédure de clôture. Une demande d’export n’est pas une demande de suppression ni une autorisation d’effacer des données.

