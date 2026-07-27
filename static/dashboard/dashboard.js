/* Dashboard glue: CSRF for HTMX, drag-drop uploads, live colour stock totals. */

document.addEventListener("DOMContentLoaded", function () {
  const token = document.querySelector("[name=csrfmiddlewaretoken]");

  // Every HTMX request carries the CSRF token.
  document.body.addEventListener("htmx:configRequest", function (event) {
    const input = document.querySelector("[name=csrfmiddlewaretoken]");
    if (input) event.detail.headers["X-CSRFToken"] = input.value;
  });

  initDropzones();
  initImageManagers();
  document.body.addEventListener("htmx:afterSwap", initDropzones);
  document.body.addEventListener("htmx:afterSwap", initImageManagers);
  document.body.addEventListener("htmx:afterSwap", bindStockTotals);
  bindStockTotals();
  bindAddColour();
  bindProductFormGuard();
  scrollToFirstError();

  if (!token) return;
});

/* Jump to the first problem so it is never left off-screen below the fold. */
function scrollToFirstError() {
  const target =
    document.querySelector("[data-error-summary]") ||
    document.querySelector(".field__error") ||
    document.querySelector(".flash--error");
  if (!target) return;

  // Re-POSTing the same URL makes the browser restore the old scroll position
  // *after* load, which would undo this. Turn that off and scroll on the next
  // frame so we win regardless of ordering.
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";

  const jump = function () {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    // Focus the input the first error belongs to, so typing fixes it at once.
    const field = document.querySelector(".field__error");
    const owner = field && field.closest(".field, [data-colour-form]");
    const input = owner && owner.querySelector("input, select, textarea");
    if (input) input.focus({ preventScroll: true });
  };

  requestAnimationFrame(function () {
    requestAnimationFrame(jump);
  });
  window.addEventListener("load", function () {
    setTimeout(jump, 60);
  });
}

/* Catch the common required-field mistakes (name, category, base price) before
   the product form submits. A server round-trip re-render would wipe staged
   images — they exist only in the browser until the product saves — so blocking
   the submit keeps everything the admin entered. Colour-level fields are still
   validated on the server; we only guard the top-level product fields here. */
