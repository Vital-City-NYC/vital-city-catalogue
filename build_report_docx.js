// Vital City audience report -> .docx
// Built for Google Docs: US Letter, DXA column widths on both table and cells
// (PERCENTAGE breaks in Google Docs), ShadingType.CLEAR, no literal newlines.
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  ImageRun, PageOrientation, LevelFormat, convertInchesToTwip,
} = require("docx");

const A = JSON.parse(fs.readFileSync("/tmp/report_data.json", "utf8"));
const ASSETS = "/tmp/vc_report_assets";

const BLACK = "050507", CHARCOAL = "707175", CLOUD = "DDDDDD";
const GREEN = "3E8233", CERULEAN = "1A6597", MAGENTA = "C43458";
const CONTENT = 9360;          // 12240 letter - 2x1440 margins, in DXA
const FONT = "Helvetica Neue";

const img = (file, wPx, hPx) => new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 160, after: 80 },
  children: [new ImageRun({
    type: "png",
    data: fs.readFileSync(path.join(ASSETS, file)),
    transformation: { width: wPx, height: hPx },
  })],
});

const cap = (t) => new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { after: 220 },
  children: [new TextRun({ text: t, size: 16, italics: true, color: CHARCOAL, font: FONT })],
});

const h1 = (t) => new Paragraph({
  heading: HeadingLevel.HEADING_1, spacing: { before: 360, after: 140 },
  children: [new TextRun({ text: t, bold: true, size: 30, color: BLACK, font: FONT })],
});
const h2 = (t) => new Paragraph({
  heading: HeadingLevel.HEADING_2, spacing: { before: 260, after: 100 },
  children: [new TextRun({ text: t, bold: true, size: 24, color: CERULEAN, font: FONT })],
});

// rich paragraph: array of [text, {bold?}] pairs
const p = (parts, opts = {}) => new Paragraph({
  spacing: { after: opts.after ?? 140, line: 300 },
  children: (Array.isArray(parts) ? parts : [[parts]]).map(
    ([t, o = {}]) => new TextRun({
      text: t, bold: !!o.b, italics: !!o.i, font: FONT,
      size: opts.size ?? 21, color: o.color ?? BLACK,
    })),
});

const bullet = (parts) => new Paragraph({
  numbering: { reference: "vc-bullets", level: 0 },
  spacing: { after: 90, line: 290 },
  children: (Array.isArray(parts) ? parts : [[parts]]).map(
    ([t, o = {}]) => new TextRun({ text: t, bold: !!o.b, italics: !!o.i, font: FONT, size: 21, color: o.color ?? BLACK })),
});

// Callout: a shaded single-cell table (paragraph borders can't shade a block)
const callout = (runs, fill = "F5F7F4", bar = GREEN) => new Table({
  columnWidths: [CONTENT],
  borders: {
    top: { style: BorderStyle.NONE }, bottom: { style: BorderStyle.NONE },
    right: { style: BorderStyle.NONE }, insideHorizontal: { style: BorderStyle.NONE },
    insideVertical: { style: BorderStyle.NONE },
    left: { style: BorderStyle.SINGLE, size: 18, color: bar },
  },
  rows: [new TableRow({
    children: [new TableCell({
      width: { size: CONTENT, type: WidthType.DXA },
      shading: { type: ShadingType.CLEAR, fill, color: "auto" },
      margins: { top: 160, bottom: 160, left: 200, right: 200 },
      children: [new Paragraph({
        spacing: { line: 300 },
        children: runs.map(([t, o = {}]) => new TextRun({
          text: t, bold: !!o.b, font: FONT, size: 21, color: o.color ?? BLACK })),
      })],
    })],
  })],
});

