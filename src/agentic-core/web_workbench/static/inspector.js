const state = { selectedRunId: null, detail: null };
const json = (value) => JSON.stringify(value ?? null, null, 2);

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "content-type": "application/json" }, ...options });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.errors?.join("; ") || payload.status || `HTTP ${response.status}`);
  return payload;
}

function setStatus(text) { document.querySelector("#status").textContent = text || ""; }

function renderControls(controls = {}) {
  const stages = ["profile", "source_catalog", "source_discovery", "agent_ranking", "inbox"];
  document.querySelector("#controls").innerHTML = stages.map((stage) => {
    const enabled = controls[stage] !== false;
    return `<div class="control-row"><span>${stage}</span><button data-control="${stage}" data-enabled="${enabled}">${enabled ? "kill" : "enable"}</button></div>`;
  }).join("");
  document.querySelectorAll("[data-control]").forEach((button) => button.addEventListener("click", async () => {
    const enabled = button.dataset.enabled !== "true";
    try {
      await request(`/api/inspector/controls/${button.dataset.control}`, { method:"POST", body:json({ enabled }) });
      await loadRuns();
      setStatus(`${button.dataset.control} ${enabled ? "enabled" : "disabled"}`);
    } catch (error) { setStatus(error.message); }
  }));
}

async function loadRuns() {
  const payload = await request("/api/inspector/runs");
  renderControls(payload.runtime_controls);
  document.querySelector("#runs").innerHTML = payload.runs.map((run) => `
    <button class="run-button" data-run="${run.run_id}">
      <strong>${run.status} · ${run.run_id}</strong>
      <span>${run.started_at} · ${run.degraded_reasons?.join("; ") || "no degradation"}</span>
    </button>`).join("") || "尚无 L4 workflow run";
  document.querySelectorAll("[data-run]").forEach((button) => button.addEventListener("click", () => loadDetail(button.dataset.run)));
}

async function loadDetail(runId) {
  const detail = await request(`/api/inspector/runs/${encodeURIComponent(runId)}`);
  state.selectedRunId = runId;
  state.detail = detail;
  document.querySelector("#run-title").textContent = runId;
  document.querySelector("#run-meta").textContent = `${detail.run.status} · profile=${detail.run.profile_id || "neutral"} · sources=${detail.run.source_snapshot_id || "legacy"}`;
  document.querySelector("#replay").disabled = false;
  document.querySelector("#timeline").innerHTML = detail.timeline.map((step) => `
    <div class="step ${step.status}"><b>${step.sequence}. ${step.step_name}</b><span>${step.status}</span><span>${step.model_id || "code"} / ${step.policy_version || "-"}</span></div>`).join("");
  document.querySelector("#profile").textContent = json({ profile:detail.profile, events:detail.profile_events });
  document.querySelector("#sources").textContent = json({ snapshot:detail.source_snapshot, candidates:detail.source_candidate_decisions, observations:detail.source_observations });
  document.querySelector("#scores").textContent = json({ assessments:detail.assessments, ranked_signals:detail.ranked_signals });
  document.querySelector("#audit").textContent = json({ run:detail.run, controls:detail.runtime_controls, chain_of_thought:detail.chain_of_thought });
}

document.querySelector("#reload").addEventListener("click", () => loadRuns().catch((error) => setStatus(error.message)));
document.querySelector("#replay").addEventListener("click", async () => {
  try {
    const replay = await request(`/api/inspector/runs/${encodeURIComponent(state.selectedRunId)}/replay`, { method:"POST", body:"{}" });
    document.querySelector("#audit").textContent = json({ run:state.detail.run, replay, chain_of_thought:null });
    setStatus(`Replay complete: ${replay.external_calls} external calls`);
  } catch (error) { setStatus(error.message); }
});

loadRuns().catch((error) => setStatus(error.message));