function bindProductFormGuard() {
  const form = document.getElementById("product-form");
  if (!form) return;
  form.addEventListener("submit", function (event) {
    form.querySelectorAll("[data-client-error]").forEach(function (el) {
      el.remove();
    });
    let firstBad = null;
    const flag = function (field, text) {
      firstBad = firstBad || field;
      const wrap = field.closest(".field") || field.parentElement;
      const message = document.createElement("span");
      message.className = "field__error";
      message.setAttribute("data-client-error", "");
      message.textContent = text;
      wrap.appendChild(message);
    };

    // Required top-level product fields (name, category, base price).
    form
      .querySelectorAll("input[required], select[required], textarea[required]")
      .forEach(function (field) {
        if (field.closest("[data-colour-form]")) return; // colours handled below
        if ((field.value || "").trim()) return;
        flag(field, "This field is required.");
      });

    // A colour with stock typed but no name is rejected server-side too; catch
    // it here so the reload (and the staged images it would drop) never happens.
    form.querySelectorAll("[data-colour-form]").forEach(function (panel) {
      const nameField = panel.querySelector('input[name$="-name"]');
      if (!nameField || nameField.value.trim()) return;
      const hasStock = Array.from(
        panel.querySelectorAll("input[data-stock-input]")
      ).some(function (input) {
        return (input.value || "").trim();
      });
      if (hasStock) {
        flag(nameField, "Name this colour — its stock and images are saved against it.");
      }
    });

    if (firstBad) {
      event.preventDefault();
      if ("scrollRestoration" in history) history.scrollRestoration = "manual";
      firstBad.focus();
      firstBad.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
}

/* "Add another colour": clone the empty formset row and bump TOTAL_FORMS. */
function bindAddColour() {
  const button = document.querySelector("[data-add-colour]");
  const list = document.querySelector("[data-colour-list]");
  const template = document.getElementById("colour-empty-template");
  const total = document.querySelector("#id_colours-TOTAL_FORMS");
  if (!button || !list || !template || !total) return;

  button.addEventListener("click", function () {
    const index = parseInt(total.value, 10);
    const markup = template.innerHTML.replace(/__prefix__/g, index);
    const holder = document.createElement("div");
    holder.innerHTML = markup;
    const panel = holder.firstElementChild;
    list.appendChild(panel);
    total.value = index + 1;

    initDropzones();
    initImageManagers();
    bindStockTotals();
    const name = panel.querySelector("input[type=text]");
    if (name) name.focus();
  });
}

/* Drag-and-drop image upload per colour. */
function initDropzones() {
  document.querySelectorAll(".dropzone:not([data-bound])").forEach(function (zone) {
    zone.dataset.bound = "1";
    const input = zone.querySelector("input[type=file]");
    if (!input) return;

    zone.addEventListener("click", function (event) {
      if (event.target !== input) input.click();
    });
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add("is-over");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.remove("is-over");
      });
    });
    zone.addEventListener("drop", function (event) {
      input.files = event.dataTransfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // The files upload with the product, so show what is queued.
    const preview = zone.querySelector("[data-image-preview]");
    if (preview) {
      input.addEventListener("change", function () {
        const names = Array.from(input.files || []).map(function (f) {
          return f.name;
        });
        preview.textContent = names.length
          ? names.length + " file(s) ready to upload: " + names.join(", ")
          : "";
      });
    }
  });
}

/* ---------------------------------------------------------------- images
   Per-colour image manager: add images one pick at a time (no "all at once"),
   and reorder by dragging a tile or using the ◀ ▶ buttons. Delete / set-cover
   ride on HTMX in the template; these bits need JS because they carry files or
   a computed order. Every change re-renders the strip from the server, so the
   DOM stays the single source of truth. */

function csrfToken() {
  const el = document.querySelector("[name=csrfmiddlewaretoken]");
  return el ? el.value : "";
}

/* Replace a colour's strip with server-rendered HTML and re-arm its controls. */
function swapImageStrip(targetSelector, html) {
  const target = document.querySelector(targetSelector);
  if (!target) return;
  target.innerHTML = html;
  if (window.htmx) window.htmx.process(target); // re-arm hx-post delete/cover buttons
  initImageManagers();
}

function initImageManagers() {
  initImageStaging();
  document
    .querySelectorAll("[data-sortable]:not([data-sortable-bound])")
    .forEach(initSortable);
}

/* New-colour images: staged in the browser with live previews — add one or
   several, remove any, reorder by drag or ◀ ▶ — then uploaded, in this order,
   when the product form is saved. There's no colour id to attach to yet, so we
   keep the <input>'s FileList in sync via DataTransfer instead of the server. */
function initImageStaging() {
  document.querySelectorAll("[data-stage]:not([data-stage-bound])").forEach(function (stage) {
    stage.dataset.stageBound = "1";
    stage._staged = [];
    const input = stage.querySelector("[data-stage-input]");
    const list = stage.querySelector("[data-stage-list]");
    if (!input || !list) return;
    list.addEventListener("dragover", function (event) {
      event.preventDefault();
    });
    input.addEventListener("change", function () {
      // Add to what's staged (don't replace), but never past the per-colour cap.
      const max = stageMax(stage);
      const room = Math.max(0, max - stageExistingCount(stage) - stage._staged.length);
      const picked = Array.from(input.files || []);
      picked.slice(0, room).forEach(function (file) {
        stage._staged.push(file);
      });
      const ignored = picked.length - Math.min(picked.length, room);
      renderStage(stage);
      if (ignored > 0) {
        const note = stage.querySelector("[data-stage-note]");
        if (note) {
          note.textContent =
            "Up to " + max + " images per colour — " + ignored + " not added.";
        }
      }
    });
  });
}

/* The per-colour image cap, and how many already-saved images count toward it. */
function stageMax(stage) {
  return parseInt(stage.dataset.max, 10) || 8;
}
function stageExistingCount(stage) {
  // Saved images live in the server strip inside the same colour panel; they
  // count against the cap alongside the ones being staged.
  const panel = stage.closest("[data-colour-form]");
  const strip = panel ? panel.querySelector('[id^="images-"]') : null;
  return strip ? strip.querySelectorAll(".imagestrip__item").length : 0;
}

/* Re-sync the input's FileList to the staged order and redraw the previews. */
function renderStage(stage) {
  const list = stage.querySelector("[data-stage-list]");
  const input = stage.querySelector("[data-stage-input]");

  const data = new DataTransfer();
  stage._staged.forEach(function (file) {
    data.items.add(file);
  });
  input.files = data.files; // submitted in exactly this order → sort_order on save

  list.querySelectorAll("img").forEach(function (img) {
    if (img.src.indexOf("blob:") === 0) URL.revokeObjectURL(img.src);
  });
  list.innerHTML = "";
  stage._staged.forEach(function (file, index) {
    const item = document.createElement("figure");
    item.className = "imagestrip__item" + (index === 0 ? " is-cover" : "");
    item.draggable = true;
    item._file = file;
    item.innerHTML =
      '<span class="imagestrip__handle" aria-hidden="true">⠿</span>' +
      (index === 0 ? '<span class="imagestrip__badge">Cover</span>' : "") +
      '<img class="imagestrip__img" draggable="false" alt="" src="' +
      URL.createObjectURL(file) +
      '">' +
      '<figcaption class="imagestrip__actions">' +
      '<button class="iconbtn" type="button" data-move="prev" aria-label="Move earlier" title="Move earlier">◀</button>' +
      '<button class="iconbtn" type="button" data-move="next" aria-label="Move later" title="Move later">▶</button>' +
      '<button class="linkbtn linkbtn--danger" type="button" data-stage-remove>Remove</button>' +
      "</figcaption>";
    list.appendChild(item);
  });
  bindStageItems(stage);

  // Reflect remaining capacity (a fresh "N not added" message from the change
  // handler overwrites this afterwards).
  const note = stage.querySelector("[data-stage-note]");
  if (note) {
    const total = stageExistingCount(stage) + stage._staged.length;
    note.textContent =
      total >= stageMax(stage)
        ? "Maximum of " + stageMax(stage) + " images per colour reached."
        : "";
  }
}

/* Rebuild the staged order from the tiles' current DOM order, then redraw. */
function stageSyncFromDom(stage) {
  const list = stage.querySelector("[data-stage-list]");
  stage._staged = Array.from(list.querySelectorAll(".imagestrip__item")).map(function (el) {
    return el._file;
  });
  renderStage(stage);
}

function bindStageItems(stage) {
  const list = stage.querySelector("[data-stage-list]");
  list.querySelectorAll(".imagestrip__item").forEach(function (item) {
    item.addEventListener("dragstart", function (event) {
      item.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      try {
        event.dataTransfer.setData("text/plain", "stage");
      } catch (err) {
        /* ignore */
      }
    });
    item.addEventListener("dragend", function () {
      item.classList.remove("is-dragging");
      stageSyncFromDom(stage);
    });
    item.addEventListener("dragover", function (event) {
      event.preventDefault();
      const dragging = list.querySelector(".is-dragging");
      if (!dragging || dragging === item) return;
      const rect = item.getBoundingClientRect();
      const before =
        event.clientY < rect.top + rect.height / 2 ||
        (event.clientX < rect.left + rect.width / 2 && event.clientY < rect.bottom);
      list.insertBefore(dragging, before ? item : item.nextElementSibling);
    });

    const remove = item.querySelector("[data-stage-remove]");
    if (remove) {
      remove.addEventListener("click", function () {
        const idx = Array.from(list.querySelectorAll(".imagestrip__item")).indexOf(item);
        if (idx > -1) {
          stage._staged.splice(idx, 1);
          renderStage(stage);
        }
      });
    }

    item.querySelectorAll("[data-move]").forEach(function (button) {
      button.addEventListener("click", function () {
        if (button.dataset.move === "prev" && item.previousElementSibling) {
          list.insertBefore(item, item.previousElementSibling);
        } else if (button.dataset.move === "next" && item.nextElementSibling) {
          list.insertBefore(item.nextElementSibling, item);
        } else {
          return;
        }
        stageSyncFromDom(stage);
      });
    });
  });
}

/* Persist the current tile order (top-to-bottom in the DOM) to the server. */
function persistImageOrder(container) {
  const ids = Array.from(container.querySelectorAll("[data-image-id]")).map(function (el) {
    return el.dataset.imageId;
  });
  fetch(container.dataset.reorderUrl, {
    method: "POST",
    headers: {
      "X-CSRFToken": csrfToken(),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ order: ids.join(",") }),
  })
    .then(function (response) {
      return response.text();
    })
    .then(function (html) {
      swapImageStrip(container.dataset.target, html);
    });
}

