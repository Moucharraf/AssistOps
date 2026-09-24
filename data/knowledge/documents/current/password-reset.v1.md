+++
document_id = "password-reset"
title = "Réinitialiser un mot de passe et traiter un problème MFA"
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

# Réinitialiser un mot de passe et traiter un problème MFA

> Document synthétique — entreprise, produit et règles fictifs. Créé pour les tests AssistOps ; aucune politique réelle ni donnée client.

## Réinitialisation standard

Depuis la page de connexion du portail AsterDesk, choisir Mot de passe oublié et saisir l’adresse du compte. Le portail affiche la même confirmation qu’un compte existe ou non, afin de ne pas révéler les inscriptions.

Le lien de réinitialisation expire après 30 minutes et ne peut être utilisé qu’une fois. Une nouvelle demande invalide le lien précédent. Si le message n’arrive pas, vérifier les courriers indésirables et l’espace concerné avant de contacter le support.

## Ce que le support ne demande pas

Le support ne demande jamais le mot de passe actuel, le nouveau mot de passe ou un code MFA. Une capture contenant un lien actif doit être expurgée avant d’être jointe à un ticket. L’assistant explique le parcours ; il ne simule pas la réussite d’une réinitialisation.

## Perte du second facteur

La réinitialisation du mot de passe ne désactive pas l’authentification multifacteur. En cas de perte du second facteur, utiliser le parcours de récupération du portail ou ouvrir un dossier vérifié auprès de l’équipe habilitée. Une déclaration dans une conversation ne suffit pas à supprimer cette protection.

## Limites

Le corpus ne contient ni code de secours ni secret utilisable. Une demande de contournement doit être refusée et orientée vers la récupération autorisée.

