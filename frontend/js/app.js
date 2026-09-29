const api = window.QuorumAPI;

const escapeHtml = (value = "") =>
  String(value).replace(/[&<>"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[character]);

const readable = (value = "") => String(value).replaceAll("_", " ");
const localInput = (value) => String(value).slice(0, 16);
const shortDate = (value) => new Intl.DateTimeFormat("en-GB", {
  weekday: "short", day: "2-digit", month: "short",
}).format(new Date(value));
const fullDate = (value) => new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "2-digit", month: "long", year: "numeric",
}).format(new Date(value));
const clock = (value) => String(value).slice(11, 16);
const decisionTime = (value) => value ? new Intl.DateTimeFormat("en-GB", {
  day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
}).format(new Date(value)) : "";

function showError(message) {
  const host = document.querySelector("#messages");
  if (host) host.innerHTML = `<p class="error">${escapeHtml(message)}</p>`;
}

function showNotice(message) {
  const host = document.querySelector("#messages");
  if (host) host.innerHTML = `<p class="notice">${escapeHtml(message)}</p>`;
}

async function getUser(optional = false) {
  try {
    return (await api.get("/api/auth/me", { allowUnauthorized: optional })).user;
  } catch (error) {
    if (optional && error.status === 401) return null;
    throw error;
  }
}

function renderHeader(user) {
  const topbar = document.querySelector("#topbar");
  if (!topbar) return;
  const brand = `<a class="brand" href="index.html">Quorum</a>`;
  if (!user) {
    topbar.innerHTML = `${brand}<nav class="public-nav"><a href="login.html">Log in</a><a href="signup.html">Sign up</a></nav>`;
    return;
  }
  const adminLinks = user.role === "admin" ? `
    <a href="admin-requests.html">Approvals</a>
    <a href="admin-all-requests.html">All requests</a>
    <a href="admin-resources.html">Resources</a>
    <a href="dashboard.html">Dashboard</a>` : "";
  topbar.innerHTML = `${brand}
    <nav><a href="resources.html">Search</a><a href="my-requests.html">My requests</a>${adminLinks}</nav>
    <div class="account-nav"><span>${escapeHtml(user.name)} / ${escapeHtml(user.role)}</span><a href="#" id="logout-link">Log out</a></div>`;
  document.querySelector("#logout-link").addEventListener("click", async (event) => {
    event.preventDefault();
    await api.post("/api/auth/logout", {});
    window.location.href = "index.html";
  });
}

function renderForbidden() {
  document.title = "Admin only / Quorum";
  document.querySelector("main").innerHTML = `
    <section class="page-head access-head">
      <p class="kicker">403 / Admin only</p>
      <h1>This page is restricted.</h1>
      <p>Your account does not have permission to view this page.</p>
    </section>
    <p class="page-actions"><a class="action" href="resources.html">Return to resources</a></p>`;
}

async function requireUser(admin = false) {
  const user = await getUser();
  renderHeader(user);
  if (admin && user.role !== "admin") {
    renderForbidden();
    return null;
  }
  return user;
}