// Data table with a header row. cols = array of widths summing to CONTENT.
function table(headers, rows, cols, aligns = []) {
  const cell = (text, { header = false, align = AlignmentType.LEFT, w, bold = false }) =>
    new TableCell({
      width: { size: w, type: WidthType.DXA },
      shading: header ? { type: ShadingType.CLEAR, fill: "EFEFEC", color: "auto" }
                      : { type: ShadingType.CLEAR, fill: "FFFFFF", color: "auto" },
      margins: { top: 90, bottom: 90, left: 130, right: 130 },
      children: [new Paragraph({
        alignment: align,
        children: [new TextRun({
          text: String(text), bold: header || bold, font: FONT, size: 20,
          color: header ? CHARCOAL : BLACK })],
      })],
    });
  return new Table({
    columnWidths: cols,
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: CLOUD },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: CLOUD },
      left: { style: BorderStyle.NONE }, right: { style: BorderStyle.NONE },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: CLOUD },
      insideVertical: { style: BorderStyle.NONE },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((h, i) =>
          cell(h, { header: true, w: cols[i], align: aligns[i] ?? AlignmentType.LEFT })),
      }),
      ...rows.map(r => new TableRow({
        children: r.map((c, i) => {
          const isObj = c && typeof c === "object" && !Array.isArray(c);
          return cell(isObj ? c.t : c, {
            w: cols[i], align: aligns[i] ?? AlignmentType.LEFT, bold: isObj ? !!c.b : false });
        }),
      })),
    ],
  });
}

const spacer = (h = 120) => new Paragraph({ spacing: { after: h }, children: [] });

const kids = [];
// ── title block
kids.push(new Paragraph({
  spacing: { after: 40 },
  children: [new TextRun({ text: "VITAL CITY", bold: true, size: 19, color: BLACK,
                           font: FONT, characterSpacing: 60 })],
}));
kids.push(new Paragraph({
  spacing: { after: 60 },
  children: [new TextRun({ text: "Reader acquisition and audience growth", bold: true, size: 40, color: BLACK, font: FONT })],
}));
kids.push(new Paragraph({
  spacing: { after: 40 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: "DDE44C" } },
  children: [new TextRun({ text: `2026 year to date  ·  data through ${A.asofLong} (${A.doy} days)`,
                           size: 21, color: CHARCOAL, font: FONT })],
}));
kids.push(spacer(220));

kids.push(callout([
  ["The short version. ", { b: true }],
  ["Reach is growing strongly and the growth is high quality — search rankings are improving, not just traffic volume. The newsletter list is now "],
  ["cleaner and more accurate", { b: true }],
  [" than it was a year ago, after bot signups were removed. The single biggest opportunity is converting the large new audience into subscribers."],
]));
kids.push(spacer(200));

// ── headline table
kids.push(h2("At a glance"));
kids.push(table(
  ["Measure", "2026 year to date", "Direction"],
  [
    ["Website visitors", `${A.visitors} (~${A.pace} annualized)`, { t: "+30% pace vs 2025", b: true }],
    ["Search clicks per day", `${A.c28} in last 28 days (year avg ${A.c365})`, { t: "~2x accelerating", b: true }],
    ["Newsletter list", `${A.list} (after bot cleanup)`, { t: "Cleaner, still growing", b: true }],
    ["Organic signups", `${A.organic} (July best month at ${A.julyOrganic})`, { t: "Steady, improving", b: true }],
    ["Visitor to subscriber", A.convPct, { t: "The opportunity", b: true }],
  ],
  [2600, 4260, 2500]));
kids.push(spacer(200));

// ── 1 reach
kids.push(h1("1.  Reach: strong, and accelerating"));
kids.push(p([["Website visitors have grown every year since tracking began. "],
             [`${A.visitors} people have visited so far this year`, { b: true }],
             [`, tracking to about `], [`${A.pace}`, { b: true }],
             [` — roughly `], ["+30%", { b: true }], [" against 2025."]]));
kids.push(img("01-visitors-by-year.png", 620, 286));
kids.push(cap("Unique visitors by year. The 2026 bar shows actual visitors to date plus the projected remainder. Source: Google Analytics 4."));

