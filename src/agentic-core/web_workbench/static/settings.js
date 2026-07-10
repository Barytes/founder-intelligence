const settingsStatusEl = document.querySelector("#settings-status");
const configSelectEl = document.querySelector("#config-select");
const providerSelectEl = document.querySelector("#provider-select");
const configNameInputEl = document.querySelector("#config-name-input");
const modelInputEl = document.querySelector("#model-input");
const providerFormEl = document.querySelector("#provider-form");
const apiKeyInputEl = document.querySelector("#api-key-input");
const baseUrlEditInputEl = document.querySelector("#base-url-edit-input");
const providerSaveBtn = document.querySelector("#provider-save");
const providerSaveStatusEl = document.querySelector("#provider-save-status");
const githubTokenFormEl = document.querySelector("#github-token-form");
const githubTokenInputEl = document.querySelector("#github-token-input");
const githubTokenSaveBtn = document.querySelector("#github-token-save");
const githubTokenStatusEl = document.querySelector("#github-token-status");
const githubTokenSaveStatusEl = document.querySelector("#github-token-save-status");
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

function setStatus(el, message, isError = false) {
  el.textContent = message || "";
  el.classList.toggle("error", isError);
}

function formatErrorPrefix(error) {
  if (error == null) return "Unknown error";
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  try {
    return JSON.stringify(error);
  } catch (_ignore) {
    return String(error);
  }
}

function providerStatusText(profile) {
  return profile && profile.api_key_configured
    ? `API token configured: ${profile.api_key_env}`
    : `API token missing: ${profile?.api_key_env || ""}`;
}

function applyProfile(profile) {
  if (!profile) return;
  configNameInputEl.value = profile.label || "";
  modelInputEl.value = profile.model || "";
  baseUrlEditInputEl.value = profile.base_url || "";
  apiKeyInputEl.value = "";
  settingsStatusEl.textContent = providerStatusText(profile);
}

function applyProviderTemplate(providerId) {
  const template = providerTemplates[providerId];
  if (!template) return;
  modelInputEl.value = template.model || "";
  baseUrlEditInputEl.value = template.base_url || "";
  apiKeyInputEl.value = "";
  settingsStatusEl.textContent = providerStatusText(template);
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
    option.textContent = profile?.label || templateId;
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
  settingsStatusEl.textContent = fallbackProvider?.api_key_configured
    ? "API token configured"
    : "API token missing";
}

function renderGitHubToken(payload) {
  const token = payload?.github_token;
  if (!token) {
    githubTokenStatusEl.textContent = "GITHUB_ACCESS_TOKEN status unavailable.";
    return;
  }
  githubTokenStatusEl.textContent = token.configured
    ? `${token.env_key} configured (${token.preview})`
    : `${token.env_key} missing`;
  githubTokenInputEl.value = "";
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    const errors = Array.isArray(payload?.errors) ? payload.errors.join(" ") : payload?.message;
    throw new Error(errors || `${path} failed with status ${response.status}`);
  }
  return payload;
}

async function loadProviderConfig() {
  const config = await fetchJson("/api/agent/default-config");
  renderProviderTemplates(config?.provider_templates);
  renderSavedConfigs(config?.saved_configs, config?.provider);
}

async function loadEnvSettings() {
  const payload = await fetchJson("/api/settings/env");
  renderGitHubToken(payload);
}

configSelectEl.addEventListener("change", () => {
  setStatus(providerSaveStatusEl, "");
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
  setStatus(providerSaveStatusEl, "");
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
    setStatus(providerSaveStatusEl, "Enter configuration name.", true);
    return;
  }
  if (!apiKey && !baseUrl && !model) {
    setStatus(providerSaveStatusEl, "Enter API key, base URL, or model.", true);
    return;
  }

  providerSaveBtn.disabled = true;
  providerSaveBtn.textContent = "Saving...";
  setStatus(providerSaveStatusEl, "");
  setError("");

  try {
    const result = await fetchJson("/api/agent/provider-settings", {
      method: "POST",
      body: JSON.stringify({
        config_id: configId === NEW_CONFIG_ID ? null : configId,
        config_name: configName,
        provider_id: providerId || null,
        api_key: apiKey || null,
        base_url: baseUrl || null,
        model: model || null,
      }),
    });
    const errors = Array.isArray(result?.errors) ? result.errors : [];
    if (result?.status !== "ok" || errors.length > 0) {
      throw new Error(errors.join(" ") || "Provider settings were not saved.");
    }
    renderProviderTemplates(result?.provider_templates);
    renderSavedConfigs(result?.saved_configs, result?.provider);
    apiKeyInputEl.value = "";
    setStatus(providerSaveStatusEl, "Saved locally");
  } catch (error) {
    const message = formatErrorPrefix(error);
    setStatus(providerSaveStatusEl, message, true);
    setError(message);
  } finally {
    providerSaveBtn.disabled = false;
    providerSaveBtn.textContent = "Save Provider";
  }
});

githubTokenFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const githubToken = githubTokenInputEl.value.trim();
  if (!githubToken) {
    setStatus(githubTokenSaveStatusEl, "Enter GitHub token.", true);
    return;
  }

  githubTokenSaveBtn.disabled = true;
  githubTokenSaveBtn.textContent = "Saving...";
  setStatus(githubTokenSaveStatusEl, "");
  setError("");

  try {
    const result = await fetchJson("/api/settings/env", {
      method: "PUT",
      body: JSON.stringify({ github_token: githubToken }),
    });
    renderGitHubToken(result);
    const rsshubStatus = result?.rsshub?.status;
    setStatus(
      githubTokenSaveStatusEl,
      rsshubStatus === "started"
        ? "Saved to .env; RSSHub restarted."
        : "Saved to .env; RSSHub restart needs attention.",
      rsshubStatus !== "started"
    );
  } catch (error) {
    const message = formatErrorPrefix(error);
    setStatus(githubTokenSaveStatusEl, message, true);
    setError(message);
  } finally {
    githubTokenSaveBtn.disabled = false;
    githubTokenSaveBtn.textContent = "Save Token";
  }
});

window.addEventListener("DOMContentLoaded", () => {
  Promise.all([loadProviderConfig(), loadEnvSettings()]).catch((error) => {
    const message = formatErrorPrefix(error);
    settingsStatusEl.textContent = "Configuration unavailable";
    setError(message);
  });
});