function statusLabel(status) {
  return `<span class="status status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function requestDecision(item) {
  if (item.status === "rejected" && item.rejection_note) return escapeHtml(item.rejection_note);
  if (item.decided_at) return `<span class="mono">${escapeHtml(decisionTime(item.decided_at))}</span>`;
  if (item.status === "pending") return `<span class="muted">Awaiting review</span>`;
  return `<span class="muted">Automatically approved</span>`;
}

async function submitBooking(payload) {
  try {
    const request = await api.post("/api/requests", payload);
    window.location.href = `confirmation.html?id=${request.id}`;
  } catch (error) {
    if (error.status === 409 && typeof error.detail === "object") {
      sessionStorage.setItem("quorumConflict", JSON.stringify({ ...error.detail, payload }));
      window.location.href = "conflict.html";
      return;
    }
    showError(error.message);
  }
}

function bindBookingForms() {
  document.querySelectorAll("form[data-booking]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = new FormData(form);
      submitBooking({
        resource_id: Number(data.get("resource_id")),
        start: data.get("start"),
        end: data.get("end"),
        attendees: Number(data.get("attendees")),
        purpose: data.get("purpose") || "Booking",
      });
    });
  });
}

async function landingPage() {
  renderHeader(await getUser(true));
}

async function loginPage() {
  renderHeader(await getUser(true));
  const demos = await api.get("/api/auth/demo-accounts", { allowUnauthorized: true });
  document.querySelector("#demo-list").innerHTML = demos.map((user) => `
    <form class="demo-account" data-demo-email="${escapeHtml(user.email)}">
      <span><strong>${escapeHtml(user.name)}</strong><br><span class="muted">${escapeHtml(user.email)} / ${escapeHtml(user.role)}</span></span>
      <button type="submit">Log in</button>
    </form>`).join("");
  document.querySelector("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const result = await api.post("/api/auth/login", {
        email: data.get("email"), password: data.get("password"),
      }, { allowUnauthorized: true });
      window.location.href = result.user.role === "admin" ? "admin-requests.html" : "resources.html";
    } catch (error) { showError(error.message); }
  });
  document.querySelectorAll("[data-demo-email]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api.post("/api/auth/demo-login", { email: form.dataset.demoEmail }, { allowUnauthorized: true });
      window.location.href = result.user.role === "admin" ? "admin-requests.html" : "resources.html";
    } catch (error) { showError(error.message); }
  }));
}

async function signupPage() {
  renderHeader(await getUser(true));
  document.querySelector("#signup-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api.post("/api/auth/signup", Object.fromEntries(data), { allowUnauthorized: true });
      window.location.href = "resources.html";
    } catch (error) {
      const message = Array.isArray(error.detail) ? error.detail[0]?.msg : error.message;
      showError(message);
    }
  });
}

function resourceRows(data) {
  if (!data.results.length) return `<section class="empty-state"><h2>No available resources</h2><p>Try another time, a smaller group, or fewer equipment requirements.</p></section>`;
  return `<div class="table-scroll"><table>
    <thead><tr><th>Resource</th><th>Zone</th><th>Capacity</th><th>Equipment</th><th>Zone load</th><th>Reason</th><th></th></tr></thead>
    <tbody>${data.results.map((item) => `<tr>
      <td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(readable(item.resource.type))}</span></td>
      <td>${escapeHtml(item.resource.zone.name)}</td><td class="mono">${item.resource.capacity}</td>
      <td>${item.resource.equipment.map(readable).map(escapeHtml).join(", ")}</td>
      <td class="load-cell ${item.zone_load > 0.6 ? "overloaded" : item.zone_load <= 0.3 ? "quiet" : ""}"><span class="mono">${item.load_percent}%</span><span class="load-track"><span style="width:${item.bar_width}%"></span></span></td>
      <td>${escapeHtml(item.reason)}</td><td><form data-booking>
        <input type="hidden" name="resource_id" value="${item.resource.id}"><input type="hidden" name="start" value="${localInput(data.filters.start)}"><input type="hidden" name="end" value="${localInput(data.filters.end)}"><input type="hidden" name="attendees" value="${data.filters.attendees}"><input type="hidden" name="purpose" value="Resource booking">
        <p class="request-outcome">${escapeHtml(item.approval_message)}</p><button type="submit">Book</button>
      </form></td>
    </tr>`).join("")}</tbody></table></div>`;
}

async function resourcesPage() {
  await requireUser();
  const params = new URLSearchParams(window.location.search);
  const load = async (query) => {
    try {
      const data = await api.get(`/api/resources?${query.toString()}`);
      document.querySelector("#resource-content").innerHTML = `
        <form class="command-form" id="command-form"><label class="sr-only" for="command">Describe the resource you need</label><input id="command" name="q" value="${escapeHtml(data.filters.query)}" placeholder="Quiet lab with a projector for 4 people tomorrow at 2pm" autocomplete="off"><button type="submit">Search</button></form>
        <form class="search-form" id="search-form">
          <label>Type<select name="type">${["", "lab", "classroom", "seminar_hall", "equipment"].map((type) => `<option value="${type}" ${data.filters.type === type ? "selected" : ""}>${type ? readable(type) : "any type"}</option>`).join("")}</select></label>
          <label>Attendees<input name="attendees" type="number" min="1" value="${data.filters.attendees}" required></label>
          <label>Equipment<input name="equipment" value="${escapeHtml(data.filters.equipment.join(", "))}" placeholder="projector, linux"></label>
          <label>Start<input name="start" type="datetime-local" step="1800" value="${localInput(data.filters.start)}" required></label>
          <label>End<input name="end" type="datetime-local" step="1800" value="${localInput(data.filters.end)}" required></label><button type="submit">Find resources</button>
        </form>
        <section class="rule-section results-head split"><h2>Available</h2><p class="mono">${data.results.length} results</p></section>${resourceRows(data)}`;
      document.querySelector("#command-form").addEventListener("submit", (event) => {
        event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); window.location.search = next;
      });
      document.querySelector("#search-form").addEventListener("submit", (event) => {
        event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); window.location.search = next;
      });
      bindBookingForms();
    } catch (error) { showError(error.message); }
  };
  await load(params);
}

async function resourcePage() {
  await requireUser();
  const id = new URLSearchParams(window.location.search).get("id");
  try {
    const data = await api.get(`/api/resources/${id}`);
    const resource = data.resource;
    document.title = `${resource.name} / Quorum`;
    document.querySelector("#resource-content").innerHTML = `
      <section class="page-head split"><div><p class="kicker">${escapeHtml(readable(resource.type))} / ${escapeHtml(resource.zone.name)}</p><h1>${escapeHtml(resource.name)}</h1><p>${resource.capacity} seats. ${resource.equipment.map(readable).map(escapeHtml).join(", ")}. Open <span class="mono">${clock(`0000-00-00T${resource.open_time}`)}-${clock(`0000-00-00T${resource.close_time}`)}</span>.</p></div>${resource.status === "maintenance" ? '<div class="status-block"><span class="status">maintenance</span></div>' : ""}</section>
      <section class="rule-section"><h2>Request</h2><form class="grid-form" data-booking><input type="hidden" name="resource_id" value="${resource.id}"><label>Start<input name="start" type="datetime-local" step="1800" required></label><label>End<input name="end" type="datetime-local" step="1800" required></label><label>Attendees<input name="attendees" type="number" min="1" max="${resource.capacity}" value="8" required></label><label>Purpose<input name="purpose" placeholder="Seminar prep"></label><p class="request-outcome">${escapeHtml(data.approval_message)}</p><button type="submit">Request slot</button></form></section>
      <section class="rule-section"><h2>Unavailable</h2>${data.unavailability.length ? `<ul class="plain-list">${data.unavailability.map((item) => `<li><span class="mono">${shortDate(item.start)} ${clock(item.start)}-${clock(item.end)}</span> ${escapeHtml(item.reason)}</li>`).join("")}</ul>` : "<p>No maintenance windows listed.</p>"}</section>
      <section class="rule-section"><h2>Recent Requests</h2><div class="table-scroll"><table><thead><tr><th>When</th><th>User</th><th>Attendees</th><th>Status</th></tr></thead><tbody>${data.recent_requests.map((item) => `<tr><td class="mono">${shortDate(item.start)} ${clock(item.start)}-${clock(item.end)}</td><td>${escapeHtml(item.user.name)}</td><td class="mono">${item.attendees}</td><td>${statusLabel(item.status)}</td></tr>`).join("")}</tbody></table></div></section>`;
    bindBookingForms();
  } catch (error) { showError(error.message); }
}

async function confirmationPage() {
  await requireUser();
  const id = new URLSearchParams(window.location.search).get("id");
  try {
    const item = await api.get(`/api/requests/${id}`);
    const copy = item.status === "approved" ? ["Your booking is confirmed.", "The slot is reserved. You can find it at any time under My requests."] : item.status === "pending" ? ["Your request is awaiting approval.", "The slot is held while an administrator reviews it. Its current status is pending."] : item.status === "rejected" ? ["Your request was rejected.", item.rejection_note || "The requested slot has been released."] : [`Your request is ${item.status}.`, "View My requests for the latest decision details."];
    document.querySelector("#confirmation-content").innerHTML = `<section class="page-head confirmation-head"><p class="kicker">Request #${item.id} submitted</p><p class="confirmation-status status status-${item.status}">${escapeHtml(item.status)}</p><h1>${escapeHtml(copy[0])}</h1><p>${escapeHtml(copy[1])}</p></section><section class="request-summary"><dl><div><dt>Resource</dt><dd>${escapeHtml(item.resource.name)}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div><div><dt>Date</dt><dd class="mono">${fullDate(item.start)}</dd></div><div><dt>Time</dt><dd class="mono">${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Attendees</dt><dd class="mono">${item.attendees}</dd></div><div><dt>Purpose</dt><dd>${escapeHtml(item.purpose)}</dd></div></dl></section><p class="page-actions"><a class="action" href="my-requests.html#request-${item.id}">View this request</a><a href="resources.html">Browse resources</a></p>`;
  } catch (error) { showError(error.message); }
}

