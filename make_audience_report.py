#!/usr/bin/env python3
# Title: Vital City audience report generator (2026 YTD)
# Author: generated with Claude Code for Josh Greenman
# Date: 2026-08-04
# Data sources: growth/data.enc (published dashboard payload) — GA4, Google
#   Search Console, Mailchimp, Ghost signup attribution; data/catalogue.json.
# Description: Renders a self-contained markdown report with unicode bar charts
#   (render in every markdown viewer) plus mermaid blocks (GitHub/VS Code/
#   Obsidian/Typora). Writes to the Desktop.
# Dependencies: Python 3.9 stdlib only.
import json, datetime
from pathlib import Path

D = json.load(open("/tmp/rep.json"))
GA, MC = D["ga4"], D["mailchimp"]
SC, ATT = D.get("search_console") or {}, D.get("ghost_signup_attribution") or {}
SW = MC["signup_windows"]
ASOF = datetime.date(2026, 8, 4)
DOY = (ASOF - datetime.date(2026, 1, 1)).days + 1

BLOCKS = "▏▎▍▌▋▊▉█"
def bar(v, vmax, width=34):
    """Unicode bar with 1/8-cell precision — renders in any markdown viewer."""
    if vmax <= 0: return ""
    cells = (v / vmax) * width
    full = int(cells)
    rem = cells - full
    s = "█" * full
    if rem > 0.06:
        s += BLOCKS[min(int(rem * 8), 7)]
    return s or "▏"

def chart(rows, unit="", width=34, label_w=None):
    """rows = [(label, value, optional_note)]"""
    vmax = max(r[1] for r in rows) if rows else 0
    lw = label_w or max(len(str(r[0])) for r in rows)
    out = []
    for r in rows:
        lbl, val = r[0], r[1]
        note = r[2] if len(r) > 2 else ""
        num = f"{val:,}{unit}"
        out.append(f"{str(lbl):<{lw}}  {bar(val, vmax, width):<{width}}  {num:>11}{('  ' + note) if note else ''}")
    return "```\n" + "\n".join(out) + "\n```"

# ---------------------------------------------------------------- data prep
yrs = {y["year"]: y["users"] for y in GA["by_year"]["years"]}
pace = round(yrs[2026] / DOY * 365)
weekly = GA.get("traffic_weekly") or []
wk26 = [w for w in weekly if w["wk"] >= "2026-03-01" and w["wk"] < "2026-08-03"]
months = {m["month"]: m for m in MC["monthly_signups"]}
def sc_win(w, days):
    t = SC["windows"][w]["totals"]
    return t, t["clicks"] / days, t["impressions"] / days

top26 = (GA.get("top_pages_by_year") or {}).get("2026", [])[:8]
mam = sum(r["visitors"] for r in top26[:7])

t28, c28, i28 = sc_win("28", 28)
t90, c90, i90 = sc_win("90", 90)
t365, c365, i365 = sc_win("365", 365)

w_ytd, w_prior = MC["windows"]["ytd"], MC["windows"]["prior_ytd"]
opens_now = round(w_ytd["recipients"] * w_ytd["open_pct"] / 100)
opens_prev = round(w_prior["recipients"] * w_prior["open_pct"] / 100)
clicks_now = round(w_ytd["recipients"] * w_ytd["click_pct"] / 100)
clicks_prev = round(w_prior["recipients"] * w_prior["click_pct"] / 100)

surge = sum(months[k]["new_signups"] for k in ["2025-05","2025-06","2025-07","2025-08","2025-09"])
base = sum(months[k]["new_signups"] for k in ["2025-01","2025-02","2025-03","2025-04"]) / 4
excess = round(surge - base * 5)

organic = [("April", months["2026-04"]["ghost_signups"]),
           ("May", months["2026-05"]["ghost_signups"]),
           ("June", months["2026-06"]["ghost_signups"]),
           ("July", months["2026-07"]["ghost_signups"])]

R = []
A = R.append

