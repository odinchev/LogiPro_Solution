"use strict";

const POLL_DELAY_MS = 1800;
const TOP_K = 5;
const ALLOWED_EXTENSIONS = new Set([
  "pdf",
  "jpg",
  "jpeg",
  "png",
  "tif",
  "tiff",
  "bmp",
  "webp",
]);

const elements = {
  uploadForm: document.querySelector("#upload-form"),
  fileInput: document.querySelector("#document-file"),
  selectedFile: document.querySelector("#selected-file"),
  selectedFileName: document.querySelector("#selected-file-name"),
  selectedFileSize: document.querySelector("#selected-file-size"),
  uploadButton: document.querySelector("#upload-button"),
  statusBadge: document.querySelector("#status-badge"),
  documentSummary: document.querySelector("#document-summary"),
  documentName: document.querySelector("#document-name"),
  documentId: document.querySelector("#document-id"),
  processingNote: document.querySelector("#processing-note"),
  uploadMessage: document.querySelector("#upload-message"),
  qaFieldset: document.querySelector("#qa-fieldset"),
  qaLock: document.querySelector("#qa-lock"),
  qaEmpty: document.querySelector("#qa-empty"),
  questionForm: document.querySelector("#question-form"),
  question: document.querySelector("#question"),
  askButton: document.querySelector("#ask-button"),
  queryMessage: document.querySelector("#query-message"),
  answerList: document.querySelector("#answer-list"),
};

const state = {
  documentId: null,
  pollTimer: null,
  pollGeneration: 0,
  queryGeneration: 0,
};

elements.fileInput.addEventListener("change", showSelectedFile);
elements.uploadForm.addEventListener("submit", uploadDocument);
elements.questionForm.addEventListener("submit", askQuestion);
window.addEventListener("beforeunload", cancelPolling);

function showSelectedFile() {
  const file = elements.fileInput.files[0];
  clearMessage(elements.uploadMessage);
  if (!file) {
    elements.selectedFile.hidden = true;
    return;
  }

  elements.selectedFileName.textContent = file.name;
  elements.selectedFileSize.textContent = formatBytes(file.size);
  elements.selectedFile.hidden = false;
}

async function uploadDocument(event) {
  event.preventDefault();
  const file = elements.fileInput.files[0];
  if (!file) {
    showError(elements.uploadMessage, "Choose a PDF or image before uploading.");
    return;
  }

  const extension = file.name.split(".").pop().toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    showError(elements.uploadMessage, "This file type is not supported.");
    return;
  }

  cancelPolling();
  resetDocumentWorkspace();
  setButtonBusy(elements.uploadButton, true, "Uploading…", "Upload and process");
  elements.fileInput.disabled = true;
  setStatus("PROCESSING");

  const body = new FormData();
  body.append("file", file);

  try {
    const response = await fetch("/api/documents/upload", {
      method: "POST",
      body,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      throw new Error(apiError(payload, `Upload failed (${response.status}).`));
    }

    state.documentId = payload.document_id;
    elements.documentName.textContent = payload.filename;
    elements.documentId.textContent = shortenId(payload.document_id);
    elements.documentId.title = payload.document_id;
    elements.documentSummary.hidden = false;
    elements.processingNote.hidden = false;
    elements.uploadMessage.textContent = "Upload accepted. Processing has started.";
    beginPolling(payload.document_id);
  } catch (error) {
    setStatus("FAILED");
    elements.processingNote.hidden = true;
    showError(elements.uploadMessage, errorMessage(error));
  } finally {
    elements.fileInput.disabled = false;
    setButtonBusy(elements.uploadButton, false, "Uploading…", "Upload and process");
  }
}

function beginPolling(documentId) {
  const generation = ++state.pollGeneration;
  pollDocumentStatus(documentId, generation);
}

