document.addEventListener("DOMContentLoaded", function () {
  // ---- PIN show/hide on login page ----
  const toggle = document.getElementById("togglePin");
  const pinInput = document.getElementById("pin");
  if (toggle && pinInput) {
    toggle.addEventListener("click", function () {
      const isHidden = pinInput.type === "password";
      pinInput.type = isHidden ? "text" : "password";
      toggle.setAttribute("aria-label", isHidden ? "Hide PIN" : "Show PIN");
    });
  }

  const navToggle = document.getElementById("navToggle");
  const appShell = document.getElementById("appShell");
  const overlay = document.getElementById("sidebarOverlay");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");

  if (!appShell) return;

  // ---- Mobile: slide-in sidebar ----
  function closeMobileSidebar() {
    appShell.classList.remove("sidebar-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
  }

  function openMobileSidebar() {
    appShell.classList.add("sidebar-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "true");
  }

  if (navToggle) {
    navToggle.addEventListener("click", function () {
      if (appShell.classList.contains("sidebar-open")) {
        closeMobileSidebar();
      } else {
        openMobileSidebar();
      }
    });
  }

  if (overlay) {
    overlay.addEventListener("click", closeMobileSidebar);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeMobileSidebar();
  });

  // ---- Desktop: collapsible sidebar (icon-only), persisted across pages ----
  const STORAGE_KEY = "apnps_sidebar_collapsed";

  function applyCollapsedState(collapsed) {
    appShell.classList.toggle("sidebar-collapsed", collapsed);
    if (collapseBtn) {
      collapseBtn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      collapseBtn.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
    }
  }

  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "1") applyCollapsedState(true);
  } catch (e) { /* localStorage unavailable — ignore */ }

  if (collapseBtn) {
    collapseBtn.addEventListener("click", function () {
      const nowCollapsed = !appShell.classList.contains("sidebar-collapsed");
      applyCollapsedState(nowCollapsed);
      try {
        window.localStorage.setItem(STORAGE_KEY, nowCollapsed ? "1" : "0");
      } catch (e) { /* ignore */ }
    });
  }

  // ---- Smart Assistant widget ----
  const assistantToggle = document.getElementById("assistantToggle");
  const assistantPanel = document.getElementById("assistantPanel");
  const assistantClose = document.getElementById("assistantClose");
  const assistantForm = document.getElementById("assistantForm");
  const assistantInput = document.getElementById("assistantInput");
  const assistantMessages = document.getElementById("assistantMessages");
  const assistantExamples = document.getElementById("assistantExamples");

  if (assistantToggle && assistantPanel) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]');
    const csrfValue = csrfToken ? csrfToken.getAttribute("content") : "";
    let examplesLoaded = false;

    function openAssistant() {
      assistantPanel.hidden = false;
      if (!examplesLoaded) loadExamples();
      assistantInput.focus();
    }
    function closeAssistant() {
      assistantPanel.hidden = true;
    }

    assistantToggle.addEventListener("click", function () {
      if (assistantPanel.hidden) openAssistant(); else closeAssistant();
    });
    if (assistantClose) assistantClose.addEventListener("click", closeAssistant);

    function addMessage(text, who) {
      const div = document.createElement("div");
      div.className = "assistant-msg " + (who === "user" ? "assistant-msg-user" : "assistant-msg-bot");
      div.textContent = text;
      assistantMessages.appendChild(div);
      assistantMessages.scrollTop = assistantMessages.scrollHeight;
      return div;
    }

    function loadExamples() {
      examplesLoaded = true;
      fetch("/assistant/examples")
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || !data.examples) return;
          assistantExamples.innerHTML = "";
          data.examples.slice(0, 4).forEach(function (ex) {
            const chip = document.createElement("button");
            chip.type = "button";
            chip.className = "assistant-example-chip";
            chip.textContent = ex;
            chip.addEventListener("click", function () {
              assistantInput.value = ex;
              assistantForm.dispatchEvent(new Event("submit", { cancelable: true }));
            });
            assistantExamples.appendChild(chip);
          });
        })
        .catch(function () { /* examples are a nice-to-have; ignore failures */ });
    }

    if (assistantForm) {
      assistantForm.addEventListener("submit", function (e) {
        e.preventDefault();
        const message = assistantInput.value.trim();
        if (!message) return;
        addMessage(message, "user");
        assistantInput.value = "";
        const typing = addMessage("Thinking…", "bot");
        typing.classList.add("assistant-msg-typing");

        fetch("/assistant/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfValue },
          body: JSON.stringify({ message: message }),
        })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("bad response")); })
          .then(function (data) {
            typing.remove();
            addMessage(data.reply || "Sorry, I couldn't work that out.", "bot");
          })
          .catch(function () {
            typing.remove();
            addMessage("Sorry, something went wrong reaching the assistant. Please try again.", "bot");
          });
      });
    }
  }
});
