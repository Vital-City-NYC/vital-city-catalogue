#!/usr/bin/env python3
"""Enrich the DEVOTED READERS in the contact database — names and employers —
as a reviewable sidecar, never as a silent write into people.json.

WHY A SIDECAR (same reasoning as infer_employers.py)
A researched name written straight into `n` is indistinguishable from a name the
person gave us. So every proposal lands in private/reader_enrichment.{json,csv}
with its confidence and the evidence behind it. Promote a row by appending it to
private/name_overrides.csv (email,name), which build_network.py already treats as
authoritative.

WHO COUNTS AS DEVOTED
Still subscribed, and either a Mailchimp rating of 4-5, or a rating of 3 with at
least one click. 260 people as of August 2026. Of those, 147 are missing a real
name or an employer.

CONFIDENCE TIERS
  confirmed  A public page shows this exact address next to this person's name,
             or their own CV/site does. Promote without further checking.
  high       No page prints the address, but the local part matches the
             organization's own convention AND a named person at that
             organization fits it AND no competing same-initial colleague turned
             up. Josh should eyeball these; they are very likely right.
  org-only   The person stays unnamed; only the employer is being corrected,
             read off a domain that resolves to one organization.
  unresolved Searched and found nothing solid. Recorded so the next pass does
             not repeat the work.

WHAT THIS DELIBERATELY DOES NOT DO
Guess. A wrong name in a fundraising database is worse than a blank one, and
consumer-mailbox addresses (gmail, yahoo) usually cannot be tied to a person
without a public footprint that names the address. Those stay blank.

Research done 2026-08-19; sources recorded per row.
"""
import csv, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIV = ROOT / "private"

