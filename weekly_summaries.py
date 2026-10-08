#!/usr/bin/env python3
"""
Write the weekly "In brief" paragraphs for the growth dashboard's report views
and publish them to growth/analysis.enc.

A port of the local Claude scheduled task vc-growth-weekly-summaries (Tuesdays,
8:30 a.m.) so it can run on GitHub Actions instead of Josh's laptop. Same
inputs, same rules, same output file:

  1. Export every report view from the dashboard (dashboard_weekly.mjs in
     VC_EXPORT_DIR mode: headless Chrome, passphrase typed into the page).
     Each report's existing "In brief" block is cut before anything reads it,
     so a rerun can't copy last run's paragraph.
  2. One Claude Opus 5.5 request (effort high) reads all the reports and
     writes one paragraph per view under the rules in RULES below.
  3. Every paragraph is checked: each figure in it must appear in that view's
     own report, plus length, banned words and a named source for visits.
     One revision round if anything fails; if it still fails, nothing is
     published and the run exits 1.
  4. Writes analysis.json and runs write_analysis.py -> growth/analysis.enc.
     Committing is the workflow's job (or yours, locally).

The dashboard never calls a model. The paragraphs are written here, offline,
and committed encrypted like the rest of the growth data.

  python3 weekly_summaries.py                    # export, write, check, publish
  python3 weekly_summaries.py --serve            # export from this checkout, served locally
  python3 weekly_summaries.py --export-dir D     # reuse an export already in D
  python3 weekly_summaries.py --no-publish       # write and check, don't touch analysis.enc
  python3 weekly_summaries.py --skip-if-current  # exit quietly if this week's are already published
  python3 weekly_summaries.py --check F.json --export-dir D   # run the checks on F, no API call

Secrets: ANTHROPIC_API_KEY and VC_NETWORK_PASS from the environment, else the
macOS Keychain (items ANTHROPIC_API_KEY and vc-network-pass). Never printed.
Cost: about $0.72 a week at Opus 5.5 prices (first test, Oct. 8, 2026); --max-cost (default $2) stops a
revision round that could go past it.

The repository is public and so are its Actions logs. Under GITHUB_ACTIONS
this script prints no report text, no paragraph and no figure: only view keys,
word counts, check results and cost.
"""
import argparse, functools, http.server, json, os, re, shutil, subprocess, sys, tempfile, threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 32000
# Opus 5.5, dollars per million tokens
PRICE = {"in": 4.0, "cache_w": 5.0, "cache_r": 0.20, "out": 20.0}
EXPECTED = ["weeks:7", "weeks:28", "weeks:56", "weeks:91", "weeks:ytd",
            "days:28", "days:56", "days:91", "days:ytd"]
NY = ZoneInfo("America/New_York")
IN_CI = bool(os.environ.get("GITHUB_ACTIONS"))


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def fail(msg, code=1):
    log(f"FAILED: {msg}")
    if IN_CI:
        print(f"::error title=growth weekly summaries::{msg}", flush=True)
    sys.exit(code)


def secret(env, keychain_item):
    v = os.environ.get(env, "").strip()
    if v:
        return v
    if sys.platform == "darwin":
        try:
            return subprocess.check_output(
                ["/usr/bin/security", "find-generic-password", "-s", keychain_item, "-w"],
                stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            pass
    return ""


def ap_date(d):
    months = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.",
              "Sept.", "Oct.", "Nov.", "Dec."]
    return f"{months[d.month - 1]} {d.day}, {d.year}"


def last_sunday(today):
    """End of the last full Monday-to-Sunday week; today is never counted."""
    return today - timedelta(days=(today.weekday() + 1) or 7)


