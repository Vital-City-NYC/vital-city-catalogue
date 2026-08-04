#!/usr/bin/env python3
# Title: Chart images for the Vital City audience report
# Author: generated with Claude Code for Josh Greenman
# Date: 2026-08-04
# Data source: /tmp/rep.json (decrypted growth-dashboard payload)
# Description: Renders the report's charts as PNGs in the Vital City palette,
#   at 2x for crisp placement in a Word/Google doc.
# Dependencies: Python 3.9, matplotlib.
import json, datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

D = json.load(open("/tmp/rep.json"))
GA, MC, SC = D["ga4"], D["mailchimp"], D.get("search_console") or {}
OUT = Path("/tmp/vc_report_assets"); OUT.mkdir(exist_ok=True)

# Vital City palette (from the dashboard's CSS variables)
BLACK, CHARCOAL, CLOUD = "#050507", "#707175", "#dddddd"
GREEN, ORANGE, CERULEAN, MAGENTA = "#57aa4a", "#ff7c53", "#217ebe", "#e7466d"
PAPER = "#ffffff"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "text.color": BLACK, "axes.labelcolor": CHARCOAL,
    "xtick.color": CHARCOAL, "ytick.color": CHARCOAL,
    "axes.edgecolor": CLOUD, "figure.facecolor": PAPER, "axes.facecolor": PAPER,
})
K = FuncFormatter(lambda v, p: f"{v/1000:.0f}k" if v >= 1000 else f"{v:.0f}")

def finish(fig, ax, name, legend=False):
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(CLOUD); ax.spines["bottom"].set_color(CLOUD)
    ax.grid(axis="y", color=CLOUD, linewidth=0.7, alpha=0.7)
    ax.set_axisbelow(True)
    if legend: ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    p = OUT / name
    fig.savefig(p, dpi=200, facecolor=PAPER)
    plt.close(fig)
    print("  ", p.name)

def label_bars(ax, bars, vals, fmt="{:,.0f}", size=9, dy=0.012):
    top = max(vals) if vals else 1
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + top*dy, fmt.format(v),
                ha="center", va="bottom", fontsize=size, fontweight="bold", color=BLACK)

ASOF = datetime.date(2026, 8, 4)
DOY = (ASOF - datetime.date(2026, 1, 1)).days + 1
yrs = {y["year"]: y["users"] for y in GA["by_year"]["years"]}
pace = round(yrs[2026] / DOY * 365)
months = {m["month"]: m for m in MC["monthly_signups"]}

# 1 ── visitors by year, with 2026 projection hatched
fig, ax = plt.subplots(figsize=(7.6, 3.5))
labels = ["2023", "2024", "2025", "2026"]
vals = [yrs[2023], yrs[2024], yrs[2025], yrs[2026]]
bars = ax.bar(labels, vals, color=[GREEN]*3 + [GREEN], width=0.62)
proj = ax.bar(["2026"], [pace - yrs[2026]], bottom=[yrs[2026]], width=0.62,
              color=GREEN, alpha=0.30, hatch="///", edgecolor=GREEN,
              label="rest of year (projected)")
label_bars(ax, bars[:3], vals[:3])
ax.text(3, pace + max(vals)*0.012, f"{pace:,}", ha="center", va="bottom",
        fontsize=9, fontweight="bold", color=BLACK)
ax.text(3, yrs[2026]/2, f"{yrs[2026]:,}\nso far", ha="center", va="center",
        fontsize=8.5, color="white", fontweight="bold")
ax.yaxis.set_major_formatter(K)
ax.set_ylabel("unique visitors")
finish(fig, ax, "01-visitors-by-year.png", legend=True)

# 2 ── weekly visitors 2026, step change annotated
wk = [w for w in (GA.get("traffic_weekly") or []) if "2026-03-01" <= w["wk"] < "2026-08-03"]
fig, ax = plt.subplots(figsize=(7.6, 3.4))
xs = list(range(len(wk))); ys = [w["visits"] for w in wk]
ax.fill_between(xs, ys, color=CERULEAN, alpha=0.16)
ax.plot(xs, ys, color=CERULEAN, linewidth=2.2, marker="o", markersize=3.4)
sidx = next(i for i, w in enumerate(wk) if w["wk"] == "2026-06-22")
ax.axvline(sidx, color=MAGENTA, linestyle="--", linewidth=1.3, alpha=0.9)
ax.annotate("six-month Mamdani\npackage published",
            xy=(sidx, ys[sidx]), xytext=(sidx-5.4, max(ys)*0.99),
            fontsize=8.5, color=MAGENTA, fontweight="bold", ha="left", va="top",
            arrowprops=dict(arrowstyle="->", color=MAGENTA, lw=1.2))
ax.set_xticks(xs[::3]); ax.set_xticklabels([wk[i]["wk"][5:] for i in xs[::3]], fontsize=8.5)
ax.yaxis.set_major_formatter(K); ax.set_ylabel("visitors per week"); ax.set_ylim(0, max(ys)*1.22)
finish(fig, ax, "02-weekly-visitors.png")

# 3 ── search: clicks/day rising while impressions/day fall
def win(w, days):
    t = SC["windows"][w]["totals"]; return t, t["clicks"]/days, t["impressions"]/days
