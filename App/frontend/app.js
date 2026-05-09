// Single-file vanilla JS for the clinical scribe UI.

const state = {
  patient: null,
  recorder: null,
  recordedBlob: null,
  pipelineResult: null,
};

// ---------------------------------------------------------------------------
// Patient search
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

async function searchPatients() {
  const q = $("patient-search").value.trim();
  const url = "/api/patients" + (q ? `?q=${encodeURIComponent(q)}` : "");
  const r = await fetch(url);
  const data = await r.json();
  renderPatientResults(data.patients || []);
}

function renderPatientResults(patients) {
  const ul = $("patient-results");
  ul.innerHTML = "";
  if (!patients.length) {
    ul.innerHTML = '<li class="muted">No matches.</li>';
    return;
  }
  for (const p of patients) {
    const li = document.createElement("li");
    li.textContent = `${p.name} — ${p.gender || "?"} · ${p.birthDate || "?"} · ${p.id.slice(0, 8)}`;
    li.onclick = () => selectPatient(p);
    ul.appendChild(li);
  }
}

function selectPatient(p) {
  state.patient = p;
  $("selected-patient-label").textContent = `${p.name} (${p.id})`;
  $("selected-patient").classList.remove("hidden");
  $("patient-results").innerHTML = "";
  $("patient-search").value = "";
}

$("patient-search-btn").onclick = searchPatients;
$("patient-search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") searchPatients();
});
$("clear-patient").onclick = () => {
  state.patient = null;
  $("selected-patient").classList.add("hidden");
};

// Load all patients on page load.
searchPatients();

// ---------------------------------------------------------------------------
// Capture tabs
// ---------------------------------------------------------------------------

document.querySelectorAll(".tab").forEach((btn) => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`tab-${btn.dataset.tab}`).classList.add("active");
  };
});

// ---------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------

$("rec-start").onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mr = new MediaRecorder(stream);
    const chunks = [];
    mr.ondataavailable = (e) => chunks.push(e.data);
    mr.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      state.recordedBlob = new Blob(chunks, { type: mr.mimeType || "audio/webm" });
      const url = URL.createObjectURL(state.recordedBlob);
      const audio = $("rec-playback");
      audio.src = url;
      audio.classList.remove("hidden");
      $("rec-status").textContent = `recorded (${(state.recordedBlob.size / 1024).toFixed(0)} KB)`;
    };
    mr.start();
    state.recorder = mr;
    $("rec-start").disabled = true;
    $("rec-stop").disabled = false;
    $("rec-status").textContent = "● recording…";
  } catch (err) {
    $("rec-status").textContent = `mic error: ${err.message}`;
  }
};

$("rec-stop").onclick = () => {
  if (state.recorder && state.recorder.state !== "inactive") {
    state.recorder.stop();
  }
  $("rec-start").disabled = false;
  $("rec-stop").disabled = true;
};

// ---------------------------------------------------------------------------
// Pipeline runner
// ---------------------------------------------------------------------------

$("run-pipeline").onclick = async () => {
  const setStatus = (msg) => ($("pipeline-status").textContent = msg);
  const activeTab = document.querySelector(".tab.active").dataset.tab;
  const patientId = state.patient ? state.patient.id : null;

  $("run-pipeline").disabled = true;
  setStatus("running…");

  try {
    let result;
    if (activeTab === "record") {
      if (!state.recordedBlob) throw new Error("Record something first.");
      const fd = new FormData();
      fd.append("audio", state.recordedBlob, "recording.webm");
      if (patientId) fd.append("patient_id", patientId);
      result = await fetchJson("/api/encounters/analyze-audio", { method: "POST", body: fd });
    } else if (activeTab === "upload") {
      const file = $("audio-file").files[0];
      if (!file) throw new Error("Choose an audio file first.");
      const fd = new FormData();
      fd.append("audio", file, file.name);
      if (patientId) fd.append("patient_id", patientId);
      result = await fetchJson("/api/encounters/analyze-audio", { method: "POST", body: fd });
    } else {
      const transcript = $("transcript-input").value.trim();
      if (!transcript) throw new Error("Paste a transcript first.");
      result = await fetchJson("/api/encounters/analyze-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, patient_id: patientId }),
      });
    }

    state.pipelineResult = result;
    renderResult(result);
    setStatus("done.");
  } catch (err) {
    setStatus(`error: ${err.message}`);
  } finally {
    $("run-pipeline").disabled = false;
  }
};