# ------------------------------------------------------------------- export
def serve_checkout():
    """Serve this checkout on a free local port so the export reads the
    committed growth data rather than whatever Pages has deployed so far."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/growth/index.html"


def export(dirpath, url=None):
    env = dict(os.environ, VC_EXPORT_DIR=str(dirpath))
    if url:
        env["VC_WEEKLY_URL"] = url
    node = shutil.which("node") or "/usr/local/bin/node"
    r = subprocess.run([node, str(ROOT / "dashboard_weekly.mjs")], env=env, cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        # The exporter's own messages carry no data and no passphrase.
        fail(f"dashboard export failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()[-600:]}")
    log((r.stdout or "").strip())


BRIEF = re.compile(r"\*\*In brief\*\*\n.*?\n_Written [^\n]*_\n?", re.S)


def load_views(dirpath):
    vf = Path(dirpath) / "views.json"
    if not vf.exists():
        fail(f"no views.json in {dirpath}")
    views = json.loads(vf.read_text())
    if not views:
        fail("the export listed no report views")
    for v in views:
        md = (Path(dirpath) / (v["key"].replace(":", "-") + ".md")).read_text()
        md = BRIEF.sub("", md)
        if len(md) < 2000 or "### The numbers that matter most" not in md:
            fail(f"{v['key']}: the exported report looks empty or malformed ({len(md)} characters)")
        v["md"] = md
    missing = [k for k in EXPECTED if k not in {v["key"] for v in views}]
    if missing:
        log(f"note: the dashboard exported no report for {', '.join(missing)}")
    return views


# ------------------------------------------------------------------- prompt
RULES = """You write the short opening summaries for Vital City's internal growth
reports. Vital City is a New York City policy publication; Josh Greenman is its
managing editor. Its strategy: grow the newsletter list, reach decision-makers
(government, universities, press, nonprofit and foundation leaders), get cited
and turn site readers into subscribers. Publishing more pieces brings more
visits. The reports cover readership and growth only; giving is left out of
them and of these paragraphs.

You will get one report for each view of the growth dashboard. Each report
gives the numbers that matter most (each with its typical figure and, where
the records allow, the same dates last year), the twelve-week trend where
present, "Pieces that did well, and what that means" (pieces that finished
their first 30 days in the period, rated Under-performing to Exceptional by
first-30-day page views, with newsletter signups; and what tends to do well
by series and subject), the long view (each measure by calendar year since
2022), and everything below the line, including the monthly key indicators
and context. Read every report in full.

For each view, write ONE paragraph, 3 to 5 sentences and about 80 to 130
words, synthesizing the overall trends across that view's whole period.

- Even tone, in perspective: not cheerleading and not brutal. Give the good
  and the weak measures equal plain treatment, and put a slow stretch in
  context (for example, one quiet week inside a stronger quarter) rather than
  softening it. No "strong," "sharply," "impressive" or similar. Where a
  typical figure rests on little history (Ghost's reader counts only go back
  to March 2026), say so. A lever (publishing pace, signup prompts on the
  most-read pieces, outreach to government and universities) may be named
  only when the report's numbers point to it.
- Use only facts and figures that appear in that view's report. Never invent
  causes; when suggesting why something moved, say "likely" or "may" and tie
  it to something in the report (such as fewer pieces published, or a spike
  the same week a year earlier).
- Give every figure the value and rounding that view's report gives it.
  Don't compute new differences, sums, shares or percentages, and don't bring
  a figure over from another view's report. AP style still applies: spell out
  one through nine ("eight signups," "about six pieces"). An automatic check
  compares every number in each paragraph, in digits or in words, with that
  view's report and rejects any it can't find there.
