const api = window.QuorumAPI;

const escapeHtml = (value = "") =>
  String(value).replace(/[&<>"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[character]);

const readable = (value = "") => String(value).replaceAll("_", " ");
const adminScopeLabel = (scope) => ({
  all: "All resources",
  labs: "Labs",
  facilities: "Classrooms, seminar halls and equipment",
})[scope] || "No scope assigned";
const homeForUser = (user) => user.role === "admin" ? "admin-home.html" : "user-dashboard.html";
const localInput = (value) => String(value).slice(0, 16);
const indiaDate = (value) => {
  const text = String(value);
  const hasOffset = /(?:Z|[+-]\d{2}:\d{2})$/.test(text);
  return new Date(hasOffset ? text : `${text}+05:30`);
};
const shortDate = (value) => new Intl.DateTimeFormat("en-GB", {
  weekday: "short", day: "2-digit", month: "short", timeZone: "Asia/Kolkata",
}).format(indiaDate(value));
const fullDate = (value) => new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "2-digit", month: "long", year: "numeric", timeZone: "Asia/Kolkata",
}).format(indiaDate(value));
const clock = (value) => String(value).slice(11, 16);
const decisionTime = (value) => value ? new Intl.DateTimeFormat("en-GB", {
  day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  timeZone: "Asia/Kolkata",
}).format(indiaDate(value)) : "";

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
  const brand = `<a class="brand" href="${user ? homeForUser(user) : "index.html"}">Quorum</a>`;
  if (!user) {
    topbar.innerHTML = `${brand}<nav class="public-nav"><a href="login.html">Log in</a><a href="signup.html">Sign up</a></nav>`;
    return;
  }
  const managementLinks = user.role === "admin" && user.admin_scope === "all" ? `
    <a href="admin-users.html">Users</a>
    <a href="admin-resources.html">Resources</a>` : "";
  const adminLinks = user.role === "admin" ? `
    <a href="admin-home.html">Home</a>
    <a href="admin-requests.html">Approvals</a>
    <a href="admin-all-requests.html">All requests</a>
    <a href="admin-history.html">History</a>
    ${managementLinks}
    <a href="dashboard.html">Dashboard</a>` : "";
  const accountLabel = user.role === "admin"
    ? `${escapeHtml(user.designation || user.name)} &middot; ${escapeHtml(adminScopeLabel(user.admin_scope))}`
    : `${escapeHtml(user.name)} / ${escapeHtml(user.role)}`;
  const userLinks = user.role === "admin"
    ? `<a href="resources.html">Search</a>${adminLinks}<a href="profile.html">Profile</a>`
    : `<a href="user-dashboard.html">Home</a><a href="resources.html">Search</a><a href="my-requests.html">My requests</a><a href="profile.html">Profile</a>`;
  topbar.innerHTML = `${brand}
    <nav>${userLinks}</nav>
    <div class="account-nav"><span>${accountLabel}</span><a href="#" id="logout-link">Log out</a></div>`;
  document.querySelector("#logout-link").addEventListener("click", async (event) => {
    event.preventDefault();
    await api.post("/api/auth/logout", {});
    window.location.href = "index.html";
  });
}

function renderForbidden(campusOnly = false) {
  document.title = `${campusOnly ? "Campus Admin" : "Admin"} only / Quorum`;
  document.querySelector("main").innerHTML = `
    <section class="page-head access-head">
      <p class="kicker">403 / ${campusOnly ? "Campus Admin" : "Admin"} only</p>
      <h1>This page is restricted.</h1>
      <p>Your account does not have permission to view this page.</p>
    </section>
    <p class="page-actions"><a class="action" href="resources.html">Return to resources</a></p>`;
}

async function requireCampusAdmin() {
  const user = await requireUser(true);
  if (!user) return null;
  if (user.admin_scope !== "all") {
    renderForbidden(true);
    return null;
  }
  return user;
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
  return `<span class="status status-${escapeHtml(status)}">${escapeHtml(readable(status))}</span>`;
}

function eventTimeline(events = []) {
  if (!events.length) return `<p class="muted">No history recorded.</p>`;
  return `<ol class="event-timeline">${events.map((event) => `<li><div><span class="status status-${escapeHtml(event.event.includes("approved") || event.event === "extended" ? "approved" : event.event.includes("rejected") ? "rejected" : event.event === "created" ? "pending" : "cancelled")}">${escapeHtml(readable(event.event))}</span><span class="mono">${escapeHtml(decisionTime(event.created_at))}</span></div><p>${event.actor ? escapeHtml(event.actor.name) : "System"}${event.note ? ` / ${escapeHtml(event.note)}` : ""}</p></li>`).join("")}</ol>`;
}

const expectedBackText = (resource) => resource.expected_back
  ? ` Expected back ${fullDate(`${resource.expected_back}T00:00`)}.`
  : "";

function requestDecision(item) {
  if (item.status === "pending") return `<span class="muted">Awaiting review</span>`;
  if (["approved", "rejected"].includes(item.status) && item.decider && item.decided_at) {
    const action = item.status === "approved" ? "Approved" : "Rejected";
    const note = item.status === "rejected" && item.rejection_note
      ? `<br><span>Note: ${escapeHtml(item.rejection_note)}</span>`
      : "";
    return `<span class="decision-${item.status}">${action} by ${escapeHtml(item.decider.name)} &middot; <span class="mono">${escapeHtml(decisionTime(item.decided_at))}</span>${note}</span>`;
  }
  if (["cancelled", "expired"].includes(item.status)) return `<span class="muted">${escapeHtml(item.status_reason || readable(item.status))}</span>`;
  return `<span class="muted">Automatically approved</span>`;
}

const displayPurpose = (value) => String(value || "").trim() || "No purpose given";
const purposePreview = (value) => {
  const purpose = displayPurpose(value);
  return purpose.length > 110 ? `${purpose.slice(0, 107)}...` : purpose;
};

function bookingUrl(resourceId, values = {}) {
  const params = new URLSearchParams({ resource: resourceId });
  for (const key of ["start", "end", "attendees"]) {
    if (values[key] !== undefined && values[key] !== "") params.set(key, values[key]);
  }
  return `book.html?${params.toString()}`;
}

const bookingCanSubmit = (form) =>
  form.checkValidity() && form.elements.confirmed.checked;

async function landingPage() {
  const user = await getUser(true);
  if (user) {
    window.location.replace(homeForUser(user));
    return;
  }
  renderHeader(null);
}

function showOtpStep(originalForm, challenge, verifyPath, onVerified) {
  originalForm.hidden = true;
  const otpForm = document.createElement("form");
  otpForm.className = "auth-form otp-form";
  otpForm.innerHTML = `
    <p class="otp-message"></p>
    <label>Verification code<input name="otp" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required></label>
    <div class="otp-actions"><button type="submit">Verify</button><button class="secondary-action" type="button" data-change-email>Use another email</button></div>`;
  otpForm.querySelector(".otp-message").textContent = challenge.message;
  originalForm.insertAdjacentElement("afterend", otpForm);
  otpForm.querySelector("input").focus();
  otpForm.querySelector("[data-change-email]").addEventListener("click", () => {
    otpForm.remove();
    originalForm.hidden = false;
  });
  otpForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api.post(verifyPath, {
        challenge_id: challenge.challenge_id,
        otp: new FormData(otpForm).get("otp"),
      }, { allowUnauthorized: true });
      onVerified(result);
    } catch (error) {
      showError(error.message);
    }
  });
}

