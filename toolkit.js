/* The Vital City toolkit — one nav, one registry, every page.
 *
 * Each tool used to hand-maintain its own <nav class="toolnav">, which is why
 * the catalogue listed three tools, growth and contacts listed four, and the
 * catalogue analysis listed none. Adding a tool meant editing every page and
 * missing one. The list below is now the only place a tool is declared.
 *
 * Usage, from any page at any depth:
 *   <link rel="stylesheet" href="../toolkit.css">
 *   <script src="../toolkit.js" data-tool="growth" defer></script>
 * The script finds its own directory from its src, so relative depth is not
 * something a page has to get right. It mounts into [data-toolkit-nav] if the
 * page provides one, otherwise it prepends itself to <body>.
 */
(function () {
  "use strict";

  // Not listed: catalogue-analysis (reached from the catalogue page itself) and
  // growth/live (a phone app, not a desk tool).
  var TOOLS = [
    { id: "catalogue",  label: "Catalogue",  path: "catalogue/",         gated: true,  data: "data/meta.json",
      blurb: "Every piece Vital City has published, searchable by author, topic, issue and date, with readership and contributor contacts." },
    { id: "growth",     label: "Growth",     path: "growth/",            gated: true,  data: "growth/data.enc",
      blurb: "The newsletter list, signups, sends, site traffic and giving, with the ten key indicators and the weekly report." },
    { id: "contacts",   label: "Contacts",   path: "network/",           gated: true,  data: "network/data.enc",
      blurb: "Everyone in Vital City's orbit: subscribers, contributors, press, funders and donors, searchable and exportable." },
    { id: "prospects",  label: "Prospects",  path: "prospects/",         gated: true,  data: "prospects/data.enc",
      blurb: "Foundations and individual donors worth approaching, ranked by the evidence in our own data." },
    { id: "press",      label: "Press",      path: "press/",             gated: true,  data: "press/data.enc",
      blurb: "Who covers New York City government: reporters, the beats their own bylines prove, and how to reach them." },
    // A document, not a nightly dataset: "static" keeps the home page from
    // calling it stale. Rebuilt by build_manual.py whenever the source changes.
    { id: "manual",     label: "Manual",     path: "manual/",            gated: true,  data: "manual/data.enc", static: true,
      blurb: "How the website works: plain steps for arranging vitalcitynyc.org in Ghost, and what only Obox can change." },
    // One tab, two views: the city's calendar and the archive pieces worth
    // reposting against it. The bar shows "Calendar"; on either page the two
    // views appear beside it so you can switch without leaving the tab.
    { id: "calendar",   label: "Calendar",   gated: false,
      href: "https://vitalcity-nyc.github.io/nyc-policy-calendar/",
      blurb: "The New York City calendar and the archive pieces worth reposting against it.",
      views: [
        { id: "calendar",  label: "City calendar",   href: "https://vitalcity-nyc.github.io/nyc-policy-calendar/", gated: false,
          dataHref: "https://vitalcity-nyc.github.io/nyc-policy-calendar/data/events.json",
          blurb: "Hearings, budget dates, anniversaries, books and city life, sized by how much they matter." },
        { id: "resharing", label: "What to reshare", path: "resharing/", gated: true, data: "resharing/data.enc",
          blurb: "Which archive piece to post, and when, bound to the calendar's real dates." }
      ] }
  ];

  // The right end of each page's confidential strip says when its data was
  // built, in one wording and AP date style on every tool.
  var AP_MON = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."];
  function apDate(v) {
    var d = v instanceof Date ? v : new Date(String(v || "").length === 10 ? v + "T12:00:00" : v);
    if (isNaN(d)) { return String(v || ""); }
    return AP_MON[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear();
  }
  window.vcApDate = apDate;

  // The installable app: one offline worker for the whole toolkit, registered
  // from every page. It changes nothing on screen; see sw.js.
  try {
    if ("serviceWorker" in navigator && location.protocol === "https:") {
      var swBase = (document.currentScript && document.currentScript.src || "").replace(/[^/]*$/, "");
      if (swBase) { navigator.serviceWorker.register(swBase + "sw.js", { scope: swBase }).catch(function () {}); }
    }
  } catch (e) {}
  window.vcTools = TOOLS;
  window.vcStamp = function (el, when, extra) {
    if (typeof el === "string") { el = document.querySelector(el); }
    if (!el || !when) { return; }
    el.textContent = "Updated " + apDate(when) + (extra ? " \u00b7 " + extra : "");
  };

  function base() {
    var s = document.currentScript;
    if (!s) {
      var all = document.getElementsByTagName("script");
      for (var i = all.length - 1; i >= 0; i--) {
        if (/toolkit\.js(\?|$)/.test(all[i].src)) { s = all[i]; break; }
      }
    }
    return s ? s.src.replace(/[^/]*$/, "") : "./";
  }

  function build(current, root) {
    var nav = document.createElement("nav");
    nav.className = "vckit";
    nav.setAttribute("aria-label", "Vital City toolkit");

    var mark = document.createElement("a");
    mark.className = "vckit-mark";
    mark.href = root;
    mark.innerHTML = '<span class="vckit-vc">Vital City</span><span class="vckit-tk">toolkit</span>';
    nav.appendChild(mark);

    var list = document.createElement("div");
    list.className = "vckit-list";

    TOOLS.forEach(function (t) {
      var inGroup = !!(t.views && t.views.some(function (v) { return v.id === current; }));
      var here = t.id === current || inGroup;
      var exact = t.id === current && !t.views;          // the tab is this very page
      var a = document.createElement(exact ? "span" : "a");
      a.className = "vckit-link" + (here ? " here" : "");
      if (!exact) { a.href = t.href || (root + t.path); }
      if (here) { a.setAttribute("aria-current", "page"); }
      // Six of the eight tools are gated, so a dot on each said almost nothing
      // and put a row of specks across the bar. The tooltip still says it.
      a.title = t.blurb + (t.gated ? " Passphrase required." : "");
      a.appendChild(document.createTextNode(t.label));
      list.appendChild(a);
      if (inGroup) {
        var sub = document.createElement("span");
        sub.className = "vckit-views";
        t.views.forEach(function (v) {
          var on = v.id === current;
          var b = document.createElement(on ? "span" : "a");
          b.className = "vckit-view" + (on ? " on" : "");
          if (!on) { b.href = v.href || (root + v.path); }
          b.title = v.blurb + (v.gated ? " Passphrase required." : "");
          b.appendChild(document.createTextNode(v.label));
          sub.appendChild(b);
        });
        list.appendChild(sub);
      }
    });

    nav.appendChild(list);

    // Page utilities (how it works, print, theme, lock) ride at the right end
    // of the same bar. They used to float over the title as a second row of
    // links; one bar carries navigation left, page controls right.
    var utils = document.querySelector(".mastlinks");
    if (utils) { utils.classList.add("vckit-utils"); nav.appendChild(utils); }

    return nav;
  }

  function mount() {
    var script = document.querySelector('script[data-tool]');
    var current = script ? script.getAttribute("data-tool") : "";
    var nav = build(current, base());
    var slot = document.querySelector("[data-toolkit-nav]");
    if (slot) { slot.appendChild(nav); }
    else { document.body.insertBefore(nav, document.body.firstChild); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
