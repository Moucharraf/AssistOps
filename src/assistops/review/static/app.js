"use strict";

const $ = (id) => document.getElementById(id);
const labels = {
  pending: "À valider",
  approved: "Approuvée",
  rejected: "Refusée",
  expired: "Expirée",
  sending: "Envoi en cours",
  succeeded: "Ticket créé",
  failed: "Échec Jira",
  uncertain: "À vérifier",
};
const messages = {
  invalid_credentials: "Identifiant ou mot de passe incorrect.",
  session_required: "Votre session a expiré. Reconnectez-vous.",
  approval_not_allowed: "Votre compte ne peut pas effectuer cette validation.",
  proposal_changed:
    "Le contenu ne correspond plus à la proposition affichée. Actualisez avant de décider.",
  decision_conflict:
    "Une décision a déjà été prise. Actualisez la proposition.",
  jira_destination_changed:
    "La destination Jira a changé. Une nouvelle proposition est nécessaire.",
  proposal_not_found: "Cette proposition est introuvable ou inaccessible.",
  review_rate_limited: "Trop de requêtes. Patientez avant de réessayer.",
  storage_unavailable: "Le service est temporairement indisponible.",
  business_backend_disabled:
    "Le service métier n’est pas activé dans cet environnement.",
  invalid_origin:
    "L’adresse de cette interface ne correspond pas à son adresse configurée.",
  invalid_csrf: "La session a changé. Rechargez cette page avant de décider.",
};
let session = null,
  selected = null,
  page = 0,
  detailVersion = 0,
  listVersion = 0;
let confirmation = null,
  submitting = false,
  refreshing = false;