async function loginPage() {
  renderHeader(await getUser(true));
  const demos = await api.get("/api/auth/demo-accounts", { allowUnauthorized: true });
  document.querySelector(".demo-accounts").hidden = demos.length === 0;
  document.querySelector("#demo-list").innerHTML = demos.map((user) => `
    <form class="demo-account" data-demo-email="${escapeHtml(user.email)}">
      <span><strong>${escapeHtml(user.name)}</strong><br><span class="muted">${escapeHtml(user.email)} / ${escapeHtml(user.role)}</span></span>
      <button type="submit">Log in</button>
    </form>`).join("");
  document.querySelector("#login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      const challenge = await api.post("/api/auth/login", {
        email: data.get("email"), password: data.get("password"),
      }, { allowUnauthorized: true });
      showOtpStep(event.currentTarget, challenge, "/api/auth/login/verify", (result) => {
        window.location.href = homeForUser(result.user);
      });
    } catch (error) { showError(error.message); }
  });
  document.querySelectorAll("[data-demo-email]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api.post("/api/auth/demo-login", { email: form.dataset.demoEmail }, { allowUnauthorized: true });
      window.location.href = homeForUser(result.user);
    } catch (error) { showError(error.message); }
  }));
}

async function signupPage() {
  renderHeader(await getUser(true));
  const form = document.querySelector("#signup-form");
  const role = document.querySelector("#signup-role");
  const yearField = document.querySelector("#year-field");
  const year = yearField.querySelector("select");
  const syncRoleFields = () => {
    const isStudent = role.value === "student";
    document.querySelector("#id-number-label").textContent = isStudent ? "Register number" : "Employee ID";
    yearField.hidden = !isStudent;
    year.required = isStudent;
    year.disabled = !isStudent;
  };
  role.addEventListener("change", syncRoleFields);
  syncRoleFields();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (data.year_of_study) data.year_of_study = Number(data.year_of_study);
    try {
      const challenge = await api.post("/api/auth/signup", data, { allowUnauthorized: true });
      showOtpStep(form, challenge, "/api/auth/signup/verify", () => {
        window.location.href = "user-dashboard.html";
      });
    } catch (error) {
      const message = Array.isArray(error.detail) ? error.detail[0]?.msg : error.message;
      showError(message);
    }
  });
}

async function profilePage() {
  await requireUser();
  const user = await api.get("/api/auth/profile");
  const adminFields = user.role === "admin" ? `
      <div><dt>Department / office</dt><dd>${escapeHtml(user.department)}</dd></div>
      <div><dt>Employee ID</dt><dd class="mono">${escapeHtml(user.id_number)}</dd></div>
      <div><dt>Designation</dt><dd>${escapeHtml(user.designation)}</dd></div>
      <div><dt>Scope</dt><dd>${escapeHtml(adminScopeLabel(user.admin_scope))}</dd></div>` : `
      <div><dt>Department</dt><dd>${escapeHtml(user.department)}</dd></div>
      <div><dt>${user.role === "student" ? "Register number" : "Employee ID"}</dt><dd class="mono">${escapeHtml(user.id_number)}</dd></div>
      ${user.role === "student" ? `<div><dt>Year of study</dt><dd class="mono">${user.year_of_study}</dd></div>` : ""}`;
  document.querySelector("#profile-content").innerHTML = `
    <section class="page-head"><p class="kicker">Account</p><h1>Profile</h1><p>Profile details are locked after sign up. Contact the admin to correct them.</p></section>
    <section class="request-summary"><dl>
      <div><dt>Name</dt><dd>${escapeHtml(user.name)}</dd></div>
      <div><dt>Email</dt><dd>${escapeHtml(user.email)}</dd></div>
      <div><dt>Role</dt><dd>${escapeHtml(readable(user.role))}</dd></div>
      ${adminFields}
      <div><dt>Member since</dt><dd class="mono">${fullDate(user.member_since)}</dd></div>
    </dl></section>`;
}

function compactRequestTable(items, emptyText) {
  if (!items.length) return `<p class="muted">${escapeHtml(emptyText)}</p>`;
  return `<div class="table-scroll"><table><thead><tr><th>Request</th><th>Resource</th><th>When</th><th>Status</th><th>Decision</th></tr></thead><tbody>${items.map((item) => `<tr><td class="mono">#${item.id}</td><td>${escapeHtml(item.resource.name)}<br><span class="muted">${escapeHtml(item.resource.zone.name)}</span></td><td class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td></tr>`).join("")}</tbody></table></div>`;
}

async function userDashboardPage() {
  const user = await requireUser();
  if (user.role === "admin") {
    window.location.replace("admin-home.html");
    return;
  }
  const data = await api.get("/api/dashboard");
  document.querySelector("#user-dashboard-content").innerHTML = `
    <section class="page-head"><p class="kicker">${escapeHtml(user.name)}</p><h1>Your dashboard</h1></section>
    <form class="command-form" id="dashboard-search"><label class="sr-only" for="dashboard-command">Describe the resource you need</label><input id="dashboard-command" name="q" placeholder="Quiet lab with a projector for 4 people tomorrow at 2pm" autocomplete="off"><button type="submit">Search</button></form>
    ${data.holds.length ? `<section class="notice-band"><h2>Resource notices</h2>${data.holds.map((resource) => `<p><a href="resource.html?id=${resource.id}">${escapeHtml(resource.name)}</a> is on hold: ${escapeHtml(resource.hold_reason || "Unavailable")}.${escapeHtml(expectedBackText(resource))}</p>`).join("")}</section>` : ""}
    <section class="rule-section"><h2>Upcoming approved</h2>${compactRequestTable(data.upcoming, "No upcoming approved bookings.")}</section>
    <section class="rule-section"><h2>Pending requests</h2>${compactRequestTable(data.pending, "No requests awaiting review.")}</section>
    <section class="rule-section"><h2>Recent decisions</h2>${compactRequestTable(data.recent_decisions, "No recent decisions.")}</section>
    <section class="rule-section"><div class="split section-title"><h2>Quieter zones right now</h2><p>Current campus load</p></div><div class="zone-load-list">${data.quieter_zones.map((item) => `<div><span>${escapeHtml(item.zone.name)}<br><small>${escapeHtml(item.zone.building)}</small></span><span class="utilization-cell"><span class="mono">${item.percent}%</span><span class="load-track"><span style="width:${Math.min(item.percent, 100)}%"></span></span></span></div>`).join("")}</div></section>`;
  document.querySelector("#dashboard-search").addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.href = `resources.html?${new URLSearchParams(new FormData(event.currentTarget))}`;
  });
}

