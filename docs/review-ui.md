# Interface de validation humaine

L’interface `/review` permet à une personne autorisée de vérifier une proposition,
de l’approuver ou de la refuser, puis de suivre la création du ticket. Elle est
servie par FastAPI : aucun serveur frontend ni conteneur supplémentaire.

## Première connexion

Le Compose local active l’interface sur **http://localhost:8000/review**.
L’activation seule ne crée aucun compte et aucun mot de passe par défaut.
Après une mise à jour, reconstruire la stack avec les mêmes fichiers Compose
que ceux utilisés au démarrage afin de conserver les intégrations actives.
Le service `migrate` applique la migration 009 pour les comptes et sessions.

Créer un compte dans le conteneur API déjà démarré :

```shell
docker compose exec api python -m assistops.review.cli set-password reviewer --tenant demo --user reviewer-001 --connector demo
```

La commande demande le mot de passe deux fois, sans l’afficher. Utiliser une
phrase de passe de **15 à 256 caractères**. Le mot de passe ne passe ni par les
arguments du processus, ni par `.env`, ni par le navigateur avant la connexion.
L’identifiant de connexion est `reviewer` ; son identité métier est `reviewer-001`.

Si l’intégration n8n est active, autoriser aussi la consultation de ses propositions :

```shell
docker compose exec api python -m assistops.review.cli set-password reviewer --tenant demo --user reviewer-001 --connector demo --connector n8n-demo
```

Cette commande remplace les droits du compte, change son mot de passe et révoque
ses sessions précédentes. Elle exige que les connecteurs existent dans la
configuration de l’API, appartiennent au tenant demandé, et que l’identité possède
le rôle `ticket_approver`. Aucun formulaire web ne peut créer un compte ou accorder
des droits.

Pour révoquer un compte :

```shell
docker compose exec api python -m assistops.review.cli disable reviewer
```

## Parcours de validation

1. Se connecter et ouvrir une proposition dans **À valider** ou **Tout l’historique**.
2. Vérifier le demandeur, le client, la facture, le sujet, la description et la destination.
3. Choisir **Approuver…** ou **Refuser**, puis confirmer dans la boîte de dialogue.
4. Suivre le résultat dans la même fiche. L’interface actualise les données toutes
   les 15 secondes lorsqu’elle est visible, hors confirmation et envoi d’une décision.

L’approbation porte sur l’UUID et l’empreinte du contenu affiché. Le navigateur
n’envoie jamais un nouveau sujet, une nouvelle destination, un rôle ou une identité
avec sa décision. L’API réutilise `BusinessTools.review`, qui contrôle les droits,
interdit l’auto-approbation, vérifie l’expiration et enregistre la décision avec l’audit.
Un rejeu de la même décision ne crée pas de deuxième ticket.

La liste masque les propositions expirées du filtre **À valider**, même si personne
ne les a encore consultées. Leur état persistant est finalisé lors de la consultation
ou d’une tentative de décision, comme pour l’API signée.

### Simulation et Jira

Les données clients et factures sont **synthétiques**, pour tester le circuit sans
exposer de données personnelles réelles. Ce caractère fictif est affiché dans la fiche.
Il ne signifie pas que toute action est simulée :

| Destination affichée | Conséquence d’une approbation |
| --- | --- |
| Simulation locale | Création dans `synthetic_tickets`, sans appel externe |
| Action réelle · Jira Cloud | Mise en file durable, puis création réelle par le worker |

Le site, le projet et le type Jira font partie de la proposition approuvée.
Le lien vers Jira apparaît après confirmation de la création. Une approbation
enregistrée ne signifie donc pas encore que Jira a créé le ticket.

Un résultat **incertain** indique que la réponse ne permet pas de savoir si Jira
a créé le ticket. L’interface ne propose aucun bouton de renvoi automatique.
Un opérateur utilise le [rapprochement Jira](jira.md) pour vérifier l’existence
du ticket. Un échec est également affiché avec son code, sans exposer la réponse
brute du fournisseur.

