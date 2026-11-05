# rata.md

Comparison of loan offers from 10 Moldovan banks. Static site on GitHub Pages.

## How the site is built

- **`index.html` is the only file to edit by hand.** Offers live in the `offers-data` JSON block, rate history in `rate-history`, UI texts and FAQ in the `I18N` object.
- `tools/build.py` opens the page in headless Chrome once per language, lets the app render, and writes the result into static HTML:
  - `index.html` — Romanian page (`https://rata.md/`); only the `SEO:HEAD` block, the `data-i` texts, the offers table, the result count and the sort options are rewritten
  - `ru/index.html`, `en/index.html` — Russian and English pages
  - `sitemap.xml` (with hreflang alternates), `robots.txt`
- Each page has its own `<title>`, description, canonical, hreflang and FAQ markup, taken from `I18N` (`title`, `metaDesc`, `q1`…`a4`).
- The language is fixed by the URL. The RO/RU/EN toggle navigates between `/`, `/ru/` and `/en/`; a returning visitor who picked RU or EN is sent from `/` to their language.
- The GitHub Action `.github/workflows/build.yml` runs the script on every push that touches `index.html` or `tools/`, and commits the result.

To run locally: `pip install playwright && python -m playwright install chromium && python3 tools/build.py`
(or point it at an installed Chrome with `CHROME=/path/to/chrome`).

## When updating data

1. Edit the offers in `index.html` and add a snapshot to `rate-history` — the latest snapshot date is the "data as of" date everywhere, including `sitemap.xml`.
2. Push. The Action rebuilds the language pages and the sitemap within a couple of minutes.
