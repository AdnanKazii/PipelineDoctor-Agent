const runSelect = document.getElementById("run-select");
const diagnoseBtn = document.getElementById("diagnose-btn");
const statusEl = document.getElementById("status");
const traceList = document.getElementById("trace-list");
const diagnosisContent = document.getElementById("diagnosis-content");

async function loadRuns() {
    const res = await fetch("/runs");
    const data = await res.json();
    runSelect.innerHTML = "";
    for (const run of data.runs) {
        const opt = document.createElement("option");
        opt.value = run.run_id;
        opt.textContent = `${run.run_date} (${run.scenario_label || "unlabeled"})`;
        runSelect.appendChild(opt);
    }
}

function renderToolCall(event) {
    const card = document.createElement("div");
    card.className = "tool-call" + (event.is_error ? " is-error" : "");
    card.innerHTML = `
        <span class="tool-name">${escapeHtml(event.tool)}</span>
        <span class="latency">${event.latency_ms} ms</span>
        <pre>input:  ${escapeHtml(JSON.stringify(event.input))}
output: ${escapeHtml(JSON.stringify(event.output))}</pre>
    `;
    traceList.appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "end" });
}

function renderDiagnosis(diagnosis, iterations, usage) {
    if (!diagnosis) {
        diagnosisContent.innerHTML = `<p class="placeholder">The agent didn't return a diagnosis.</p>`;
        return;
    }
    const badgeClass = diagnosis.bug_type_guess === "clean" ? "clean" : "other-bug";
    const rows = (diagnosis.supporting_numbers || []).map(n => `
        <tr>
            <td>${escapeHtml(n.label)}</td>
            <td>${n.value}</td>
            <td>${escapeHtml(n.source_tool)}</td>
            <td class="${n.verified ? "verified-yes" : "verified-no"}">${n.verified ? "✓ verified" : "unverified"}</td>
        </tr>
    `).join("");

    diagnosisContent.innerHTML = `
        <div class="field">
            <div class="field-label">Bug type</div>
            <span class="bug-badge ${badgeClass}">${escapeHtml(diagnosis.bug_type_guess)}</span>
            &nbsp; <span class="status">confidence ${(diagnosis.confidence * 100).toFixed(0)}%</span>
        </div>
        <div class="field">
            <div class="field-label">Root cause</div>
            ${escapeHtml(diagnosis.root_cause_diagnosis)}
        </div>
        <div class="field">
            <div class="field-label">Affected scope</div>
            ${escapeHtml(diagnosis.affected_scope)}
        </div>
        <div class="field">
            <div class="field-label">Supporting numbers</div>
            <table class="supporting-numbers">
                <thead><tr><th>Label</th><th>Value</th><th>Tool</th><th>Verified</th></tr></thead>
                <tbody>${rows || "<tr><td colspan=4>none</td></tr>"}</tbody>
            </table>
        </div>
        <div class="field">
            <div class="field-label">Evidence</div>
            <ul class="evidence-list">${(diagnosis.evidence || []).map(e => `<li>${escapeHtml(e)}</li>`).join("")}</ul>
        </div>
        <div class="field">
            <div class="field-label">Caveats</div>
            <ul class="caveats-list">${(diagnosis.caveats || []).map(c => `<li>${escapeHtml(c)}</li>`).join("") || "<li>none</li>"}</ul>
        </div>
        <div class="field">
            <div class="field-label">Cost</div>
            ${iterations} tool-runner iteration(s) &middot;
            ${usage.input_tokens} input / ${usage.output_tokens} output tokens
            (${usage.cache_read_input_tokens} cache-read)
        </div>
    `;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

diagnoseBtn.addEventListener("click", () => {
    const runId = runSelect.value;
    if (!runId) return;

    traceList.innerHTML = "";
    diagnosisContent.innerHTML = `<p class="placeholder">Investigating...</p>`;
    diagnoseBtn.disabled = true;
    statusEl.textContent = "running...";

    const source = new EventSource(`/diagnose/stream?run_id=${encodeURIComponent(runId)}`);

    source.onmessage = (msg) => {
        const event = JSON.parse(msg.data);
        if (event.type === "tool_call") {
            renderToolCall(event);
        } else if (event.type === "done") {
            renderDiagnosis(event.diagnosis, event.iterations, event.usage);
            statusEl.textContent = "done";
            diagnoseBtn.disabled = false;
            source.close();
        } else if (event.type === "error") {
            diagnosisContent.innerHTML = `<p class="placeholder">Error: ${escapeHtml(event.message)}</p>`;
            statusEl.textContent = "error";
            diagnoseBtn.disabled = false;
            source.close();
        }
    };

    source.onerror = () => {
        statusEl.textContent = "connection error";
        diagnoseBtn.disabled = false;
        source.close();
    };
});

loadRuns();