async function adminHomePage() {
  const admin = await requireUser(true);
  if (!admin) return;
  const data = await api.get("/api/admin/home");
  document.querySelector("#admin-home-content").innerHTML = `
    <section class="page-head split"><div><p class="kicker">${escapeHtml(adminScopeLabel(admin.admin_scope))}</p><h1>Admin home</h1><p>Requests and resource availability in your scope.</p></div><p class="queue-count"><span class="mono">${data.pending.length}</span> pending</p></section>
    <section class="metric-band">${["pending", "approved", "rejected"].map((status) => `<div><span class="metric-number">${data.today_counts[status]}</span>${statusLabel(status)}</div>`).join("")}</section>
    <section class="rule-section"><h2>Pending requests</h2>${data.pending.length ? `<div class="approval-list">${data.pending.map((item) => `<article class="approval-row"><div><p class="kicker">Request #${item.id} / ${decisionTime(item.created_at)}${item.is_new ? ' / <span class="new-label">New</span>' : ""}</p><h2>${escapeHtml(item.resource.name)}</h2><p>${escapeHtml(item.user.name)} / ${escapeHtml(item.user.role)}</p><p class="purpose-preview">${escapeHtml(purposePreview(item.purpose))}</p></div><dl class="compact-details"><div><dt>When</dt><dd class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div></dl><div class="review-link"><a class="action" href="admin-request.html?id=${item.id}">Review request</a></div></article>`).join("")}</div>` : `<p class="muted">No requests awaiting review.</p>`}</section>
    <section class="rule-section"><h2>Resources on hold</h2>${data.holds.length ? `<div class="table-scroll"><table><thead><tr><th>Resource</th><th>Zone</th><th>Reason</th><th>Expected back</th></tr></thead><tbody>${data.holds.map((resource) => `<tr><td><a href="resource.html?id=${resource.id}">${escapeHtml(resource.name)}</a></td><td>${escapeHtml(resource.zone.name)}</td><td>${escapeHtml(resource.hold_reason || "Unavailable")}</td><td class="mono">${resource.expected_back ? fullDate(`${resource.expected_back}T00:00`) : "Not specified"}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">No resources are on hold in your scope.</p>`}</section>`;
}

function resourceRows(data, user) {
  if (!data.results.length) return `<section class="empty-state"><h2>No available resources</h2><p>Try another time, a smaller group, or fewer equipment requirements.</p></section>`;
  return `<div class="table-scroll"><table>
    <thead><tr><th>Resource</th><th>Zone</th><th>Capacity</th><th>Equipment</th><th>Zone load</th><th>Reason</th><th></th></tr></thead>
    <tbody>${data.results.map((item) => `<tr>
      <td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(readable(item.resource.type))}</span></td>
      <td>${escapeHtml(item.resource.zone.name)}</td><td class="mono">${item.resource.capacity}</td>
      <td>${item.resource.equipment.map(readable).map(escapeHtml).join(", ")}</td>
      <td class="load-cell ${item.zone_load > 0.6 ? "overloaded" : item.zone_load <= 0.3 ? "quiet" : ""}"><span class="mono">${item.load_percent}%</span><span class="load-track"><span style="width:${item.bar_width}%"></span></span></td>
      <td>${escapeHtml(item.reason)}${item.resource.status === "on_hold" ? `<br><span class="muted">${escapeHtml(item.resource.hold_reason || "Unavailable")}.${escapeHtml(expectedBackText(item.resource))}</span>` : ""}</td><td>${!item.available ? `<span class="availability-label">${escapeHtml(item.availability_label || readable(item.resource.status))}</span>` : user.role !== "admin" ? `<p class="request-outcome">${escapeHtml(item.approval_message)}</p><a class="action" href="${escapeHtml(bookingUrl(item.resource.id, { start: localInput(data.filters.start), end: localInput(data.filters.end), attendees: data.filters.attendees }))}">Book</a>` : ""}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

async function resourcesPage() {
  const user = await requireUser();
  const params = new URLSearchParams(window.location.search);
  const renderQueryError = (message, query) => {
    document.querySelector("#resource-content").innerHTML = `
      <form class="command-form" id="command-form"><label class="sr-only" for="command">Describe the resource you need</label><input id="command" name="q" value="${escapeHtml(query)}" placeholder="Quiet lab with a projector for 4 people tomorrow at 2pm" autocomplete="off"><button type="submit">Search</button></form>
      <section class="empty-state"><h2>Query too vague</h2><p>${escapeHtml(message)}</p></section>`;
    document.querySelector("#command-form").addEventListener("submit", (event) => {
      event.preventDefault();
      window.location.search = new URLSearchParams(new FormData(event.currentTarget));
    });
  };
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
          <label>End<input name="end" type="datetime-local" step="1800" value="${localInput(data.filters.end)}" required></label><label class="check"><input name="show_on_hold" type="checkbox" value="true" ${data.filters.show_on_hold ? "checked" : ""}> Show on hold</label><button type="submit">Find resources</button>
        </form>
        <section class="rule-section results-head split"><h2>Resources</h2><p class="mono">${data.results.length} results</p></section>${resourceRows(data, user)}`;
      document.querySelector("#command-form").addEventListener("submit", (event) => {
        event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); window.location.search = next;
      });
      document.querySelector("#search-form").addEventListener("submit", (event) => {
        event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); window.location.search = next;
      });
    } catch (error) {
      if (error.status === 400 && query.get("q")) {
        renderQueryError(error.message, query.get("q"));
      } else {
        showError(error.message);
      }
    }
  };
  await load(params);
}

async function resourcePage() {
  const user = await requireUser();
  const id = new URLSearchParams(window.location.search).get("id");
  try {
    const data = await api.get(`/api/resources/${id}`);
    const resource = data.resource;
    document.title = `${resource.name} / Quorum`;
    document.querySelector("#resource-content").innerHTML = `
      <section class="page-head split"><div><p class="kicker">${escapeHtml(readable(resource.type))} / ${escapeHtml(resource.zone.name)}</p><h1>${escapeHtml(resource.name)}</h1><p>${resource.capacity} seats. ${resource.equipment.map(readable).map(escapeHtml).join(", ")}. Open <span class="mono">${clock(`0000-00-00T${resource.open_time}`)}-${clock(`0000-00-00T${resource.close_time}`)}</span>.</p>${resource.status === "on_hold" ? `<p class="hold-notice">On hold: ${escapeHtml(resource.hold_reason || "Unavailable")}.${escapeHtml(expectedBackText(resource))}</p>` : ""}</div>${resource.status !== "active" ? `<div class="status-block">${statusLabel(resource.status)}</div>` : ""}</section>
      ${user.role !== "admin" && resource.status === "active" ? `<section class="rule-section"><h2>Request</h2><p class="request-outcome">${escapeHtml(data.approval_message)}</p><a class="action" href="${escapeHtml(bookingUrl(resource.id))}">Book this resource</a></section>` : ""}
      <section class="rule-section"><h2>Unavailable</h2>${data.unavailability.length ? `<ul class="plain-list">${data.unavailability.map((item) => `<li><span class="mono">${shortDate(item.start)} ${clock(item.start)}-${clock(item.end)}</span> ${escapeHtml(item.reason)}</li>`).join("")}</ul>` : "<p>No maintenance windows listed.</p>"}</section>
      <section class="rule-section"><h2>Recent Requests</h2><div class="table-scroll"><table><thead><tr><th>When</th><th>User</th><th>Attendees</th><th>Status</th></tr></thead><tbody>${data.recent_requests.map((item) => `<tr><td class="mono">${shortDate(item.start)} ${clock(item.start)}-${clock(item.end)}</td><td>${escapeHtml(item.user.name)}</td><td class="mono">${item.attendees}</td><td>${statusLabel(item.status)}</td></tr>`).join("")}</tbody></table></div></section>`;
  } catch (error) { showError(error.message); }
}

function renderBookingAlternatives(detail, payload) {
  const host = document.querySelector("#booking-alternatives");
  host.innerHTML = `<section class="conflict-options"><p class="kicker">${escapeHtml(detail.title)}</p><h2>${escapeHtml(detail.reason)}</h2>${detail.alternatives.length ? `<div class="table-scroll"><table><thead><tr><th>Option</th><th>Resource</th><th>When</th><th></th></tr></thead><tbody>${detail.alternatives.map((option) => `<tr><td>${escapeHtml(option.kind)}</td><td>${escapeHtml(option.resource.name)}</td><td class="mono">${shortDate(option.start)} ${clock(option.start)}-${clock(option.end)}</td><td><button type="button" data-booking-alternative data-resource="${option.resource.id}" data-start="${escapeHtml(localInput(option.start))}" data-end="${escapeHtml(localInput(option.end))}">Use this slot</button></td></tr>`).join("")}</tbody></table></div>` : "<p>No nearby alternative is free.</p>"}</section>`;
  host.querySelectorAll("[data-booking-alternative]").forEach((button) => button.addEventListener("click", () => {
    sessionStorage.setItem("quorumBookingDraft", JSON.stringify({ purpose: payload.purpose }));
    window.location.href = bookingUrl(button.dataset.resource, {
      start: button.dataset.start,
      end: button.dataset.end,
      attendees: payload.attendees,
    });
  }));
}

