/* Friendly editors for the Site settings JSON fields (USPs, FAQs, footer links).
 *
 * Each <textarea data-editor="usp|faq|footer"> is enhanced into a row editor with
 * add / remove / drag-to-reorder. The textarea stays in the DOM as the value that
 * actually submits (kept in sync as JSON) and as a raw-JSON escape hatch — so if
 * this script never runs, the field still works exactly as before. */
(function () {
  "use strict";

  var USP_ICONS = ["truck", "returns", "leaf", "lock"];

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(function () {
    var fields = document.querySelectorAll("textarea[data-editor]");
    Array.prototype.forEach.call(fields, setup);
  });

  // --------------------------------------------------------------- helpers
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function input(placeholder, value, oninput) {
    var i = el("input", "input jed__input");
    i.type = "text";
    i.placeholder = placeholder || "";
    i.value = value || "";
    i.addEventListener("input", oninput);
    return i;
  }

  function removeBtn(onclick, title) {
    var b = el("button", "jed__x", "×");
    b.type = "button";
    b.title = title || "Remove";
    b.addEventListener("click", onclick);
    return b;
  }

  function handle() {
    var h = el("span", "jed__handle", "☰");
    h.title = "Drag to reorder";
    return h;
  }

  function addBtn(label, onclick) {
    var b = el("button", "btn btn--ghost btn--sm jed__add", "+ " + label);
    b.type = "button";
    b.addEventListener("click", onclick);
    return b;
  }

  function parse(value) {
    try {
      var v = JSON.parse(value);
      return Array.isArray(v) ? v : null;
    } catch (e) {
      return null;
    }
  }

  // Row drag-and-drop within a list. Rows are [data-row]; a [data-handle] child
  // is the grab point. onReorder(from, to) mutates the model and re-renders.
  function sortable(list, onReorder) {
    var from = null;
    Array.prototype.forEach.call(list.querySelectorAll("[data-row]"), function (row, i) {
      var grip = row.querySelector("[data-handle]");
      if (!grip) return;
      grip.setAttribute("draggable", "true");
      grip.addEventListener("dragstart", function (e) {
        from = i;
        row.classList.add("is-dragging");
        if (e.dataTransfer) {
          e.dataTransfer.effectAllowed = "move";
          try { e.dataTransfer.setDragImage(row, 10, 10); } catch (err) {}
        }
      });
      grip.addEventListener("dragend", function () {
        row.classList.remove("is-dragging");
        from = null;
      });
    });
    list.addEventListener("dragover", function (e) { e.preventDefault(); });
    list.addEventListener("drop", function (e) {
      e.preventDefault();
      if (from === null) return;
      var target = e.target.closest ? e.target.closest("[data-row]") : null;
      if (!target || target.parentNode !== list) return;
      var to = Array.prototype.indexOf.call(list.children, target);
      if (to < 0 || to === from) return;
      onReorder(from, to);
    });
  }

  function move(arr, from, to) {
    arr.splice(to, 0, arr.splice(from, 1)[0]);
  }

  // ------------------------------------------------------------------- setup
  function setup(textarea) {
    var kind = textarea.dataset.editor;
    var data = parse(textarea.value);
    if (data === null) return; // invalid JSON — leave the raw textarea for repair

    var host = el("div", "jed");
    textarea.parentNode.insertBefore(host, textarea);
    textarea.setAttribute("hidden", "");

    var sync = function () { textarea.value = JSON.stringify(data); };
    var renderers = { usp: renderUsp, faq: renderFaq, footer: renderFooter };
    var render = function () {
      host.innerHTML = "";
      (renderers[kind] || function () {})(host, data, sync, render);
      sync();
    };
    render();

    // Raw-JSON escape hatch.
    var toggle = el("button", "linkbtn jed__toggle", "Edit as JSON");
    toggle.type = "button";
    toggle.addEventListener("click", function () {
      if (textarea.hasAttribute("hidden")) {
        textarea.removeAttribute("hidden");
        host.setAttribute("hidden", "");
        toggle.textContent = "Use the editor";
      } else {
        var next = parse(textarea.value);
        if (next) { data.length = 0; Array.prototype.push.apply(data, next); }
        textarea.setAttribute("hidden", "");
        host.removeAttribute("hidden");
        toggle.textContent = "Edit as JSON";
        render();
      }
    });
    host.parentNode.insertBefore(toggle, textarea.nextSibling);
  }

  // -------------------------------------------------------------- USP editor
  function renderUsp(host, data, sync, render) {
    var list = el("div", "jed__list");
    data.forEach(function (item, i) {
      var row = el("div", "jed__row");
      row.setAttribute("data-row", "");
      row.appendChild(makeHandle());

      var sel = el("select", "input jed__icon");
      var icons = USP_ICONS.slice();
      if (item.icon && icons.indexOf(item.icon) < 0) icons.push(item.icon);
      icons.forEach(function (name) {
        var opt = el("option", null, name);
        opt.value = name;
        if (name === item.icon) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", function () { item.icon = sel.value; sync(); });
      row.appendChild(sel);

      row.appendChild(input("Label, e.g. Free UK delivery over £50", item.label, function (e) {
        item.label = e.target.value; sync();
      }));
      row.appendChild(removeBtn(function () { data.splice(i, 1); render(); }));
      list.appendChild(row);
    });
    host.appendChild(list);
    host.appendChild(addBtn("Add USP", function () {
      data.push({ icon: "truck", label: "" }); render();
    }));
    sortable(list, function (f, t) { move(data, f, t); render(); });
  }

  // -------------------------------------------------------------- FAQ editor
  function renderFaq(host, data, sync, render) {
    var list = el("div", "jed__list");
    data.forEach(function (item, i) {
      var card = el("div", "jed__card");
      card.setAttribute("data-row", "");

      var head = el("div", "jed__cardhead");
      head.appendChild(makeHandle());
      head.appendChild(input("Group, e.g. Delivery", item.group, function (e) {
        item.group = e.target.value; sync();
      }));
      head.appendChild(removeBtn(function () { data.splice(i, 1); render(); }, "Remove FAQ"));
      card.appendChild(head);

      card.appendChild(input("Question", item.question, function (e) {
        item.question = e.target.value; sync();
      }));

      var ans = el("textarea", "input input--area jed__answer");
      ans.rows = 2;
      ans.placeholder = "Answer";
      ans.value = item.answer || "";
      ans.addEventListener("input", function () { item.answer = ans.value; sync(); });
      card.appendChild(ans);

      list.appendChild(card);
    });
    host.appendChild(list);
    host.appendChild(addBtn("Add question", function () {
      data.push({ group: "", question: "", answer: "" }); render();
    }));
    sortable(list, function (f, t) { move(data, f, t); render(); });
  }

  // ----------------------------------------------------------- Footer editor
  function renderFooter(host, data, sync, render) {
    var list = el("div", "jed__cols");
    data.forEach(function (col, ci) {
      if (!Array.isArray(col.links)) col.links = [];
      var card = el("div", "jed__card jed__col");
      card.setAttribute("data-row", "");

      var head = el("div", "jed__cardhead");
      head.appendChild(makeHandle());
      head.appendChild(input("Column title, e.g. Shop", col.title, function (e) {
        col.title = e.target.value; sync();
      }));
      head.appendChild(removeBtn(function () { data.splice(ci, 1); render(); }, "Remove column"));
      card.appendChild(head);

      var linkList = el("div", "jed__list");
      col.links.forEach(function (link, li) {
        var row = el("div", "jed__row");
        row.setAttribute("data-row", "");
        row.appendChild(makeHandle());
        row.appendChild(input("Label", link.label, function (e) { link.label = e.target.value; sync(); }));
        row.appendChild(input("/path or https://…", link.href, function (e) { link.href = e.target.value; sync(); }));
        row.appendChild(removeBtn(function () { col.links.splice(li, 1); render(); }, "Remove link"));
        linkList.appendChild(row);
      });
      card.appendChild(linkList);
      card.appendChild(addBtn("Add link", function () {
        col.links.push({ label: "", href: "" }); render();
      }));
      sortable(linkList, function (f, t) { move(col.links, f, t); render(); });

      list.appendChild(card);
    });
    host.appendChild(list);
    host.appendChild(addBtn("Add column", function () {
      data.push({ title: "", links: [] }); render();
    }));
    sortable(list, function (f, t) { move(data, f, t); render(); });
  }

  // A fresh handle per row (nodes can't be shared across the DOM).
  function makeHandle() {
    var h = handle();
    h.setAttribute("data-handle", "");
    return h;
  }
})();
