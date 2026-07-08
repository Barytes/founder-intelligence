const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#chat-form");
const inputEl = document.querySelector("#message-input");
const tokenStatusEl = document.querySelector("#token-status");
const configSelectEl = document.querySelector("#config-select");
const providerSelectEl = document.querySelector("#provider-select");
const configNameInputEl = document.querySelector("#config-name-input");
const modelInputEl = document.querySelector("#model-input");
const providerFormEl = document.querySelector("#provider-form");
const apiKeyInputEl = document.querySelector("#api-key-input");
const baseUrlEditInputEl = document.querySelector("#base-url-edit-input");
const providerSaveBtn = document.querySelector("#provider-save");
const providerSaveStatusEl = document.querySelector("#provider-save-status");
const toolsEl = document.querySelector("#tools");
const toolLogEl = document.querySelector("#tool-log");
const submitBtn = document.querySelector("#chat-submit");
const errorBannerEl = document.querySelector("#error-banner");
const NEW_CONFIG_ID = "__new__";
let providerTemplates = {};
let savedConfigs = {};

function setError(message) {
  if (!message) {
    errorBannerEl.hidden = true;
    errorBannerEl.textContent = "";
    return;
  }
  errorBannerEl.hidden = false;
  errorBannerEl.textContent = message;
}

function setProviderStatus(message, isError = false) {
  providerSaveStatusEl.textContent = message || "";
  providerSaveStatusEl.classList.toggle("error", isError);
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

function providerStatusText(profile) {
  return profile && profile.api_key_configured
    ? `API token configured: ${profile.api_key_env}`
    : `API token missing: ${profile?.api_key_env || ""}`;
}

function applyProfile(profile) {
  if (!profile) {
    return;
  }

  configNameInputEl.value = profile.label || "";
  modelInputEl.value = profile.model || "";
  baseUrlEditInputEl.value = profile.base_url || "";
  apiKeyInputEl.value = "";
  tokenStatusEl.textContent = providerStatusText(profile);
}

function applyProviderTemplate(providerId) {
  const template = providerTemplates[providerId];
  if (!template) {
    return;
  }

  modelInputEl.value = template.model || "";
  baseUrlEditInputEl.value = template.base_url || "";
  apiKeyInputEl.value = "";
  tokenStatusEl.textContent = providerStatusText(template);
}

function renderProviderTemplates(templatePayload) {
  providerTemplates = templatePayload?.items || {};
  providerSelectEl.innerHTML = "";

  const templateIds = Object.keys(providerTemplates);
  if (templateIds.length === 0) {
    const option = document.createElement("option");
    option.value = "default";
    option.textContent = "Default";
    providerSelectEl.appendChild(option);
    return;
  }

  for (const templateId of templateIds) {
    const profile = providerTemplates[templateId];
    const option = document.createElement("option");
    option.value = templateId;
    option.textContent = profile?.label || profileId;
    providerSelectEl.appendChild(option);
  }
}

function renderSavedConfigs(savedPayload, fallbackProvider) {
  savedConfigs = savedPayload?.items || {};
  configSelectEl.innerHTML = "";

  const newOption = document.createElement("option");
  newOption.value = NEW_CONFIG_ID;
  newOption.textContent = "New Configuration";
  configSelectEl.appendChild(newOption);

  for (const [configId, profile] of Object.entries(savedConfigs)) {
    const option = document.createElement("option");
    option.value = configId;
    option.textContent = profile?.label || configId;
    configSelectEl.appendChild(option);
  }

  const active = savedPayload?.active;
  if (active && savedConfigs[active]) {
    configSelectEl.value = active;
    const activeProfile = savedConfigs[active];
    providerSelectEl.value = activeProfile.template || active;
    applyProfile(activeProfile);
    return;
  }

  configSelectEl.value = NEW_CONFIG_ID;
  configNameInputEl.value = "";
  modelInputEl.value = fallbackProvider?.model || "";
  baseUrlEditInputEl.value = fallbackProvider?.base_url || "";
  tokenStatusEl.textContent = fallbackProvider?.api_key_configured
    ? "API token configured"
    : "API token missing";
}

async function loadConfig() {
  setError("");
  const response = await fetch("/api/default-config");
  if (!response.ok) {
    throw new Error(`Config request failed with status ${response.status}`);
  }

  const config = await response.json();
  renderProviderTemplates(config?.provider_templates);
  renderSavedConfigs(config?.saved_configs, config?.provider);
  renderTools(config?.tools);
}

configSelectEl.addEventListener("change", () => {
  setProviderStatus("");
  const configId = configSelectEl.value;
  if (configId === NEW_CONFIG_ID) {
    configNameInputEl.value = "";
    applyProviderTemplate(providerSelectEl.value);
    return;
  }

  const profile = savedConfigs[configId];
  if (profile) {
    providerSelectEl.value = profile.template || configId;
    applyProfile(profile);
  }
});

providerSelectEl.addEventListener("change", () => {
  setProviderStatus("");
  if (configSelectEl.value === NEW_CONFIG_ID) {
    applyProviderTemplate(providerSelectEl.value);
  }
});

providerFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const configId = configSelectEl.value;
  const providerId = providerSelectEl.value;
  const configName = configNameInputEl.value.trim();
  const apiKey = apiKeyInputEl.value.trim();
  const baseUrl = baseUrlEditInputEl.value.trim();
  const model = modelInputEl.value.trim();

  if (!configName) {
    setProviderStatus("Enter configuration name.", true);
    return;
  }

  if (!apiKey && !baseUrl && !model) {
    setProviderStatus("Enter API key, base URL, or model.", true);
    return;
  }

  providerSaveBtn.disabled = true;
  providerSaveBtn.textContent = "Saving…";
  setProviderStatus("");
  setError("");

  try {
    const response = await fetch("/api/provider-settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        config_id: configId === NEW_CONFIG_ID ? null : configId,
        config_name: configName,
        provider_id: providerId || null,
        api_key: apiKey || null,
        base_url: baseUrl || null,
        model: model || null,
      }),
    });

    if (!response.ok) {
      throw new Error(`Provider settings failed with status ${response.status}`);
    }

    const result = await response.json();
    const errors = Array.isArray(result?.errors) ? result.errors : [];
    if (result?.status !== "ok" || errors.length > 0) {
      throw new Error(errors.join(" ") || "Provider settings were not saved.");
    }

    const provider = result?.provider || {};
    renderProviderTemplates(result?.provider_templates);
    renderSavedConfigs(result?.saved_configs, provider);
    apiKeyInputEl.value = "";
    setProviderStatus("Saved locally");
  } catch (error) {
    const message = formatErrorPrefix(error);
    setProviderStatus(message, true);
    setError(message);
  } finally {
    providerSaveBtn.disabled = false;
    providerSaveBtn.textContent = "Save";
  }
});

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