async function bookPage() {
  const user = await requireUser();
  if (user.role === "admin") {
    document.querySelector("main").innerHTML = `<section class="page-head access-head"><p class="kicker">403 / Booking unavailable</p><h1>Administrators cannot create requests.</h1><p>Use the approval and resource tools from the admin home.</p></section><p class="page-actions"><a class="action" href="admin-home.html">Return to admin home</a></p>`;
    return;
  }
  const params = new URLSearchParams(window.location.search);
  const resourceId = params.get("resource");
  const [resourceData, profile] = await Promise.all([
    api.get(`/api/resources/${resourceId}`),
    api.get("/api/auth/profile"),
  ]);
  const resource = resourceData.resource;
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const maximumDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() + 30 * 86400000));
  const startValue = params.get("start") || "";
  const endValue = params.get("end") || "";
  const draft = JSON.parse(sessionStorage.getItem("quorumBookingDraft") || "null");
  sessionStorage.removeItem("quorumBookingDraft");
  document.title = `Book ${resource.name} / Quorum`;
  document.querySelector("#book-content").innerHTML = `
    <section class="page-head"><p class="kicker">Booking request</p><h1>${escapeHtml(resource.name)}</h1><p>This request will need admin approval.</p></section>
    <section class="request-summary"><dl>
      <div><dt>Zone</dt><dd>${escapeHtml(resource.zone.name)}</dd></div>
      <div><dt>Capacity</dt><dd class="mono">${resource.capacity}</dd></div>
      <div><dt>Equipment</dt><dd>${escapeHtml(resource.equipment.map(readable).join(", ") || "None listed")}</dd></div>
      <div><dt>Open hours</dt><dd class="mono">${resource.open_time.slice(0, 5)}-${resource.close_time.slice(0, 5)}</dd></div>
    </dl></section>
    <form class="booking-form" id="booking-form">
      <section class="rule-section"><h2>Date and time</h2><div class="booking-grid"><label>Date<input name="date" type="date" min="${today}" max="${maximumDate}" value="${escapeHtml(startValue.slice(0, 10))}" required></label><label>Start time<input name="start_time" type="time" step="1800" value="${escapeHtml(startValue.slice(11, 16))}" required></label><label>End time<input name="end_time" type="time" step="1800" value="${escapeHtml(endValue.slice(11, 16))}" required></label></div></section>
      <section class="rule-section"><h2>Requester</h2><dl class="profile-inline"><div><dt>Name</dt><dd>${escapeHtml(profile.name)}</dd></div><div><dt>Role</dt><dd>${escapeHtml(profile.role)}</dd></div><div><dt>Department</dt><dd>${escapeHtml(profile.department)}</dd></div><div><dt>${profile.role === "student" ? "Register number" : "Employee ID"}</dt><dd class="mono">${escapeHtml(profile.id_number)}</dd></div>${profile.role === "student" ? `<div><dt>Year</dt><dd class="mono">${profile.year_of_study}</dd></div>` : ""}</dl></section>
      <section class="rule-section"><h2>Request details</h2><div class="booking-grid"><label>Number of attendees<input name="attendees" type="number" min="1" max="${resource.capacity}" value="${escapeHtml(params.get("attendees") || "")}" required></label><label class="purpose-field">Purpose<textarea name="purpose" minlength="15" required placeholder="e.g. ML lab session for 3rd-year CSE, section B">${escapeHtml(draft?.purpose || "")}</textarea></label></div></section>
      <section class="rule-section booking-confirm"><label class="check"><input name="confirmed" type="checkbox" required> I confirm these details are correct and I will follow the rules for this resource.</label><button id="booking-submit" type="submit" disabled>Submit request</button></section>
    </form><div id="booking-alternatives"></div>`;
  const form = document.querySelector("#booking-form");
  const submit = document.querySelector("#booking-submit");
  const date = form.elements.date;
  const start = form.elements.start_time;
  const end = form.elements.end_time;
  const validate = () => {
    start.setCustomValidity(":00 or :30 start times are required.");
    end.setCustomValidity(":00 or :30 end times are required.");
    if (/^(?:[01]\d|2[0-3]):(?:00|30)$/.test(start.value)) start.setCustomValidity("");
    if (/^(?:[01]\d|2[0-3]):(?:00|30)$/.test(end.value)) end.setCustomValidity("");
    if (start.value && (start.value < resource.open_time.slice(0, 5) || start.value >= resource.close_time.slice(0, 5))) start.setCustomValidity(`Start time must be within ${resource.open_time.slice(0, 5)}-${resource.close_time.slice(0, 5)}.`);
    if (end.value && (end.value <= resource.open_time.slice(0, 5) || end.value > resource.close_time.slice(0, 5))) end.setCustomValidity(`End time must be within ${resource.open_time.slice(0, 5)}-${resource.close_time.slice(0, 5)}.`);
    if (start.value && end.value && end.value <= start.value) end.setCustomValidity("End time must be after start time.");
    submit.disabled = !bookingCanSubmit(form);
  };
  form.addEventListener("input", validate);
  form.addEventListener("change", validate);
  validate();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    validate();
    if (!form.reportValidity()) return;
    const values = new FormData(form);
    const payload = {
      resource_id: resource.id,
      start: `${date.value}T${start.value}`,
      end: `${date.value}T${end.value}`,
      attendees: Number(values.get("attendees")),
      purpose: String(values.get("purpose")).trim(),
      confirmed: true,
    };
    try {
      const request = await api.post("/api/requests", payload);
      window.location.href = `confirmation.html?id=${request.id}`;
    } catch (error) {
      if (error.status === 409 && typeof error.detail === "object") {
        renderBookingAlternatives(error.detail, payload);
      } else {
        showError(Array.isArray(error.detail) ? error.detail[0]?.msg : error.message);
      }
    }
  });
}

async function confirmationPage() {
  await requireUser();
  const id = new URLSearchParams(window.location.search).get("id");
  try {
    const item = await api.get(`/api/requests/${id}`);
    const copy = item.status === "approved" ? ["Your booking is confirmed.", "The slot is reserved. You can find it at any time under My requests."] : item.status === "pending" ? ["Your request is awaiting approval.", "The slot is held while an administrator reviews it. Its current status is pending."] : item.status === "rejected" ? ["Your request was rejected.", item.rejection_note || "The requested slot has been released."] : item.status === "cancelled" ? ["Your request was cancelled.", item.status_reason || "The requested slot has been released."] : item.status === "expired" ? ["Your request expired.", "The start time passed before an administrator decided it."] : [`Your request is ${item.status}.`, "View My requests for the latest decision details."];
    document.querySelector("#confirmation-content").innerHTML = `<section class="page-head confirmation-head"><p class="kicker">Request #${item.id} submitted</p><p class="confirmation-status status status-${item.status}">${escapeHtml(item.status)}</p><h1>${escapeHtml(copy[0])}</h1><p>${escapeHtml(copy[1])}</p></section><section class="request-summary"><dl><div><dt>Resource</dt><dd>${escapeHtml(item.resource.name)}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div><div><dt>Date</dt><dd class="mono">${fullDate(item.start)}</dd></div><div><dt>Time</dt><dd class="mono">${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Attendees</dt><dd class="mono">${item.attendees}</dd></div><div><dt>Purpose</dt><dd>${escapeHtml(item.purpose)}</dd></div></dl></section><section class="rule-section"><h2>History</h2>${eventTimeline(item.events)}</section><p class="page-actions"><a class="action" href="my-requests.html#request-${item.id}">View this request</a><a href="resources.html">Browse resources</a></p>`;
  } catch (error) { showError(error.message); }
}

