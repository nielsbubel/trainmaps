"use strict";

const menu = document.querySelector(".sidebar details");
const mobile = window.matchMedia("(max-width: 760px)");
if (menu) {
  menu.open = !mobile.matches;
  mobile.addEventListener("change", (event) => { menu.open = !event.matches; });
}

document.querySelector("#print-page")?.addEventListener("click", () => window.print());

if (navigator.clipboard?.writeText) {
  for (const block of document.querySelectorAll(".prose pre")) {
    const code = block.querySelector("code");
    if (!code) continue;
    const wrapper = document.createElement("div");
    wrapper.className = "code-wrapper";
    block.replaceWith(wrapper);
    wrapper.append(block);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-button";
    button.textContent = "Kopieren";
    button.setAttribute("aria-label", "Codebeispiel kopieren");
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        button.textContent = "Kopiert ✓";
        document.querySelector("#copy-status").textContent = "Codebeispiel kopiert.";
      } catch {
        button.textContent = "Bitte manuell kopieren";
        document.querySelector("#copy-status").textContent = "Kopieren nicht erlaubt. Bitte den Code markieren und kopieren.";
      }
      window.setTimeout(() => { button.textContent = "Kopieren"; }, 2400);
    });
    wrapper.append(button);
  }
}