async function conflictPage() {
  await requireUser();
  const data = JSON.parse(sessionStorage.getItem("quorumConflict") || "null");
  if (!data) { window.location.href = "resources.html"; return; }
  document.querySelector("#conflict-content").innerHTML = `<section class="page-head conflict-head"><p class="kicker">${escapeHtml(data.title)}</p><h1>Booking conflict</h1><p class="conflict-reason">${escapeHtml(data.reason)}</p></section><section class="conflict-options"><h2>Alternatives</h2>${data.alternatives.length ? `<div class="table-scroll"><table><thead><tr><th>Option</th><th>Resource</th><th>Time</th><th>Capacity</th><th></th></tr></thead><tbody>${data.alternatives.map((option) => `<tr><td>${escapeHtml(option.kind)}</td><td>${escapeHtml(option.resource.name)}</td><td class="mono">${shortDate(option.start)} ${clock(option.start)}-${clock(option.end)}</td><td class="mono">${option.resource.capacity}</td><td><form data-booking><input type="hidden" name="resource_id" value="${option.resource.id}"><input type="hidden" name="start" value="${localInput(option.start)}"><input type="hidden" name="end" value="${localInput(option.end)}"><input type="hidden" name="attendees" value="${data.payload.attendees}"><input type="hidden" name="purpose" value="${escapeHtml(data.payload.purpose)}"><button type="submit">Book</button></form></td></tr>`).join("")}</tbody></table></div>` : "<p>No nearby alternative is free.</p>"}</section>`;
  bindBookingForms();
}

