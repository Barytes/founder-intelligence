const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#chat-form");
const inputEl = document.querySelector("#message-input");
const tokenStatusEl = document.querySelector("#token-status");
const modelInputEl = document.querySelector("#model-input");
const baseUrlInputEl = document.querySelector("#base-url-input");
const toolsEl = document.querySelector("#tools");
const toolLogEl = document.querySelector("#tool-log");
const submitBtn = document.querySelector("#chat-submit");
const errorBannerEl = document.querySelector("#error-banner");

function setError(message) {
  if (!message) {
    errorBannerEl.hidden = true;
    errorBannerEl.textContent = "";
    return;
  }
  errorBannerEl.hidden = false;
  errorBannerEl.textContent = message;
}

function appendMessage(role, content) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = content;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function formatErrorPrefix(error) {
  if (error == null) {
    return "Unknown error";
  }
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  try {
    return JSON.stringify(error);
  } catch (_ignore) {
    return String(error);
  }
}

function renderTools(tools = {}) {
  toolsEl.innerHTML = "";
  const names = Object.keys(tools);
  if (names.length === 0) {
    const empty = document.createElement("div");
    empty.className = "tool-row";
    empty.textContent = "No tools loaded.";
    toolsEl.appendChild(empty);
    return;
  }

  for (const [name, tool] of Object.entries(tools)) {
    const row = document.createElement("div");
    row.className = "tool-row";
    const nameEl = document.createElement("span");
    nameEl.textContent = name;
    const statusEl = document.createElement("strong");
    statusEl.textContent = tool && tool.enabled ? "enabled" : "disabled";
    row.appendChild(nameEl);
    row.appendChild(statusEl);
    toolsEl.appendChild(row);
  }
}

function renderToolCalls(toolCalls) {
  try {
    const payload = JSON.stringify(toolCalls ?? [], null, 2);
    toolLogEl.textContent = payload;
  } catch (_ignore) {
    toolLogEl.textContent = "[]";
  }
}

async function loadConfig() {
  setError("");
  const response = await fetch("/api/default-config");
  if (!response.ok) {
    throw new Error(`Config request failed with status ${response.status}`);
  }

  const config = await response.json();
  tokenStatusEl.textContent = config?.provider?.api_key_configured
    ? "API token configured"
    : "API token missing";

  modelInputEl.value = config?.provider?.model || "";
  baseUrlInputEl.value = config?.provider?.base_url || "";
  renderTools(config?.tools);
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) {
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Sending…";
  setError("");

  appendMessage("user", message);
  inputEl.value = "";

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message }),
    });

    if (!response.ok) {
      throw new Error(`Chat request failed with status ${response.status}`);
    }

    const result = await response.json();
    const assistantText = result?.final_text || "";
    const errors = Array.isArray(result?.errors) ? result.errors : [];
    renderToolCalls(result?.tool_calls || []);

    if (assistantText) {
      appendMessage("assistant", assistantText);
    }
    if (errors.length > 0) {
      appendMessage("assistant", errors.join("\n"));
      setError(errors.join(" "));
    } else if (!assistantText) {
      appendMessage("assistant", "No response text returned.");
    }
  } catch (error) {
    appendMessage("assistant", "Failed to send message.");
    setError(formatErrorPrefix(error));
    renderToolCalls([]);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Send";
    inputEl.focus();
  }
});

window.addEventListener("DOMContentLoaded", () => {
  loadConfig().catch((error) => {
    setError(`Config error: ${formatErrorPrefix(error)}`);
    tokenStatusEl.textContent = "Configuration unavailable";
    renderTools({});
    renderToolCalls([]);
  });
});