async function conflictPage() {
  await requireUser();
  const data = JSON.parse(sessionStorage.getItem("quorumConflict") || "null");
  if (!data) { window.location.href = "resources.html"; return; }
  document.querySelector("#conflict-content").innerHTML = `<section class="page-head conflict-head"><p class="kicker">${escapeHtml(data.title)}</p><h1>Booking conflict</h1><p class="conflict-reason">${escapeHtml(data.reason)}</p></section><section class="conflict-options"><h2>Alternatives</h2>${data.alternatives.length ? `<div class="table-scroll"><table><thead><tr><th>Option</th><th>Resource</th><th>Time</th><th>Capacity</th><th></th></tr></thead><tbody>${data.alternatives.map((option) => `<tr><td>${escapeHtml(option.kind)}</td><td>${escapeHtml(option.resource.name)}</td><td class="mono">${shortDate(option.start)} ${clock(option.start)}-${clock(option.end)}</td><td class="mono">${option.resource.capacity}</td><td><a class="action" href="${escapeHtml(bookingUrl(option.resource.id, { start: localInput(option.start), end: localInput(option.end), attendees: data.payload.attendees }))}">Book</a></td></tr>`).join("")}</tbody></table></div>` : "<p>No nearby alternative is free.</p>"}</section>`;
}

async function myRequestsPage() {
  const user = await requireUser();
  const status = new URLSearchParams(window.location.search).get("status") || "all";
  const data = await api.get(`/api/my-requests?status=${encodeURIComponent(status)}`);
  const canCancel = (item) => item.status === "pending" || (item.status === "approved" && indiaDate(item.start) > new Date());
  document.querySelector("#requests-content").innerHTML = `<section class="page-head"><p class="kicker">${escapeHtml(user.name)}</p><h1>My requests</h1><p>Booking requests and their current decisions.</p></section><nav class="filter-tabs" aria-label="Request status">${["all", "pending", "approved", "rejected", "cancelled", "expired"].map((value) => `<a href="my-requests.html?status=${value}" ${status === value ? 'aria-current="page"' : ""}>${value}</a>`).join("")}</nav>${data.requests.length ? `<div class="table-scroll"><table><thead><tr><th>Request</th><th>Resource</th><th>When</th><th>Purpose</th><th>Status</th><th>Decision</th><th>History</th><th></th></tr></thead><tbody>${data.requests.map((item) => `<tr id="request-${item.id}"><td class="mono">#${item.id}</td><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(item.resource.zone.name)}</span></td><td class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</td><td>${escapeHtml(displayPurpose(item.purpose))}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td><td><details class="history-details"><summary>Timeline</summary>${eventTimeline(item.events)}</details></td><td>${canCancel(item) ? `<form data-cancel-request="${item.id}"><button class="secondary-action" type="submit">Cancel</button></form>` : ""}</td></tr>`).join("")}</tbody></table></div>` : `<section class="empty-state"><h2>No requests yet</h2><p>Choose a resource to make your first booking request.</p><a class="action" href="resources.html">Browse resources</a></section>`}`;
  document.querySelectorAll("[data-cancel-request]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.post(`/api/requests/${form.dataset.cancelRequest}/cancel`, {});
      await myRequestsPage();
      showNotice("Request cancelled");
    } catch (error) { showError(error.message); }
  }));
}

async function approvalsPage() {
  if (!await requireUser(true)) return;
  const data = await api.get("/api/admin/requests");
  document.querySelector("#approvals-content").innerHTML = `<section class="page-head split"><div><p class="kicker">Admin</p><h1>Approval queue</h1><p>Pending requests, newest first.</p></div><p class="queue-count"><span class="mono">${data.requests.length}</span> pending</p></section>${data.requests.length ? `<div class="approval-list">${data.requests.map((item) => `<article class="approval-row"><div><p class="kicker">Request #${item.id} / ${decisionTime(item.created_at)}${item.is_new ? ' / <span class="new-label">New</span>' : ""}</p><p>${statusLabel(item.status)}</p><h2>${escapeHtml(item.resource.name)}</h2><p>${escapeHtml(item.user.name)} / ${escapeHtml(item.user.role)}</p><p class="purpose-preview">${escapeHtml(purposePreview(item.purpose))}</p></div><dl class="compact-details"><div><dt>When</dt><dd class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Attendees</dt><dd class="mono">${item.attendees} / ${item.resource.capacity}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div></dl><div class="review-link"><a class="action" href="admin-request.html?id=${item.id}">Review request</a></div></article>`).join("")}</div>` : `<section class="empty-state"><h2>Queue clear</h2><p>There are no requests awaiting approval.</p></section>`}`;
}

