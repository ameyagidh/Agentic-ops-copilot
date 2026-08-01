const form = document.getElementById("incident-form");
const submitBtn = document.getElementById("submit-btn");
const progressCard = document.getElementById("progress-card");
const progressList = document.getElementById("progress-list");
const resultCard = document.getElementById("result-card");
const resultBody = document.getElementById("result-body");
const historyBody = document.querySelector("#history-table tbody");
const refreshBtn = document.getElementById("refresh-btn");

const NODE_LABELS = {
  route: "Routing & triage",
  fetch_logs: "Fetching logs",
  fetch_metrics: "Fetching metrics",
  fetch_context: "Looking up service context",
  retrieve_runbooks: "Retrieving runbooks",
  synthesize: "Synthesizing root-cause hypothesis",
  validate: "Validating evidence grounding",
};

function confidenceBadge(finding) {
  if (!finding) return "";
  if (finding.insufficient_evidence) return `<span class="badge insufficient">insufficient evidence</span>`;
  return `<span class="badge ${finding.confidence}">${finding.confidence} confidence</span>`;
}

function renderFinding(record) {
  const finding = record.finding;
  if (!finding) {
    resultBody.innerHTML = `<p class="explanation">Run ${record.status}${record.error ? ": " + record.error : ""}</p>`;
    return;
  }
  const hyps = (finding.hypotheses || []).map((h) => `<li>${h}</li>`).join("");
  resultBody.innerHTML = `
    ${confidenceBadge(finding)}
    ${hyps ? `<ul class="evidence-list">${hyps}</ul>` : ""}
    ${finding.recommended_action ? `<p><strong>Recommended action:</strong> ${finding.recommended_action}</p>` : ""}
    ${finding.evidence_refs && finding.evidence_refs.length ? `<p><strong>Evidence used:</strong> ${finding.evidence_refs.join(", ")}</p>` : ""}
    <p class="explanation">${finding.explanation || ""}</p>
  `;
}

async function loadHistory() {
  try {
    const res = await fetch("/api/v1/incidents?limit=25");
    if (!res.ok) return;
    const runs = await res.json();
    historyBody.innerHTML = runs
      .map((r) => {
        const confidence = r.finding
          ? r.finding.insufficient_evidence
            ? "insufficient"
            : r.finding.confidence
          : "-";
        return `<tr>
          <td>${r.run_id.slice(0, 8)}</td>
          <td>${r.incident.service_name}</td>
          <td>${r.triage ? r.triage.severity : "-"}</td>
          <td><span class="badge ${r.status}">${r.status}</span></td>
          <td><span class="badge ${confidence}">${confidence}</span></td>
          <td>${new Date(r.created_at).toLocaleString()}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    console.error("failed to load history", err);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitBtn.disabled = true;
  progressCard.hidden = false;
  resultCard.hidden = true;
  progressList.innerHTML = "";
  resultBody.innerHTML = "";

  const payload = {
    service_name: document.getElementById("service").value,
    ticket_text: document.getElementById("ticket").value,
  };

  try {
    const response = await fetch("/api/v1/incidents/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalRecord = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();
      for (const raw of events) {
        const lines = raw.split("\n");
        let eventName = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        const parsed = JSON.parse(data);
        if (eventName === "node") {
          const li = document.createElement("li");
          li.className = "active";
          li.textContent = NODE_LABELS[parsed.node] || parsed.node;
          progressList.appendChild(li);
        } else if (eventName === "completed") {
          finalRecord = parsed;
        }
      }
    }

    resultCard.hidden = false;
    if (finalRecord) renderFinding(finalRecord);
    await loadHistory();
  } catch (err) {
    resultCard.hidden = false;
    resultBody.innerHTML = `<p class="explanation">Request failed: ${err}</p>`;
  } finally {
    submitBtn.disabled = false;
  }
});

refreshBtn.addEventListener("click", loadHistory);
loadHistory();