async function myRequestsPage() {
  const user = await requireUser();
  const status = new URLSearchParams(window.location.search).get("status") || "all";
  const data = await api.get(`/api/my-requests?status=${encodeURIComponent(status)}`);
  document.querySelector("#requests-content").innerHTML = `<section class="page-head"><p class="kicker">${escapeHtml(user.name)}</p><h1>My requests</h1><p>Booking requests and their current decisions.</p></section><nav class="filter-tabs" aria-label="Request status">${["all", "pending", "approved", "rejected"].map((value) => `<a href="my-requests.html?status=${value}" ${status === value ? 'aria-current="page"' : ""}>${value}</a>`).join("")}</nav>${data.requests.length ? `<div class="table-scroll"><table><thead><tr><th>Request</th><th>Resource</th><th>When</th><th>Purpose</th><th>Status</th><th>Decision</th></tr></thead><tbody>${data.requests.map((item) => `<tr id="request-${item.id}"><td class="mono">#${item.id}</td><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(item.resource.zone.name)}</span></td><td class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</td><td>${escapeHtml(item.purpose)}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td></tr>`).join("")}</tbody></table></div>` : `<section class="empty-state"><h2>No requests yet</h2><p>Choose a resource to make your first booking request.</p><a class="action" href="resources.html">Browse resources</a></section>`}`;
}