async function allRequestsPage() {
  if (!await requireUser(true)) return;
  const query = new URLSearchParams(window.location.search);
  const status = query.get("status") || "all"; const role = query.get("role") || "all"; const resourceId = query.get("resource_id") || "";
  const [data, resources] = await Promise.all([api.get(`/api/admin/all-requests?status=${encodeURIComponent(status)}&role=${encodeURIComponent(role)}${resourceId ? `&resource_id=${resourceId}` : ""}`), api.get("/api/admin/request-resources")]);
  document.querySelector("#all-requests-content").innerHTML = `<section class="page-head split"><div><p class="kicker">Admin</p><h1>All requests</h1><p>Requests from students, faculty, and administrators, newest first.</p></div><p class="queue-count"><span class="mono">${data.requests.length}</span> shown</p></section><form class="request-filters" id="request-filters"><label>Status<select name="status">${["all", "pending", "approved", "rejected", "cancelled", "expired"].map((value) => `<option ${status === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>Role<select name="role">${["all", "student", "faculty", "admin"].map((value) => `<option ${role === value ? "selected" : ""}>${value}</option>`).join("")}</select></label><label>Resource<select name="resource_id"><option value="">all resources</option>${resources.map((resource) => `<option value="${resource.id}" ${String(resource.id) === resourceId ? "selected" : ""}>${escapeHtml(resource.name)}</option>`).join("")}</select></label><button type="submit">Apply filters</button></form>${data.requests.length ? `<div class="table-scroll"><table><thead><tr><th>Request</th><th>User</th><th>Resource</th><th>When</th><th>Status</th><th>Decision</th></tr></thead><tbody>${data.requests.map((item) => `<tr><td class="mono"><a href="admin-request.html?id=${item.id}">#${item.id}</a></td><td>${escapeHtml(item.user.name)}<br><span class="muted">${escapeHtml(item.user.role)}</span></td><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a><br><span class="muted">${escapeHtml(item.resource.zone.name)}</span></td><td class="mono">${shortDate(item.start)}<br>${clock(item.start)}-${clock(item.end)}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td></tr>`).join("")}</tbody></table></div>` : `<section class="empty-state"><h2>No matching requests</h2><p>Change a filter to broaden the results.</p></section>`}`;
  document.querySelector("#request-filters").addEventListener("submit", (event) => { event.preventDefault(); const next = new URLSearchParams(new FormData(event.currentTarget)); [...next.entries()].forEach(([key, value]) => { if (!value) next.delete(key); }); window.location.search = next; });
}

async function adminHistoryPage() {
  if (!await requireUser(true)) return;
  const query = new URLSearchParams(window.location.search);
  const data = await api.get(`/api/admin/history?${query.toString()}`);
  const selected = (key, value) => String(data.filters[key] ?? "") === String(value) ? "selected" : "";
  const exportUrl = `${api.baseUrl}/api/admin/history.csv${query.toString() ? `?${query.toString()}` : ""}`;
  document.querySelector("#admin-history-content").innerHTML = `
    <section class="page-head split"><div><p class="kicker">Admin</p><h1>History</h1><p>Request activity within your resource scope.</p></div><p class="queue-count"><span class="mono">${data.requests.length}</span> results</p></section>
    <form class="history-filters" id="history-filters"><label>Status<select name="status">${["all", "pending", "approved", "rejected", "cancelled", "expired"].map((value) => `<option ${selected("status", value)}>${value}</option>`).join("")}</select></label><label>From<input name="date_from" type="date" value="${escapeHtml(data.filters.date_from || "")}"></label><label>To<input name="date_to" type="date" value="${escapeHtml(data.filters.date_to || "")}"></label><label>Resource<select name="resource_id"><option value="">all resources</option>${data.resources.map((item) => `<option value="${item.id}" ${selected("resource_id", item.id)}>${escapeHtml(item.name)}</option>`).join("")}</select></label><label>Requester<select name="requester_id"><option value="">all requesters</option>${data.requesters.map((item) => `<option value="${item.id}" ${selected("requester_id", item.id)}>${escapeHtml(item.name)}</option>`).join("")}</select></label><label>Deciding admin<select name="deciding_admin_id"><option value="">all admins</option>${data.deciding_admins.map((item) => `<option value="${item.id}" ${selected("deciding_admin_id", item.id)}>${escapeHtml(item.name)}</option>`).join("")}</select></label><label class="history-search">Search<input name="q" value="${escapeHtml(data.filters.q)}" placeholder="Purpose, resource, requester or note"></label><button type="submit">Apply filters</button><a class="action" href="${escapeHtml(exportUrl)}">Export CSV</a></form>
    ${data.requests.length ? `<div class="table-scroll"><table><thead><tr><th>Request</th><th>Requester</th><th>Resource</th><th>Submitted</th><th>Status</th><th>Decision</th></tr></thead><tbody>${data.requests.map((item) => `<tr><td><a href="admin-request.html?id=${item.id}" class="mono">#${item.id}</a></td><td>${escapeHtml(item.user.name)}</td><td>${escapeHtml(item.resource.name)}</td><td class="mono">${decisionTime(item.created_at)}</td><td>${statusLabel(item.status)}</td><td>${requestDecision(item)}</td></tr>`).join("")}</tbody></table></div>` : `<section class="empty-state"><h2>No matching history</h2><p>Change a filter to broaden the results.</p></section>`}`;
  document.querySelector("#history-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    const next = new URLSearchParams(new FormData(event.currentTarget));
    [...next.entries()].forEach(([key, value]) => { if (!value || (key === "status" && value === "all")) next.delete(key); });
    window.location.search = next;
  });
}

async function adminRequestPage() {
  if (!await requireUser(true)) return;
  const id = new URLSearchParams(window.location.search).get("id");
  const data = await api.get(`/api/admin/requests/${id}`);
  const item = data.request;
  document.querySelector("#admin-request-content").innerHTML = `
    <section class="page-head split"><div><p class="kicker">Request #${item.id}</p><h1>Review request</h1><p>${statusLabel(item.status)}</p></div><p class="page-actions"><a href="admin-requests.html">Back to queue</a></p></section>
    <section class="review-columns">
      <div><h2>Requester</h2><dl class="detail-list"><div><dt>Name</dt><dd>${escapeHtml(item.user.name)}</dd></div><div><dt>Role</dt><dd>${escapeHtml(item.user.role)}</dd></div><div><dt>Department</dt><dd>${escapeHtml(item.user.department || "Not recorded")}</dd></div><div><dt>${item.user.role === "student" ? "Register number" : "Employee ID"}</dt><dd class="mono">${escapeHtml(item.user.id_number || "Not recorded")}</dd></div>${item.user.role === "student" ? `<div><dt>Year</dt><dd class="mono">${item.user.year_of_study || "Not recorded"}</dd></div>` : ""}</dl></div>
      <div><h2>Resource</h2><dl class="detail-list"><div><dt>Name</dt><dd>${escapeHtml(item.resource.name)}</dd></div><div><dt>Zone</dt><dd>${escapeHtml(item.resource.zone.name)}</dd></div><div><dt>Capacity</dt><dd class="mono">${item.resource.capacity}</dd></div><div><dt>Equipment</dt><dd>${escapeHtml(item.resource.equipment.map(readable).join(", ") || "None listed")}</dd></div><div><dt>Open hours</dt><dd class="mono">${item.resource.open_time.slice(0, 5)}-${item.resource.close_time.slice(0, 5)}</dd></div></dl></div>
    </section>
    <section class="rule-section"><h2>Booking</h2><div class="request-summary"><dl><div><dt>Date</dt><dd class="mono">${fullDate(item.start)}</dd></div><div><dt>Time</dt><dd class="mono">${clock(item.start)}-${clock(item.end)}</dd></div><div><dt>Attendees</dt><dd class="mono">${item.attendees}</dd></div><div><dt>Submitted</dt><dd class="mono">${decisionTime(item.created_at)}</dd></div><div><dt>Confirmed</dt><dd class="mono">${item.confirmed_at ? decisionTime(item.confirmed_at) : "Not recorded"}</dd></div><div><dt>Slot still free</dt><dd>${data.slot_is_free ? "Yes" : "No"}</dd></div><div><dt>Zone load</dt><dd class="mono">${data.load_percent}%</dd></div></dl></div><div class="purpose-block"><dt>Purpose</dt><dd>${escapeHtml(displayPurpose(item.purpose))}</dd></div></section>
    ${["pending", "approved"].includes(item.status) ? `<section class="rule-section"><h2>Extend booking</h2><form class="extension-form" data-extend="${item.id}"><label>New end time<input name="new_end" type="datetime-local" min="${escapeHtml(localInput(item.end))}" step="1800" required></label><button type="submit">Extend</button></form></section>` : ""}
    <section class="rule-section"><h2>Decision</h2>${item.status === "pending" ? `<div class="decision-panel"><form data-approve="${item.id}"><button type="submit">Approve</button></form><form data-reject="${item.id}"><label>Rejection note (optional)<textarea name="rejection_note" placeholder="Reason for rejection"></textarea></label><button class="secondary-action" type="submit">Reject</button></form></div>` : `<p>${requestDecision(item)}</p>`}</section>
    <section class="rule-section"><h2>History</h2>${eventTimeline(item.events)}</section>`;
  const approve = document.querySelector("[data-approve]");
  const reject = document.querySelector("[data-reject]");
  const extend = document.querySelector("[data-extend]");
  if (extend) extend.addEventListener("submit", async (event) => {
    event.preventDefault();
    const newEnd = new FormData(event.currentTarget).get("new_end");
    try {
      await api.post(`/api/admin/requests/${item.id}/extend`, { new_end: newEnd });
      await adminRequestPage();
      showNotice("Booking extended");
    } catch (error) {
      showError(error.message);
    }
  });
  if (approve) approve.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.post(`/api/admin/requests/${item.id}/approve`, {});
      await adminRequestPage();
      showNotice("Request approved");
    } catch (error) {
      await adminRequestPage();
      showNotice(error.message);
    }
  });
  if (reject) reject.addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = new FormData(event.currentTarget).get("rejection_note");
    try {
      await api.post(`/api/admin/requests/${item.id}/reject`, { rejection_note: note });
      await adminRequestPage();
      showNotice("Request rejected");
    } catch (error) {
      await adminRequestPage();
      showNotice(error.message);
    }
  });
}