function notice(text = "") {
  $("notice").textContent = text;
  $("notice").hidden = !text;
}
function formatDate(value) {
  return new Date(value).toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
function showLogin() {
  session = null;
  selected = null;
  detailVersion++;
  listVersion++;
  $("workspace").hidden = true;
  $("account").hidden = true;
  $("login-view").hidden = false;
  $("proposal-list").replaceChildren();
  $("proposal-detail").hidden = true;
  $("confirm-dialog").close();
  confirmation = null;
}
async function api(path, data) {
  const headers = {};
  if (data !== undefined)
    Object.assign(headers, {
      "Content-Type": "application/json",
      "X-AssistOps-UI": "1",
      "X-CSRF-Token": session?.csrf_token || "",
    });
  let response;
  try {
    response = await fetch(`/review/api/${path}`, {
      method: data === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers,
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error(
      data === undefined
        ? "Connexion interrompue. Réessayez dans un instant."
        : "Réponse non reçue. Vérifiez l’état de la proposition avant toute nouvelle décision.",
    );
  }
  if (!response.ok) {
    const error = (await response.json()).error || {};
    if (response.status === 401 && path !== "login") showLogin();
    const reference = error.correlation_id
      ? ` Référence : ${error.correlation_id}.`
      : "";
    throw new Error(
      (messages[error.code] || "La requête n’a pas pu aboutir.") + reference,
    );
  }
  return response.status === 204 ? null : response.json();
}
function report(error) {
  notice(error.message);
}
function badge(status) {
  const el = document.createElement("span");
  el.className = "badge";
  el.dataset.status = status;
  el.textContent = labels[status] || status;
  return el;
}
async function loadList() {
  const version = ++listVersion;
  const data = await api(`proposals?status=${$("filter").value}&page=${page}`);
  if (version !== listVersion || !session) return;
  const list = $("proposal-list");
  list.replaceChildren();
  for (const item of data.items) {
    const button = document.createElement("button");
    button.className = "proposal-row";
    button.setAttribute(
      "aria-pressed",
      String(selected?.proposal.id === item.id),
    );
    const top = document.createElement("span");
    top.className = "row-top";
    const provider = document.createElement("span");
    provider.className = "row-meta";
    provider.textContent =
      item.provider === "jira" ? "Jira Cloud" : "Simulation";
    top.append(badge(item.delivery_status || item.status), provider);
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = item.subject;
    const meta = document.createElement("span");
    meta.className = "row-meta";
    meta.textContent = `${item.requester_id} · ${formatDate(item.created_at)}`;
    button.append(top, title, meta);
    button.addEventListener("click", () =>
      selectProposal(item.id).catch(report),
    );
    list.append(button);
  }
  if (!data.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent =
      $("filter").value === "pending"
        ? "Aucune proposition en attente de validation."
        : "Aucune proposition dans cet historique.";
    list.append(empty);
  }
  $("previous").disabled = page === 0;
  $("next").disabled = !data.has_more;
  $("page-number").textContent = `Page ${page + 1}`;
}
function renderDetail(data) {
  selected = data;
  const p = data.proposal,
    args = p.arguments,
    target = args.ticket_target;
  $("empty-detail").hidden = true;
  $("proposal-detail").hidden = false;
  $("subject").textContent = args.subject;
  $("detail-status").replaceWith(
    Object.assign(badge(data.delivery_status || p.status), {
      id: "detail-status",
    }),
  );
  $("proposal-meta").textContent =
    `${formatDate(data.created_at)} · ${data.connector_id}`;
  $("destination").textContent = target
    ? `Action réelle · Jira Cloud\n${target.site} · Projet ${target.project} · Type ${target.issue_type_id}`
    : "Simulation locale · Aucun ticket envoyé à un service externe.";
  $("requester").textContent = data.requester_id;
  $("customer").textContent = args.customer_id;
  $("invoice").textContent = args.invoice_id;
  $("description").textContent = args.description;
  $("proposal-id").textContent = p.id;
  $("proposal-hash").textContent = p.arguments_hash;
  const outcomes = {
    awaiting_approval: "En attente d’une décision humaine.",
    rejected: "Proposition refusée. Aucun ticket créé.",
    expired: "Proposition expirée. Une nouvelle demande est nécessaire.",
    ticket_created: target
      ? "Ticket créé dans Jira."
      : "Ticket créé dans le simulateur local.",
    ticket_pending:
      "Approbation enregistrée. Livraison Jira en attente ou en cours.",
    ticket_failed:
      "La création Jira a échoué. Contactez un opérateur pour examiner l’erreur.",
    ticket_uncertain:
      "Résultat Jira incertain. Un opérateur doit vérifier si le ticket existe avant toute reprise. Aucun renvoi automatique.",
  };
  $("delivery").textContent =
    (outcomes[data.outcome] || data.outcome) +
    (data.error_code ? ` Code : ${data.error_code}.` : "");
  $("delivery").dataset.status = data.outcome;
  const link = $("ticket-link");
  link.hidden = true;
  link.removeAttribute("href");
  // Only construct links for the reviewed Atlassian destination; never trust arbitrary URLs.
  if (
    target &&
    /^https:\/\/[a-z0-9-]+\.atlassian\.net$/.test(target.site) &&
    /^[A-Z][A-Z0-9_]*-\d+$/.test(data.ticket_id || "")
  ) {
    link.href = `${target.site}/browse/${data.ticket_id}`;
    link.textContent = `Ouvrir ${data.ticket_id} dans Jira ↗`;
    link.hidden = false;
  }
  $("decision-meta").textContent = p.decided_by
    ? `Décision enregistrée par ${p.decided_by}.`
    : `Valable jusqu’au ${formatDate(p.expires_at)}.`;
  $("decision-actions").hidden = !data.can_decide;
  $("approve").textContent = target
    ? "Approuver l’envoi Jira…"
    : "Approuver la simulation…";
  $("decision-help").textContent = data.can_decide
    ? "L’approbation porte sur le contenu et la destination affichés."
    : p.status === "pending"
      ? "Vous ne pouvez pas valider votre propre demande."
      : "Cette proposition ne nécessite plus de décision.";
}
async function selectProposal(id) {
  const version = ++detailVersion;
  $("decision-actions").hidden = true;
  const data = await api(`proposals/${id}`);
  if (version !== detailVersion || !session) return;
  renderDetail(data);
  await loadList();
}
async function refresh() {
  if (refreshing || submitting || $("confirm-dialog").open || !session) return;
  refreshing = true;
  try {
    if (selected) await selectProposal(selected.proposal.id);
    else await loadList();
  } finally {
    refreshing = false;
  }
}
function confirmDecision(decision) {
  if (!selected?.can_decide) return;
  const p = selected.proposal,
    target = p.arguments.ticket_target;
  // Freeze the reviewed ID/hash while the confirmation is open; polling cannot replace them.
  confirmation = { id: p.id, arguments_hash: p.arguments_hash, decision };
  $("confirm-title").textContent =
    decision === "approved"
      ? "Approuver cette proposition ?"
      : "Refuser cette proposition ?";
  $("confirm-text").textContent =
    decision === "rejected"
      ? "Le ticket ne sera pas créé. Cette décision sera journalisée."
      : target
        ? `Cette décision autorise la création réelle d’un ticket sur ${target.site}, dans le projet ${target.project}.`
        : "Cette décision créera uniquement un ticket simulé localement.";
  $("confirm-subject").textContent = p.arguments.subject;
  $("confirm-decision").textContent =
    decision === "approved" ? "Confirmer l’approbation" : "Confirmer le refus";
  $("confirm-dialog").showModal();
}
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  notice();
  try {
    await api("login", {
      username: $("username").value,
      password: $("password").value,
    });
    $("password").value = "";
    await startSession();
  } catch (error) {
    report(error);
  } finally {
    button.disabled = false;
  }
});
$("logout").addEventListener("click", async () => {
  try {
    await api("logout", {});
    showLogin();
    notice();
  } catch (error) {
    report(error);
  }
});
$("refresh").addEventListener("click", () => {
  notice();
  refresh().catch(report);
});
$("filter").addEventListener("change", () => {
  page = 0;
  loadList().catch(report);
});
$("previous").addEventListener("click", () => {
  page = Math.max(0, page - 1);
  loadList().catch(report);
});
$("next").addEventListener("click", () => {
  page++;
  loadList().catch(report);
});
$("approve").addEventListener("click", () => confirmDecision("approved"));
$("reject").addEventListener("click", () => confirmDecision("rejected"));
$("confirm-dialog").addEventListener("cancel", (event) => {
  if (submitting) event.preventDefault();
});
$("confirm-decision").addEventListener("click", async () => {
  if (submitting || !confirmation) return;
  submitting = true;
  $("confirm-decision").disabled = true;
  $("cancel-decision").disabled = true;
  notice();
  const choice = confirmation;
  try {
    const data = await api(`proposals/${choice.id}/decision`, {
      decision: choice.decision,
      arguments_hash: choice.arguments_hash,
    });
    if (session) renderDetail(data);
  } catch (error) {
    report(error);
  } finally {
    submitting = false;
    confirmation = null;
    $("confirm-dialog").close();
    $("confirm-decision").disabled = false;
    $("cancel-decision").disabled = false;
    // Refresh after a lost response instead of automatically repeating the decision.
    if (session) refresh().catch(report);
  }
});
async function startSession() {
  session = await api("session");
  page = 0;
  $("identity").textContent = `${session.username} · ${session.tenant_id}`;
  $("account").hidden = false;
  $("login-view").hidden = true;
  $("workspace").hidden = false;
  $("empty-detail").hidden = false;
  await loadList();
}
startSession()
  .catch((error) => {
    showLogin();
    if (!error.message.startsWith(messages.session_required)) report(error);
  })
  .finally(() => {
    $("loading").hidden = true;
  });
setInterval(() => {
  if (!document.hidden) refresh().catch(report);
}, 15000);