async function approvalsPage() {
  if (!await requireUser(true)) return;
  const data = await api.get("/api/admin/requests");
  document.querySelector("#approvals-content").innerHTML = `<section class="page-head split"><div><p class="kicker">Admin</p><h1>Approval queue</h1><p>Pending requests, newest first.</p></div><p class="queue-count"><span class="mono">${data.requests.length}</span> pending</p></section>${data.requests.length ? `<div class="approval-list">${data.requests.map((item) => `<article class="approval-row"><div><p class="kicker">Request #${item.id} / ${decisionTime(item.created_at)}${item.is_new ? ' / <span class="new-label">New</span>' : ""}</p><h2>${escapeHtml(item.resource.name)}</h2><p>${escapeHtml(item.user.name)} / ${escapeHtml(item.user.role)}<br>${escapeHtml(item.purpose)}</p></div><dl class="compact-details"><div><dt>When</dt><dd class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Attendees</dt><dd class="mono">${item.attendees} / ${item.resource.capacity}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div></dl><div class="decision-actions"><form data-approve="${item.id}"><button type="submit">Approve</button></form><form data-reject="${item.id}"><label>Rejection note (optional)</label><input name="rejection_note" placeholder="Reason for rejection"><button class="secondary-action" type="submit">Reject</button></form></div></article>`).join("")}</div>` : `<section class="empty-state"><h2>Queue clear</h2><p>There are no requests awaiting approval.</p></section>`}`;
  document.querySelectorAll("[data-approve]").forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); await api.post(`/api/admin/requests/${form.dataset.approve}/approve`, {}); showNotice("Request approved"); await approvalsPage(); }));
  document.querySelectorAll("[data-reject]").forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); const note = new FormData(form).get("rejection_note"); await api.post(`/api/admin/requests/${form.dataset.reject}/reject`, { rejection_note: note }); showNotice("Request rejected"); await approvalsPage(); }));
}