const departments = ["CSE", "ECE", "EEE", "Mechanical", "Civil", "Biotech", "Other"];

async function adminUsersPage() {
  const currentUser = await requireCampusAdmin();
  if (!currentUser) return;
  const data = await api.get("/api/admin/users");
  const userEditor = (user) => {
    const summary = `<summary><span>${escapeHtml(user.name)}</span><span class="mono">${escapeHtml(user.role)} / ${escapeHtml(user.id_number)}</span></summary>`;
    if (user.id === currentUser.id) {
      return `<details class="resource-editor">${summary}<p class="muted">Current account. Admins cannot edit their own profile or role.</p></details>`;
    }
    return `<details class="resource-editor">${summary}<form class="profile-admin-form" data-edit-user="${user.id}"><label>Name<input name="name" value="${escapeHtml(user.name)}" required></label><label>Email<input name="email" type="email" value="${escapeHtml(user.email)}" required></label><label>Role<select name="role">${["student", "faculty", "admin"].map((role) => `<option value="${role}" ${user.role === role ? "selected" : ""}>${role}</option>`).join("")}</select></label><label>Department / office<select name="department">${departments.map((department) => `<option ${user.department === department ? "selected" : ""}>${department}</option>`).join("")}</select></label><label>ID number<input name="id_number" value="${escapeHtml(user.id_number)}" required></label><label data-year-field>Year of study<select name="year_of_study"><option value="">Not applicable</option>${[1, 2, 3, 4].map((year) => `<option value="${year}" ${user.year_of_study === year ? "selected" : ""}>${year}</option>`).join("")}</select></label><div data-admin-fields><label>Designation<input name="designation" value="${escapeHtml(user.designation || "")}"></label><label>Admin scope<select name="admin_scope"><option value="all" ${user.admin_scope === "all" ? "selected" : ""}>All resources</option><option value="labs" ${user.admin_scope === "labs" ? "selected" : ""}>Labs</option><option value="facilities" ${user.admin_scope === "facilities" ? "selected" : ""}>Classrooms, seminar halls and equipment</option></select></label></div><button type="submit">Save</button></form></details>`;
  };
  document.querySelector("#admin-users-content").innerHTML = `<section class="page-head"><p class="kicker">Campus Admin</p><h1>Users</h1><p>Correct locked account and academic profile details.</p></section><section>${data.users.map(userEditor).join("")}</section>`;
  document.querySelectorAll("[data-edit-user]").forEach((form) => {
    const role = form.elements.role;
    const year = form.elements.year_of_study;
    const yearField = form.querySelector("[data-year-field]");
    const adminFields = form.querySelector("[data-admin-fields]");
    const designation = form.elements.designation;
    const adminScope = form.elements.admin_scope;
    const syncRole = () => {
      const student = role.value === "student";
      const isAdmin = role.value === "admin";
      yearField.hidden = !student;
      year.disabled = !student;
      year.required = student;
      adminFields.hidden = !isAdmin;
      designation.disabled = !isAdmin;
      designation.required = isAdmin;
      adminScope.disabled = !isAdmin;
    };
    role.addEventListener("change", syncRole);
    syncRole();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      values.year_of_study = values.year_of_study ? Number(values.year_of_study) : null;
      try {
        await api.put(`/api/admin/users/${form.dataset.editUser}`, values);
        showNotice("Profile updated");
        await adminUsersPage();
      } catch (error) {
        showError(Array.isArray(error.detail) ? error.detail[0]?.msg : error.message);
      }
    });
  });
}

function resourcePayload(form, includeStatus = false) {
  const data = new FormData(form);
  const payload = { name: data.get("name"), type: data.get("type"), zone_id: Number(data.get("zone_id")), capacity: Number(data.get("capacity")), equipment: String(data.get("equipment") || "").split(",").map((item) => item.trim()).filter(Boolean), requires_approval: data.get("requires_approval") === "true", open_time: data.get("open_time"), close_time: data.get("close_time") };
  if (includeStatus) payload.status = data.get("status");
  return payload;
}