t365, c365, i365 = win("365", 365); t90, c90, i90 = win("90", 90); t28, c28, i28 = win("28", 28)
fig, ax = plt.subplots(figsize=(7.6, 3.4))
lab = ["Year average", "Last 90 days", "Last 28 days"]
cl = [c365, c90, c28]
bars = ax.bar(lab, cl, color=[CLOUD, "#9dc4de", CERULEAN], width=0.55)
label_bars(ax, bars, cl)
ax.set_ylabel("search clicks per day"); ax.set_ylim(0, max(cl)*1.2)
ax2 = ax.twinx()
ax2.plot(lab, [i365, i90, i28], color=ORANGE, linewidth=2.2, marker="o", markersize=6)
ax2.set_ylabel("impressions per day", color=ORANGE)
ax2.tick_params(axis="y", colors=ORANGE); ax2.spines["top"].set_visible(False)
ax2.set_ylim(0, max(i365, i90, i28)*1.25)
ax2.yaxis.set_major_formatter(K)
ax2.text(2, i28*1.06, "impressions falling", color=ORANGE, fontsize=8.5, fontweight="bold", ha="center")
finish(fig, ax, "03-search-acceleration.png")

# 4 ── top pieces 2026
top = (GA.get("top_pages_by_year") or {}).get("2026", [])[:8][::-1]
fig, ax = plt.subplots(figsize=(7.6, 3.8))
names = [(t["title"][:46] + "…") if len(t["title"]) > 47 else t["title"] for t in top]
v = [t["visitors"] for t in top]
bars = ax.barh(names, v, color=[MAGENTA if i >= 6 else CERULEAN for i in range(len(v))], height=0.68)
for b, val in zip(bars, v):
    ax.text(val + max(v)*0.012, b.get_y() + b.get_height()/2, f"{val:,}",
            va="center", fontsize=8.5, fontweight="bold", color=BLACK)
ax.xaxis.set_major_formatter(K); ax.set_xlim(0, max(v)*1.16)
ax.tick_params(axis="y", labelsize=8.4)
ax.grid(axis="x", color=CLOUD, linewidth=0.7); ax.grid(axis="y", visible=False)
finish(fig, ax, "04-top-pieces.png")

# 5 ── 2025 monthly net additions: the contaminated surge
fig, ax = plt.subplots(figsize=(7.6, 3.4))
ms = [f"2025-{m:02d}" for m in range(1, 13)]
v = [months[m]["new_signups"] for m in ms]
cols = [MAGENTA if "2025-05" <= m <= "2025-09" else CLOUD for m in ms]
bars = ax.bar([m[5:] for m in ms], v, color=cols, width=0.62)
# Bars below the baseline get their label floated above the dotted line, which
# otherwise strikes through the number.
_base0 = sum(months[f"2025-{m:02d}"]["new_signups"] for m in range(1, 5))/4
for b, val in zip(bars, v):
    y = max(val, _base0 + max(v)*0.028) + max(v)*0.012
    ax.text(b.get_x()+b.get_width()/2, y, f"{val:,}", ha="center", va="bottom",
            fontsize=8, fontweight="bold", color=BLACK)
base = sum(months[f"2025-{m:02d}"]["new_signups"] for m in range(1, 5))/4
# Draw the baseline only across the months it was measured from, and label it
# in the empty space above those short bars — a full-width line collided with
# the April value label and the autumn bars.
ax.hlines(base, -0.5, 3.5, color=BLACK, linestyle=":", linewidth=1.5)
ax.annotate(f"organic baseline ≈ {base:.0f}/mo",
            xy=(1.5, base), xytext=(-0.4, max(v)*0.30),
            fontsize=8.5, color=BLACK, fontweight="bold", ha="left", va="bottom",
            arrowprops=dict(arrowstyle="->", color=BLACK, lw=1.0))
ax.annotate("surge later identified as\nincluding bot signups",
            xy=(6, v[6]), xytext=(-0.4, max(v)*1.18), fontsize=8.5, color=MAGENTA,
            fontweight="bold", ha="left", va="top",
            arrowprops=dict(arrowstyle="->", color=MAGENTA, lw=1.2,
                            connectionstyle="arc3,rad=-0.15"))
ax.set_ylabel("net additions"); ax.set_ylim(0, max(v)*1.30)
finish(fig, ax, "05-2025-surge.png")

# 6 ── 2026: organic signups vs list removals (the cleanup)
fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.6, 3.2))
om = ["2026-04", "2026-05", "2026-06", "2026-07"]
ov = [months[m]["ghost_signups"] for m in om]
b1 = axa.bar(["Apr", "May", "Jun", "Jul"], ov, color=GREEN, width=0.6)
label_bars(axa, b1, ov, size=9)
axa.set_title("Real organic signups", fontsize=10, fontweight="bold", color=BLACK, pad=8)
axa.set_ylim(0, max(ov)*1.2)
rem = [("Jan", 86), ("Feb", 42), ("Mar", 108), ("Apr", 91), ("May", 575), ("Jun", 74), ("Jul", 68)]
rv = [r[1] for r in rem]
b2 = axb.bar([r[0] for r in rem], rv, width=0.6,
             color=[ORANGE if r[0] == "May" else CLOUD for r in rem])
label_bars(axb, b2, rv, size=8)
axb.set_title("Removed from the list", fontsize=10, fontweight="bold", color=BLACK, pad=8)
axb.annotate("bot cleanup", xy=(4, 575), xytext=(2.1, 520), fontsize=8.5, color=ORANGE,
             fontweight="bold", arrowprops=dict(arrowstyle="->", color=ORANGE, lw=1.2))
axb.set_ylim(0, max(rv)*1.2)
for a in (axa, axb):
    for s in ("top", "right"): a.spines[s].set_visible(False)
    a.spines["left"].set_color(CLOUD); a.spines["bottom"].set_color(CLOUD)
    a.grid(axis="y", color=CLOUD, linewidth=0.7); a.set_axisbelow(True)
fig.tight_layout(); fig.savefig(OUT / "06-signups-and-cleanup.png", dpi=200, facecolor=PAPER)
plt.close(fig); print("   06-signups-and-cleanup.png")

print(f"\ncharts written to {OUT}")
