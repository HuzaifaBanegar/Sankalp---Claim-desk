// Calls the FastAPI backend. Same origin, so no CORS setup is needed.
const form = document.getElementById("ask");
const status = document.getElementById("status");
const requestType = document.getElementById("request-type");
const questionInput = document.getElementById("q");
const submitButton = form.querySelector("button[type='submit']");
const submitLabel = submitButton.querySelector("span");
const output = document.getElementById("out");
const evidenceSection = document.getElementById("evidence-section");
const debugPanel = document.getElementById("debug-panel");
const debugTrace = document.getElementById("debug-trace");
const modeDescription = document.getElementById("mode-description");
const requiredNoteText = document.getElementById("required-note-text");
const claimNoInput = document.getElementById("claim-no");
const stockistInput = document.getElementById("stockist-code");
const batchInput = document.getElementById("batch-no");
const quantityInput = document.getElementById("quantity");
const quantityUnit = document.getElementById("quantity-unit");
const claimType = document.getElementById("claim-type");
const invoiceInput = document.getElementById("invoice-ref");
const invoiceException = document.getElementById("invoice-exception");
const invoiceField = invoiceInput.closest(".field");

const PANELS = {
  general: document.getElementById("panel-general"),
  claim_status: document.getElementById("panel-claim-status"),
  raise_claim: document.getElementById("panel-raise-claim"),
};

const MODE_COPY = {
  general: {
    description: "Ask a question in natural language. I'll look up the relevant records.",
    note: "Include a batch number when you need expiry or product details",
    submit: "Find answer",
  },
  claim_status: {
    description: "Enter the claim number to look up its current status and credit-note details.",
    note: "Claim number is required",
    submit: "Check status",
  },
  raise_claim: {
    description: "Fill in the required claim details. I'll assess the request against company records.",
    note: "Fields marked * are required",
    submit: "Submit claim",
  },
};

const LABELS = {
  claim_no: "Claim number", claim_date: "Claim date", status: "Status",
  stockist_code: "Stockist", cnf_code: "C&F", sku_code: "SKU",
  batch_no: "Batch", expiry_date_as_claimed: "Expiry date", qty_claimed: "Quantity claimed",
  claim_value_inr: "Claim value", claim_type: "Claim type", original_invoice_ref: "Invoice reference",
  credit_note_no: "Credit note", credit_note_date: "Credit note date", credit_value_inr: "Credit value",
  product_description: "Product", mfg_date: "Manufactured", expiry_date: "Expiry date",
  batch_qty_packs: "Batch quantity", remarks: "Remarks",
};

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#039;", '"': "&quot;",
  }[character]));
}

