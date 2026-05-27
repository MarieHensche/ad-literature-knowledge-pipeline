const state = {
  config: null,
  activeJobId: null,
  activeManifestPath: null,
  lastGeneratedContractPath: null,
  jobTimer: null,
};

const $ = (id) => document.getElementById(id);

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.classList.remove("is-visible");
  }, 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function option(value, label = value) {
  const item = document.createElement("option");
  item.value = value || "";
  item.textContent = label || "";
  return item;
}

function fillSelect(select, items, placeholder) {
  select.replaceChildren(option("", placeholder));
  for (const item of items) {
    const path = typeof item === "string" ? item : item.path;
    select.appendChild(option(path, path));
  }
}

function fillStepSelect(select, steps) {
  fillSelect(select, steps, "Any");
}

function setStatus(element, status) {
  element.textContent = status || "Idle";
  element.className = `status-pill ${status || ""}`;
}

function activeContractPath() {
  return $("contractPath").value.trim();
}

function selectedContractForMain() {
  return $("mainContractPath").value.trim() || activeContractPath();
}

function generatedContractPath(collection) {
  return `data/collection_plans/${collection}_topic_contract.yaml`;
}

function syncSuggestedContractPath() {
  const collection = $("collectionName").value.trim();
  if (!collection || activeContractPath()) {
    return;
  }
  $("contractPath").value = generatedContractPath(collection);
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("workspacePath").textContent = state.config.workspace;
  $("collectionModel").value = state.config.defaults.model;
  $("mainModel").value = state.config.defaults.model;
  $("baseContract").value = state.config.defaults.baseContract;
  $("maxResults").value = state.config.defaults.maxResults;

  fillSelect($("contractSelect"), state.config.contracts, "Choose a contract");
  fillSelect($("paperInputSelect"), state.config.paperInputs, "Choose an input file");
  fillStepSelect($("collectionOnlyStep"), state.config.steps.collectionWithContract);
  fillStepSelect($("collectionFromStep"), state.config.steps.collectionWithContract);
  fillStepSelect($("mainOnlyStep"), state.config.steps.main);
  fillStepSelect($("mainFromStep"), state.config.steps.main);
  renderManifestList(state.config.manifests);

  if (state.config.contracts[0] && !$("contractPath").value) {
    $("contractPath").value = state.config.contracts[0].path;
    $("mainContractPath").value = state.config.contracts[0].path;
  }
  if (state.config.paperInputs[0] && !$("paperPath").value) {
    $("paperPath").value = state.config.paperInputs[0].path;
  }
}

async function loadContract(path = activeContractPath()) {
  if (!path) {
    showToast("Choose a contract path first.");
    return;
  }
  setStatus($("contractState"), "loading");
  const file = await api(`/api/files?path=${encodeURIComponent(path)}`);
  $("contractPath").value = file.path;
  $("mainContractPath").value = file.path;
  $("contractEditor").value = file.content;
  setStatus($("contractState"), "loaded");
}

async function saveContract() {
  const path = activeContractPath();
  const content = $("contractEditor").value;
  if (!path || !content.trim()) {
    showToast("Contract path and content are required.");
    return null;
  }
  setStatus($("contractState"), "saving");
  const file = await api("/api/contracts/save", {
    method: "POST",
    body: JSON.stringify({ path, content }),
  });
  $("contractPath").value = file.path;
  $("mainContractPath").value = file.path;
  setStatus($("contractState"), "saved");
  showToast("Contract saved.");
  await refreshManifests();
  return file;
}

function collectionPayload(workflow = "collection") {
  const collection = $("collectionName").value.trim();
  const generateTopicContract = $("generateInRun").checked || workflow === "contract";
  const payload = {
    workflow,
    topic: $("collectionTopic").value.trim(),
    collection,
    maxResults: $("maxResults").value,
    model: $("collectionModel").value.trim(),
    runId: $("collectionRunId").value.trim(),
    topicContract: activeContractPath(),
    baseContract: $("baseContract").value.trim(),
    overwriteTopicContract: $("overwriteContract").checked,
    generateTopicContract,
    dryRun: $("collectionDryRun").checked,
    onlyStep: $("collectionOnlyStep").value,
    fromStep: $("collectionFromStep").value,
    traceDir: $("collectionTraceDir").value.trim(),
    runMainAfterCollection: $("runMainAfterCollection").checked,
  };
  if (workflow === "contract") {
    payload.topicContract = "";
    payload.onlyStep = "generate_topic_contract";
    payload.fromStep = "";
    state.lastGeneratedContractPath = generatedContractPath(collection);
    $("contractPath").value = state.lastGeneratedContractPath;
  }
  return payload;
}