# ---------------------------------------------------------------- findings
# email, name, employer, role, confidence, evidence url, note
FINDINGS = [
 dict(email="zjelveh@umd.edu", name="Zubin Jelveh",
      employer="University of Maryland", role="Assistant professor, College of Information and Dept. of Criminology and Criminal Justice",
      conf="confirmed", url="https://zjelveh.github.io/files/zj_cv.pdf",
      note="His own CV header reads 'Zubin Jelveh zjelveh@umd.edu'. Formerly research director at Crime Lab New York."),
 dict(email="davekirk@sas.upenn.edu", name="David S. Kirk",
      employer="University of Pennsylvania", role="Professor and Chair, Dept. of Criminology",
      conf="confirmed", url="https://crim.sas.upenn.edu/people/david-kirk",
      note="Penn's faculty page lists davekirk@sas.upenn.edu. Researches policing, recidivism and gun violence."),
 dict(email="lfiorenza@ocbaacp.org", name="Laura Fiorenza",
      employer="Onondaga County Bar Association Assigned Counsel Program", role="Director of Quality Enhancement",
      conf="confirmed", url="https://www.ocbaacp.org/join/",
      note="The program's own join page gives LFiorenza@ocbaacp.org as the contact. DB employer read 'Ocbaacp' — a domain string, not a name. 74 opens, 62 clicks."),
 dict(email="lvanderlugt@csg.org", name="Laura van der Lugt",
      employer="Council of State Governments Justice Center", role="Justice reinvestment technical assistance",
      conf="confirmed", url="https://csgjusticecenter.org/people/laura-van-der-lugt/",
      note="Her CSG conference profile slug is literally /lvanderlugt, matching the address."),
 dict(email="janny@jannyscott.com", name="Janny Scott",
      employer="Independent — author and journalist", role="Author; New York Times reporter 1994-2008",
      conf="confirmed", url="https://en.wikipedia.org/wiki/Janny_Scott",
      note="CORRECTION: the DB says 'Janet Scott'. She is Janny Scott, on the Times team that won the 2000 Pulitzer for national reporting, author of 'A Singular Woman' and 'The Beneficiary'. Address is her own name domain."),
 dict(email="jmascia@thetrace.org", name="Jennifer Mascia",
      employer="The Trace", role="Senior news writer; founding staffer",
      conf="high", url="https://www.thetrace.org/author/jennifer-mascia/",
      note="Founding staffer and the only Mascia on the masthead; covered gun violence at the NYT before. Convention j+lastname."),
 dict(email="jburnett@thetrace.org", name="James Burnett",
      employer="The Trace", role="Founding editor; managing director",
      conf="high", url="https://www.thetrace.org/author/james-burnett/",
      note="Also now listed with UVA's Karsh Institute of Democracy — the thetrace.org employer may be the older of the two."),
 dict(email="mplanty@rti.org", name="Michael Planty",
      employer="RTI International", role="Senior director, Center for Community Safety and Crime Prevention",
      conf="high", url="https://www.rti.org/expert/michael-planty",
      note="Former deputy director of the federal Bureau of Justice Statistics. Convention m+lastname."),
 dict(email="dgilbert@vera.org", name="Daniela Gilbert",
      employer="Vera Institute of Justice", role="Director, Redefining Public Safety",
      conf="high", url="https://www.vera.org/who-we-are/people",
      note="Convention first-initial+lastname; her programme is squarely Vital City's subject. No competing D. Gilbert found."),
 dict(email="mnelson@vera.org", name="Marta Nelson",
      employer="Vera Institute of Justice", role="Director of sentencing reform",
      conf="high", url="https://www.vera.org/who-we-are/people",
      note="Same convention. No competing M. Nelson found, but Vera has 200+ staff — worth a glance before use."),
 dict(email="redcrossc@bronxda.nyc.gov", name="Cindy Redcross",
      employer="Bronx County District Attorney's Office", role="",
      conf="high", url="https://www.linkedin.com/in/cindyredcross/",
      note="Office convention is lastname+first-initial (redcross + c). Applied researcher, long associated with MDRC's criminal justice work."),
 dict(email="watkinsm@courtinnovation.org", name="Matt Watkins",
      employer="Center for Justice Innovation", role="Host, 'New Thinking' podcast",
      conf="high", url="https://www.innovatingjustice.org/about/staff/",
      note="Same lastname+initial convention as the Bronx DA record (watkins + m)."),
 dict(email="lstegmaier@bcfny.org", name="Liane Stegmaier",
      employer="Brooklyn Org (formerly Brooklyn Community Foundation)", role="Vice president, communications and strategy",
      conf="high", url="https://brooklyn.org/team/liane-stegmaier/",
      note="bcfny.org is Brooklyn Community Foundation, which rebranded to Brooklyn Org. DB employer read 'Bcfny'. 60 opens, 44 clicks."),
 dict(email="mmarkham@policingequity.org", name="Max Markham",
      employer="Policing Project, NYU School of Law", role="Executive director",
      conf="high", url="https://www.law.nyu.edu/news/max-markham-alumnus-policing-project",
      note="STALE DOMAIN: he was VP of policy at the Center for Policing Equity Feb 2022 - July 2024 and has since moved to the Policing Project. The address may no longer reach him."),
 dict(email="jmc@mccreightpartners.com", name="John A. McCreight",
      employer="McCreight Partners", role="Founder and chairman",
      conf="high", url="https://mccreightpartners.com/about-us/meet-john-mccreight/",
      note="Initials at his own firm's domain, the pattern that usually means the principal. 72 opens and 61 clicks — one of the most engaged readers on the list, and a consulting-firm founder."),
 dict(email="njordan@dpw.com", name="Nora M. Jordan",
      employer="Davis Polk & Wardwell", role="Senior counsel; former head of the investment management group",
      conf="high", url="https://www.davispolk.com/lawyers/nora-jordan",
      note="dpw.com is Davis Polk's own domain. Name was already right; only the employer was blank. Retired as partner end of 2020 after 37 years."),
 dict(email="arti.finn@apdscorporate.com", name="Arti Finn",
      employer="Orijin (formerly APDS, American Prison Data Systems)", role="",
      conf="org-only", url="https://apdscorporate.com/",
      note="Name already given. The domain now resolves to Orijin, a correctional education and workforce platform."),
 dict(email="bweinberg@citizensunionfoundation.org", name="Ben Weinberg",
      employer="Citizens Union Foundation", role="",
      conf="org-only", url="https://citizensunionfoundation.org/",
      note="Name already given; employer read straight off the organisation's own domain."),
 dict(email="emily@lagratta.com", name="Emily LaGratta",
      employer="LaGratta Consulting", role="",
      conf="org-only", url="https://lagratta.com/",
      note="Name already given; own-name domain, so the firm is hers."),
 dict(email="leslie@1235strategies.com", name="Leslie Kerns",
      employer="1235 Strategies", role="",
      conf="org-only", url="https://1235strategies.com/",
      note="Name already given; employer read off the domain."),
 dict(email="joan@joanbyron.com", name="Joan Byron",
      employer="Independent — own consultancy", role="",
      conf="org-only", url="",
      note="CORRECTION: the DB name reads 'Joan Joanbyron', built from the domain. Own-name domain; no employer beyond her own practice should be asserted."),
 dict(email="lnapoli@appad.org", name="",
      employer="Appellate Advocates", role="",
      conf="org-only", url="https://appad.org/",
      note="DB employer read 'Appad'. appad.org is Appellate Advocates, the New York appellate public-defence office. Person not identified."),
 dict(email="mbedeau@ceoworks.org", name="",
      employer="Center for Employment Opportunities", role="",
      conf="org-only", url="https://www.ceoworks.org/",
      note="DB employer read 'Ceoworks'. Person not identified."),
 dict(email="paulc@lemosandcrane.co.uk", name="",
      employer="Lemos&Crane", role="",
      conf="org-only", url="https://lemosandcrane.co.uk/",
      note="UK social policy organisation. Local part 'paulc' suggests a Paul C., but nothing public confirmed it."),
 dict(email="maguilar@osc.ny.gov", name="",
      employer="Office of the New York State Comptroller", role="",
      conf="org-only", url="https://www.osc.ny.gov/",
      note="DB employer read 'NY', which is meaningless. Person not identified."),
 dict(email="william.rapfogel@idt.net", name="William Rapfogel",
      employer="", role="",
      conf="unresolved", url="",
      note="DO NOT infer an employer here. idt.net is a consumer ISP domain, not a workplace — worth adding to the CONSUMER pattern in infer_employers.py so nobody later records 'IDT' as his employer."),
 dict(email="jsevere@advocate.nyc.gov", name="",
      employer="Office of the New York City Public Advocate", role="",
      conf="unresolved", url="https://www.advocate.nyc.gov/about/staff",
      note="Employer is certain from the domain; the staff page did not surface a Severe. Recorded so the next pass skips it."),
]

