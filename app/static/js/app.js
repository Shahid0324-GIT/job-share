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
const jobPreview = document.querySelector("#job-preview");
let previewUrl = "";
if (jobForm)
  jobForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = document.querySelector("#job-message");
    try {
      const result = await api("/api/admin/jobs/preview", {
        method: "POST",
        body: JSON.stringify({ url: document.querySelector("#job-url").value }),
      });
      previewUrl = result.url;
      document.querySelector("#preview-company").value = result.company || "";
      document.querySelector("#preview-role").value = result.role || "";
      document.querySelector("#preview-location").value = result.location || "";
      document.querySelector("#preview-source").value =
        result.source || "Company Careers";
      document.querySelector("#preview-description").value =
        result.description || "";
      document.querySelector("#preview-confidence").textContent =
        `Confidence: ${result.confidence}`;
      document.querySelector("#preview-warnings").textContent =
        result.warnings?.join(" ") || "Review the fields before saving.";
      jobPreview.hidden = false;
      message.textContent =
        "Details fetched. Review and save the job when ready.";
    } catch (error) {
      message.textContent = error.message;
      message.className = "message error";
    }
  });
if (jobPreview)
  jobPreview.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("/api/admin/jobs", {
        method: "POST",
        body: JSON.stringify({
          url: previewUrl,
          company: document.querySelector("#preview-company").value,
          role: document.querySelector("#preview-role").value,
          location: document.querySelector("#preview-location").value,
          source: document.querySelector("#preview-source").value,
          description: document.querySelector("#preview-description").value,
        }),
      });
      window.location.reload();
    } catch (error) {
      document.querySelector("#preview-warnings").textContent = error.message;
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
function updateDateSelectAll(group) {
  if (!group) return;
  const selectAll = group.querySelector(".date-select-all");
  if (!selectAll) return;
  const checkboxes = [...group.querySelectorAll(".job-select")];
  const checkedCount = checkboxes.filter((cb) => cb.checked).length;
  selectAll.checked = checkedCount > 0 && checkedCount === checkboxes.length;
  selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
}
document.querySelectorAll(".date-group").forEach((group) => {
  const selectAll = group.querySelector(".date-select-all");
  if (selectAll) {
    selectAll.addEventListener("change", () => {
      const isChecked = selectAll.checked;
      group.querySelectorAll(".job-select").forEach((cb) => {
        cb.checked = isChecked;
        const card = cb.closest(".job-card");
        if (card) card.classList.toggle("selected", isChecked);
      });
    });
  }
});
document.querySelectorAll(".job-card").forEach((card) => {
  const checkbox = card.querySelector(".job-select");
  if (!checkbox) return;
  if (checkbox.checked) card.classList.add("selected");
  card.addEventListener("click", (event) => {
    if (
      event.target.closest(".actions") ||
      event.target.closest("button") ||
      event.target.closest("a")
    ) {
      return;
    }
    if (event.target === checkbox) {
      card.classList.toggle("selected", checkbox.checked);
      updateDateSelectAll(card.closest(".date-group"));
      return;
    }
    checkbox.checked = !checkbox.checked;
    card.classList.toggle("selected", checkbox.checked);
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    updateDateSelectAll(card.closest(".date-group"));
  });
  checkbox.addEventListener("change", () => {
    card.classList.toggle("selected", checkbox.checked);
    updateDateSelectAll(card.closest(".date-group"));
  });
});
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
    if (
      !confirm(
        "Regenerate this friend's private link? The old link will stop working.",
      )
    )
      return;
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
    const result = await api(`/api/admin/friends/${button.dataset.id}/link`, {
      method: "POST",
    });
    await navigator.clipboard.writeText(result.url);
    alert("Private link copied. The existing link is unchanged.");
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
let currentFilter = "all";
function applyCurrentFilter() {
  const batchGroups = document.querySelectorAll(".batch-group");
  if (!batchGroups.length) return;
  batchGroups.forEach((group, index) => {
    const cards = group.querySelectorAll(".job-card");
    let visibleCount = 0;
    cards.forEach((card) => {
      let show = true;
      if (currentFilter === "latest") {
        show = index === 0;
      } else if (currentFilter === "unapplied") {
        show = card.dataset.applied !== "true";
      }
      card.style.display = show ? "" : "none";
      if (show) visibleCount++;
    });
    group.style.display = visibleCount > 0 ? "" : "none";
  });
}
document.querySelectorAll(".filter-pill").forEach((pill) =>
  pill.addEventListener("click", () => {
    document
      .querySelectorAll(".filter-pill")
      .forEach((item) => item.classList.toggle("active", item === pill));
    currentFilter = pill.dataset.filter || "all";
    applyCurrentFilter();
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
    const card = button.closest(".job-card");
    if (card)
      card.dataset.applied = result.status === "APPLIED" ? "true" : "false";
    applyCurrentFilter();
  }),
);