function mainPayload() {
  return {
    workflow: "main",
    collection: $("mainCollectionName").value.trim(),
    papers: $("paperPath").value.trim(),
    topicContract: selectedContractForMain(),
    model: $("mainModel").value.trim(),
    runId: $("mainRunId").value.trim(),
    dryRun: $("mainDryRun").checked,
    resume: $("mainResume").checked,
    onlyStep: $("mainOnlyStep").value,
    fromStep: $("mainFromStep").value,
    traceDir: $("mainTraceDir").value.trim(),
  };
}

async function startJob(payload) {
  const job = await api("/api/runs/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.activeJobId = job.id;
  renderJob(job);
  watchJob(job.id);
  return job;
}

function renderJob(job) {
  setStatus($("jobState"), job.status);
  const summary = $("jobSummary");
  summary.replaceChildren();
  for (const command of job.commands) {
    const item = document.createElement("div");
    item.className = "job-command";
    item.innerHTML = `
      <strong>${escapeHtml(command.label)}: ${escapeHtml(command.runId)}</strong>
      <div class="run-meta">${escapeHtml(command.manifestPath)}</div>
      <code>${escapeHtml(command.command)}</code>
    `;
    summary.appendChild(item);
  }
  $("jobLog").textContent = job.log || "";
  $("jobLog").scrollTop = $("jobLog").scrollHeight;
}

function watchJob(jobId) {
  window.clearInterval(state.jobTimer);
  state.jobTimer = window.setInterval(async () => {
    try {
      const job = await api(`/api/jobs/${jobId}`);
      renderJob(job);
      if (!["queued", "running"].includes(job.status)) {
        window.clearInterval(state.jobTimer);
        await refreshManifests();
        if (job.status === "succeeded" && state.lastGeneratedContractPath) {
          await loadContract(state.lastGeneratedContractPath);
        }
      }
    } catch (error) {
      window.clearInterval(state.jobTimer);
      showToast(error.message);
    }
  }, 1500);
}

async function startContractGeneration() {
  showMainJobPanel();
  const job = await startJob(collectionPayload("contract"));
  showToast(`Started ${job.commands[0].runId}.`);
}

async function startCollection(saveFirst = false) {
  if (saveFirst) {
    await saveContract();
  }
  showMainJobPanel();
  const job = await startJob(collectionPayload("collection"));
  showToast(`Started ${job.commands[0].runId}.`);
}

async function startMain() {
  showMainJobPanel();
  const job = await startJob(mainPayload());
  showToast(`Started ${job.commands[0].runId}.`);
}

function showMainJobPanel() {
  switchTab("main");
}

async function refreshManifests() {
  const result = await api("/api/manifests");
  state.config.manifests = result.manifests;
  renderManifestList(result.manifests);
}

function renderManifestList(items) {
  const filter = $("manifestFilter").value.trim().toLowerCase();
  const list = $("manifestList");
  list.replaceChildren();
  for (const manifest of items) {
    const haystack = [
      manifest.runId,
      manifest.collection,
      manifest.pipelineName,
      manifest.status,
      manifest.path,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (filter && !haystack.includes(filter)) {
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = `run-item ${manifest.path === state.activeManifestPath ? "is-active" : ""}`;
    button.dataset.path = manifest.path;
    button.innerHTML = `
      <strong>${escapeHtml(manifest.runId)}</strong>
      <div class="run-meta">${escapeHtml(manifest.pipelineName || "")} / ${escapeHtml(manifest.collection || "")}</div>
      <div class="run-meta">${escapeHtml(manifest.status || "")} / ${escapeHtml(manifest.startedAt || "")}</div>
    `;
    list.appendChild(button);
  }
}

async function loadManifest(path) {
  const file = await api(`/api/files?path=${encodeURIComponent(path)}`);
  const manifest = JSON.parse(file.content);
  state.activeManifestPath = path;
  renderManifestList(state.config.manifests);
  renderManifest(manifest, file.content);
}

function renderManifest(manifest, rawContent) {
  $("manifestTitle").textContent = manifest.run_id || "Manifest";
  setStatus($("manifestState"), manifest.status || "unknown");
  $("rawManifest").textContent = rawContent;

  const summary = $("manifestSummary");
  summary.replaceChildren(
    metric("Pipeline", manifest.pipeline_name),
    metric("Collection", manifest.collection),
    metric("Model", manifest.model),
    metric("Steps", String((manifest.steps || []).length)),
    metric("Started", manifest.started_at),
    metric("Ended", manifest.ended_at),
    metric("Failed Step", manifest.failed_step || "None"),
    metric("Contract", manifest.topic_contract?.path || "None")
  );

  const steps = $("manifestSteps");
  steps.replaceChildren();
  for (const step of manifest.steps || []) {
    steps.appendChild(renderStep(step));
  }
}

function metric(label, value) {
  const item = document.createElement("div");
  item.className = "metric";
  item.innerHTML = `<span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "")}</strong>`;
  return item;
}

function renderStep(step) {
  const details = document.createElement("details");
  details.className = "step";
  if (step.status !== "succeeded") {
    details.open = true;
  }
  details.innerHTML = `
    <summary>
      <span class="step-title">${escapeHtml(step.step_name || "")}</span>
      <span class="badge ${escapeHtml(step.status || "")}">${escapeHtml(step.status || "")}</span>
    </summary>
    <div class="step-body">
      <div class="manifest-summary">
        ${metricHtml("Elapsed", formatSeconds(step.elapsed_seconds))}
        ${metricHtml("Rows", rowCountsText(step.row_counts))}
        ${metricHtml("Warnings", String((step.warnings || []).length))}
        ${metricHtml("Traces", String((step.trace_paths || []).length))}
      </div>
      ${step.error ? `<p class="error-text">${escapeHtml(step.error)}</p>` : ""}
      <div class="path-grid">
        ${pathTable("Inputs", step.inputs || {})}
        ${pathTable("Outputs", step.outputs || {})}
      </div>
      ${traceList(step.trace_paths || [])}
      ${warningsList(step.warnings || [])}
    </div>
  `;
  return details;
}

function metricHtml(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value || "")}</strong></div>`;
}

function pathTable(title, paths) {
  const rows = Object.entries(paths)
    .map(([name, payload]) => {
      const path = payload?.path || "";
      return `
        <tr>
          <td>${escapeHtml(name)}</td>
          <td><button class="path-button" data-path="${escapeAttr(path)}" type="button">${escapeHtml(path)}</button></td>
        </tr>
      `;
    })
    .join("");
  return `
    <div>
      <table class="mini-table">
        <thead><tr><th colspan="2">${escapeHtml(title)}</th></tr></thead>
        <tbody>${rows || "<tr><td colspan=\"2\">None</td></tr>"}</tbody>
      </table>
    </div>
  `;
}

function traceList(paths) {
  if (!paths.length) {
    return "";
  }
  const rows = paths
    .map((path) => `
      <tr>
        <td><button class="path-button" data-path="${escapeAttr(path)}" type="button">${escapeHtml(path)}</button></td>
      </tr>
    `)
    .join("");
  return `
    <table class="mini-table">
      <thead><tr><th>Trace Files</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function warningsList(warnings) {
  if (!warnings.length) {
    return "";
  }
  const rows = warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("");
  return `<ul>${rows}</ul>`;
}

async function previewFile(path) {
  if (!path) {
    return;
  }
  const file = await api(`/api/files?path=${encodeURIComponent(path)}`);
  $("filePreviewTitle").textContent = file.path;
  $("filePreview").textContent = file.content;
}

function rowCountsText(rowCounts = {}) {
  const entries = Object.entries(rowCounts);
  if (!entries.length) {
    return "None";
  }
  return entries.map(([key, value]) => `${key}: ${value}`).join(", ");
}

function formatSeconds(value) {
  if (typeof value !== "number") {
    return "";
  }
  if (value < 1) {
    return `${Math.round(value * 1000)} ms`;
  }
  return `${value.toFixed(1)} s`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `${name}Panel`);
  });
}