kids.push(h2("The June step change"));
kids.push(p([["Traffic ran 8,000–13,000 a week through May and mid-June, then "],
             ["stepped up to 18,000–23,000 from the week of June 22 and has held there for six straight weeks", { b: true }],
             [". That is a level change, not a spike — and it begins exactly when the six-month Mamdani package published."]]));
kids.push(img("02-weekly-visitors.png", 620, 277));
kids.push(cap("Weekly visitors, March through July 2026. Source: Google Analytics 4."));

// ── 2 drivers
kids.push(h1("2.  What is driving it"));
kids.push(h2("Driver one: search rankings are improving"));
kids.push(p([["This is the most durable finding in the data. Vital City is being "], ["shown", { i: true }],
             [" less often but ranking "], ["better", { i: true }],
             [", and better rank converts far more efficiently than raw exposure. Daily search clicks have roughly doubled while impressions have fallen."]]));
kids.push(table(
  ["", "Last 365 days", "Last 90 days", "Last 28 days"],
  [
    ["Clicks per day", A.c365, A.c90, { t: A.c28, b: true }],
    ["Impressions per day", A.i365, A.i90, A.i28],
    ["Average position", A.pos365, A.pos90, { t: A.pos28, b: true }],
    ["Click-through rate", A.ctr365, A.ctr90, { t: A.ctr28, b: true }],
  ],
  [2760, 2200, 2200, 2200],
  [AlignmentType.LEFT, AlignmentType.RIGHT, AlignmentType.RIGHT, AlignmentType.RIGHT]));
kids.push(spacer(140));
kids.push(img("03-search-acceleration.png", 620, 277));
kids.push(cap("Search clicks per day (bars, left axis) against impressions per day (line, right axis). Source: Google Search Console."));
kids.push(p([["Average position improved from "], [`${A.pos365} to ${A.pos28}`, { b: true }],
             [" and click-through nearly tripled, from "], [`${A.ctr365} to ${A.ctr28}`, { b: true }],
             [". This compounds quietly and does not depend on a news cycle."]]));

kids.push(h2("Driver two: Mamdani accountability coverage"));
kids.push(p([["Six of the top seven pages this year are Mamdani pieces. "],
             [`Seven pieces account for ${A.mamVisitors} visitors — ${A.mamShare} of all traffic this year.`, { b: true }]]));
kids.push(img("04-top-pieces.png", 620, 310));
kids.push(cap("Most-read pieces of 2026 by unique visitors. Source: Google Analytics 4."));
kids.push(p([["The scheduled-accountability format is the reliable performer: "], ["100 days", { b: true }], [", "],
             ["six months", { b: true }], [", "], ["what has he done so far", { b: true }],
             [". The two six-month pieces published July 1 and 2 are the two biggest pages of the year."]]));

// ── 3 newsletter
kids.push(h1("3.  The newsletter: a cleaner, truer list"));
kids.push(p([["Last year's signup numbers included bot signups", { b: true }],
             [", which reframes the year-over-year comparison entirely. The pattern is visible in the data: monthly additions ran at about "],
             [`${A.base} a month`, { b: true }],
             [" through April 2025, then jumped sharply for five months before collapsing back to normal in October."]]));
kids.push(img("05-2025-surge.png", 620, 277));
kids.push(cap("Monthly net additions to the list, 2025. Source: Mailchimp growth history."));
kids.push(p([["May through September 2025 added "], [`${A.surge}`, { b: true }],
             [` — roughly `], [`${A.excess} above`, { b: true }],
             [" the organic baseline. Genuine election-driven interest would have peaked in October and November, ahead of the general election. It did the opposite."]]));

kids.push(h2("The list has since been cleaned, and real growth is improving"));
kids.push(p([["Monthly removals run 42–108 in a normal month. In "], ["May 2026, 575 were removed", { b: true }],
             [" in a deliberate cleanup. So the list moving from a peak of 11,114 in April to "],
             [`${A.list} today is not shrinkage — it is hygiene.`, { b: true }],
             [" The current number represents real people more accurately than the April peak did."]]));