async function fetchJson(url, init) {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = j.detail || JSON.stringify(j);
    } catch (_) {}
    throw new Error(`${r.status} ${detail}`);
  }
  return r.json();
}

function renderResult(result) {
  $("results-section").classList.remove("hidden");
  $("result-transcript").textContent = result.transcript || "(no transcript)";
  $("result-structured").value = JSON.stringify(result.structured || {}, null, 2);
  renderDiagnosis(result.diagnosis || {});
  $("result-tool-calls").textContent = JSON.stringify(
    result.diagnosis_tool_calls || [],
    null,
    2,
  );
}

function renderDiagnosis(dx) {
  const root = $("result-diagnosis");
  root.innerHTML = "";
  if (!dx || Object.keys(dx).length === 0) {
    root.innerHTML = '<p class="muted">No diagnosis output.</p>';
    return;
  }
  if (dx.summary) {
    const p = document.createElement("p");
    p.textContent = dx.summary;
    root.appendChild(p);
  }
  if (dx.differential?.length) {
    root.insertAdjacentHTML("beforeend", "<h4>Differential</h4>");
    const ol = document.createElement("ol");
    dx.differential.forEach((d) => {
      const li = document.createElement("li");
      li.textContent = d;
      ol.appendChild(li);
    });
    root.appendChild(ol);
  }
  if (dx.recommended_next_steps?.length) {
    root.insertAdjacentHTML("beforeend", "<h4>Recommended next steps</h4>");
    dx.recommended_next_steps.forEach((s) => {
      const div = document.createElement("div");
      div.className = `step ${s.priority || "routine"}`;
      div.innerHTML = `<strong>${escapeHtml(s.title)}</strong> <span class="muted small">[${s.priority || "routine"}]</span><br><span class="muted small">${escapeHtml(s.rationale || "")}</span>`;
      root.appendChild(div);
    });
  }
  if (dx.red_flags?.length) {
    root.insertAdjacentHTML("beforeend", "<h4>Red flags</h4>");
    dx.red_flags.forEach((f) => {
      const div = document.createElement("div");
      div.className = "flag";
      div.textContent = f;
      root.appendChild(div);
    });
  }
  if (dx.history_signals_used?.length) {
    root.insertAdjacentHTML("beforeend", "<h4>History signals used</h4>");
    const ul = document.createElement("ul");
    dx.history_signals_used.forEach((h) => {
      const li = document.createElement("li");
      li.textContent = h;
      ul.appendChild(li);
    });
    root.appendChild(ul);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

// ---------------------------------------------------------------------------
// Approval
// ---------------------------------------------------------------------------

$("approve-btn").onclick = async () => {
  const setStatus = (msg) => ($("approve-status").textContent = msg);
  if (!state.patient) {
    setStatus("Pick a patient first.");
    return;
  }
  let approvedPayload;
  try {
    approvedPayload = JSON.parse($("result-structured").value);
  } catch (err) {
    setStatus(`JSON parse error: ${err.message}`);
    return;
  }
  $("approve-btn").disabled = true;
  setStatus("saving…");
  try {
    const dx = state.pipelineResult?.diagnosis || {};
    const r = await fetchJson("/api/encounters/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        patient_id: state.patient.id,
        approved_payload: approvedPayload,
        diagnosis_summary: dx.summary || null,
      }),
    });
    setStatus(`saved ${r.resources_written?.length || 0} FHIR resources.`);
  } catch (err) {
    setStatus(`error: ${err.message}`);
  } finally {
    $("approve-btn").disabled = false;
  }
};