function bindEvents() {
  document.querySelector(".tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab]");
    if (tab) {
      switchTab(tab.dataset.tab);
    }
  });

  $("refreshConfig").addEventListener("click", () => loadConfig().catch(showError));
  $("refreshManifests").addEventListener("click", () => refreshManifests().catch(showError));
  $("manifestFilter").addEventListener("input", () => renderManifestList(state.config.manifests));
  $("collectionName").addEventListener("input", syncSuggestedContractPath);
  $("contractSelect").addEventListener("change", (event) => {
    $("contractPath").value = event.target.value;
    $("mainContractPath").value = event.target.value;
  });
  $("paperInputSelect").addEventListener("change", (event) => {
    $("paperPath").value = event.target.value;
  });
  $("loadContract").addEventListener("click", () => loadContract().catch(showError));
  $("saveContract").addEventListener("click", () => saveContract().catch(showError));
  $("generateContract").addEventListener("click", () => startContractGeneration().catch(showError));
  $("startCollection").addEventListener("click", () => startCollection(false).catch(showError));
  $("saveAndStartCollection").addEventListener("click", () => startCollection(true).catch(showError));
  $("startMain").addEventListener("click", () => startMain().catch(showError));

  $("manifestList").addEventListener("click", (event) => {
    const item = event.target.closest("[data-path]");
    if (item) {
      loadManifest(item.dataset.path).catch(showError);
    }
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".path-button");
    if (button) {
      previewFile(button.dataset.path).catch(showError);
    }
  });
}

function showError(error) {
  showToast(error.message || String(error));
  setStatus($("jobState"), "failed");
}

bindEvents();
loadConfig()
  .then(() => {
    if (state.config.manifests[0]) {
      loadManifest(state.config.manifests[0].path).catch(showError);
    }
  })
  .catch(showError);
