#!/usr/bin/env python3
"""Build the language pages and SEO files for rata.md.

index.html is the single source of truth: edit offers, translations and the app there.
This script opens the page in headless Chrome once per language, lets the app render
itself, and writes what it rendered into static HTML, so search engines get the full
content without running JavaScript. It (re)generates, idempotently:

  index.html      Romanian page — only the generated parts are rewritten in place
  ru/index.html   Russian page
  en/index.html   English page
  sitemap.xml     the three URLs with hreflang alternates
  robots.txt      allows everything, points to the sitemap

Generated per language:
  * <html lang>, <title>, meta description, canonical, hreflang, Open Graph,
    JSON-LD (WebSite + FAQPage from the visible FAQ)
  * window.RATA_LANG, so the app opens in the page's language whatever the browser says
  * every [data-i] text and placeholder, the "data as of" badge, the language toggle state
  * the offers table (#browseRows), the result count and the sort options

The app rebuilds all of these on load, so the prerendered markup is only what is
visible before JavaScript runs, and it is exactly what the app would draw.

Run:   pip install playwright && python3 tools/build.py
       (set CHROME=/path/to/chrome to use an installed Chrome instead of
        `python -m playwright install chromium`)
The GitHub Action .github/workflows/build.yml runs it on every push.
"""
import asyncio
import html
import json
import os
import re
import sys

from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.html")
SITE = "https://rata.md"
LANGS = ["ro", "ru", "en"]
PATHS = {"ro": "/", "ru": "/ru/", "en": "/en/"}
OG_LOCALE = {"ro": "ro_MD", "ru": "ru_MD", "en": "en_GB"}

# What the browser hands back after the app has rendered in a given language.
COLLECT_JS = r"""() => {
  const out = {texts: {}, placeholders: {}, faq: []};
  out.title = document.title;
  const md = document.querySelector('meta[name="description"]');
  out.desc = md ? md.getAttribute('content') : '';
  document.querySelectorAll('[data-i]').forEach(el => {
    if (!el.children.length) out.texts[el.getAttribute('data-i')] = el.textContent;
  });
  document.querySelectorAll('[data-i-ph]').forEach(el => {
    out.placeholders[el.getAttribute('data-i-ph')] = el.getAttribute('placeholder') || '';
  });
  out.badge = document.getElementById('badgeText').textContent;
  out.rows = document.getElementById('browseRows').innerHTML;
  out.rowCount = document.querySelectorAll('#browseRows tr').length;
  out.resultCount = document.getElementById('resultCount').innerHTML;
  out.sortOptions = document.getElementById('sortSelect').innerHTML;
  document.querySelectorAll('#faq details').forEach(d => {
    const q = d.querySelector('summary [data-i]'), a = d.querySelector('p[data-i]');
    if (q && a && q.textContent.trim() && a.textContent.trim())
      out.faq.push([q.textContent.trim(), a.textContent.trim()]);
  });
  return out;
}"""


def esc(s):
    return html.escape(str(s), quote=True)


def replace_once(doc, pattern, repl, what, flags=re.S):
    new, n = re.subn(pattern, repl, doc, count=1, flags=flags)
    if n != 1:
        sys.exit("build.py: could not find %s in index.html" % what)
    return new


def as_of_date(src):
    m = re.search(r'<script type="application/json" id="rate-history">(.*?)</script>', src, re.S)
    snaps = json.loads(m.group(1))["snapshots"]
    return max(s["date"] for s in snaps)  # same "as of" date the app shows (ISO yyyy-mm-dd)


async def render_all(src):
    """Render the page once per language and collect what the app drew."""
    results = {}
    async with async_playwright() as p:
        kw = {"args": ["--no-sandbox"]}
        if os.environ.get("CHROME"):
            kw["executable_path"] = os.environ["CHROME"]
        browser = await p.chromium.launch(**kw)
        for lang in LANGS:
            ctx = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
            page = await ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            # No network needed: fonts are cosmetic and the page has no other external resources.
            await page.route("**/*", lambda route: route.abort()
                             if not route.request.url.startswith("https://rata.md/") else route.continue_())
            forced = src.replace("<!-- /SEO:HEAD -->",
                                 '<script>window.RATA_LANG="%s";</script>\n<!-- /SEO:HEAD -->' % lang, 1)
            def serve(body):
                return lambda route: route.fulfill(
                    status=200, content_type="text/html; charset=utf-8", body=body)
            await page.route("https://rata.md/", serve(forced))
            await page.goto("https://rata.md/")
            await page.wait_for_function("document.querySelectorAll('#browseRows tr').length > 0")
            data = await page.evaluate(COLLECT_JS)
            if errors:
                sys.exit("build.py: JavaScript errors while rendering %s: %s" % (lang, errors))
            results[lang] = data
            await ctx.close()
        await browser.close()
    return results