## Authentification et limites

Le navigateur reçoit un cookie de session opaque, `HttpOnly`, `SameSite=Strict`,
et `Secure` avec une origine HTTPS. PostgreSQL conserve uniquement l’empreinte
SHA-256 de ce jeton. Les sessions expirent après une heure par défaut ; déconnexion,
changement de mot de passe et désactivation invalident les sessions côté serveur.
Le mot de passe est stocké sous forme PBKDF2-HMAC-SHA256, avec sel aléatoire et
600 000 itérations, conformément au facteur décrit par
[OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

Les requêtes de modification exigent l’origine configurée, un en-tête dédié et,
après connexion, un jeton CSRF lié à la session. Les protections des cookies suivent
les [recommandations de gestion des sessions OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
Les réponses ne sont pas mises en cache, l’intégration dans une iframe est interdite
et la CSP n’autorise que les scripts et styles locaux. Les données métier sont
affichées comme du texte, jamais injectées comme du HTML.

La limitation partagée via PostgreSQL autorise au maximum 10 tentatives de connexion
par identifiant et 30 par adresse cliente sur une fenêtre de 5 minutes ; les requêtes
authentifiées sont limitées à 120 par compte et par minute. Une limitation renvoie
`429` avec `Retry-After`. La fenêtre peut bloquer temporairement un compte ciblé par
des tentatives répétées. Derrière un proxy, configurer explicitement les adresses
de proxy de confiance pour que l’API identifie correctement les clients.

Les droits de revue sont distincts de l’autorisation d’émettre des événements :
un compte peut examiner les propositions `n8n-demo` sans donner à n8n le droit
d’émettre des requêtes au nom de l’approbateur. L’API résout tenant, identité et
connecteurs à partir de la session ; les droits métier sont relus à chaque requête.
Les secrets HMAC, OpenAI et Jira ne sont jamais transmis au navigateur.

| Configuration | Valeur par défaut |
| --- | --- |
| `ASSISTOPS_REVIEW_UI_ENABLED` | `false`, activé par le Compose local |
| `ASSISTOPS_REVIEW_UI_ORIGIN` | `http://localhost:8000`, sans `/` final |
| `ASSISTOPS_REVIEW_SESSION_SECONDS` | `3600`, de 300 à 28 800 |

L’origine doit correspondre exactement à l’adresse ouverte dans le navigateur :
`localhost` et `127.0.0.1` sont des origines différentes. En production, une origine
HTTPS est obligatoire. Terminer TLS sur un proxy correctement configuré et remplacer
les identifiants publics du Compose local avant toute exposition réseau.

Il s’agit d’une authentification par comptes administrés, **sans SSO ni MFA**.
Ces capacités restent à ajouter pour un déploiement qui les exige. Le backend métier
actuel reste synthétique et interdit en mode `production` : cette interface ne transforme
pas à elle seule le projet en service de production complet.

## Vérifications automatisées

Les tests API vérifient sessions, cookies, CSRF, isolation des tenants/connecteurs,
révocation des droits, auto-approbation, empreinte, expiration, audit et rejeu. Les tests
Chromium vérifient le parcours réel connexion → consultation → confirmation → suivi →
déconnexion, ainsi que le refus et l’affichage de contenu hostile sur mobile.
Chaque test utilise un schéma PostgreSQL isolé ; aucun ticket Jira réel n’est créé.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,e2e]"
.\.venv\Scripts\python.exe -m playwright install chromium
$env:ASSISTOPS_TEST_DATABASE_URL = 'postgresql://assistops:assistops-local-only@localhost:5432/assistops'
.\.venv\Scripts\python.exe -m pytest tests/test_review_ui.py tests/test_review_browser.py
```

Chromium et Playwright ne sont installés que pour les tests, pas dans l’image API.
La CI exécute aussi ces parcours. La capture locale `.cache/review-ui.png` contient
uniquement le cas synthétique de test.