- Written for someone with no analytics background: no jargon (no "norm,"
  "cohort," "CTR," "conversion," "baseline," "YoY"). Spell things out ("new
  subscribers per 1,000 website visitors").
- Name the source when citing visits or visitors (Ghost or Google
  Analytics); the two differ and must never be compared with each other.
- Don't make any comparison against the May-September 2025 bot months.
- House style: AP style, no serial comma, "New York City" in full, straight
  quotes and apostrophes, numbers with commas. Plain declarative sentences.
  No "It's not X, it's Y" constructions, no superlatives, no filler
  ("notably," "importantly," "it's worth noting"), no praise words. Don't
  address a reader by name.
- Anchor the numbers where the report allows: name one piece that did well in
  the period and what "well" means (its band and page views), or set a figure
  against the long view or the same dates last year. One anchor per paragraph
  is enough.
- Each view gets its own paragraph fitted to its length: the one-week view is
  about the week; the 13-week and year-to-date views are about the longer
  arc. Don't repeat the same sentences across views."""


def schema(keys):
    return {
        "type": "object",
        "properties": {"paragraphs": {"type": "array", "items": {
            "type": "object",
            "properties": {"key": {"type": "string", "enum": keys},
                           "text": {"type": "string"}},
            "required": ["key", "text"], "additionalProperties": False}}},
        "required": ["paragraphs"], "additionalProperties": False,
    }


def first_message(views, today):
    reports = "\n\n".join(
        f'<report key="{v["key"]}" label="{v["label"]}" period="{v["period"]}">\n{v["md"]}\n</report>'
        for v in views)
    keys = ", ".join(v["key"] for v in views)
    task = (f"Today is {ap_date(today)}. Write one paragraph for each of these views, "
            f"keyed exactly as given: {keys}. Return them in the paragraphs array.")
    return {"role": "user", "content": [
        {"type": "text", "text": reports},
        # The breakpoint sits on the last block, so a revision round re-reads
        # the reports from the cache at a twentieth of the price.
        {"type": "text", "text": task, "cache_control": {"type": "ephemeral"}},
    ]}


# ------------------------------------------------------------------- checks
WORDNUM = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
WORDNUM.update({w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"})
NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])")
WORD = re.compile(r"\b(" + "|".join(sorted(WORDNUM, key=len, reverse=True)) +
                  r")(?:-(one|two|three|four|five|six|seven|eight|nine))?\b", re.I)


def numbers(text, words=True):
    """Every number in the text as a Decimal, so 3.6 and 3.60 or 1,234 and
    1234 count as the same figure. 'one' is left out: it is a pronoun as
    often as a number."""
    out = []
    for m in NUM.finditer(text):
        out.append((m.group(0), Decimal(m.group(1).replace(",", "") + (m.group(2) or ""))))
    if words:
        for m in WORD.finditer(text):
            w, unit = m.group(1).lower(), (m.group(2) or "").lower()
            if w == "one" and not unit:
                continue
            out.append((m.group(0), Decimal(WORDNUM[w] + (WORDNUM[unit] if unit else 0))))
    return out


BANNED = [
    (r"\bsharply\b", "sharply"), (r"\bimpressive(ly)?\b", "impressive"),
    (r"\bnotably\b", "notably"), (r"\bimportantly\b", "importantly"),
    (r"\bworth noting\b", "worth noting"), (r"\bnorms?\b", "norm"),
    (r"\bcohorts?\b", "cohort"), (r"\bCTR\b", "CTR"), (r"\bconversions?\b", "conversion"),
    (r"\bbaselines?\b", "baseline"), (r"\bYoY\b|\byear[- ]over[- ]year\b", "YoY"),
    (r"\bNYC\b", "NYC"), (r"[‘’“”]", "curly quotes"),
    (r"\bit'?s not\b[^.]{0,60}\bit'?s\b", "it's not X, it's Y"),
    (r"^(Liz|Anthony|Josh)\b", "addresses a reader by name"),
    # "Strong" is also one of the dashboard's bands for a piece; naming the
    # band is allowed, using the word as praise isn't.
    (r"(?<!rated )(?<!as )\bstrong(ly|er|est)?\b(?! band)", "strong"),
]


def check(text, report_md, view):
    """The reasons a paragraph can't go out as written."""
    problems = []
    allowed = {n for _, n in numbers(report_md)}
    allowed |= {n for _, n in numbers(" ".join([view["label"], view["period"], view["start"], view["end"]]))}
    missing = sorted({tok for tok, n in numbers(text) if n not in allowed})
    if missing:
        problems.append("figures not in this view's report: " + ", ".join(missing))
    n = len(text.split())
    if not 70 <= n <= 145:
        problems.append(f"{n} words (the rule is about 80 to 130)")
    for pat, name in BANNED:
        if re.search(pat, text, 0 if name in ("CTR", "YoY", "NYC", "addresses a reader by name") else re.I):
            problems.append(f'uses "{name}"')
    if re.search(r"\bvisit(s|ors?)?\b", text, re.I) and not re.search(r"Ghost|Google Analytics", text):
        problems.append("cites visits or visitors without naming Ghost or Google Analytics")
    return problems


def check_all(paras, views):
    by = {v["key"]: v for v in views}
    out = {}
    for k in by:
        if k not in paras:
            out[k] = ["no paragraph for this view"]
    for k, t in paras.items():
        if k not in by:
            out[k] = ["not a view in this export"]
            continue
        p = check(t, by[k]["md"], by[k])
        if p:
            out[k] = p
    return out


# ------------------------------------------------------------------- Claude
class Spend:
    def __init__(self):
        self.tok = {"in": 0, "cache_w": 0, "cache_r": 0, "out": 0}

    def add(self, u):
        # With a fallback, top-level usage covers only the serving attempt;
        # the per-attempt list is the full bill.
        its = getattr(u, "iterations", None) or [u]
        for x in its:
            self.tok["in"] += getattr(x, "input_tokens", 0) or 0
            self.tok["cache_w"] += getattr(x, "cache_creation_input_tokens", 0) or 0
            self.tok["cache_r"] += getattr(x, "cache_read_input_tokens", 0) or 0
            self.tok["out"] += getattr(x, "output_tokens", 0) or 0

    def dollars(self):
        return sum(self.tok[k] * PRICE[k] for k in PRICE) / 1e6

    def line(self):
        t = self.tok
        return (f"${self.dollars():.2f} ({t['in']:,} input, {t['cache_w']:,} cache-write, "
                f"{t['cache_r']:,} cache-read, {t['out']:,} output tokens)")


def call(client, messages, keys, spend):
    import anthropic
    try:
        with client.beta.messages.stream(
                model=MODEL, max_tokens=MAX_TOKENS, system=RULES, messages=messages,
                output_config={"effort": EFFORT,
                               "format": {"type": "json_schema", "schema": schema(keys)}},
                # A safety-classifier decline is retried on the model Anthropic
                # recommends for that category instead of failing the week.
                betas=["server-side-fallback-2026-07-01"], fallbacks="default") as stream:
            msg = stream.get_final_message()
    except anthropic.APIStatusError as e:
        fail(f"Claude API error {e.status_code} ({type(e).__name__}): {e.message}")
    except anthropic.APIConnectionError as e:
        fail(f"could not reach the Claude API: {e}")
    spend.add(msg.usage)
    if msg.stop_reason == "refusal":
        cat = getattr(msg.stop_details, "category", None) if msg.stop_details else None
        fail(f"Claude declined (category: {cat}) [request {msg.id}]")
    if msg.stop_reason != "end_turn":
        fail(f"Claude stopped early (stop_reason: {msg.stop_reason}) [request {msg.id}]")
    text = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        items = json.loads(text)["paragraphs"]
    except Exception as e:
        fail(f"the reply was not the expected JSON ({e})")
    paras = {}
    for it in items:
        if it["key"] in paras:
            fail(f"two paragraphs for {it['key']}")
        paras[it["key"]] = re.sub(r"\s+", " ", it["text"]).strip()
    return msg, paras


def feedback(problems, views):
    lines = ["An automatic check rejected some paragraphs. Rewrite only these views, "
             "keeping to every rule, and return the full paragraphs array again with "
             "all views (unchanged ones as they were):"]
    for k, ps in problems.items():
        lines.append(f"- {k}: " + "; ".join(ps))
    lines.append("For a figure the check couldn't find, use the figure as that view's own "
                 "report writes it, or leave it out.")
    return "\n".join(lines)


def write_paragraphs(views, today, max_cost):
    key = secret("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
    if not key:
        fail("ANTHROPIC_API_KEY is not set (repo secret or Keychain); nothing was written")
    try:
        import anthropic
    except ImportError:
        fail("the anthropic package is not installed (pip install anthropic)")
    client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=900)
    keys = [v["key"] for v in views]
    spend = Spend()
    messages = [first_message(views, today)]
    msg, paras = call(client, messages, keys, spend)
    log(f"draft written: {spend.line()}")
    problems = check_all(paras, views)
    if problems:
        report_problems(problems, "first draft")
        # Worst case for a revision: the reports again from cache plus a full
        # max_tokens reply.
        est = sum(len(v["md"]) for v in views) / 3.5 * PRICE["cache_r"] / 1e6 + MAX_TOKENS * PRICE["out"] / 1e6
        if spend.dollars() + est > max_cost:
            fail(f"checks failed and a revision could pass the ${max_cost:.2f} cap; nothing published")
        messages += [{"role": "assistant", "content": msg.content},
                     {"role": "user", "content": feedback(problems, views)}]
        msg, revised = call(client, messages, keys, spend)
        paras.update({k: v for k, v in revised.items() if k in keys})
        log(f"revision written: {spend.line()}")
        problems = check_all(paras, views)
        if problems:
            report_problems(problems, "after revision")
            fail("paragraphs still fail the checks after one revision; nothing published")
    return paras, spend


def report_problems(problems, when):
    for k, ps in problems.items():
        if IN_CI:
            # Counts only: the figures themselves are internal.
            log(f"  {when} {k}: {len(ps)} problem(s): " +
                "; ".join(p.split(":")[0] for p in ps))
        else:
            log(f"  {when} {k}: " + "; ".join(ps))


# ------------------------------------------------------------------- publish
def published_end():
    """The week the published summaries cover, or None."""
    f = ROOT / "growth" / "analysis.enc"
    if not f.exists():
        return None
    sys.path.insert(0, str(ROOT))
    from slack_mentions import decrypt
    try:
        a = json.loads(decrypt(json.loads(f.read_text())))
    except Exception as e:
        fail(f"could not read growth/analysis.enc ({type(e).__name__}); is VC_NETWORK_PASS right?")
    return (a.get("items", {}).get("weeks:7") or {}).get("end")


def gh_output(**kw):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-dir", help="reuse an export (views.json + .md files) instead of running one")
    ap.add_argument("--serve", action="store_true", help="export from this checkout served on localhost")
    ap.add_argument("--out", help="where to write analysis.json (default: the export folder)")
    ap.add_argument("--no-publish", action="store_true", help="don't write growth/analysis.enc")
    ap.add_argument("--skip-if-current", action="store_true",
                    help="exit quietly when this week's summaries are already published")
    ap.add_argument("--check", metavar="JSON", help="run the checks on an analysis.json; no API call")
    ap.add_argument("--max-cost", type=float, default=2.0, help="dollar cap for one run (default 2)")
    a = ap.parse_args()

    pw = secret("VC_NETWORK_PASS", "vc-network-pass")
    if not pw:
        fail("VC_NETWORK_PASS is not set (repo secret or Keychain)")
    os.environ["VC_NETWORK_PASS"] = pw   # for the exporter and write_analysis.py

    today = datetime.now(NY).date()
    week_end = last_sunday(today)
    gh_output(week_ending=ap_date(week_end), published="false")

    if a.skip_if_current and published_end() == week_end.isoformat():
        log(f"summaries for the week ending {ap_date(week_end)} are already published; nothing to do")
        return 0

    tmp = None
    if a.export_dir:
        exp = Path(a.export_dir)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="vc-summaries-"))
        exp = tmp
        export(exp, serve_checkout() if a.serve else None)
    try:
        views = load_views(exp)
        if a.check:
            items = json.loads(Path(a.check).read_text())["items"]
            problems = check_all({k: v["text"] for k, v in items.items()}, views)
            report_problems(problems, "check")
            log(f"{len(items) - len(problems)} of {len(items)} paragraphs pass")
            return 1 if problems else 0

        if not any(v["end"] == week_end.isoformat() for v in views if v["key"].startswith("weeks:")):
            fail(f"the exported weekly views don't end on {week_end.isoformat()}; is the data stale?")

        paras, spend = write_paragraphs(views, today, a.max_cost)
        analysis = {"written_at": today.isoformat(), "items": {
            v["key"]: {"end": v["end"], "period": v["period"], "text": paras[v["key"]]} for v in views}}
        out = Path(a.out) if a.out else exp / "analysis.json"
        out.write_text(json.dumps(analysis, indent=1, ensure_ascii=False))
        for v in views:
            t = paras[v["key"]]
            log(f"  {v['key']}: {len(t.split())} words, checks pass")
            if not IN_CI:
                print(f"\n[{v['key']}] {v['period']}\n{t}")
        log(f"Claude spend: {spend.line()}")
        if not a.no_publish:
            r = subprocess.run([sys.executable, str(ROOT / "write_analysis.py"), str(out)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"write_analysis.py failed: {r.stderr.strip()[-400:]}")
            log(r.stdout.strip())
            gh_output(published="true")
        return 0
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
