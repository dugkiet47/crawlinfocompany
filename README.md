# MaSoThue company crawler

Python source crawler with two flows:

- `search`: search a company name or an exact tax ID.
- `all`: discover locality URLs, read company listings, and optionally fetch each company's detail URL.

Install and run from this directory:

```sh
python -m venv .venv
# Activate .venv for your shell, then:
python -m pip install -r requirements.txt
python crawl.py all --province ha-noi --max-pages 1 --max-records 1 --detail --delay 10 --format both
```

`--max-records` is a total run limit across selected localities. `--max-pages` is a per-locality limit. With no limits the `all` command can make many requests. Start with a bounded run and the access/rate limits agreed with the source. CSV and XLSX files are written under `output/`.

Use the Python sources for this update. The pre-existing `crawlmst.zip` artifact has not been rebuilt and does not contain these fixes.

## Correctness and stopping rules

- Tax IDs have 10 digits, or a 10-digit parent plus a 3-digit branch suffix. Compact 13-digit branch IDs normalize to `XXXXXXXXXX-XXX`.
- A numeric search must match the exact requested tax ID. A redirect to another company's detail page raises an error instead of exporting that company. This detects incorrect source responses; it does not repair the source's search service.
- Detail fetches verify the listing's expected tax ID. Conflicting table/heading IDs are rejected.
- Locality URLs are deduplicated independently of their displayed labels. These are the source's locality categories, not a verified current administrative registry.
- Listing pagination follows an advertised next link only on the same source/path with the same other query filters. Records are deduplicated within a locality.
- Redirects stay on the source and use the configured request interval. HTTP 403, 429 and recognized challenge pages stop immediately. Other 4xx responses are not retried. Network failures and 5xx responses have bounded retries.
- On a refusal or data mismatch the CLI returns exit status 1 and does not export a new partial result for that run. Previous output files are not deleted.

## Verification

Run the synthetic regression tests, without live requests:

```sh
python -m unittest discover -s tests -v
```

On 2026-11-12, a separate bounded evaluation exercised the original sources and the patched scraper against the live directory, one Hanoi listing and one observed detail link. Both runs returned HTTP 200 for all three stages, read five listing records, and matched the selected listing tax ID to its detail page. Five available fields matched a separate table reader on the same fetched HTML; this is not official tax-registry validation. No operation date was present for the selected record.

The patched run also repeated a tax search that redirected to a different company's profile (HTTP 302 then 200). The patched scraper rejected that mismatch. Each evaluation used a transparent evaluation User-Agent, a 10-second request interval, no proxy or challenge solving, and a request budget. No raw response HTML was retained. Live multi-page crawling and all-locality coverage have not been verified; pagination/branch cases are covered by synthetic tests.
