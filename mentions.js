/* Vital City toolkit: media mentions, one definition for every tool.
 *
 * The growth dashboard, the press page's rail and the mentions page all show
 * the same list from the same nightly feed (growth/data.enc: news_mentions and
 * mentions_ledger, written by growth_pull.py). This file holds the only copy
 * of the rules: which hits count as a press mention, how each is tagged by the
 * way it uses Vital City, which government items are verified, and how a row
 * is drawn. Change them here and every tool changes together.
 *
 *   <script src="../mentions.js"></script>   (before the page's own script)
 *   vcMentions.press(data)    press mentions, each with ._kind
 *   vcMentions.gov(data)      { items, rejected, unverifiable }
 *   vcMentions.ledger(data)   { items, appearances, citations, last_audit }
 *   vcMentions.pressRow(p) / govRow(p) / ledgerRow(m)   one <li> each
 *   vcMentions.summary(items) the row of tag counts
 *
 * The stricter count of citations (no roundups, passing mentions or
 * duplicates) is a different thing: the impact ledger in Prospects.
 */
(function () {
  "use strict";

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  // How a press mention uses Vital City, read from the passage that names it
  // (mention_context), the title and the page check. Order matters: a
  // republished piece or a roundup is that first, whatever else it says.
  var KINDS = [
    { k: "work",      l: "Cites our work",       t: "Draws on a Vital City analysis, report, map or article" },
    { k: "people",    l: "Our people cited",     t: "A Vital City editor or researcher quoted, cited or described as a source" },
    { k: "repub",     l: "Republished",          t: "A Vital City piece run by another outlet" },
    { k: "event",     l: "Our event or podcast", t: "News made at a Vital City event or on its podcast" },
    { k: "writer",    l: "By our writer",        t: "A Vital City contributor writing elsewhere and pointing to their Vital City piece" },
    { k: "roundup",   l: "Roundup link",         t: "A link in a daily headlines post or newsletter briefing: distribution, not coverage" },
    { k: "named",     l: "Names us",             t: "Names Vital City without drawing on a piece, quoting its people or linking in a roundup" },
    { k: "unchecked", l: "Not yet checked",      t: "The page could not be read, so how it uses Vital City is unknown" }
  ];
  var KIND = {};
  KINDS.forEach(function (k) { KIND[k.k] = k; });

  var VC_PEOPLE = /\b(Elizabeth|Liz) Glazer|\bGlazer\b|Josh Greenman|\bGreenman\b|Greg Berman|Paul Reeping|Harry Siegel|Aaron Short/;

  function kindOf(p) {
    var c = String(p.mention_context || ""), t = String(p.title || "");
    if (/originally (published|appeared) (by|in|on) Vital City|from our partners at Vital City|in partnership with Vital City|part of Vital City.s (ongoing )?series|republished (with permission )?from Vital City/i.test(c)) return "repub";
    if (p.roundup || /\bheadlines\b|\bbriefing\b|round-?up|morning read|playbook|what we.re reading|links? of the day/i.test(t)) return "roundup";
    if (/(hosted by|podcast|forum|panel|town hall|conversation)[^.]{0,70}Vital City|Vital City[^.]{0,40}(podcast|forum|panel|event|discussion|conversation)/i.test(c)) return "event";
    if (/\b(as )?I (wrote|argued|noted|explained|showed)\b[^.]{0,60}Vital City|\b(my|our) (earlier |recent )?(piece|article|essay|column) (for|in) Vital City/i.test(c)) return "writer";
    if (VC_PEOPLE.test(c)) return "people";
    if (/\b(analysis|report|data|study|map|graphic|chart|article|story|piece|essay|series|survey|findings?|tracker|scorecard|graded|noted|found|shows?|showed|according to|wrote|writes|reported|deep dive|guide|interview|published|breakdown|put it|points? out|argued|argues)\b|\b(in|told) Vital City\b/i.test(c)) return "work";
    if (!c && p.verified !== true) return "unchecked";
    return c ? "named" : "unchecked";
  }

  // Subject, inferred from the words of the headline (counted double) and of
  // the passage that names Vital City. The feed carries no topic field, so this
  // is a reading of the listing, not of the article; a hand-logged entry such
  // as "Liz quoted" names no subject and lands in "other". Government and
  // politics is the fallback, used only when no policy subject matches, since
  // nearly every story this year names the mayor.
  var SUBJECTS = [
    { k: "jails", l: "Jails, courts and prosecution", re: /\b(rikers|jails?|incarcerat\w*|prisons?|courts?|judges?|prosecut\w*|district attorneys?|bail|raise the age|discovery law|parole|probation|sentenc\w*|correction officers?|solitary|department of correction|borough jails?|federal monitor|receiver(ship)?)\b/gi },
    { k: "policing", l: "Policing and public safety", re: /\b(nypd|n\.y\.p\.d\.?|police|policing|public safety|community safety|ice|immigration enforcement|officers?|cops?|tisch|strategic response group|stop-and-frisk|precincts?|commissioner|ccrb|overtime|gang database)\b/gi },
    { k: "crime", l: "Crime and violence", re: /\b(crimes?|criminal|shootings?|guns?|gun violence|firearms?|homicides?|murders?|assaults?|violen\w*|felon\w*|robber\w*|burglar\w*|shoplift\w*|victims?|retail theft|disorder|quality of life|recidivism|urinat\w*)\b/gi },
    { k: "health", l: "Mental health and drugs", re: /\b(mental(ly)? (health|ill\w*)|psychiatric|involuntar\w*|crisis response|b-heard|overdoses?|drugs?|opioids?|fentanyl|addiction|substance|cannabis|marijuana|naloxone|safe consumption|overdose prevention)\b/gi },
    { k: "homeless", l: "Homelessness", re: /\b(homeless\w*|shelters?|encampments?|unsheltered|supportive housing)\b/gi },
    { k: "housing", l: "Housing and land use", re: /\b(housing|rents?|rental|landlords?|tenants?|nycha|evictions?|apartments?|rent guidelines|rgb|rent freeze|zoning|rezon\w*|developers?|construction|basement)\b/gi },
    { k: "schools", l: "Schools and youth", re: /\b(schools?|education|students?|regents|teachers?|chalkbeat|youth|young people|teens?|syep|summer jobs?|cuny|colleges?|universit\w*|child ?care|kids|children|literacy|charter schools?)\b/gi },
    { k: "transit", l: "Transit and streets", re: /\b(subways?|mta|transit|bus(es)?|congestion pricing|traffic|bikes?|citi bike|e-bikes?|micromobility|e-mobility|streets?|pedestrians?|cars?|drivers?|vision zero|parking|trains?|railyard|sunnyside|waymos?|plows?|snow|walk\w*|curb\w*|outdoor dining)\b/gi },
    { k: "climate", l: "Climate and environment", re: /\b(climate|flood\w*|heat|cold|freezing|weather|sanitation|trash|garbage|rats?|environment\w*|energy|emissions|parks?)\b/gi },
    { k: "money", l: "Budget, jobs and the economy", re: /\b(budgets?|spending|taxe?s?|econom\w*|jobs|wages?|civil service|workforce|workers?|pensions?|fiscal|grocery|groceries|edc|affordab\w*|cost of living|poverty|income|contracts?|nonprofits?|minimum wage|labor|unions?|millionaires?|billionaires?|bailout|ngos?|philanthrop\w*)\b/gi },
    { k: "govt", l: "Government and politics", re: /\b(mamdani|adams|mayor\w*|city council|council members?|elections?|campaigns?|ballot|proposals?|hochul|albany|governors?|charter|cuomo|primary|voters?|polls?|trump|federal|shutdown|legislat\w*|bills?|government|city hall|speech\w*|administration|bureaucra\w*|permits?|efficien\w*|red tape|scorecard|100 days|just fix it|radical)\b/gi },
    { k: "other", l: "Subject not clear from the listing", re: null }
  ];
  var SUBJECT = {};
  SUBJECTS.forEach(function (s) { SUBJECT[s.k] = s; });
  // Words describing Vital City or its people, which say nothing about the
  // story's subject ("founder of the policy journal Vital City and a former
  // director of the Mayor's Office of Criminal Justice").
  var BIO = /(former )?(director|founder|editor|co-editor|managing editor|head)[^.;]{0,90}?Vital City[^.;,]{0,90}|Vital City, an? [^,.;]{0,90}|Mayor.s Office of Criminal Justice|(policy|civic|online|public policy) (journal|magazine|think tank|publication) Vital City|Vital City Forum/gi;
  var hits = function (s, re) { return (String(s).match(re) || []).length; };

  function subjectOf(p) {
    if (p._subj) { return p._subj; }
    var t = String(p.title || p.program || "").replace(/^(\w+day.s )?headlines\b[^:]*:?/i, "");
    var c = String(p.mention_context || p.note || p.snippet || "").replace(BIO, " ");
    var best = null, bs = 0;
    SUBJECTS.forEach(function (s) {
      if (!s.re || s.k === "govt") { return; }
      var n = 2 * hits(t, s.re) + hits(c, s.re);
      if (n > bs) { bs = n; best = s.k; }
    });
    if (!best) { best = (hits(t, SUBJECT.govt.re) + hits(c, SUBJECT.govt.re)) ? "govt" : "other"; }
    p._subj = best;
    return best;
  }

  // One name per outlet, so "NYTimes", "NY Times" and "Dana Rubinstein, New
  // York Times" group together. The row itself keeps the name as logged.
  var OUTLETS = [
    [/^(the )?(new york times|ny ?times|nyt)$/i, "The New York Times"],
    [/^(new york|ny) daily news( editorial board)?$/i, "New York Daily News"],
    [/^(new york|ny) post$/i, "New York Post"],
    [/^(new york magazine|ny mag|intelligencer)$/i, "New York Magazine"],
    [/^(the )?new yorker$/i, "The New Yorker"],
    [/^(the )?washington post$/i, "The Washington Post"],
    [/^city (&|and) state( new york| ny)?$/i, "City & State New York"],
    [/^(city limits|citylimits\.org)$/i, "City Limits"],
    [/^the city( reporter)?$/i, "The City Reporter"],
    [/faq nyc/i, "FAQ NYC"],
    [/^(amnewyork|amny)$/i, "amNewYork"],
    [/^politico/i, "Politico"],
    [/^streets ?blog ?usa$/i, "Streetsblog USA"],
    [/^streets ?blog( nyc| new york city)?$/i, "Streetsblog New York City"],
    [/ny1/i, "NY1"],
    [/^fox ?5/i, "FOX 5 New York"],
    [/^epi?c?center nyc$/i, "Epicenter NYC"],
    [/^w4?2?st/i, "W42ST"],
    [/^(ncja|national criminal justice association)/i, "National Criminal Justice Association"],
    [/brian lehrer|^wnyc/i, "WNYC"],
    [/^semafor/i, "Semafor"],
    [/^the bigger apple/i, "The Bigger Apple"]
  ];
  function outletName(s) {
    s = String(s || "").trim();
    for (var i = 0; i < OUTLETS.length; i++) { if (OUTLETS[i][0].test(s)) { return OUTLETS[i][1]; } }
    return "";
  }
  function outletOf(p) {
    var s = String(p.source || p.outlet || p.domain || "web").trim();
    var n = outletName(s);
    if (n) { return n; }
    var j = s.lastIndexOf(", ");                       // "Reporter Name, Outlet"
    if (j > 0) { var tail = s.slice(j + 2); return outletName(tail) || tail; }
    return s;
  }

  // Third-party press only (kind 'media'). Hits the page check rejected are
  // left out: named only in a related-story card or sidebar, not on the page
  // at all, or an author or section page. Roundups stay in, tagged.
  function press(data) {
    var news = (data && data.news_mentions) || [];
    return news.filter(function (it) {
      return it.kind === "media" && it.incidental !== true && it.verified !== false && !it.own_post
        && ["phrase not found on the page", "phrase present but used generically"].indexOf(it.verify_note) < 0
        && !/(?:^|, )Vital City$|^Story Archive|^(Public Safety|Criminal Justice) News\b|\| Page \d+ of \d+/.test(it.title || "");
    }).map(function (p) { p._kind = kindOf(p); return p; });
  }

  // Government bodies and policy institutions. Only items whose page was
  // fetched and checked count: "vital city" is ordinary English on exactly
  // these domains. "Could not fetch" (a site that blocks scripts) is counted
  // apart from "rejected", because it is unknown rather than disproven.
  function gov(data) {
    var news = (data && data.news_mentions) || [];
    var all = news.filter(function (it) { return it.kind === "gov" || it.kind === "republication"; });
    var items = all.filter(function (it) { return it.verified; });
    var unverifiable = all.filter(function (it) { return !it.verified && it.verify_note === "page could not be fetched"; }).length;
    return { items: items, unverifiable: unverifiable, rejected: all.length - items.length - unverifiable };
  }

  // Podcasts, radio and video, logged by hand (Google News does not index audio).
  function ledger(data) {
    var led = (data && data.mentions_ledger) || {};
    return { items: led.items || [], appearances: led.appearances || 0, citations: led.citations || 0, last_audit: led.last_audit || "" };
  }

  function day(p) { return String(p.published_iso || p.published || p.date || "").slice(0, 10); }

  function counts(items) {
    var c = {};
    items.forEach(function (p) { c[p._kind] = (c[p._kind] || 0) + 1; });
    return c;
  }

  function badge(k) {
    var d = KIND[k] || {};
    return '<span class="mbadge mb-' + esc(k) + '" title="' + esc(d.t || "") + '">' + esc(d.l || "") + "</span>";
  }

  function summary(items) {
    var c = counts(items);
    return KINDS.filter(function (k) { return c[k.k]; })
      .map(function (k) { return badge(k.k) + " " + c[k.k]; }).join(" &nbsp;");
  }

  function pressRow(p) {
    return '<li data-kind="' + esc(p._kind) + '">'
      + '<span class="src">' + esc(p.source || p.domain || "web") + "</span> " + badge(p._kind)
      + '<a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + esc(p.title) + "</a>"
      + '<span class="date">' + esc(day(p)) + "</span>"
      + (p.snippet ? '<div class="snip">' + esc(p.snippet) + "</div>" : "")
      + "</li>";
  }

  function govRow(p) {
    return "<li>"
      + '<span class="src">' + esc(p.source || p.domain || "web")
      + (p.kind === "gov" ? ' &middot; <i title="Government body">official</i>' : ' &middot; <i title="Policy institution republishing or citing our work">policy org</i>')
      + "</span>"
      + '<a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + esc(p.title) + "</a>"
      + '<span class="date">' + esc(day(p)) + "</span>"
      + (p.snippet ? '<div class="snip">' + esc(p.snippet) + "</div>" : "")
      + "</li>";
  }

  function ledgerRow(m) {
    return "<li>"
      + '<span class="src">' + esc(m.outlet || "") + ' &middot; <i title="' + (m.kind === "audio" ? "Audio, not indexed by Google News" : "Video, not indexed by Google News") + '">' + esc(m.kind || "") + "</i>"
      + (m.role === "citation" ? ' &middot; <i title="Someone else cited Vital City on the record">cited</i>' : "") + "</span>"
      + '<a href="' + esc(m.url) + '" target="_blank" rel="noopener">' + esc(m.program || m.outlet || "") + "</a>"
      + '<span class="date">' + esc(m.date || "") + "</span>"
      + '<div class="snip"><b>' + esc(m.who || "") + "</b>" + (m.note ? " &mdash; " + esc(m.note) : "") + "</div>"
      + "</li>";
  }

  window.vcMentions = {
    KINDS: KINDS, kindOf: kindOf, press: press, gov: gov, ledger: ledger,
    SUBJECTS: SUBJECTS, subjectOf: subjectOf, outletOf: outletOf,
    counts: counts, summary: summary, badge: badge, day: day,
    pressRow: pressRow, govRow: govRow, ledgerRow: ledgerRow
  };
})();
