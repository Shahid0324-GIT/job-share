const csrf = window.JOBSHARE?.csrf;
document.querySelectorAll(".tab").forEach((tab) =>
  tab.addEventListener("click", () => {
    document
      .querySelectorAll(".tab")
      .forEach((item) => item.classList.toggle("active", item === tab));
    document
      .querySelectorAll(".tab-panel")
      .forEach((panel) =>
        panel.classList.toggle(
          "active",
          panel.dataset.panel === tab.dataset.tab,
        ),
      );
  }),
);
async function api(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(url, { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Something went wrong.");
  return body;
}
const jobForm = document.querySelector("#job-form");
if (jobForm)
  jobForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#job-message");
    try {
      await api("/api/admin/jobs", {
        method: "POST",
        body: JSON.stringify({ url: document.querySelector("#job-url").value }),
      });
      message.textContent =
        "Job added. Review the details in the database before sharing.";
      window.location.reload();
    } catch (error) {
      message.textContent = error.message;
      message.className = "message error";
    }
  });
document.querySelectorAll(".delete-job").forEach((button) =>
  button.addEventListener("click", async () => {
    if (confirm("Delete this job?")) {
      await api(`/api/admin/jobs/${button.dataset.id}`, { method: "DELETE" });
      window.location.reload();
    }
  }),
);
document.querySelectorAll(".edit-job").forEach((button) =>
  button.addEventListener("click", async () => {
    const value = (label, current) => prompt(label, current) ?? current;
    await api(`/api/admin/jobs/${button.dataset.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        url: value("URL", button.dataset.url),
        company: value("Company", button.dataset.company),
        role: value("Role", button.dataset.role),
        location: value("Location", button.dataset.location),
        source: value("Source", button.dataset.source),
      }),
    });
    window.location.reload();
  }),
);
const batchButton = document.querySelector("#batch-button");
if (batchButton)
  batchButton.addEventListener("click", async () => {
    const jobIds = [...document.querySelectorAll(".job-select:checked")].map(
      (item) => item.value,
    );
    if (!jobIds.length) return alert("Select at least one job.");
    const name = prompt("Batch name (optional):");
    await api("/api/admin/batches", {
      method: "POST",
      body: JSON.stringify({ name, job_ids: jobIds }),
    });
    window.location.reload();
  });
document.querySelectorAll(".delete-batch").forEach((button) =>
  button.addEventListener("click", async () => {
    if (!confirm("Delete this batch? The jobs themselves will remain saved."))
      return;
    await api(`/api/admin/batches/${button.dataset.id}`, { method: "DELETE" });
    window.location.reload();
  }),
);
const friendButton = document.querySelector("#friend-button");
if (friendButton)
  friendButton.addEventListener("click", async () => {
    const name = prompt("Friend name:");
    if (!name) return;
    const result = await api("/api/admin/friends", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    await navigator.clipboard.writeText(
      `${window.JOBSHARE.baseUrl}/u/${result.token}`,
    );
    alert("Friend created. Private link copied.");
    window.location.reload();
  });
document.querySelectorAll(".regenerate").forEach((button) =>
  button.addEventListener("click", async () => {
    const result = await api(
      `/api/admin/friends/${button.dataset.id}/regenerate`,
      { method: "POST" },
    );
    await navigator.clipboard.writeText(
      `${window.JOBSHARE.baseUrl}/u/${result.token}`,
    );
    alert("New private link copied.");
  }),
);
document.querySelectorAll(".copy-link").forEach((button) =>
  button.addEventListener("click", async () => {
    const result = await api(
      `/api/admin/friends/${button.dataset.id}/regenerate`,
      { method: "POST" },
    );
    await navigator.clipboard.writeText(
      `${window.JOBSHARE.baseUrl}/u/${result.token}`,
    );
    alert("New private link copied.");
  }),
);
document.querySelectorAll(".edit-friend").forEach((button) =>
  button.addEventListener("click", async () => {
    const name = prompt("Friend name:", button.dataset.name);
    if (!name || name === button.dataset.name) return;
    await api(`/api/admin/friends/${button.dataset.id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
    window.location.reload();
  }),
);
document.querySelectorAll(".delete-friend").forEach((button) =>
  button.addEventListener("click", async () => {
    if (button.textContent.trim() === "Revoked") return;
    if (
      !confirm("Deactivate this friend? Their private link will stop working.")
    )
      return;
    await api(`/api/admin/friends/${button.dataset.id}`, { method: "DELETE" });
    window.location.reload();
  }),
);
document.querySelectorAll(".status-button").forEach((button) =>
  button.addEventListener("click", async () => {
    const next = button.classList.contains("applied")
      ? "NOT_APPLIED"
      : "APPLIED";
    const result = await api(
      `/api/public/jobs/${button.dataset.jobId}/status`,
      { method: "PATCH", body: JSON.stringify({ status: next }) },
    );
    button.classList.toggle("applied", result.status === "APPLIED");
    button.textContent =
      result.status === "APPLIED" ? "✓ Applied" : "○ Not applied";
  }),
);
