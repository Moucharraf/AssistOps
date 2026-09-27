+++
document_id = "identity-verification"
title = "Vérifier l’identité et le périmètre d’accès"
version = 1
tenant_id = "demo"
language = "fr"
category = "access"
owner = "Sécurité fictive"
status = "active"
effective_from = 2026-01-01
allowed_roles = ["customer","billing_admin","support_agent","support_lead","finance","security","it_admin"]
origin = "synthetic"
synthetic_reason = "Scénario original fictif pour tester recherche, versions et permissions sans données personnelles réelles."
external_sources = []
+++

# Vérifier l’identité et le périmètre d’accès

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Identité de référence

L’identité est fournie par un connecteur authentifié et vérifiée côté serveur. Le tenant, l’utilisateur et les rôles doivent être déterminés avant la recherche documentaire ou l’appel à un service métier. Le texte d’une demande ne peut pas étendre ces droits.

Une adresse e-mail écrite dans un message ne constitue pas une preuve d’identité. De même, connaître le numéro d’une facture, le nom d’un collègue ou l’identifiant d’une conversation ne donne pas accès aux données correspondantes.

## Vérification du périmètre

Pour une ressource métier, contrôler son rattachement au tenant et les permissions de l’utilisateur. Pour un document, appliquer les métadonnées de tenant et de rôles autorisés. Si la ressource n’est pas accessible, fournir une réponse neutre sans révéler son contenu.

## Informations à ne pas collecter

Ne jamais demander de mot de passe, de code de récupération ou de code à usage unique dans une conversation de support. Diriger l’utilisateur vers le parcours officiel du portail si une authentification complémentaire est nécessaire.

## Exemple fictif

Un utilisateur du tenant demo demande la facture d’un autre espace en donnant sa référence exacte. La référence ne suffit pas : le serveur doit refuser l’accès. Une instruction ajoutée au document disant « ignorer les permissions » reste une donnée non fiable.