# ---------------------------------------------------------------- found by exact-address search
# Josh found dpearlstein@gmail.com on Google in one search and asked, fairly,
# why I could not. Two reasons, both worth recording:
#   1. My first query was "dpearlstein@gmail.com" OR "Pearlstein" New York
#      criminal justice policy. The OR let the engine satisfy the query without
#      ever matching the address. A bare quoted address is the only honest test.
#   2. Even bare, my search tool's index does not contain the page Google
#      returns first — a Sage journal article. Google, Bing, DuckDuckGo and
#      Brave all refuse scripted queries or silently drop the exact-phrase
#      constraint. Google Scholar does answer them, and indexes the full text of
#      papers and reports, which is exactly where people print their own email.
# find_reader_names.py runs that sweep. These are its confirmed results: the
# address appears in a document the person wrote, which is proof, not inference.
SEARCH_FINDINGS = [
 dict(email="dpearlstein@gmail.com", name="Daniel Pearlstein",
      employer="Riders Alliance", role="Policy and communications director",
      conf="confirmed", url="https://journals.sagepub.com/doi/10.1177/1538513210366980",
      note="His own paper prints the address: 'Sweeping Six Percent Philanthropy Away: The New Deal "
           "in Sunnyside Gardens', Journal of Planning History 2010, under Benjamin N. Cardozo School "
           "of Law. Now policy and communications director at Riders Alliance, the subway and bus "
           "riders' organisation; previously chief of staff to a City Council land use chair. Opens "
           "92% of sends and clicks 46% — the most engaged reader who had no name."),
 dict(email="hfader@csg.org", name="Hallie Fader-Towe",
      employer="Council of State Governments Justice Center", role="",
      conf="confirmed", url="https://csgjusticecenter.org/people/hallie-fader-towe/",
      note="Address appears in 'Just and Well: Rethinking How States Approach Competency to Stand "
           "Trial' (CSG Justice Center, 2020), which she co-authored. Harvard JD, McKinsey before "
           "CSG; works on courts and mental illness. Second CSG Justice Center reader found in this "
           "pass, after Laura van der Lugt."),
]

