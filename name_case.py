"""Proper capitalization for people's names, shared by every toolkit build.

Names arrive as people typed them into Ghost, Mailchimp and Donorbox: "John
ARNOLD", "Barry cooper". This fixes only the words that are entirely capitals or
entirely lowercase, and leaves deliberate mixed case alone (McKinsey, DeBlasio,
"K-D"). Initials, roman numerals, lowercase particles (de, van, von) and anything
that looks like an organization rather than a person are left as they are.
"""
import re

PARTICLES = {"de", "da", "di", "del", "della", "der", "den", "des", "du", "la", "le",
             "van", "von", "y", "e", "and", "und", "et", "bin", "ibn", "al", "el", "dos", "das", "do", "ten", "ter"}
KEEP_UPPER = {"II", "III", "IV", "VI", "NYC", "USA", "UK"}   # not MD/JD: "Md." abbreviates Muhammad
ORG_WORDS = re.compile(
    r"\b(foundation|fund|council|institute|center|centre|project|network|news|trust|giving|"
    r"association|society|committee|coalition|university|college|school|office|department|"
    r"agency|group|partners|llc|inc|corp|company|media|press|board|roundtable|america|"
    r"justice|campaign|program|initiative|alliance|club|church|union|city|state|county|"
    r"team|staff|editors?|service|services)\b", re.I)

def _word(w, first, shouting=False):
    letters = re.sub(r"[^A-Za-zÀ-ɏ]", "", w)
    if len(letters) < 2:
        return w                                   # initials: J. or J
    if re.fullmatch(r"Mc[A-Z]{3,}", letters):       # McKINSEY: the prefix hides the capitals
        return "Mc" + letters[2:3] + letters[3:].lower()
    if letters.isupper() and w.lower() in PARTICLES and not first and shouting:
        return w.lower()                           # "Bill DE BLASIO" -> de
    if w.upper().strip(".,") in KEEP_UPPER:
        return w.upper() if w.upper().strip(".,") != "JR" and w.upper().strip(".,") != "SR" else w.capitalize()
    if re.fullmatch(r"(?:[A-Z]\.){2,}", w):        # R.A.E.
        return w
    if not (letters.isupper() or letters.islower()):
        return w                                   # deliberate mixed case: leave it
    if letters.islower() and w in PARTICLES and not first:
        return w
    if letters.isupper() and (len(letters) <= 2 or not re.search(r"[AEIOUY]", letters)):
        return w                                   # "JD", "MJ", "DHR": initials, not a name
    def cap(part):
        low = part.lower()
        out = low[:1].upper() + low[1:]
        out = re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), out)
        out = re.sub(r"^(O|D)(['’])([a-z])", lambda m: m.group(1) + m.group(2) + m.group(3).upper(), out)
        return out
    return "-".join(cap(p) for p in w.split("-"))

def fix_name_case(name):
    """Return the name with badly cased words fixed; anything else unchanged."""
    if not isinstance(name, str):
        return name
    s = name.strip()
    if not s or "@" in s or re.search(r"\d", s) or ORG_WORDS.search(s):
        return name
    words = s.split()
    if len(words) > 6 or any(re.search(r"[()\[\]{}!?;:/\\|]", w) for w in words):
        return name
    shouting = any(len(re.sub(r"[^A-Za-z]", "", w)) >= 3 and re.sub(r"[^A-Za-z]", "", w).isupper() for w in words)
    fixed = " ".join(_word(w, i == 0, shouting) for i, w in enumerate(words))
    return fixed if fixed != s else name

if __name__ == "__main__":
    tests = ["John ARNOLD", "Barry cooper", "arthur williams", "Martin chilewich", "JOHN ARNOLD",
             "Ana Margarida Amorim dos Santos", "Colin K-D", "R.A.E. Wells", "Hugh McKINSEY",
             "Bill DE BLASIO", "Ludwig van beethoven", "PATRICK O'BRIEN", "John Arnold Jr.",
             "Martin Luther King III", "Council on Criminal Justice", "ABNY Foundation",
             "An expert roundtable", "MJ Slaby", "DeRay McKesson", "jean-paul SARTRE", "Denise DHR"]
    for t in tests:
        print(f"{t!r:36} -> {fix_name_case(t)!r}")
