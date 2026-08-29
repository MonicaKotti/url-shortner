(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const shortenForm = byId("shorten-form");
  const createButton = byId("create-button");
  const createStatus = byId("create-status");
  const result = byId("result");
  const shortUrl = byId("short-url");
  const copyButton = byId("copy-button");
  const openLink = byId("open-link");
  const adminForm = byId("admin-form");
  const adminKeyInput = byId("admin-key");
  const connectButton = byId("connect-button");
  const disconnectButton = byId("disconnect-button");
  const operatorStatus = byId("operator-status");
  const linkList = byId("link-list");
  const emptyState = byId("empty-state");
  const statusDot = document.querySelector(".status-dot");
  const disableDialog = byId("disable-dialog");
  const dialogCopy = byId("dialog-copy");
  const confirmDisable = byId("confirm-disable");

  let adminKey = "";
  let pendingDisableCode = "";

  function setStatus(element, message, success = false) {
    element.textContent = message;
    element.classList.toggle("success", success);
  }

  function setBusy(button, busy, busyLabel, normalLabel) {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
    const label = button.querySelector("span") || button;
    label.textContent = busy ? busyLabel : normalLabel;
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    if (!response.ok) {
      let message = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") message = body.detail;
      } catch (_) {
        // The status code remains a useful safe fallback for non-JSON responses.
      }
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function safeHttpUrl(value) {
    try {
      const parsed = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  }

  shortenForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    result.hidden = true;
    setStatus(createStatus, "");
    if (!shortenForm.reportValidity()) return;

    const url = byId("target-url").value.trim();
    const customAlias = byId("custom-alias").value.trim();
    const expiresAt = byId("expires-at").value;
    if (expiresAt && new Date(expiresAt).getTime() <= Date.now()) {
      setStatus(createStatus, "Expiration must be in the future.");
      byId("expires-at").focus();
      return;
    }
    const payload = { url };
    if (customAlias) payload.custom_alias = customAlias;
    if (expiresAt) payload.expires_at = new Date(expiresAt).toISOString();

    setBusy(createButton, true, "Shortening…", "Shorten link");
    try {
      const created = await api("/api/v1/links", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify(payload),
      });
      const safeUrl = safeHttpUrl(created.short_url);
      if (!safeUrl) throw new Error("The server returned an invalid short URL.");
      shortUrl.textContent = created.short_url;
      shortUrl.href = safeUrl;
      openLink.href = safeUrl;
      result.hidden = false;
      setStatus(createStatus, "Link created successfully.", true);
      result.focus?.();
      if (adminKey) await loadLinks();
    } catch (error) {
      setStatus(createStatus, error instanceof Error ? error.message : "Unable to create the link.");
    } finally {
      setBusy(createButton, false, "Shortening…", "Shorten link");
    }
  });

  copyButton.addEventListener("click", async () => {
    const value = shortUrl.textContent;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const field = document.createElement("textarea");
        field.value = value;
        field.setAttribute("readonly", "");
        field.className = "sr-only";
        document.body.append(field);
        field.select();
        document.execCommand("copy");
        field.remove();
      }
      copyButton.textContent = "Copied";
      setStatus(createStatus, "Short link copied to clipboard.", true);
      window.setTimeout(() => { copyButton.textContent = "Copy"; }, 1800);
    } catch (_) {
      setStatus(createStatus, "Copy failed. Select the short link and copy it manually.");
    }
  });

  function adminHeaders() {
    return { "X-Admin-Key": adminKey };
  }

  function lockOperator(message) {
    adminKey = "";
    linkList.replaceChildren();
    emptyState.hidden = false;
    emptyState.querySelector("h3").textContent = "Waiting for a signal";
    emptyState.querySelector("p").textContent = "Connect as an operator to see shortened links and analytics.";
    statusDot.classList.remove("connected");
    connectButton.hidden = false;
    adminKeyInput.hidden = false;
    disconnectButton.hidden = true;
    setStatus(operatorStatus, message);
  }

  function reportOperatorError(error, fallback) {
    const message = error instanceof Error ? error.message : fallback;
    if (error && error.status === 401) {
      lockOperator("Operator access expired. Enter the admin key again.");
      return;
    }
    setStatus(operatorStatus, message);
  }

  function createTextElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    return element;
  }

  function formatDate(value) {
    if (!value) return "Never";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
  }

  function appendMeta(container, text, className = "") {
    container.append(createTextElement("span", className, text));
  }

  function renderAnalytics(panel, analytics) {
    panel.replaceChildren();
    const grid = document.createElement("div");
    grid.className = "analytics-grid";
    const cards = [
      [String(analytics.total_clicks), "Total clicks"],
      [String(analytics.clicks_by_day.length), "Active days"],
      [String(analytics.top_referrers.length), "Referrers"],
    ];
    cards.forEach(([value, label]) => {
      const card = document.createElement("div");
      card.className = "metric-card";
      card.append(createTextElement("strong", "", value), createTextElement("span", "", label));
      grid.append(card);
    });
    panel.append(grid);

    const list = document.createElement("ul");
    list.className = "analytics-list";
    const referrers = analytics.top_referrers.slice(0, 5);
    if (!referrers.length) {
      list.append(createTextElement("li", "", "No referrer activity yet."));
    } else {
      referrers.forEach((item) => {
        const row = document.createElement("li");
        row.append(createTextElement("span", "", item.referrer || "Direct"));
        row.append(createTextElement("strong", "", `${item.clicks} clicks`));
        list.append(row);
      });
    }
    panel.append(list);
  }

  function renderLink(link) {
    const article = document.createElement("article");
    article.className = `link-card${link.disabled ? " disabled" : ""}`;
    const copy = document.createElement("div");
    const href = safeHttpUrl(link.short_url);
    const title = document.createElement("h3");
    const anchor = document.createElement("a");
    anchor.textContent = link.short_url;
    if (href) {
      anchor.href = href;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
    }
    title.append(anchor);
    copy.append(title, createTextElement("p", "destination", link.target_url));
    const meta = document.createElement("div");
    meta.className = "link-meta";
    appendMeta(meta, link.disabled ? "Disabled" : "Active", link.disabled ? "inactive" : "active");
    appendMeta(meta, `${link.click_count} clicks`);
    appendMeta(meta, `Expires: ${formatDate(link.expires_at)}`);
    copy.append(meta);

    const actions = document.createElement("div");
    actions.className = "link-actions";
    const analyticsButton = createTextElement("button", "secondary-button", "Analytics");
    analyticsButton.type = "button";
    const disableButton = createTextElement("button", "danger-button", "Disable");
    disableButton.type = "button";
    disableButton.disabled = Boolean(link.disabled);
    actions.append(analyticsButton, disableButton);

    const analyticsPanel = document.createElement("div");
    analyticsPanel.className = "analytics-panel";
    analyticsPanel.hidden = true;
    analyticsButton.addEventListener("click", async () => {
      if (!analyticsPanel.hidden) {
        analyticsPanel.hidden = true;
        analyticsButton.textContent = "Analytics";
        return;
      }
      analyticsButton.disabled = true;
      analyticsButton.textContent = "Loading…";
      try {
        const analytics = await api(`/api/v1/links/${encodeURIComponent(link.code)}/analytics`, {
          headers: adminHeaders(),
        });
        renderAnalytics(analyticsPanel, analytics);
        analyticsPanel.hidden = false;
        analyticsButton.textContent = "Hide analytics";
      } catch (error) {
        reportOperatorError(error, "Unable to load analytics.");
        analyticsButton.textContent = "Analytics";
      } finally {
        analyticsButton.disabled = false;
      }
    });
    disableButton.addEventListener("click", () => {
      pendingDisableCode = link.code;
      dialogCopy.textContent = `The short link “${link.code}” will stop redirecting. Existing analytics are preserved.`;
      disableDialog.returnValue = "";
      disableDialog.showModal();
    });

    article.append(copy, actions, analyticsPanel);
    return article;
  }

  async function loadLinks() {
    setStatus(operatorStatus, "Loading links…");
    try {
      const links = await api("/api/v1/links?limit=100", { headers: adminHeaders() });
      linkList.replaceChildren(...links.map(renderLink));
      emptyState.hidden = links.length > 0;
      if (!links.length) {
        emptyState.querySelector("h3").textContent = "No links yet";
        emptyState.querySelector("p").textContent = "Create your first signal above.";
      }
      setStatus(operatorStatus, `${links.length} ${links.length === 1 ? "link" : "links"} loaded.`, true);
    } catch (error) {
      linkList.replaceChildren();
      emptyState.hidden = false;
      throw error;
    }
  }

  adminForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!adminForm.reportValidity()) return;
    adminKey = adminKeyInput.value;
    adminKeyInput.value = "";
    connectButton.disabled = true;
    connectButton.textContent = "Connecting…";
    try {
      await loadLinks();
      statusDot.classList.add("connected");
      connectButton.hidden = true;
      adminKeyInput.hidden = true;
      disconnectButton.hidden = false;
    } catch (error) {
      reportOperatorError(error, "Unable to connect.");
    } finally {
      connectButton.disabled = false;
      connectButton.textContent = "Connect";
    }
  });

  disconnectButton.addEventListener("click", () => {
    lockOperator("Disconnected. The admin key was cleared.");
    operatorStatus.classList.add("success");
    adminKeyInput.focus();
  });

  disableDialog.addEventListener("close", async () => {
    if (disableDialog.returnValue !== "confirm" || !pendingDisableCode) {
      pendingDisableCode = "";
      return;
    }
    const code = pendingDisableCode;
    pendingDisableCode = "";
    confirmDisable.disabled = true;
    setStatus(operatorStatus, `Disabling ${code}…`);
    try {
      await api(`/api/v1/links/${encodeURIComponent(code)}`, { method: "DELETE", headers: adminHeaders() });
      await loadLinks();
      setStatus(operatorStatus, `${code} is disabled.`, true);
    } catch (error) {
      reportOperatorError(error, "Unable to disable the link.");
    } finally {
      confirmDisable.disabled = false;
    }
  });
})();