/* Drag-and-drop reordering, plus the ◀ ▶ move buttons as a reliable fallback. */
function initSortable(container) {
  container.dataset.sortableBound = "1";

  container.querySelectorAll(".imagestrip__item").forEach(function (item) {
    item.addEventListener("dragstart", function (event) {
      item.classList.add("is-dragging");
      event.dataTransfer.effectAllowed = "move";
      try {
        event.dataTransfer.setData("text/plain", item.dataset.imageId); // Firefox needs this
      } catch (err) {
        /* ignore */
      }
    });
    item.addEventListener("dragend", function () {
      item.classList.remove("is-dragging");
      persistImageOrder(container);
    });
    item.addEventListener("dragover", function (event) {
      event.preventDefault();
      const dragging = container.querySelector(".is-dragging");
      if (!dragging || dragging === item) return;
      const rect = item.getBoundingClientRect();
      const before =
        event.clientY < rect.top + rect.height / 2 ||
        (event.clientX < rect.left + rect.width / 2 && event.clientY < rect.bottom);
      container.insertBefore(dragging, before ? item : item.nextElementSibling);
    });
  });

  container.addEventListener("dragover", function (event) {
    event.preventDefault(); // allow drop, and stop the browser opening the image
  });

  container.querySelectorAll("[data-move]").forEach(function (button) {
    button.addEventListener("click", function () {
      const item = button.closest(".imagestrip__item");
      if (!item) return;
      if (button.dataset.move === "prev" && item.previousElementSibling) {
        container.insertBefore(item, item.previousElementSibling);
      } else if (button.dataset.move === "next" && item.nextElementSibling) {
        container.insertBefore(item.nextElementSibling, item);
      } else {
        return;
      }
      persistImageOrder(container);
    });
  });
}

/* Live "stock available for this colour" subtotal as the grid is edited. */
function bindStockTotals() {
  document.querySelectorAll("[data-stock-grid]:not([data-bound])").forEach(function (grid) {
    grid.dataset.bound = "1";
    const output = grid.querySelector("[data-stock-total]");
    const recompute = function () {
      let total = 0;
      grid.querySelectorAll("input[data-stock-input]").forEach(function (input) {
        const value = parseInt(input.value, 10);
        if (!isNaN(value)) total += value;
      });
      if (output) output.textContent = total;
      const header = document.querySelector(
        '[data-colour-stock="' + grid.dataset.stockGrid + '"]'
      );
      if (header) header.textContent = total + " in stock";
    };
    grid.addEventListener("input", recompute);
    recompute();
  });
}

/* Confirm destructive actions. Honour the clicked button's data-confirm first
   (so one form can have distinct approve/reject prompts), then the form's. */
document.addEventListener("submit", function (event) {
  const form = event.target;
  const message =
    (event.submitter && event.submitter.dataset.confirm) || form.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
