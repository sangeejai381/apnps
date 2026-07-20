document.addEventListener("DOMContentLoaded", function () {
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

  function closeSidebar() {
    if (!appShell) return;
    appShell.classList.remove("sidebar-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "false");
  }

  function openSidebar() {
    if (!appShell) return;
    appShell.classList.add("sidebar-open");
    if (navToggle) navToggle.setAttribute("aria-expanded", "true");
  }

  if (navToggle && appShell) {
    navToggle.addEventListener("click", function () {
      if (appShell.classList.contains("sidebar-open")) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });
  }

  if (overlay) {
    overlay.addEventListener("click", closeSidebar);
  }

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeSidebar();
  });
});
