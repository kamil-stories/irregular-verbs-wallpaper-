"""Generate irregular-verb lock-screen wallpapers.

Usage:
  python3 src/build.py --samples [DAY]   # 3 sample cards for one day -> samples/
  python3 src/build.py --all             # every day/slot -> images/
"""
import html
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
W, H = 1320, 2868
INTERVALS = (1, 3, 7, 21)  # spaced-repetition offsets, days

GROUPS = {
    "AAA": ("#7CC4FF", "все три одинаковые"),
    "AAB": ("#FF8FC7", "1-я = 2-я"),
    "ABA": ("#B79CFF", "1-я = 3-я"),
    "ABB": ("#C6F35A", "2-я = 3-я"),
    "ABC": ("#FF7A45", "все три разные"),
}


def group(v):
    a, b, c = v["base"], v["past"].split("/")[0], v["pp"].split("/")[0]
    if a == b == c:
        return "AAA"
    if b == c:
        return "ABB"
    if a == c:
        return "ABA"
    if a == b:
        return "AAB"
    return "ABC"


def changed_span(base, form):
    """(start, end) of the part of `form` that differs from `base`."""
    p = 0
    while p < min(len(base), len(form)) and base[p] == form[p]:
        p += 1
    s = 0
    while s < min(len(base), len(form)) - p and base[-1 - s] == form[-1 - s]:
        s += 1
    return p, len(form) - s


def mark(word, idx):
    """HTML for `word` with indices in `idx` wrapped in <em>."""
    out = ""
    for i, ch in enumerate(word):
        c = html.escape(ch)
        out += f"<em>{c}</em>" if i in idx else c
    return out.replace("</em><em>", "")


def mark_form(base, form):
    parts = []
    for f in form.split("/"):
        a, b = changed_span(base, f)
        parts.append(mark(f, set(range(a, b))))
    return '<span class="slash">/</span>'.join(parts)


def mark_base(v):
    base, idx = v["base"], set()
    for form in (v["past"] + "/" + v["pp"]).split("/"):
        a, b = changed_span(form, base)  # span inside base that differs from form
        idx |= set(range(a, b))
    return mark(base, idx)


# ---------- schedule ----------

def schedule(n):
    """day -> {"new": verb index | None, "due": [(verb index, interval)]}"""
    last = n + max(INTERVALS)
    days = {}
    for d in range(1, last + 1):
        new = d - 1 if d <= n else None
        due = [(d - k - 1, k) for k in INTERVALS if 1 <= d - k <= n]
        days[d] = {"new": new, "due": due}
    return days


def slots(day):
    """3 cards for a day: (kind, items)."""
    new, due = day["new"], day["due"] or [(day["new"], 0)]
    if new is not None:
        return [("new", [(new, 0)]), ("quiz", due), ("answer", due)]
    return [("quiz", due), ("answer", due), ("answer", due)]


# ---------- HTML ----------

def head():
    css = (ROOT / "src" / "style.css").read_text()
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1'
        '&family=Manrope:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=block" rel="stylesheet">'
        f"<style>{css}</style></head>"
    )


def badge(g):
    color, desc = GROUPS[g]
    return (f'<div class="badge"><span class="dot"></span><b>{g}</b>'
            f'<span class="desc">{desc}</span></div>')


def ticks(n, total):
    return '<div class="ticks">' + "".join(
        f'<i class="{"on" if i < n else ""}{" cur" if i == n - 1 else ""}"></i>' for i in range(total)
    ) + "</div>"


def card_new(v, num, total):
    g = group(v)
    note = f'<div class="note">{html.escape(v["note"])}</div>' if "note" in v else ""
    return f"""
<div class="meta"><span class="mono">{num:03d} <span class="dim">/ {total}</span></span>{badge(g)}</div>
<div class="rule"></div>
<div class="kicker">new · новый глагол</div>
<div class="base fit">{mark_base(v)}</div>
<div class="ru">{html.escape(v["ru"])}</div>
<div class="forms">
  <div><div class="form fit">{mark_form(v["base"], v["past"])}</div><div class="lbl">past simple</div></div>
  <div><div class="form fit">{mark_form(v["base"], v["pp"])}</div><div class="lbl">past participle</div></div>
</div>
{note}
<div class="rule"></div>
{ticks(num, total)}
""", g


