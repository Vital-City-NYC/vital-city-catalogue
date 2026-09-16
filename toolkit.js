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
    { id: "catalogue",  label: "Catalogue",  path: "",                   gated: false,
      blurb: "Every piece published on vitalcitynyc.org, searchable by author, topic, issue and date." },
    { id: "growth",     label: "Growth",     path: "growth/",            gated: true,
      blurb: "Audience, signups, sends and traffic." },
    { id: "contacts",   label: "Contacts",   path: "network/",           gated: true,
      blurb: "The people database: contributors, press, funders, members, donors." },
    { id: "prospects",  label: "Prospects",  path: "prospects/",         gated: true,
      blurb: "Funder and donor prospecting." },
    { id: "resharing",  label: "Resharing",  path: "resharing/",         gated: true,
      blurb: "Which archive piece to post, and when — bound to the calendar's real dates." },
    { id: "press",      label: "Press",      path: "press/",             gated: true,
      blurb: "Who covers New York City government: reporters, the beats their own bylines prove, and how to reach them." },
    { id: "calendar",   label: "Calendar",   gated: false,
      href: "https://vitalcity-nyc.github.io/nyc-policy-calendar/",
      blurb: "The New York City calendar: hearings, budget dates, anniversaries, books, city life." }
  ];

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
      var here = t.id === current;
      var a = document.createElement(here ? "span" : "a");
      a.className = "vckit-link" + (here ? " here" : "");
      if (!here) { a.href = t.href || (root + t.path); }
      if (here) { a.setAttribute("aria-current", "page"); }
      // Six of the eight tools are gated, so a dot on each said almost nothing
      // and put a row of specks across the bar. The tooltip still says it.
      a.title = t.blurb + (t.gated ? " Passphrase required." : "");
      a.appendChild(document.createTextNode(t.label));
      list.appendChild(a);
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