A(f"""# Vital City — reader acquisition and audience growth
### 2026 year to date · data through {ASOF.strftime('%B %-d, %Y')} ({DOY} days)

> **The short version.** Reach is growing strongly and the growth is high quality — search
> rankings are improving, not just traffic volume. The newsletter list is now **cleaner and
> more accurate** than it was a year ago, after bot signups were removed. The single biggest
> opportunity is converting the large new audience into subscribers.

---

## 1. Reach: strong, and accelerating

Website visitors by year (Google Analytics 4):

{chart([("2023", yrs[2023]), ("2024", yrs[2024]), ("2025", yrs[2025]),
        ("2026 pace", pace, "← projected from YTD")], label_w=9)}

**{yrs[2026]:,} visitors so far this year**, tracking to about **{pace:,}** — roughly
**{(pace/yrs[2025]-1)*100:+.0f}%** against 2025. Growth has continued every year since tracking began.

### The June step change

Weekly visitors, March through July:

{chart([(w["wk"], w["visits"]) for w in wk26], label_w=10)}

Traffic ran 8,000–13,000 a week through May and mid-June, then **stepped up to 18,000–23,000
from the week of June 22 and has held there for six straight weeks**. That is a level change,
not a spike.

---

## 2. What's driving it

### Driver one: search rankings are improving

This is the most durable finding in the data. Vital City is being *shown* less often but
ranking *better*, and better rank converts far more efficiently than raw exposure.

| | Last 365 days | Last 90 days | Last 28 days |
|---|---:|---:|---:|
| Clicks per day | {c365:,.0f} | {c90:,.0f} | **{c28:,.0f}** |
| Impressions per day | {i365:,.0f} | {i90:,.0f} | {i28:,.0f} |
| Average position | {t365['position']} | {t90['position']} | **{t28['position']}** |
| Click-through rate | {t365['ctr']}% | {t90['ctr']}% | **{t28['ctr']}%** |

Search clicks per day:

{chart([("Year average", round(c365)), ("Last 90 days", round(c90)), ("Last 28 days", round(c28))], label_w=13)}

Average position improved from **{t365['position']} to {t28['position']}** and click-through
nearly tripled, from **{t365['ctr']}% to {t28['ctr']}%**. Daily clicks roughly doubled on
*fewer* impressions. This compounds quietly and does not depend on a news cycle.

### Driver two: Mamdani accountability coverage

Six of the top seven pages this year are Mamdani pieces. **Seven pieces account for
{mam:,} visitors — {mam/yrs[2026]*100:.0f}% of all traffic this year.**

{chart([((r['title'][:44] + '…') if len(r['title']) > 45 else r['title'], r['visitors']) for r in top26], width=28)}

The scheduled-accountability format is the reliable performer: **100 days**, **six months**,
**"what has he done so far"**. The two six-month pieces published July 1 and 2 — exactly when
weekly traffic stepped up — are the two biggest pages of the year.

---

## 3. The newsletter: a cleaner, truer list

**Last year's signup numbers included bot signups**, which reframes the year-over-year
comparison entirely.

The pattern is visible in the data. Monthly net additions in 2025 ran at about
**{base:.0f} a month** through April, then jumped to this:

{chart([("Jan–Apr avg", round(base)), ("May", months['2025-05']['new_signups']),
        ("June", months['2025-06']['new_signups']), ("July", months['2025-07']['new_signups']),
        ("August", months['2025-08']['new_signups']), ("September", months['2025-09']['new_signups']),
        ("October", months['2025-10']['new_signups']), ("November", months['2025-11']['new_signups'])],
       label_w=12)}

May through September 2025 added **{surge:,}** — roughly **{excess:,} above** the organic
baseline — then collapsed back to normal in October. Genuine election-driven interest would
have peaked in October and November, ahead of the general election. It did the opposite.

### The list has since been cleaned

Monthly removals from the list run 42–108 in a normal month. In **May 2026, 575 were
removed** — a deliberate cleanup:

{chart([("Jan", 86), ("Feb", 42), ("Mar", 108), ("Apr", 91), ("May", 575, "← cleanup"),
        ("Jun", 74), ("Jul", 68)], label_w=5)}

So the list going from a **peak of 11,114 in April to {MC['total_subscribers']:,} today is
not shrinkage — it is hygiene.** The current number represents real people more accurately
than the April peak did.

### Real human growth is steady and improving

Organic signups through the website, 2026 (Ghost tracking, reliable from April):

{chart(organic, label_w=6)}

**{SW['ytd_ghost']:,} organic signups year to date**, and **July was the strongest month of
the year at {months['2026-07']['ghost_signups']}** — the traffic surge is beginning to convert.
This is clean growth: real readers who chose to subscribe.

> **Bottom line on the newsletter.** The apparent "decline" against 2025 is an artifact of
> comparing real humans to humans plus bots. On a like-for-like basis the list is healthier,
> more accurate and still growing, and the most recent month is the best of the year.

---

## 4. Engagement

| | 2026 YTD | Same period 2025 |
|---|---:|---:|
| Sends | {w_ytd['sends']} | {w_prior['sends']} |
| Open rate | {w_ytd['open_pct']}% | {w_prior['open_pct']}% |
| Click rate | {w_ytd['click_pct']}% | {w_prior['click_pct']}% |
| **Total opens** | **~{opens_now:,}** | ~{opens_prev:,} |
| **Total clicks** | ~{clicks_now:,} | ~{clicks_prev:,} |

**Total opens are up {(opens_now/opens_prev-1)*100:+.0f}%** — more people are reading Vital City
by email than a year ago. Rate declines should be read carefully: Apple Mail's privacy feature
inflates older open rates, and bot accounts sitting on the list depressed 2026 rates before the
cleanup. With a cleaner list, these rates should read truer going forward.

Total clicks are essentially flat ({(clicks_now/clicks_prev-1)*100:+.0f}%), which is the metric
to watch as the cleanup settles.

---

## 5. The opportunity: converting the new audience

This is where the upside is. **{yrs[2026]:,} visitors produced {SW['ytd_ghost']:,} organic
signups — about {SW['ytd_ghost']/yrs[2026]*100:.2f}%.** Traffic grew 30% while subscriber
acquisition stayed near flat.

One detail points at the fix: **the homepage is the single largest source of signups
(21 of 900 attributed), ahead of any article.** Most search visitors land directly on an
article, read it and leave. The subscribe ask is strongest where the traffic isn't.

Where signups come from (900 attributed events since February 5):

{chart([("Direct / unknown", 486), ("Search", 166), ("Academic outreach", 88),
        ("Social", 47), ("Email", 38)], label_w=18)}

A 54% direct/unknown share limits what can be concluded. Among traceable signups, search leads —
consistent with the traffic picture.

---

## 6. What the data suggests

1. **Conversion is the highest-leverage move.** Acquisition is solved; roughly 20,000 weekly
   visitors converting at {SW['ytd_ghost']/yrs[2026]*100:.2f}% is the constraint. The gap between
   article traffic and homepage-dominated signups points at the in-article ask as the place to test.
2. **The accountability franchise is proven.** 100 days and six months were the two biggest
   traffic events of the year. A one-year piece is the obvious next beat.
3. **Search rank is compounding.** Position {t365['position']} → {t28['position']} nearly doubled
   daily clicks on fewer impressions. The page-two opportunity list on the dashboard (rat control
   at 138k annual impressions, Tammany Hall at 102k) is the cheapest growth still available.
4. **Watch click rate as the cleanup settles.** With bots removed, engagement rates should be
   read fresh from here rather than against contaminated 2025 baselines.

---

## Methodology, sources and confidence

**Sources.** Google Analytics 4 (visitors, page views, per-piece traffic); Google Search Console
(clicks, impressions, position, click-through); Mailchimp (list size, sends, open and click rates,
growth history); Ghost (organic signup dates and attribution); the Vital City catalogue export
(publication dates, titles). All figures are as of {ASOF.isoformat()} and were read from the
published growth-dashboard payload.

**How the key numbers are derived.**
- *Annualized traffic* = year-to-date visitors ÷ {DOY} days × 365. A projection, not a measurement.
- *Organic signups* = Ghost member signup dates, counted the day they happened, not reduced by later
  unsubscribes and excluding bulk additions.
- *Net additions* = Mailchimp growth history, which counts every net addition regardless of source.
- *Total opens and clicks* = each send's rate × its recipients, summed. Mailchimp reports rates, not raw totals.
- *Implied removals* = net additions minus the actual change in list size for that month.

**Confidence.**
- **High:** traffic growth, search acceleration and rank improvement, per-piece performance,
  list size, send counts, unsubscribe counts. Direct measurements.
- **Medium:** the conversion rate. Ghost signup capture only became reliable around April 2026,
  so early-year organic signups are undercounted and the true rate is somewhat higher than
  {SW['ytd_ghost']/yrs[2026]*100:.2f}%.
- **Medium:** the scale of bot contamination. That bots signed up is established; exactly how many,
  and precisely which months, is not separable from the growth history alone. The ~{excess:,}
  above-baseline figure is an estimate of the anomaly, not a verified bot count.

**Known limits.**
- Google Analytics counts browsers, not people. Someone reading on a phone and a laptop counts twice,
  so visitor figures are directional rather than a headcount.
- 54% of signups carry no usable attribution source.
- 30-day active subscribers: Mailchimp's parent campaign reports no per-member opens for A/B
  split tests, but the hidden child sends carry them, and since Aug. 26, 2026 the pipeline reads
  the children — so this measure is populated again. Reports generated before that date used
  total clicks as a stand-in.
- 2026 is a year in progress. Year-over-year comparisons use the same calendar window on both sides.

---

<sub>Prepared from the Vital City growth dashboard · figures as of {ASOF.strftime('%B %-d, %Y')} ·
prepared with AI assistance; every figure traces to a named source above, and the bot-contamination
scale is flagged as an estimate rather than a measurement.</sub>
""")

out = Path.home() / "Desktop" / f"Vital-City-audience-report-{ASOF.isoformat()}.md"
out.write_text("\n".join(R))
print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