def build_head(lang, r, date_iso):
    url = SITE + PATHS[lang]
    alts = [('<link rel="alternate" hreflang="%s" href="%s">' % (l, SITE + PATHS[l])) for l in LANGS]
    alts.append('<link rel="alternate" hreflang="x-default" href="%s">' % (SITE + PATHS["ro"]))
    graph = [
        {"@type": "WebSite", "@id": SITE + "/#website", "name": "rata.md", "url": SITE + "/",
         "inLanguage": LANGS},
        {"@type": "WebPage", "@id": url + "#webpage", "url": url, "name": r["title"],
         "description": r["desc"], "inLanguage": lang, "isPartOf": {"@id": SITE + "/#website"},
         "dateModified": date_iso},
    ]
    if r["faq"]:
        graph.append({"@type": "FAQPage", "@id": url + "#faq", "inLanguage": lang, "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in r["faq"]]})
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    ld = ld.replace("</", "<\\/")
    return "\n".join([
        "<title>%s</title>" % esc(r["title"]),
        '<meta name="description" content="%s">' % esc(r["desc"]),
        '<link rel="canonical" href="%s">' % url,
        *alts,
        '<meta property="og:type" content="website">',
        '<meta property="og:site_name" content="rata.md">',
        '<meta property="og:url" content="%s">' % url,
        '<meta property="og:title" content="%s">' % esc(r["title"]),
        '<meta property="og:description" content="%s">' % esc(r["desc"]),
        '<meta property="og:locale" content="%s">' % OG_LOCALE[lang],
        '<script type="application/ld+json">%s</script>' % ld,
        '<script>window.RATA_LANG="%s";</script>' % lang,
    ])


def normalize_attrs(markup):
    """Chromium versions differ in escaping < and > inside attribute values; pin one form."""
    return re.sub(r'="([^"]*)"',
                  lambda m: '="' + m.group(1).replace("<", "&lt;").replace(">", "&gt;") + '"', markup)


def build_page(src, lang, r, date_iso):
    doc = replace_once(src, r'<html lang="[^"]*"', '<html lang="%s"' % lang, "<html lang>")
    doc = replace_once(doc, r"(<!-- SEO:HEAD\b[^>]*-->).*?(<!-- /SEO:HEAD -->)",
                       lambda m: m.group(1) + "\n" + build_head(lang, r, date_iso) + "\n" + m.group(2),
                       "SEO:HEAD markers")

    # Visible texts: only elements whose content is plain text are touched.
    for key, text in r["texts"].items():
        doc = re.sub(r'(<(\w+)\b[^>]*\bdata-i="%s"[^>]*>)[^<]*(</\2>)' % re.escape(key),
                     lambda m: m.group(1) + esc(text) + m.group(3), doc)
    for key, text in r["placeholders"].items():
        doc = re.sub(r'(<input\b[^>]*\bdata-i-ph="%s")(?:\s+placeholder="[^"]*")?' % re.escape(key),
                     lambda m: m.group(1) + ' placeholder="%s"' % esc(text), doc)

    doc = replace_once(doc, r'(<span id="badgeText">)[^<]*(</span>)',
                       lambda m: m.group(1) + esc(r["badge"]) + m.group(2), "#badgeText")
    doc = replace_once(doc, r'(<tbody id="browseRows">).*?(</tbody>)',
                       lambda m: m.group(1) + normalize_attrs(r["rows"]) + m.group(2), "#browseRows")
    doc = replace_once(doc, r'(<p class="count" id="resultCount"[^>]*>).*?(</p>)',
                       lambda m: m.group(1) + normalize_attrs(r["resultCount"]) + m.group(2), "#resultCount")
    doc = replace_once(doc, r'(<select class="select" id="sortSelect">).*?(</select>)',
                       lambda m: m.group(1) + normalize_attrs(r["sortOptions"]) + m.group(2), "#sortSelect")
    doc = re.sub(r'(<button type="button" data-lang="(\w+)" aria-pressed=")(?:true|false)(")',
                 lambda m: m.group(1) + ("true" if m.group(2) == lang else "false") + m.group(3), doc)
    return doc


def build_sitemap(date_iso):
    urls = []
    for l in LANGS:
        alts = "".join('\n    <xhtml:link rel="alternate" hreflang="%s" href="%s"/>' % (a, SITE + PATHS[a])
                       for a in LANGS)
        alts += '\n    <xhtml:link rel="alternate" hreflang="x-default" href="%s"/>' % (SITE + PATHS["ro"])
        urls.append("  <url>\n    <loc>%s</loc>\n    <lastmod>%s</lastmod>%s\n  </url>"
                    % (SITE + PATHS[l], date_iso, alts))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(urls) + "\n</urlset>\n")


ROBOTS = "User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n" % SITE


def write(path, content):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    old = open(full, encoding="utf-8").read() if os.path.exists(full) else None
    if old != content:
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print("updated", path)


def main():
    src = open(SRC, encoding="utf-8").read()
    date_iso = as_of_date(src)
    rendered = asyncio.run(render_all(src))
    for lang in LANGS:
        r = rendered[lang]
        if r["rowCount"] == 0:
            sys.exit("build.py: the offers table rendered empty for %s" % lang)
        page = build_page(src, lang, r, date_iso)
        write("index.html" if lang == "ro" else "%s/index.html" % lang, page)
        print("%s: %d offers, title: %s" % (lang, r["rowCount"], r["title"]))
    write("sitemap.xml", build_sitemap(date_iso))
    write("robots.txt", ROBOTS)


if __name__ == "__main__":
    main()