kids.push(img("06-signups-and-cleanup.png", 620, 261));
kids.push(cap("Left: organic website signups, 2026. Right: subscribers removed from the list each month. Sources: Ghost, Mailchimp."));
kids.push(callout([
  ["Bottom line on the newsletter. ", { b: true }],
  ["The apparent decline against 2025 is an artifact of comparing real humans to humans plus bots. On a like-for-like basis the list is healthier, more accurate and still growing — "],
  [`${A.organic} organic signups so far this year, and July was the strongest month at ${A.julyOrganic}.`, { b: true }],
], "F2F7F1", GREEN));
kids.push(spacer(200));

// ── 4 engagement
kids.push(h1("4.  Engagement"));
kids.push(table(
  ["", "2026 year to date", "Same period 2025"],
  [
    ["Sends", A.sends, A.sendsPrev],
    ["Open rate", A.openPct, A.openPctPrev],
    ["Click rate", A.clickPct, A.clickPctPrev],
    [{ t: "Total opens", b: true }, { t: `~${A.opens}`, b: true }, `~${A.opensPrev}`],
    [{ t: "Total clicks", b: true }, `~${A.clicks}`, `~${A.clicksPrev}`],
  ],
  [3360, 3000, 3000],
  [AlignmentType.LEFT, AlignmentType.RIGHT, AlignmentType.RIGHT]));
kids.push(spacer(160));
kids.push(p([["Total opens are up ", ], [`${A.opensDelta}`, { b: true }],
             [" — more people are reading Vital City by email than a year ago. Rate declines should be read carefully: Apple Mail's privacy feature inflates older open rates, and bot accounts sitting on the list depressed 2026 rates before the cleanup. With a cleaner list these rates should read truer from here. Total clicks are essentially flat ("],
             [`${A.clicksDelta}`, { b: true }], ["), which is the metric to watch as the cleanup settles."]]));

// ── 5 opportunity
kids.push(h1("5.  The opportunity: converting the new audience"));
kids.push(p([[`${A.visitors} visitors produced ${A.organic} organic signups — about `],
             [`${A.convPct}`, { b: true }],
             [". Traffic grew 30% while subscriber acquisition stayed close to flat. That gap is the clearest upside in the business."]]));
kids.push(p([["One detail points at the fix: "],
             ["the homepage is the single largest source of signups (21 of 900 attributed), ahead of any article", { b: true }],
             [". Most search visitors land directly on an article, read it and leave. The subscribe ask is strongest where the traffic is not."]]));
kids.push(table(
  ["Where signups come from", "Signups", "Share"],
  [
    ["Direct / unknown", "486", "54%"],
    ["Search", "166", "18%"],
    ["Academic outreach", "88", "10%"],
    ["Social", "47", "5%"],
    ["Email", "38", "4%"],
  ],
  [4360, 2500, 2500],
  [AlignmentType.LEFT, AlignmentType.RIGHT, AlignmentType.RIGHT]));
kids.push(spacer(140));
kids.push(p([["900 attributed signup events since February 5. A 54% direct/unknown share limits what can be concluded; among traceable signups, search leads — consistent with the traffic picture."]]));

// ── 6 what to do
kids.push(h1("6.  What the data suggests"));
kids.push(bullet([["Conversion is the highest-leverage move. ", { b: true }],
  [`Acquisition is solved; roughly 20,000 weekly visitors converting at ${A.convPct} is the constraint. The gap between article traffic and homepage-dominated signups points at the in-article ask as the place to test.`]]));
kids.push(bullet([["The accountability franchise is proven. ", { b: true }],
  ["100 days and six months were the two biggest traffic events of the year. A one-year piece is the obvious next beat."]]));
kids.push(bullet([["Search rank is compounding. ", { b: true }],
  [`Position ${A.pos365} to ${A.pos28} nearly doubled daily clicks on fewer impressions. The page-two opportunity list on the dashboard (rat control at 138k annual impressions, Tammany Hall at 102k) is the cheapest growth still available.`]]));