async function allRequestsPage() {
  if (!await requireUser(true)) return;
  const query = new URLSearchParams(window.location.search);
  const status = query.get("status") || "all"; const role = query.get("role") || "all"; const resourceId = query.get("resource_id") || "";
  const [data, resourceData] = await Promise.all([api.get(`/api/admin/all-requests?status=${encodeURIComponent(status)}&role=${encodeURIComponent(role)}${resourceId ? `&resource_id=${resourceId}` : ""}`), api.get("/api/admin/resources")]);
  document.querySelector("#all-requests-content").innerHTML = `<section class="page-head split"><div><p class="kicker">Admin</p><h1>All requests</h1><p>Requests from students, faculty, and administrators, newest first.</p></div><p class="queue-count"><span class="mono">${data.requests.length}</span> shown</p></section><form class="request-filters" id="request-filters"><label>Status<select name="status">${["all", "pending", "approved", "rejected", "cancelled"].map((value) => `<option ${status === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>Role<select name="role">${["all", "student", "faculty", "admin"].map((value) => `<option ${role === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>Resource<select name="resource_id"><option value="">all resources</option>${resourceData.resources.map((resource) => `<option value="${resource.id}" ${String(resource.id) === resourceId ? "selected" : ""}>${escapeHtml(resource.name)}</option>`).join("")}</select></label><button type="submit">Apply filters</button></form>${data.requests.length ? `<div class="table-scroll"><table><thead><tr><th>Request</th><th>User</th><th>Resource</th><th>When</th><th>Status</th><th>Decision</th></tr></thead><tbody>${data.requests.map((item) => `<tr><td class="mono">#${item.id}</td><td>${escapeHtml(item.user.name)}<br><span class="muted">${escapeHtml(item.user.role)}</span></td><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(item.resource.zone.name)}</span></td><td class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td></tr>`).join("")}</tbody></table></div>` : `<section class="empty-state"><h2>No matching requests</h2><p>Change a filter to broaden the results.</p></section>`}`;
  document.querySelector("#request-filters").addEventListener("submit", (event) => { event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); [...next.entries()].forEach(([key, value]) => { if (!value) next.delete(key); }); window.location.search = next; });
}

function resourcePayload(form, includeStatus = false) {
  const data = new FormData(form);
  const payload = { name: data.get("name"), type: data.get("type"), zone_id: Number(data.get("zone_id")), capacity: Number(data.get("capacity")), equipment: String(data.get("equipment") || "").split(",").map((item) => item.trim()).filter(Boolean), requires_approval: data.get("requires_approval") === "true", open_time: data.get("open_time"), close_time: data.get("close_time") };
  if (includeStatus) payload.status = data.get("status");
  return payload;
}

async function adminResourcesPage() {
  if (!await requireUser(true)) return;
  const data = await api.get("/api/admin/resources");
  const zoneOptions = (selected) => data.zones.map((zone) => `<option value="${zone.id}" ${zone.id === selected ? "selected" : ""}>${escapeHtml(zone.name)}</option>`).join("");
  document.querySelector("#admin-resources-content").innerHTML = `<section class="page-head"><p class="kicker">Admin</p><h1>Resources</h1><p>Register, edit, deactivate, and block resources.</p></section><section class="rule-section"><h2>Register Resource</h2><form class="grid-form" id="create-resource"><label>Name<input name="name" required></label><label>Type<select name="type"><option>lab</option><option>classroom</option><option value="seminar_hall">seminar hall</option><option>equipment</option></select></label><label>Zone<select name="zone_id">${zoneOptions()}</select></label><label>Capacity<input name="capacity" type="number" min="1" value="30"></label><label>Equipment<input name="equipment" placeholder="projector, linux"></label><label>Open<input name="open_time" type="time" step="1800" value="08:00"></label><label>Close<input name="close_time" type="time" step="1800" value="20:00"></label><label class="check"><input name="requires_approval" type="checkbox" value="true"> Requires approval</label><button type="submit">Add</button></form></section><section class="rule-section"><h2>Edit Resources</h2>${data.resources.map((resource) => `<details class="resource-editor"><summary><span>${escapeHtml(resource.name)}</span><span class="mono">${escapeHtml(resource.zone.name)} / ${resource.capacity}${resource.status === "maintenance" ? " / maintenance" : ""}</span></summary><form class="grid-form" data-edit-resource="${resource.id}"><label>Name<input name="name" value="${escapeHtml(resource.name)}" required></label><label>Type<select name="type">${["lab", "classroom", "seminar_hall", "equipment"].map((type) => `<option value="${type}" ${resource.type === type ? "selected" : ""}>${readable(type)}</option>`).join("")}</select></label><label>Zone<select name="zone_id">${zoneOptions(resource.zone_id)}</select></label><label>Capacity<input name="capacity" type="number" min="1" value="${resource.capacity}"></label><label>Equipment<input name="equipment" value="${escapeHtml(resource.equipment.join(", "))}"></label><label>Status<select name="status"><option ${resource.status === "active" ? "selected" : ""}>active</option><option ${resource.status === "maintenance" ? "selected" : ""}>maintenance</option></select></label><label>Open<input name="open_time" type="time" value="${resource.open_time.slice(0, 5)}"></label><label>Close<input name="close_time" type="time" value="${resource.close_time.slice(0, 5)}"></label><label class="check"><input name="requires_approval" type="checkbox" value="true" ${resource.requires_approval ? "checked" : ""}> Requires approval</label><button type="submit">Save</button></form><form class="grid-form narrow" data-block-resource="${resource.id}"><label>Unavailable start<input name="start" type="datetime-local" step="1800" required></label><label>Unavailable end<input name="end" type="datetime-local" step="1800" required></label><label>Reason<input name="reason" value="maintenance" required></label><button type="submit">Block</button></form></details>`).join("")}</section>`;
  document.querySelector("#create-resource").addEventListener("submit", async (event) => { event.preventDefault(); await api.post("/api/admin/resources", resourcePayload(event.currentTarget)); await adminResourcesPage(); });
  document.querySelectorAll("[data-edit-resource]").forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); await api.put(`/api/admin/resources/${form.dataset.editResource}`, resourcePayload(form, true)); await adminResourcesPage(); }));
  document.querySelectorAll("[data-block-resource]").forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(form)); await api.post(`/api/admin/resources/${form.dataset.blockResource}/unavailability`, values); await adminResourcesPage(); }));
}