async function pollDocumentStatus(documentId, generation) {
  if (generation !== state.pollGeneration || documentId !== state.documentId) {
    return;
  }

  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/status`,
      { cache: "no-store" },
    );
    const payload = await readJson(response);
    if (!response.ok) {
      throw new Error(apiError(payload, `Status check failed (${response.status}).`));
    }

    setStatus(payload.status);
    if (payload.status === "READY") {
      elements.processingNote.hidden = true;
      elements.uploadMessage.textContent = "Document is ready for questions.";
      unlockQa();
      return;
    }

    if (payload.status === "FAILED") {
      elements.processingNote.hidden = true;
      lockQa();
      showError(
        elements.uploadMessage,
        payload.error_message || "Document processing failed.",
      );
      return;
    }

    elements.processingNote.hidden = false;
    schedulePoll(documentId, generation);
  } catch (error) {
    if (generation !== state.pollGeneration) {
      return;
    }
    elements.uploadMessage.textContent = `${errorMessage(error)} Retrying…`;
    schedulePoll(documentId, generation);
  }
}

function schedulePoll(documentId, generation) {
  clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(
    () => pollDocumentStatus(documentId, generation),
    POLL_DELAY_MS,
  );
}

function cancelPolling() {
  state.pollGeneration += 1;
  clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

async function askQuestion(event) {
  event.preventDefault();
  const question = elements.question.value.trim();
  if (!state.documentId || !question) {
    showError(elements.queryMessage, "Enter a question about the ready document.");
    return;
  }

  clearMessage(elements.queryMessage);
  const documentId = state.documentId;
  const queryGeneration = ++state.queryGeneration;
  setButtonBusy(elements.askButton, true, "Thinking…", "Ask question");
  elements.question.disabled = true;

  try {
    const response = await fetch(
      `/api/documents/${encodeURIComponent(documentId)}/query`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, top_k: TOP_K }),
      },
    );
    const payload = await readJson(response);
    if (!response.ok) {
      throw new Error(apiError(payload, `Question failed (${response.status}).`));
    }
    if (
      queryGeneration !== state.queryGeneration ||
      documentId !== state.documentId
    ) {
      return;
    }

    renderAnswer(payload);
    elements.question.value = "";
  } catch (error) {
    if (queryGeneration === state.queryGeneration) {
      showError(elements.queryMessage, errorMessage(error));
    }
  } finally {
    if (queryGeneration === state.queryGeneration) {
      elements.question.disabled = false;
      setButtonBusy(elements.askButton, false, "Thinking…", "Ask question");
      elements.question.focus();
    }
  }
}

function renderAnswer(payload) {
  const card = createElement("article", "answer-card");
  const question = createElement("p", "answer-question", payload.question);
  const answer = createElement("p", "answer-text", payload.answer);
  const meta = createElement("div", "answer-meta");
  const provider = createElement(
    "span",
    "provider-badge",
    providerLabel(payload.llm_provider),
  );
  meta.append(provider);
  if (payload.used_fallback) {
    meta.append(createElement("span", "provider-badge fallback", "Fallback mode"));
  }

  card.append(question, answer, meta);
  const citations = Array.isArray(payload.citations) ? payload.citations : [];
  if (citations.length > 0) {
    card.append(createElement("h3", "citations-heading", "Sources"));
    const list = createElement("ol", "citation-list");
    citations.forEach((citation, index) => {
      list.append(renderCitation(citation, index));
    });
    card.append(list);
  }

  elements.answerList.prepend(card);
  card.scrollIntoView({
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth",
    block: "nearest",
  });
}

function renderCitation(citation, index) {
  const item = createElement("li", "citation");
  const meta = createElement("div", "citation-meta");
  const page = citation.page_number == null ? "Page unknown" : `Page ${citation.page_number}`;
  const score = formatScore(citation.relevance_score);
  meta.append(
    createElement("span", "", `Source ${index + 1} · ${page}`),
    createElement("span", "", score),
  );
  item.append(
    meta,
    createElement("p", "citation-snippet", citation.text || "No snippet available."),
    createElement("code", "citation-id", citation.chunk_id || "Unknown chunk"),
  );
  return item;
}

function resetDocumentWorkspace() {
  state.queryGeneration += 1;
  state.documentId = null;
  elements.documentSummary.hidden = true;
  elements.processingNote.hidden = true;
  elements.answerList.replaceChildren();
  elements.question.value = "";
  elements.question.disabled = false;
  setButtonBusy(elements.askButton, false, "Thinking…", "Ask question");
  clearMessage(elements.uploadMessage);
  clearMessage(elements.queryMessage);
  lockQa();
}

function unlockQa() {
  elements.qaFieldset.disabled = false;
  elements.qaLock.textContent = "Ready";
  elements.qaLock.classList.add("unlocked");
  elements.qaEmpty.hidden = true;
  elements.question.focus();
}

function lockQa() {
  elements.qaFieldset.disabled = true;
  elements.qaLock.textContent = "Locked";
  elements.qaLock.classList.remove("unlocked");
  elements.qaEmpty.hidden = false;
}

function setStatus(status) {
  const normalized = ["PROCESSING", "READY", "FAILED"].includes(status)
    ? status
    : "IDLE";
  const label = normalized === "IDLE" ? "No document" : normalized;
  elements.statusBadge.textContent = label;
  elements.statusBadge.className = `status-badge status-${normalized.toLowerCase()}`;
}

function setButtonBusy(button, busy, busyText, idleText) {
  button.disabled = busy;
  button.textContent = busy ? busyText : idleText;
  button.setAttribute("aria-busy", String(busy));
}

async function readJson(response) {
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return {};
  }
  return response.json();
}

function apiError(payload, fallback) {
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item) => item.msg || "Invalid request")
      .join(" ");
  }
  return fallback;
}

function showError(element, message) {
  element.textContent = message;
  element.classList.add("error");
}

function clearMessage(element) {
  element.textContent = "";
  element.classList.remove("error");
}

function createElement(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) {
    element.className = className;
  }
  element.textContent = text;
  return element;
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function shortenId(documentId) {
  return `${documentId.slice(0, 8)}…${documentId.slice(-4)}`;
}

function formatScore(score) {
  const numericScore = Number(score);
  if (!Number.isFinite(numericScore)) {
    return "Score unavailable";
  }
  const bounded = Math.min(Math.max(numericScore, 0), 1);
  return `${Math.round(bounded * 100)}% match`;
}

function providerLabel(provider) {
  if (provider === "mock") {
    return "Mock fallback";
  }
  if (typeof provider === "string" && provider.startsWith("ollama:")) {
    return `Ollama · ${provider.slice("ollama:".length)}`;
  }
  return provider || "Answer provider";
}

function errorMessage(error) {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}