kids.push(bullet([["Watch click rate as the cleanup settles. ", { b: true }],
  ["With bots removed, engagement rates should be read fresh from here rather than against contaminated 2025 baselines."]]));

// ── methodology
kids.push(h1("Methodology, sources and confidence"));
kids.push(p([["Sources. ", { b: true }],
  ["Google Analytics 4 (visitors, page views, per-piece traffic); Google Search Console (clicks, impressions, position, click-through); Mailchimp (list size, sends, open and click rates, growth history); Ghost (organic signup dates and attribution); the Vital City catalogue export (publication dates, titles). All figures are as of "],
  [A.asof], [" and were read from the published growth-dashboard payload."]]));
kids.push(p([["How the key numbers are derived.", { b: true }]], { after: 60 }));
kids.push(bullet([["Annualized traffic", { i: true }], [` = year-to-date visitors ÷ ${A.doy} days × 365. A projection, not a measurement.`]]));
kids.push(bullet([["Organic signups", { i: true }], [" = Ghost member signup dates, counted the day they happened, not reduced by later unsubscribes and excluding bulk additions."]]));
kids.push(bullet([["Total opens and clicks", { i: true }], [" = each send's rate × its recipients, summed. Mailchimp reports rates, not raw totals."]]));
kids.push(bullet([["Implied removals", { i: true }], [" = net additions minus the actual change in list size that month."]]));
kids.push(spacer(80));
kids.push(p([["Confidence.", { b: true }]], { after: 60 }));
kids.push(bullet([["High: ", { b: true }], ["traffic growth, search acceleration and rank improvement, per-piece performance, list size, send counts, unsubscribe counts. Direct measurements."]]));
kids.push(bullet([["Medium: ", { b: true }], [`the conversion rate. Ghost signup capture only became reliable around April 2026, so early-year organic signups are undercounted and the true rate is somewhat higher than ${A.convPct}.`]]));
kids.push(bullet([["Medium: ", { b: true }], [`the scale of bot contamination. That bots signed up is established; exactly how many, and precisely which months, is not separable from the growth history alone. The ${A.excess} above-baseline figure is an estimate of the anomaly, not a verified bot count.`]]));
kids.push(spacer(80));
kids.push(p([["Known limits.", { b: true }]], { after: 60 }));
kids.push(bullet([["Google Analytics counts browsers, not people. Someone reading on a phone and a laptop counts twice, so visitor figures are directional rather than a headcount."]]));
kids.push(bullet([["54% of signups carry no usable attribution source."]]));
kids.push(bullet([["The 30-day active-subscriber measure is currently unavailable: Mailchimp does not report per-member opens for A/B split-test sends, and every recent newsletter was an A/B test. Total clicks is used as the engagement measure instead."]]));
kids.push(bullet([["2026 is a year in progress. Year-over-year comparisons use the same calendar window on both sides."]]));
kids.push(spacer(140));
kids.push(new Paragraph({
  border: { top: { style: BorderStyle.SINGLE, size: 4, color: CLOUD } },
  spacing: { before: 120, after: 0 }, children: [],
}));
kids.push(p([[`Prepared from the Vital City growth dashboard · figures as of ${A.asofLong} · prepared with AI assistance; every figure traces to a named source above, and the bot-contamination scale is flagged as an estimate rather than a measurement.`,
              { color: CHARCOAL }]], { size: 17 }));

const doc = new Document({
  numbering: {
    config: [{
      reference: "vc-bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: convertInchesToTwip(0.18) } } },
      }],
    }],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 12240, height: 15840, orientation: PageOrientation.PORTRAIT },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      },
    },
    children: kids,
  }],
});

Packer.toBuffer(doc).then(buf => {
  const out = process.argv[2];
  fs.writeFileSync(out, buf);
  console.log(`wrote ${out} (${buf.length.toLocaleString()} bytes)`);
});
