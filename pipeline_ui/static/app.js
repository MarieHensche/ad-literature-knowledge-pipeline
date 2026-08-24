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

function refillStepSelect(select, steps) {
  const current = select.value;
  fillStepSelect(select, steps);
  if (steps.includes(current)) {
    select.value = current;
  }
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

function collectionUsesContractBootstrap(workflow = "collection") {
  return (
    workflow === "contract" ||
    $("generateInRun").checked ||
    !activeContractPath()
  );
}

function collectionStepsForCurrentMode() {
  if (!state.config) {
    return [];
  }
  if (collectionUsesContractBootstrap()) {
    return state.config.steps.collectionWithContract;
  }
  return state.config.steps.collection;
}

function updateCollectionStepControls() {
  const steps = collectionStepsForCurrentMode();
  refillStepSelect($("collectionOnlyStep"), steps);
  refillStepSelect($("collectionFromStep"), steps);
}

function mainStepsForCurrentMode() {
  if (!state.config) {
    return [];
  }
  if ($("mainGenerateReview").checked || $("mainReviewReviewLabelValues").checked) {
    return $("mainReviewTaggingCategories").checked || $("mainReviewReviewLabelValues").checked
      ? state.config.steps.mainWithTaggingAndLiteratureReview
      : state.config.steps.mainWithLiteratureReview;
  }
  return $("mainReviewTaggingCategories").checked
    ? state.config.steps.mainWithReview
    : state.config.steps.main;
}

function updateMainStepControls() {
  const steps = mainStepsForCurrentMode();
  refillStepSelect($("mainOnlyStep"), steps);
  refillStepSelect($("mainFromStep"), steps);
}

function selectedCollectionStepValue(element, usesBootstrap) {
  const steps = usesBootstrap
    ? state.config.steps.collectionWithContract
    : state.config.steps.collection;
  return steps.includes(element.value) ? element.value : "";
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("workspacePath").textContent = state.config.workspace;
  $("collectionModel").value = state.config.defaults.model;
  $("mainModel").value = state.config.defaults.model;
  $("baseContract").value = state.config.defaults.baseContract;
  $("maxResults").value = state.config.defaults.maxResults;
  $("maxReviewOverviews").value = state.config.defaults.maxReviewOverviews;

  fillSelect($("contractSelect"), state.config.contracts, "Choose a contract");
  fillSelect($("mainContractSelect"), state.config.contracts, "Choose a contract");
  fillSelect($("paperInputSelect"), state.config.paperInputs, "Choose an input file");
  updateCollectionStepControls();
  updateMainStepControls();
  renderManifestList(state.config.manifests);

  if (state.config.contracts[0] && !$("mainContractPath").value) {
    $("mainContractPath").value = state.config.contracts[0].path;
    $("mainContractSelect").value = state.config.contracts[0].path;
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
  $("mainContractSelect").value = file.path;
  $("contractEditor").value = file.content;
  $("generateInRun").checked = false;
  updateCollectionStepControls();
  await loadContractOverview(file.path).catch(() => {});
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
  $("mainContractSelect").value = file.path;
  $("generateInRun").checked = false;
  updateCollectionStepControls();
  await loadContractOverview(file.path).catch(() => {});
  setStatus($("contractState"), "saved");
  showToast("Contract saved.");
  await refreshManifests();
  return file;
}

function collectionPayload(workflow = "collection") {
  const collection = $("collectionName").value.trim();
  const usesBootstrap = collectionUsesContractBootstrap(workflow);
  const payload = {
    workflow,
    topic: $("collectionTopic").value.trim(),
    collection,
    maxResults: $("maxResults").value,
    maxReviewOverviews: $("maxReviewOverviews").value,
    model: $("collectionModel").value.trim(),
    runId: $("collectionRunId").value.trim(),
    topicContract: activeContractPath(),
    baseContract: $("baseContract").value.trim(),
    overwriteTopicContract: $("overwriteContract").checked,
    generateTopicContract: usesBootstrap,
    dryRun: $("collectionDryRun").checked,
    onlyStep: selectedCollectionStepValue($("collectionOnlyStep"), usesBootstrap),
    fromStep: selectedCollectionStepValue($("collectionFromStep"), usesBootstrap),
    traceDir: $("collectionTraceDir").value.trim(),
    runMainAfterCollection: $("runMainAfterCollection").checked,
    reviewTaggingCategories: $("collectionReviewTaggingCategories").checked,
    generateReview: $("collectionGenerateReview").checked,
    reviewReviewLabelValues: $("collectionReviewReviewLabelValues").checked,
  };
  if (workflow === "contract") {
    payload.topicContract = "";
    payload.contractBootstrapOnly = true;
    payload.onlyStep = "";
    payload.fromStep = "";
    state.lastGeneratedContractPath = generatedContractPath(collection);
    $("contractPath").value = "";
    $("contractEditor").value = "";
    $("generateInRun").checked = false;
    updateCollectionStepControls();
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
    reviewTaggingCategories: $("mainReviewTaggingCategories").checked,
    generateReview: $("mainGenerateReview").checked,
    reviewReviewLabelValues: $("mainReviewReviewLabelValues").checked,
    reviewMaxPapers: $("mainReviewMaxPapers").value.trim(),
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

async function revealReplayCollection(collection) {
  const papersPath = `data/raw/${collection}_papers.csv`;
  const contractPath = `data/collection_plans/${collection}_topic_contract.yaml`;
  $("mainCollectionName").value = collection;
  $("paperPath").value = papersPath;
  $("paperInputSelect").value = papersPath;
  $("mainContractPath").value = contractPath;
  $("mainContractSelect").value = contractPath;
  $("mainGenerateReview").checked = true;
  $("mainReviewTaggingCategories").checked = true;
  $("mainReviewReviewLabelValues").checked = true;
  updateMainStepControls();
  switchTab("main");
  await Promise.all([
    loadPaperOverview(papersPath),
    loadContractOverview(contractPath),
    loadReviewOutputs(collection),
  ]);
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
        await loadReviewOutputs().catch(() => {});
        const generatedContractPath = state.lastGeneratedContractPath;
        state.lastGeneratedContractPath = null;
        if (job.status === "succeeded" && generatedContractPath) {
          await loadContract(generatedContractPath);
        }
        if (
          job.status === "succeeded" &&
          job.replayCollection &&
          job.replayWorkflow !== "contract"
        ) {
          await revealReplayCollection(job.replayCollection);
          showToast(`${job.replayCollection} is ready.`);
        }
        if (job.status === "succeeded" && job.replayWorkflow === "contract") {
          switchTab("collect");
          showToast("Topic contract ready for review.");
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

async function loadPaperOverview(path = $("paperPath").value.trim()) {
  const container = $("paperOverview");
  container.replaceChildren();
  if (!path) {
    container.innerHTML = `<p class="empty-text">Choose a paper CSV to preview collected papers.</p>`;
    return;
  }
  const result = await api(`/api/papers?path=${encodeURIComponent(path)}`);
  $("paperOverviewTitle").textContent = `${result.total} Papers`;
  const list = document.createElement("div");
  list.className = "paper-list";
  for (const paper of result.papers) {
    const item = document.createElement("article");
    item.className = "paper-card";
    item.innerHTML = `
      <h4>${escapeHtml(paper.title || "Untitled paper")}</h4>
      <p>${escapeHtml([paper.year, firstAuthorText(paper.authors)].filter(Boolean).join(" · "))}</p>
    `;
    list.appendChild(item);
  }
  if (result.total > result.papers.length) {
    const note = document.createElement("p");
    note.className = "empty-text";
    note.textContent = `Showing ${result.papers.length} of ${result.total} papers.`;
    list.appendChild(note);
  }
  container.replaceChildren(list);
}

async function loadContractOverview(path = selectedContractForMain()) {
  const topicContainer = $("topicOverview");
  const categoryContainer = $("categoryOverview");
  topicContainer.replaceChildren();
  categoryContainer.replaceChildren();
  if (!path) {
    topicContainer.innerHTML = `<p class="empty-text">Choose a topic contract to preview topics.</p>`;
    categoryContainer.innerHTML = `<p class="empty-text">Choose a topic contract to preview categories.</p>`;
    return;
  }
  const overview = await api(`/api/contracts/overview?path=${encodeURIComponent(path)}`);
  renderTopicOverview(overview);
  renderCategoryOverview(overview);
}

async function loadReviewOutputs(
  collection = $("mainCollectionName").value.trim()
) {
  if (!collection) {
    showToast("Collection is required to find review outputs.");
    return;
  }
  const outputs = await api(`/api/review-outputs?collection=${encodeURIComponent(collection)}`);
  renderReviewOutputs(outputs);
}

function renderTopicOverview(overview) {
  $("topicOverviewTitle").textContent = overview.title || "Topic Overview";
  const container = $("topicOverview");
  const lead = document.createElement("p");
  lead.className = "overview-lead";
  lead.textContent = overview.description || "Main contract topics and matching terms.";
  const topics = [...(overview.mainTopics || []), ...(overview.secondaryTopics || [])];
  const list = document.createElement("div");
  list.className = "chip-groups";
  for (const topic of topics) {
    const item = document.createElement("article");
    item.className = "overview-card";
    item.innerHTML = `
      <div class="overview-card-head">
        <h4>${escapeHtml(topic.label || topic.id)}</h4>
        ${topic.parentLabel ? `<span>${escapeHtml(topic.parentLabel)}</span>` : ""}
      </div>
      <div class="chips">${(topic.terms || [])
        .map((term) => `<span class="chip">${escapeHtml(term)}</span>`)
        .join("")}</div>
    `;
    list.appendChild(item);
  }
  container.replaceChildren(lead, list);
}

function renderCategoryOverview(overview) {
  const container = $("categoryOverview");
  const list = document.createElement("div");
  list.className = "chip-groups";
  for (const category of overview.categories || []) {
    const item = document.createElement("article");
    item.className = "overview-card";
    item.innerHTML = `
      <div class="overview-card-head">
        <h4>${escapeHtml(category.label || category.id)}</h4>
        ${category.required ? "<span>Required</span>" : ""}
      </div>
      ${category.description ? `<p>${escapeHtml(category.description)}</p>` : ""}
      <div class="chips">${(category.values || [])
        .map((value) => `<span class="chip">${escapeHtml(value.label)}</span>`)
        .join("")}</div>
    `;
    list.appendChild(item);
  }
  if (!list.children.length) {
    list.innerHTML = `<p class="empty-text">No tagging categories found in this contract.</p>`;
  }
  container.replaceChildren(list);
}

function renderReviewOutputs(outputs) {
  const container = $("reviewOutput");
  const mantisPath = outputs.mantisCsv?.path || "";
  const mantisExists = Boolean(outputs.mantisCsv?.exists);
  const pdfPath = outputs.pdf?.path || "";
  const pdfExists = Boolean(outputs.pdf?.exists);
  const mdPath = outputs.markdown?.path || "";
  container.innerHTML = `
    <div class="mantis-launch-card">
      <div>
        <strong>Mantis-ready CSV</strong>
        <p>${escapeHtml(mantisPath)}</p>
      </div>
      <div class="mantis-actions">
        <button
          class="secondary-button mantis-download"
          data-path="${escapeAttr(mantisPath)}"
          type="button"
          ${mantisExists ? "" : "disabled"}
        >Download Mantis CSV</button>
        <button
          class="primary-button mantis-launch"
          type="button"
          disabled
        >Open Mantis</button>
      </div>
    </div>
    <div class="artifact-row">
      <button class="path-button" data-path="${escapeAttr(mdPath)}" type="button">${escapeHtml(mdPath)}</button>
      <span class="badge ${outputs.markdown?.exists ? "succeeded" : ""}">${outputs.markdown?.exists ? "found" : "missing"}</span>
    </div>
    <div class="artifact-row">
      <span>${escapeHtml(pdfPath)}</span>
      <span class="badge ${pdfExists ? "succeeded" : ""}">${pdfExists ? "found" : "missing"}</span>
    </div>
    ${
      pdfExists
        ? `<iframe class="pdf-frame" title="Literature review PDF" src="/api/workspace-file?path=${encodeURIComponent(pdfPath)}"></iframe>`
        : `<p class="empty-text">Generate the literature review to show the main PDF here.</p>`
    }
  `;
}

function downloadMantisCsv(csvPath, button) {
  if (!csvPath) {
    showToast("The Mantis-ready CSV is not available.");
    return;
  }
  const download = document.createElement("a");
  download.href = `/api/workspace-file?path=${encodeURIComponent(csvPath)}`;
  download.download = csvPath.split("/").pop() || "mantis_ready.csv";
  document.body.appendChild(download);
  download.click();
  download.remove();
  const launchButton = button.closest(".mantis-actions")?.querySelector(".mantis-launch");
  if (launchButton) {
    launchButton.disabled = false;
  }
  showToast("Mantis-ready CSV downloaded.");
}

function launchMantis() {
  window.open(
    "https://mantis.csail.mit.edu/new-space/csv_synthesis/",
    "_blank",
    "noopener,noreferrer"
  );
}

function firstAuthorText(authors) {
  if (!authors) {
    return "";
  }
  return String(authors).split(";")[0].trim();
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
  $("collectionName").addEventListener("input", updateCollectionStepControls);
  $("contractPath").addEventListener("input", updateCollectionStepControls);
  $("generateInRun").addEventListener("change", updateCollectionStepControls);
  $("mainReviewTaggingCategories").addEventListener("change", updateMainStepControls);
  $("mainGenerateReview").addEventListener("change", updateMainStepControls);
  $("mainReviewReviewLabelValues").addEventListener("change", updateMainStepControls);
  $("contractSelect").addEventListener("change", (event) => {
    $("contractPath").value = event.target.value;
    $("mainContractPath").value = event.target.value;
    $("mainContractSelect").value = event.target.value;
    updateCollectionStepControls();
    loadContractOverview(event.target.value).catch(showError);
  });
  $("mainContractSelect").addEventListener("change", (event) => {
    $("mainContractPath").value = event.target.value;
    loadContractOverview(event.target.value).catch(showError);
  });
  $("paperInputSelect").addEventListener("change", (event) => {
    $("paperPath").value = event.target.value;
    loadPaperOverview(event.target.value).catch(showError);
  });
  $("paperPath").addEventListener("change", () => loadPaperOverview().catch(showError));
  $("mainContractPath").addEventListener("change", () => loadContractOverview().catch(showError));
  $("loadContract").addEventListener("click", () => loadContract().catch(showError));
  $("saveContract").addEventListener("click", () => saveContract().catch(showError));
  $("generateContract").addEventListener("click", () => startContractGeneration().catch(showError));
  $("startCollection").addEventListener("click", () => startCollection(false).catch(showError));
  $("saveAndStartCollection").addEventListener("click", () => startCollection(true).catch(showError));
  $("startMain").addEventListener("click", () => startMain().catch(showError));
  $("refreshPaperOverview").addEventListener("click", () => loadPaperOverview().catch(showError));
  $("refreshContractOverview").addEventListener("click", () => loadContractOverview().catch(showError));
  $("refreshReviewOutputs").addEventListener("click", () => loadReviewOutputs().catch(showError));

  $("manifestList").addEventListener("click", (event) => {
    const item = event.target.closest("[data-path]");
    if (item) {
      loadManifest(item.dataset.path).catch(showError);
    }
  });

  document.addEventListener("click", (event) => {
    const downloadButton = event.target.closest(".mantis-download");
    if (downloadButton) {
      downloadMantisCsv(downloadButton.dataset.path, downloadButton);
      return;
    }
    const mantisButton = event.target.closest(".mantis-launch");
    if (mantisButton) {
      launchMantis();
      return;
    }
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
    loadPaperOverview().catch(showError);
    loadContractOverview().catch(showError);
    loadReviewOutputs().catch(() => {});
    if (state.config.manifests[0]) {
      loadManifest(state.config.manifests[0].path).catch(showError);
    }
  })
  .catch(showError);