# ---------------------------------------------------------------- browser sweep
# Josh: "you can drive my browser." He was right, and it changes everything.
# Google refuses scripted queries from a server but answers normally in his own
# Chrome. Driving it — same-origin fetches to /search from a google.com tab,
# reading only the results region so the page's echo of the query does not
# register as a hit — turns "unfindable" into a solved problem for a good share
# of this list. Roughly 28 queries in, Google starts rate-limiting; the sweep
# pauses there rather than risk a block on his account, and resumes later.
#
# Everything here is CONFIRMED in the strict sense: a page prints the address
# next to the name. Three of these upgrade an earlier convention-based guess to
# proof, which is the point.
BROWSER_FINDINGS = [
 dict(email="mfhorn626@yahoo.com", name="Martin F. Horn",
      employer="John Jay College of Criminal Justice", role="Distinguished lecturer in corrections; executive director, New York State Sentencing Commission",
      conf="confirmed", url="https://www.jjay.cuny.edu/faculty/martin-f-horn",
      note="His CV, filed as an exhibit in Lucero-Gonzalez v. Kline, prints mfhorn626@yahoo.com above "
           "an employment history beginning 'EXECUTIVE DIRECTOR, NEW YORK STATE UNIFIED COURT SYSTEM, "
           "NEW YORK STATE SENTENCING'. He was Bloomberg's Commissioner of Correction AND Probation "
           "simultaneously, 2002-2009, and Pennsylvania's Secretary of Corrections before that. Opens "
           "90% of sends and clicks 30%. Given the Rikers work, one of the more consequential readers "
           "on the list."),
 dict(email="jmc@mccreightpartners.com", name="John A. McCreight",
      employer="McCreight Partners", role="Founder and chairman",
      conf="confirmed", url="https://mccreightpartners.com/",
      note="UPGRADE from convention-guess to proof: the firm's own contact page and a 2020 PDF both "
           "print 'John McCreight: jmc@mccreightpartners.com'. Opens 72%, clicks 61%."),
 dict(email="jmascia@thetrace.org", name="Jennifer Mascia",
      employer="The Trace", role="Senior news writer",
      conf="confirmed", url="https://www.thetrace.org/2025/12/immigration-ice-shootings/",
      note="UPGRADE: a Trace article says 'you can email senior news writer Jennifer Mascia at "
           "jmascia@thetrace.org'."),
 dict(email="dgilbert@vera.org", name="Daniela Gilbert",
      employer="Vera Institute of Justice", role="Director, Redefining Public Safety",
      conf="confirmed", url="https://www.vera.org/civilian-crisis-response-toolkit",
      note="UPGRADE: Vera's Civilian Crisis Response toolkit says 'please contact Daniela Gilbert, "
           "director, Redefining Public Safety, at dgilbert@vera.org'."),
 dict(email="dudell@fordham.edu", name="David Udell",
      employer="National Center for Access to Justice", role="Executive director",
      conf="confirmed", url="https://ncaj.org/",
      note="The NCAJ, housed at Fordham Law, is the top result for the address."),
 dict(email="neagan4@gmail.com", name="Nathan Eagan",
      employer="Colorado Coalition for Restorative Justice Practices", role="Co-chair, board of directors",
      conf="confirmed", url="https://ccrjp.org/who-we-are",
      note="The coalition's own Who We Are page lists 'Nathan Eagan, Co-Chair: neagan4@gmail.com'. "
           "A consumer mailbox, findable in one search — exactly Josh's point."),
 dict(email="kcleeson@gmail.com", name="Kellie Leeson",
      employer="Refugee Self-Reliance Initiative", role="Independent consultant, initiative lead",
      conf="confirmed", url="https://www.rsc.ox.ac.uk/people/kellie-leeson",
      note="Oxford's Refugee Studies Centre profile prints KCLeeson@gmail.com."),
 dict(email="wstopp11@gmail.com", name="Walter S. Topp",
      employer="Independent — writer", role="Non-fiction and technical writer, Cleveland",
      conf="confirmed", url="https://wstopp.com/",
      note="His own site and its Facebook page carry the address. A former reporter, emergency "
           "manager, naval officer and police officer."),
 # -- found, but only in people-search aggregators. Recorded, deliberately not promoted.
 dict(email="wjenett@gmail.com", name="", conf="broker-only",
      url="", note="A people-search aggregator ties this to a Willoughby Jenett and shows a second "
           "address at legal-aid.org, which would fit a Legal Aid Society lawyer. The only sources are "
           "data brokers, which are often wrong and which I do not think should silently become the "
           "provenance of a name in this database. Josh's call."),
 dict(email="pcsarna1@yahoo.com", name="", conf="broker-only",
      url="", note="Same: an aggregator gives Peter C. Sarna II in Palm Desert, California. Broker "
           "source only."),
 # -- organisational or shared addresses clarified by the sweep
 dict(email="centerforadvancedprosecution@gmail.com", name="", employer="Center for Advanced Prosecution",
      conf="organisation", url="https://www.repatriationgroup.org/contact",
      note="Used as the contact address on Repatriation Group International's site. An organisational "
           "mailbox, not a person."),
 dict(email="sgreenfield04@gmail.com", name="", conf="searched",
      url="https://www.merrickjc.org/",
      note="Appears only as the Zelle payment address for Merrick Jewish Centre on Long Island. Tells "
           "us the person handles payments there; does not give a name."),
]