function formatAnswer(answer) {
  return escapeHtml(answer)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function displayValue(key, value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  if (key.includes("value_inr")) return `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (key.includes("date") && typeof value === "string") return value.slice(0, 10).split("-").reverse().join("-");
  return String(value);
}

function parseEvidence(evidence) {
  return evidence.flatMap((item) => {
    try {
      const parsed = typeof item === "string" ? JSON.parse(item) : item;
      return parsed.records || [parsed];
    } catch {
      return [{ raw: item }];
    }
  });
}

function renderEvidence(evidence) {
  const target = document.getElementById("evidence");
  const records = parseEvidence(evidence);
  target.innerHTML = records.map((record) => {
    if (record.raw) return `<article class="evidence-card"><p>${escapeHtml(record.raw)}</p></article>`;
    const statusLabel = record.status ? `<span class="claim-status ${record.status.toLowerCase().replace(/\s+/g, "-")}">${escapeHtml(record.status)}</span>` : "";
    const fields = Object.entries(record)
      .filter(([key, value]) => LABELS[key] && value !== null && value !== "")
      .map(([key, value]) => `<div class="fact"><dt>${LABELS[key]}</dt><dd>${escapeHtml(displayValue(key, value))}</dd></div>`)
      .join("");
    const title = record.claim_no || record.batch_no || "Data record";
    return `<article class="evidence-card"><div class="record-top"><h3>${escapeHtml(title)}</h3>${statusLabel}</div><dl class="facts">${fields}</dl></article>`;
  }).join("");
  evidenceSection.hidden = records.length === 0;
}

function renderDebugTrace(trace) {
  if (!trace || trace.length === 0) {
    debugPanel.hidden = true;
    return;
  }
  debugTrace.innerHTML = trace.map((entry) => {
    const details = Object.entries(entry)
      .filter(([key]) => key !== "step" && key !== "event")
      .map(([key, value]) => `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : value}`)
      .join(" · ");
    return `<li><strong>${escapeHtml(entry.event.replaceAll("_", " "))}</strong><span>${escapeHtml(details)}</span></li>`;
  }).join("");
  debugPanel.hidden = false;
}

function syncInvoiceRequirement() {
  const invoiceRequired = !invoiceException.checked;
  invoiceInput.required = requestType.value === "raise_claim" && invoiceRequired;
  invoiceField.hidden = !invoiceRequired;
}

function setMode(mode) {
  requestType.value = mode;
  Object.entries(PANELS).forEach(([key, panel]) => {
    panel.hidden = key !== mode;
  });
  form.classList.toggle("mode-chat", mode === "general");
  form.classList.toggle("mode-form", mode !== "general");
  const copy = MODE_COPY[mode];
  modeDescription.textContent = copy.description;
  requiredNoteText.textContent = copy.note;
  submitLabel.textContent = copy.submit;
  questionInput.required = mode === "general";
  claimNoInput.required = mode === "claim_status";
  const claimForm = mode === "raise_claim";
  stockistInput.required = claimForm;
  batchInput.required = claimForm;
  quantityInput.required = claimForm;
  claimType.required = claimForm;
  syncInvoiceRequirement();
}

function buildQuestion() {
  const mode = requestType.value;
  if (mode === "claim_status") {
    return `What is the status of ${claimNoInput.value.trim()}?`;
  }
  if (mode === "raise_claim") {
    const parts = [
      `${claimType.value} claim: ${stockistInput.value.trim()}, ${batchInput.value.trim()}, ${quantityInput.value.trim()} ${quantityUnit.value}`,
    ];
    if (!invoiceException.checked) {
      parts.push(`invoice ${invoiceInput.value.trim()}`);
    } else {
      parts.push("purchase ledger verification and written Area Manager approval");
    }
    return parts.join(", ") + ".";
  }
  return questionInput.value.trim();
}

function applySuggestion(button) {
  const mode = button.dataset.mode || "general";
  setMode(mode);
  if (mode === "claim_status") {
    claimNoInput.value = button.dataset.claimNo || "";
    claimNoInput.focus();
    return;
  }
  if (mode === "raise_claim") {
    stockistInput.value = button.dataset.stockist || "";
    batchInput.value = button.dataset.batch || "";
    quantityInput.value = button.dataset.quantity || "";
    quantityUnit.value = button.dataset.unit || "strips";
    claimType.value = button.dataset.claimType || "";
    invoiceInput.value = button.dataset.invoice || "";
    invoiceException.checked = false;
    syncInvoiceRequirement();
    stockistInput.focus();
    return;
  }
  questionInput.value = button.dataset.question || button.textContent.trim();
  questionInput.focus();
}

requestType.addEventListener("change", () => setMode(requestType.value));
invoiceException.addEventListener("change", syncInvoiceRequirement);
setMode(requestType.value);

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => applySuggestion(button));
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = buildQuestion();
  if (!question) return;
  const idleLabel = MODE_COPY[requestType.value].submit;
  status.textContent = "Checking the company data…";
  submitButton.disabled = true;
  submitLabel.textContent = "Checking…";
  try {
    const res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
    document.getElementById("answer").innerHTML = formatAnswer(data.answer);
    renderEvidence(data.evidence || []);
    renderDebugTrace(data.debug_trace || []);
    output.hidden = false;
    status.textContent = data.model_calls ? `Completed using ${data.model_calls} model call${data.model_calls === 1 ? "" : "s"}.` : "More information is needed before a claim can be checked.";
  } catch (err) {
    status.textContent = `Something went wrong: ${err.message}. Check /api/health and the logs.`;
  } finally {
    submitButton.disabled = false;
    submitLabel.textContent = idleLabel;
  }
});