def plural_days(k):
    return "сегодня" if k == 0 else f"+{k} {'день' if k == 1 else 'дня' if k < 5 else 'дней'}"


def card_rows(verbs, items, reveal, daynum):
    rows = ""
    for i, k in items:
        v = verbs[i]
        if reveal:
            forms = (f'<span class="f">{mark_form(v["base"], v["past"])}</span>'
                     f'<span class="arr">→</span><span class="f">{mark_form(v["base"], v["pp"])}</span>')
        else:
            forms = '<span class="q">?</span><span class="arr">→</span><span class="q">?</span>'
        rows += f"""
<div class="row" style="--accent:{GROUPS[group(v)][0]}">
  <div class="rtop"><span class="rbase fit">{mark_base(v) if reveal else html.escape(v["base"])}</span>
    <span class="ago mono">{plural_days(k)}</span></div>
  <div class="rru">{html.escape(v["ru"])}</div>
  <div class="rforms"><span class="arr">→</span>{forms}</div>
</div>"""
    kicker = "answer · проверь себя" if reveal else "recall · вспомни формы"
    return f"""
<div class="meta"><span class="mono">день {daynum:03d}</span><span class="mono dim">{len(items)} × повтор</span></div>
<div class="rule"></div>
<div class="kicker">{kicker}</div>
<div class="rows">{rows}</div>
<div class="rule"></div>
"""


def page(body, accent, kind):
    return (head() + f'<body class="{kind}" style="--accent:{accent}">'
            f'<main class="safe">{body}</main></body></html>')


def render_day(verbs, days, d):
    total = len(verbs)
    out = []
    for kind, items in slots(days[d]):
        if kind == "new":
            body, g = card_new(verbs[items[0][0]], items[0][0] + 1, total)
            accent = GROUPS[g][0]
        else:
            body = card_rows(verbs, items, kind == "answer", d)
            accent = "#F2EEE6"
        out.append(page(body, accent, kind))
    return out


FIT_JS = """
() => {
  for (const el of document.querySelectorAll('.fit')) {
    const max = el.parentElement.clientWidth;
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > max && size > 20) { size *= 0.96; el.style.fontSize = size + 'px'; }
  }
}
"""


def shoot(pages_and_paths):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for html_s, path in pages_and_paths:
            pg.set_content(html_s, wait_until="networkidle")
            pg.evaluate("document.fonts.ready.then(() => 0)")
            pg.evaluate(FIT_JS)
            path.parent.mkdir(parents=True, exist_ok=True)
            pg.screenshot(path=str(path))
        b.close()


def main():
    verbs = json.loads((ROOT / "data" / "verbs.json").read_text())
    days = schedule(len(verbs))

    # sanity: every verb introduced once and reviewed at every interval
    seen = {}
    for d, day in days.items():
        for i, k in day["due"]:
            seen.setdefault(i, []).append(k)
    assert all(seen[i] == list(INTERVALS) for i in range(len(verbs))), "schedule broken"

    if "--samples" in sys.argv:
        d = int(sys.argv[2]) if len(sys.argv) > 2 else 47
        names = ["1-new", "2-quiz", "3-answer"]
        jobs = [(h, ROOT / "samples" / f"day-{d:03d}-{n}.png") for h, n in zip(render_day(verbs, days, d), names)]
    elif "--all" in sys.argv:
        jobs = [(h, ROOT / "images" / f"day-{d:03d}-{s + 1}.png")
                for d in days for s, h in enumerate(render_day(verbs, days, d))]
    else:
        sys.exit(__doc__)
    shoot(jobs)
    print(f"{len(jobs)} images, {len(days)} days")


if __name__ == "__main__":
    main()