# ---------------------------------------------------------------- consumer mailboxes
# Josh's push-back, and he was right: a consumer domain is not the same as
# unfindable. Two different things live in this cohort, and they deserve
# different treatment.
#
#   address-encoded  The address SPELLS a full name. Writing "Rachel Fine" for
#                    rachelfine515@ is not an identity claim about a human being;
#                    it is reading what the address already says, and it is
#                    strictly better than the "Rachelfine" the guesser produces.
#                    Safe to promote.
#   likely           The address encodes a partial or truncated name AND exactly
#                    one person in this publication's subject area fits it. A
#                    real judgement call. Flagged, never auto-applied.
#   organisation     Not a person at all. Should not carry a personal name.
#   searched         Looked, found nothing that ties the address to a person.
#
# Exact-address searches were run on this cohort first. Consumer addresses
# almost never appear in a public page, which is why the identifications below
# lean on what the address spells rather than on a search hit.
CONSUMER_FINDINGS = [
 # -- address-encoded: safe, and a plain improvement on the current mangled form
 dict(email="rachelfine515@gmail.com", name="Rachel Fine", conf="address-encoded",
      note="First and surname both already in the database's own name vocabulary."),
 dict(email="benwolf1132@gmail.com", name="Ben Wolf", conf="address-encoded",
      note="Both parts known to the database. Could be short for Wolfson; Wolf is the literal reading."),
 dict(email="jimpickman@gmail.com", name="Jim Pickman", conf="address-encoded", note=""),
 dict(email="claraoshea5@gmail.com", name="Clara O'Shea", conf="address-encoded",
      note="Apostrophe restored: 'oshea' is O'Shea."),
 dict(email="caitlinflood453@gmail.com", name="Caitlin Flood", conf="address-encoded", note=""),
 dict(email="jonmacone@yahoo.com", name="Jon Macone", conf="address-encoded", note=""),
 dict(email="jessetowsen@gmail.com", name="Jesse Towsen", conf="address-encoded", note=""),
 dict(email="sarahpcassel@gmail.com", name="Sarah P. Cassel", conf="address-encoded",
      note="Middle initial between the names."),
 dict(email="carlamariedavis@gmail.com", name="Carla Marie Davis", conf="address-encoded",
      note="Three-part name; the naive splitter cannot see this one."),
 dict(email="jimjohnsonemail@yahoo.com", name="Jim Johnson", conf="address-encoded",
      note="The trailing 'email' is a suffix, not part of the surname."),
 # -- likely: the judgement calls, for Josh not for the machine
 dict(email="vgullap@gmail.com", name="Vaidya Gullapalli", conf="likely",
      url="https://muckrack.com/vaidya-gullapalli",
      note="'vgullap' is a truncation of v-gullapalli. She is a criminal justice journalist and "
           "lawyer, formerly of the Bronx Defenders and the Office of the Appellate Defender in New "
           "York, and wrote The Appeal's Daily Appeal — precisely this readership. The address itself "
           "appears nowhere public, so this is inference, not proof."),
 dict(email="clarawutsai@gmail.com", name="Clara Wu Tsai", conf="likely",
      url="",
      note="WORTH A HUMAN LOOK. The address spells a distinctive three-part name. If this is the "
           "Clara Wu Tsai, she funds criminal justice reform heavily and is a significant prospect. "
           "The address has no public footprint, so the identity is unconfirmed — do not treat as a "
           "funder record until someone checks. 98% open rate since March 2022."),
 dict(email="carlhamad@gmail.com", name="", conf="likely",
      url="https://envisionfreedom.org/about-us/remembering-carl-hamad-lipscombe/",
      note="HANDLE WITH CARE, DO NOT SOLICIT. Possibly Carl Hamad-Lipscombe, executive director of "
           "Envision Freedom Fund, who died in 2024. If it is him the record should be suppressed, "
           "not enriched. If there has been engagement since March 2024 it is someone else. Either "
           "way a name should not be written in without checking."),
 # -- organisations, not people
 dict(email="coneygravesendtaskforce@yahoo.com", name="", employer="Coney Island / Gravesend community task force",
      conf="organisation",
      note="A shared organisational mailbox. Currently carries the personal name "
           "'Coneygravesendtaskforce'. Should be flagged as an organisation so it never appears in a "
           "personal salutation."),
 dict(email="centerforadvancedprosecution@gmail.com", name="", employer="Center for Advanced Prosecution",
      conf="organisation",
      note="Same: an organisational mailbox carrying a personal name."),
 # -- searched, nothing solid
 dict(email="meisenholdert@gmail.com", name="", conf="searched",
      note="No Eisenholder/Eisenholdt found in New York policy or nonprofit records."),
]