async function dashboardPage() {
  if (!await requireUser(true)) return;
  const data = await api.get("/api/admin/dashboard");
  document.querySelector("#dashboard-content").innerHTML = `<section class="page-head split"><div><p class="kicker">${shortDate(data.week_start)}-${shortDate(data.week_last_day)}</p><h1>Utilization</h1><p>Booking pressure across campus for the current week.</p></div><dl class="usage-extremes"><div><dt>Most used</dt><dd>${escapeHtml(data.most_used.resource.name)}<br><span class="mono">${data.most_used.booked_hours.toFixed(1)}h</span></dd></div><div><dt>Least used</dt><dd>${escapeHtml(data.least_used.resource.name)}<br><span class="mono">${data.least_used.booked_hours.toFixed(1)}h</span></dd></div></dl></section><section class="metric-band">${["pending", "approved", "rejected"].map((status) => `<div><span class="metric-number">${data.counts[status]}</span>${statusLabel(status)}</div>`).join("")}</section><section class="rule-section"><div class="split section-title"><h2>Peak hours</h2><p>Share of active resources booked</p></div><div class="peak-grid" style="--slot-count:${data.slot_labels.length}"><div></div>${data.slot_labels.map((label, index) => `<div class="peak-time">${index % 4 === 0 ? label : ""}</div>`).join("")}${data.peak_rows.map((row) => `<div class="peak-day">${row.day}</div>${row.cells.map((cell) => `<div class="peak-cell" style="--intensity:${cell.intensity}" title="${cell.label} / ${cell.booked_count} resources / ${cell.percent}%"></div>`).join("")}`).join("")}</div><p class="grid-legend"><span>Quiet</span><span class="legend-scale"></span><span>Busy</span></p></section><section class="rule-section"><h2>Zones</h2><div class="table-scroll"><table><thead><tr><th>Zone</th><th>Booked</th><th>Open</th><th>Utilization</th></tr></thead><tbody>${data.zone_rows.map((item) => `<tr><td>${escapeHtml(item.zone.name)}<br><span class="muted">${escapeHtml(item.zone.building)}</span></td><td class="mono">${item.booked_hours.toFixed(1)}h</td><td class="mono">${item.open_hours.toFixed(0)}h</td><td class="utilization-cell"><span class="mono">${item.percent}%</span><span class="load-track"><span style="width:${item.percent}%"></span></span></td></tr>`).join("")}</tbody></table></div></section><section class="rule-section"><h2>Resources</h2><div class="table-scroll"><table><thead><tr><th>Resource</th><th>Zone</th><th>Booked</th><th>Open</th><th>Utilization</th></tr></thead><tbody>${data.resource_rows.map((item) => `<tr><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a></td><td>${escapeHtml(item.resource.zone.name)}</td><td class="mono">${item.booked_hours.toFixed(1)}h</td><td class="mono">${item.open_hours.toFixed(0)}h</td><td class="utilization-cell"><span class="mono">${item.percent}%</span><span class="load-track"><span style="width:${item.percent}%"></span></span></td></tr>`).join("")}</tbody></table></div></section>`;
}

const pages = { landing: landingPage, login: loginPage, signup: signupPage, resources: resourcesPage, resource: resourcePage, confirmation: confirmationPage, conflict: conflictPage, "my-requests": myRequestsPage, approvals: approvalsPage, "all-requests": allRequestsPage, "admin-resources": adminResourcesPage, dashboard: dashboardPage };

document.addEventListener("DOMContentLoaded", async () => {
  try { await pages[document.body.dataset.page]?.(); }
  catch (error) {
    if (error.status === 403) renderForbidden(); else if (error.status !== 401) showError(error.message || "Something went wrong.");
  }
});