async function adminResourcesPage() {
  if (!await requireCampusAdmin()) return;
  const data = await api.get("/api/admin/resources");
  const zoneOptions = (selected) => data.zones.map((zone) => `<option value="${zone.id}" ${zone.id === selected ? "selected" : ""}>${escapeHtml(zone.name)}</option>`).join("");
  const statusControl = (resource) => resource.status === "on_hold"
    ? `<label>Status<select disabled><option>on hold</option></select><input name="status" type="hidden" value="active"></label>`
    : `<label>Status<select name="status"><option value="active" ${resource.status === "active" ? "selected" : ""}>active</option><option value="inactive" ${resource.status === "inactive" ? "selected" : ""}>inactive</option></select></label>`;
  const holdControl = (resource) => resource.status === "on_hold"
    ? `<section class="resource-control"><p><strong>On hold:</strong> ${escapeHtml(resource.hold_reason || "Unavailable")}.${escapeHtml(expectedBackText(resource))}</p><form data-lift-hold="${resource.id}"><button type="submit">Lift hold</button></form></section>`
    : `<form class="grid-form narrow resource-control" data-hold-resource="${resource.id}"><label>Hold reason<input name="reason" required></label><label>Expected back<input name="expected_back" type="date"></label><button type="submit">Put on hold</button></form>`;
  document.querySelector("#admin-resources-content").innerHTML = `<section class="page-head"><p class="kicker">Campus Admin</p><h1>Resources</h1><p>Register, edit, deactivate, hold, and block resources.</p></section><section class="rule-section"><h2>Register Resource</h2><form class="grid-form" id="create-resource"><label>Name<input name="name" required></label><label>Type<select name="type"><option>lab</option><option>classroom</option><option value="seminar_hall">seminar hall</option><option>equipment</option></select></label><label>Zone<select name="zone_id">${zoneOptions()}</select></label><label>Capacity<input name="capacity" type="number" min="1" value="30"></label><label>Equipment<input name="equipment" placeholder="projector, linux"></label><label>Open<input name="open_time" type="time" step="1800" value="08:00"></label><label>Close<input name="close_time" type="time" step="1800" value="20:00"></label><label class="check"><input name="requires_approval" type="checkbox" value="true"> Requires approval</label><button type="submit">Add</button></form></section><section class="rule-section"><h2>Edit Resources</h2>${data.resources.map((resource) => `<details class="resource-editor"><summary><span>${escapeHtml(resource.name)}</span><span class="mono">${escapeHtml(resource.zone.name)} / ${resource.capacity}${resource.status !== "active" ? ` / ${escapeHtml(readable(resource.status))}` : ""}</span></summary><form class="grid-form" data-edit-resource="${resource.id}"><label>Name<input name="name" value="${escapeHtml(resource.name)}" required></label><label>Type<select name="type">${["lab", "classroom", "seminar_hall", "equipment"].map((type) => `<option value="${type}" ${resource.type === type ? "selected" : ""}>${readable(type)}</option>`).join("")}</select></label><label>Zone<select name="zone_id">${zoneOptions(resource.zone_id)}</select></label><label>Capacity<input name="capacity" type="number" min="1" value="${resource.capacity}"></label><label>Equipment<input name="equipment" value="${escapeHtml(resource.equipment.join(", "))}"></label>${statusControl(resource)}<label>Open<input name="open_time" type="time" value="${resource.open_time.slice(0, 5)}"></label><label>Close<input name="close_time" type="time" value="${resource.close_time.slice(0, 5)}"></label><label class="check"><input name="requires_approval" type="checkbox" value="true" ${resource.requires_approval ? "checked" : ""}> Requires approval</label><button type="submit">Save</button></form>${holdControl(resource)}<form class="grid-form narrow resource-control" data-block-resource="${resource.id}"><label>Unavailable start<input name="start" type="datetime-local" step="1800" required></label><label>Unavailable end<input name="end" type="datetime-local" step="1800" required></label><label>Reason<input name="reason" value="maintenance" required></label><button type="submit">Block dates</button></form></details>`).join("")}</section>`;
  document.querySelector("#create-resource").addEventListener("submit", async (event) => { event.preventDefault(); await api.post("/api/admin/resources", resourcePayload(event.currentTarget)); await adminResourcesPage(); });
  document.querySelectorAll("[data-edit-resource]").forEach((form) => form.addEventListener("submit", async (event) => { event.preventDefault(); await api.put(`/api/admin/resources/${form.dataset.editResource}`, resourcePayload(form, true)); await adminResourcesPage(); }));
  const showImpact = (form, error, buttonText, confirm) => {
    form.querySelector("[data-impact-preview]")?.remove();
    const preview = document.createElement("div");
    preview.dataset.impactPreview = "true";
    preview.className = "impact-preview";
    preview.innerHTML = `<p><strong>${escapeHtml(error.detail.reason)}</strong></p><ul class="plain-list">${error.detail.affected_requests.map((item) => `<li>#${item.id} / ${escapeHtml(item.user.name)} / <span class="mono">${shortDate(item.start)} ${clock(item.start)}-${clock(item.end)}</span> / ${escapeHtml(displayPurpose(item.purpose))}</li>`).join("")}</ul><button type="button" data-confirm-impact>${escapeHtml(buttonText)}</button>`;
    form.append(preview);
    preview.querySelector("[data-confirm-impact]").addEventListener("click", confirm);
  };
  document.querySelectorAll("[data-hold-resource]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    if (!values.expected_back) values.expected_back = null;
    const submit = async () => api.post(`/api/admin/resources/${form.dataset.holdResource}/hold`, values);
    try { await submit(); await adminResourcesPage(); showNotice("Resource placed on hold"); }
    catch (error) {
      if (error.status !== 409 || !Array.isArray(error.detail?.affected_requests)) { showError(error.message); return; }
      showImpact(form, error, "Confirm hold and cancel bookings", async () => {
        values.confirmed_request_ids = error.detail.affected_requests.map((item) => item.id);
        try { await submit(); await adminResourcesPage(); showNotice("Resource placed on hold and affected bookings cancelled"); }
        catch (confirmError) { showError(confirmError.message); }
      });
    }
  }));
  document.querySelectorAll("[data-lift-hold]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try { await api.post(`/api/admin/resources/${form.dataset.liftHold}/lift-hold`, {}); await adminResourcesPage(); showNotice("Resource hold lifted"); }
    catch (error) { showError(error.message); }
  }));
  document.querySelectorAll("[data-block-resource]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    try {
      await api.post(`/api/admin/resources/${form.dataset.blockResource}/unavailability`, values);
      await adminResourcesPage();
      showNotice("Unavailability added");
    } catch (error) {
      if (error.status !== 409 || !Array.isArray(error.detail?.affected_requests)) {
        showError(error.message);
        return;
      }
      showImpact(form, error, "Confirm and cancel affected bookings", async () => {
        values.confirmed_request_ids = error.detail.affected_requests.map((item) => item.id);
        try {
          await api.post(`/api/admin/resources/${form.dataset.blockResource}/unavailability`, values);
          await adminResourcesPage();
          showNotice("Unavailability added and affected bookings cancelled");
        } catch (confirmError) { showError(confirmError.message); }
      });
    }
  }));
}

async function dashboardPage() {
  if (!await requireUser(true)) return;
  const data = await api.get("/api/admin/dashboard");
  document.querySelector("#dashboard-content").innerHTML = `<section class="page-head split"><div><p class="kicker">${shortDate(data.week_start)}-${shortDate(data.week_last_day)}</p><h1>Utilization</h1><p>Booking pressure across campus for the current week.</p></div><dl class="usage-extremes"><div><dt>Most used</dt><dd>${escapeHtml(data.most_used.resource.name)}<br><span class="mono">${data.most_used.booked_hours.toFixed(1)}h</span></dd></div><div><dt>Least used</dt><dd>${escapeHtml(data.least_used.resource.name)}<br><span class="mono">${data.least_used.booked_hours.toFixed(1)}h</span></dd></div></dl></section><section class="metric-band">${["pending", "approved", "rejected"].map((status) => `<div><span class="metric-number">${data.counts[status]}</span>${statusLabel(status)}</div>`).join("")}</section><section class="rule-section"><div class="split section-title"><h2>Peak hours</h2><p>Share of active resources booked</p></div><div class="peak-grid" style="--slot-count:${data.slot_labels.length}"><div></div>${data.slot_labels.map((label, index) => `<div class="peak-time">${index % 4 === 0 ? label : ""}</div>`).join("")}${data.peak_rows.map((row) => `<div class="peak-day">${row.day}</div>${row.cells.map((cell) => `<div class="peak-cell" style="--intensity:${cell.intensity}" title="${cell.label} / ${cell.booked_count} resources / ${cell.percent}%"></div>`).join("")}`).join("")}</div><p class="grid-legend"><span>Quiet</span><span class="legend-scale"></span><span>Busy</span></p></section><section class="rule-section"><h2>Zones</h2><div class="table-scroll"><table><thead><tr><th>Zone</th><th>Booked</th><th>Open</th><th>Utilization</th></tr></thead><tbody>${data.zone_rows.map((item) => `<tr><td>${escapeHtml(item.zone.name)}<br><span class="muted">${escapeHtml(item.zone.building)}</span></td><td class="mono">${item.booked_hours.toFixed(1)}h</td><td class="mono">${item.open_hours.toFixed(0)}h</td><td class="utilization-cell"><span class="mono">${item.percent}%</span><span class="load-track"><span style="width:${item.percent}%"></span></span></td></tr>`).join("")}</tbody></table></div></section><section class="rule-section"><h2>Resources</h2><div class="table-scroll"><table><thead><tr><th>Resource</th><th>Zone</th><th>Booked</th><th>Open</th><th>Utilization</th></tr></thead><tbody>${data.resource_rows.map((item) => `<tr><td><a href="resource.html?id=${item.resource.id}">${escapeHtml(item.resource.name)}</a></td><td>${escapeHtml(item.resource.zone.name)}</td><td class="mono">${item.booked_hours.toFixed(1)}h</td><td class="mono">${item.open_hours.toFixed(0)}h</td><td class="utilization-cell"><span class="mono">${item.percent}%</span><span class="load-track"><span style="width:${item.percent}%"></span></span></td></tr>`).join("")}</tbody></table></div></section>`;
}

const pages = { landing: landingPage, login: loginPage, signup: signupPage, profile: profilePage, "user-dashboard": userDashboardPage, "admin-home": adminHomePage, resources: resourcesPage, resource: resourcePage, book: bookPage, confirmation: confirmationPage, conflict: conflictPage, "my-requests": myRequestsPage, approvals: approvalsPage, "all-requests": allRequestsPage, "admin-history": adminHistoryPage, "admin-request": adminRequestPage, "admin-users": adminUsersPage, "admin-resources": adminResourcesPage, dashboard: dashboardPage };

document.addEventListener("DOMContentLoaded", async () => {
  try { await pages[document.body.dataset.page]?.(); }
  catch (error) {
    if (error.status === 403) renderForbidden(); else if (error.status !== 401) showError(error.message || "Something went wrong.");
  }
});