# Domain -> proper organisation name, for records whose employer is a mangled
# domain string. Applies beyond the individuals above.
DOMAIN_FIX = {
 "ocbaacp.org": "Onondaga County Bar Association Assigned Counsel Program",
 "bcfny.org": "Brooklyn Org (formerly Brooklyn Community Foundation)",
 "appad.org": "Appellate Advocates",
 "ceoworks.org": "Center for Employment Opportunities",
 "osc.ny.gov": "Office of the New York State Comptroller",
 "apdscorporate.com": "Orijin (formerly APDS)",
 "lemosandcrane.co.uk": "Lemos&Crane",
 "dpw.com": "Davis Polk & Wardwell",
 "citizensunionfoundation.org": "Citizens Union Foundation",
 "1235strategies.com": "1235 Strategies",
 "mccreightpartners.com": "McCreight Partners",
}


def devoted(r):
    return (not r.get("unsub")) and ((r.get("erate") or 0) >= 4
                                     or ((r.get("erate") or 0) >= 3 and (r.get("eclick") or 0) > 0))


def weak_name(r):
    n = (r.get("n") or "").strip()
    return (not n) or (r.get("ns") == "guess" and len(n.split()) < 2)


def main():
    people = json.loads((PRIV / "people.json").read_text())
    by_email = {}
    for r in people:
        for e in (r.get("emails") or [r.get("e")]):
            if e: by_email[e.strip().lower()] = r

    out = []
    merged = {}
    for f in FINDINGS + CONSUMER_FINDINGS + SEARCH_FINDINGS + BROWSER_FINDINGS:
        merged[f["email"].lower()] = f      # a later, better-sourced finding supersedes an earlier one
    for f in merged.values():
        r = by_email.get(f["email"].lower())
        if not r:
            print(f"  WARNING: {f['email']} is no longer in people.json — skipping")
            continue
        out.append({
            **f,
            "current_name": r.get("n") or "",
            "current_employer": r.get("inst") or "",
            "name_changes": bool(f.get("name")) and (f["name"] != (r.get("n") or "")),
            "employer_changes": bool(f.get("employer")) and (f["employer"] != (r.get("inst") or "")),
            "open_rate_pct": r.get("eopen") or 0, "click_rate_pct": r.get("eclick") or 0,
            "rating": r.get("erate") or 0, "donor": bool(r.get("don")),
        })

    (PRIV / "reader_enrichment.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    cols = ["conf", "email", "current_name", "name", "current_employer", "employer", "role",
            "open_rate_pct", "click_rate_pct", "rating", "donor", "url", "note"]
    with open(PRIV / "reader_enrichment.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in sorted(out, key=lambda x: (x["conf"] != "confirmed", x["conf"], -x["click_rate_pct"])):
            w.writerow(row)

    # A ready-to-append block for name_overrides.csv, confirmed rows only.
    promote = [o for o in out if o["conf"] in ("confirmed", "address-encoded") and o["name_changes"]]
    (PRIV / "reader_enrichment_promote.csv").write_text(
        "email,name\n" + "".join(f'{o["email"]},{o["name"]}\n' for o in promote))

    # How much of the devoted cohort is still unfilled, so the number is honest.
    dev = [r for r in people if devoted(r)]
    need = [r for r in dev if weak_name(r) or not (r.get("inst") or "").strip()]
    covered = {f["email"].lower() for f in FINDINGS}
    left = [r for r in need if not ({(e or "").lower() for e in (r.get("emails") or [])} & covered)]
    print(f"devoted readers: {len(dev)} | missing a name or employer: {len(need)}")
    from collections import Counter
    tiers = Counter(o["conf"] for o in out)
    print("researched here: %d | %s" % (len(out), " | ".join(f"{k}: {v}" for k, v in sorted(tiers.items()))))
    print(f"still open: {len(left)} — the exact-address sweep in find_reader_names.py is working "
          f"through these; Google Scholar rate-limits after a few queries, so it resumes in rounds")
    print(f"ready to promote into name_overrides.csv: {len(promote)}")
    print(f"wrote {PRIV/'reader_enrichment.csv'} and {PRIV/'reader_enrichment_promote.csv'}")


if __name__ == "__main__":
    main()
