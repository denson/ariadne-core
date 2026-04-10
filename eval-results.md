# Ariadne Core — Format Coverage Eval Results

**Run timestamp:** 2026-04-05T04:07:29.701228+00:00
**Model:** claude-opus-4-6
**Collection:** `eval-format-coverage`
**Total files in corpus:** 231
**store:** `true` (documents are searchable via MCP `search` tool)

## 1. Summary by Extension

| Extension | Total | Succeeded | Failed | Skipped | Timeout |
|-----------|-------|-----------|--------|---------|---------|
| `(none)` | 1 | 1 | 0 | 0 | 0 |
| `.bmp` | 1 | 0 | 1 | 0 | 0 |
| `.csv` | 10 | 10 | 0 | 0 | 0 |
| `.doc` | 5 | 1 | 4 | 0 | 0 |
| `.docx` | 20 | 19 | 0 | 1 | 0 |
| `.eml` | 40 | 39 | 1 | 0 | 0 |
| `.epub` | 3 | 3 | 0 | 0 | 0 |
| `.go` | 1 | 1 | 0 | 0 | 0 |
| `.heic` | 1 | 0 | 1 | 0 | 0 |
| `.htm` | 1 | 1 | 0 | 0 | 0 |
| `.html` | 16 | 16 | 0 | 0 | 0 |
| `.jpeg` | 2 | 2 | 0 | 0 | 0 |
| `.jpg` | 8 | 8 | 0 | 0 | 0 |
| `.json` | 3 | 3 | 0 | 0 | 0 |
| `.md` | 6 | 6 | 0 | 0 | 0 |
| `.msg` | 5 | 4 | 0 | 1 | 0 |
| `.ndjson` | 2 | 2 | 0 | 0 | 0 |
| `.odt` | 3 | 0 | 3 | 0 | 0 |
| `.org` | 3 | 3 | 0 | 0 | 0 |
| `.p7s` | 1 | 1 | 0 | 0 | 0 |
| `.pdf` | 37 | 32 | 2 | 3 | 0 |
| `.png` | 3 | 3 | 0 | 0 | 0 |
| `.ppt` | 2 | 1 | 1 | 0 | 0 |
| `.pptx` | 12 | 12 | 0 | 0 | 0 |
| `.py` | 1 | 1 | 0 | 0 | 0 |
| `.rst` | 3 | 3 | 0 | 0 | 0 |
| `.rtf` | 2 | 2 | 0 | 0 | 0 |
| `.tiff` | 2 | 0 | 2 | 0 | 0 |
| `.tsv` | 2 | 2 | 0 | 0 | 0 |
| `.txt` | 18 | 17 | 1 | 0 | 0 |
| `.wav` | 1 | 0 | 1 | 0 | 0 |
| `.xls` | 1 | 1 | 0 | 0 | 0 |
| `.xlsx` | 9 | 8 | 0 | 1 | 0 |
| `.xml` | 3 | 3 | 0 | 0 | 0 |
| `.xsl` | 1 | 1 | 0 | 0 | 0 |
| `.yaml` | 1 | 1 | 0 | 0 | 0 |
| `.zip` | 1 | 1 | 0 | 0 | 0 |
| **TOTAL** | **231** | **208** | **17** | **6** | **0** |

## 2. Format Support Matrix

| Extension | Verdict | Notes |
|-----------|---------|-------|
| `(none)` | &#x2705; supported | quality: empty=1 |
| `.bmp` | &#x274C; unsupported |  |
| `.csv` | &#x2705; supported | quality: good=10 |
| `.doc` | &#x26A0; partial | quality: good=1 |
| `.docx` | &#x26A0; partial | quality: good=3, partial=16 |
| `.eml` | &#x26A0; partial | quality: empty=1, good=38 |
| `.epub` | &#x2705; supported | quality: good=2, partial=1 |
| `.go` | &#x2705; supported | quality: good=1 |
| `.heic` | &#x274C; unsupported |  |
| `.htm` | &#x2705; supported | quality: good=1 |
| `.html` | &#x2705; supported | quality: good=9, partial=7 |
| `.jpeg` | &#x2705; supported | quality: empty=2 |
| `.jpg` | &#x2705; supported | quality: empty=8 |
| `.json` | &#x2705; supported | quality: good=3 |
| `.md` | &#x2705; supported | quality: good=6 |
| `.msg` | &#x26A0; partial | quality: partial=4 |
| `.ndjson` | &#x2705; supported | quality: good=2 |
| `.odt` | &#x274C; unsupported |  |
| `.org` | &#x2705; supported | quality: good=3 |
| `.p7s` | &#x2705; supported | quality: good=1 |
| `.pdf` | &#x26A0; partial | quality: empty=3, good=2, partial=27 |
| `.png` | &#x2705; supported | quality: empty=3 |
| `.ppt` | &#x26A0; partial | quality: partial=1 |
| `.pptx` | &#x2705; supported | quality: partial=12 |
| `.py` | &#x2705; supported | quality: good=1 |
| `.rst` | &#x2705; supported | quality: good=3 |
| `.rtf` | &#x2705; supported | quality: good=2 |
| `.tiff` | &#x274C; unsupported |  |
| `.tsv` | &#x2705; supported | quality: good=2 |
| `.txt` | &#x26A0; partial | quality: empty=2, good=15 |
| `.wav` | &#x274C; unsupported |  |
| `.xls` | &#x2705; supported | quality: partial=1 |
| `.xlsx` | &#x26A0; partial | quality: good=2, partial=6 |
| `.xml` | &#x2705; supported | quality: good=3 |
| `.xsl` | &#x2705; supported | quality: good=1 |
| `.yaml` | &#x2705; supported | quality: good=1 |
| `.zip` | &#x2705; supported | quality: good=1 |

## 3. Gold Standard Comparison Results

No gold standard comparisons were computed.

## 4. Search Verification Results

These queries simulate how a Claude Cowork session would search the collection.

| # | Query | Purpose | Results | Expected Found | Interactions Present | Top Result Preview |
|---|-------|---------|---------|----------------|---------------------|-------------------|
| 1 | What are the government auditing standards? | natural-language | 5 | yes | yes | ndards require that we plan and perform the audit to obtain  |
| 2 | Show me data about currency codes and exchange rates | natural-language | 5 | yes | yes | \| 13 \|
\| NaN \| NaN \| NaN \| NaN \| NaN \| NaN \|
\| NaN \| Other \| |
| 3 | Find information about credit loan classification | natural-language | 5 | yes | yes | sections for the Fair
        Credit Reporting Act (15 U.S.C |
| 4 | What are the key points about hamburgers and dogs? | natural-language | 5 | yes | yes | This is a test document to use for unit tests.

Doylestown,  |
| 5 | Tell me about winter sports and skiing | natural-language | 5 | yes | yes | WINTER SPORTS IN SWITZERLAND |
| 6 | financial data tables and numbers | cross-format | 5 | n/a | yes | \|  \|  \|  \|  \|  \|
\| --- \| --- \| --- \| --- \| --- \|
\|  \|  \|  \|  |
| 7 | text formatting with headers and sections | cross-format | 5 | n/a | yes | {\rtf1\ansi\deff0
{\pard \ql \f0 \sa180 \li0 \fi0 \outlinele |
| 8 | images charts and visual content | cross-format | 5 | n/a | yes | ## ILLUSTRATIONS |
| 9 | government performance audit discussion and standards | gold-standard-retrieval | 5 | yes | yes | ndards require that we plan and perform the audit to obtain  |
| 10 | bank credit loan categories good bad | gold-standard-retrieval | 5 | yes | yes | Reclassifications. Certain accounts and financial statement  |
| 11 | currency codes country names monetary units | gold-standard-retrieval | 5 | yes | yes | \| 13 \|
\| NaN \| NaN \| NaN \| NaN \| NaN \| NaN \|
\| NaN \| Other \| |

### Interaction Metadata Samples

**Query:** "What are the government auditing standards?"
```json
{
  "agent_id": "eval-harness-format-coverage",
  "agent_type": "claude-cowork",
  "agent_notes": "Eval run: testing .html extraction. Large file (11.8MB). Ingested for format coverage eval and Cowork search testing.",
  "agent_metadata": {
    "eval_run": "format-coverage-v1",
    "eval_timestamp": "2026-04-05T04:07:29.701228+00:00",
    "file_extension": ".html",
    "file_size_bytes": 12356515,
    "expected_result": "success",
    "has_gold_standard": false,
    "gold_standard_type": null,
    "test_category": "supported-format",
    "corpus_source": "unstructured/example-docs"
  },
  "action": "ingest",
  "was_dedup_skip": false,
  "created_at": "2026-04-05T04:07:46.174906+00:00"
}
```

**Query:** "Show me data about currency codes and exchange rates"
```json
{
  "agent_id": "eval-harness-format-coverage",
  "agent_type": "claude-cowork",
  "agent_notes": "Eval run: testing .xlsx extraction. Ingested for format coverage eval and Cowork search testing.",
  "agent_metadata": {
    "eval_run": "format-coverage-v1",
    "eval_timestamp": "2026-04-05T04:07:29.701228+00:00",
    "file_extension": ".xlsx",
    "file_size_bytes": 12541,
    "expected_result": "success",
    "has_gold_standard": false,
    "gold_standard_type": null,
    "test_category": "supported-format",
    "corpus_source": "unstructured/example-docs"
  },
  "action": "ingest",
  "was_dedup_skip": false,
  "created_at": "2026-04-05T04:08:25.566187+00:00"
}
```


## 5. Failure Log

| File | Extension | Status | Error |
|------|-----------|--------|-------|
| `CantinaBand3.wav` | `.wav` | error | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - AudioConverter threw UnknownValueError with message: 
 |
| `book-war-and-peace-1225p.txt` | `.txt` | error | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PlainTextConverter threw UnicodeDecodeError with message: 'ascii' codec can't decode byte 0xc3 in position 107917: ordinal not  |
| `img/bmp_24.bmp` | `.bmp` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `img/layout-parser-paper-combined.tiff` | `.tiff` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `img/layout-parser-paper-fast.tiff` | `.tiff` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `pdf/invalid-pdf-structure-pdfminer-entire-doc.pdf` | `.pdf` | error | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConverter threw PSSyntaxError with message: Invalid dictionary construct: [/'Producer', b'pdfTeX-1.40.21', /b'Collaborative' |
| `pdf/pdf-bad-color-space.pdf` | `.pdf` | error | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConverter threw KeyError with message: 'N'
 |
| `duplicate-paragraphs.doc` | `.doc` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `fake-doc-emphasized-text.doc` | `.doc` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `fake-power-point.ppt` | `.ppt` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `fake.doc` | `.doc` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `fake.odt` | `.odt` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `simple.doc` | `.doc` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `simple.odt` | `.odt` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `eml/fake-email-utf-16-be.eml` | `.eml` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |
| `img/DA-1p.heic` | `.heic` | error | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - AudioConverter threw FileNotFoundError with message: [Errno 2] No such file or directory: 'ffprobe'
 |
| `language-docs/eng_spa_mult.odt` | `.odt` | error | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not supported. |

## 6. Surprises

### Expected to fail but SUCCEEDED

- `README-w-include.org` (.org) — 930 chars, quality: good
- `README.org` (.org) — 889 chars, quality: good
- `fake-doc.rtf` (.rtf) — 408 chars, quality: good
- `fake-email-attachment.msg` (.msg) — 265 chars, quality: partial
- `fake-email-multiple-attachments.msg` (.msg) — 208 chars, quality: partial
- `fake-email-with-cc-and-bcc.msg` (.msg) — 195 chars, quality: partial
- `fake-email.eml` (.eml) — 806 chars, quality: good
- `fake-email.msg` (.msg) — 219 chars, quality: partial
- `fake.go` (.go) — 70 chars, quality: good
- `file_we_dont_want_imported` () — 6 chars, quality: empty
- `logger.py` (.py) — 538 chars, quality: good
- `eml/email-equals-attachment-filename.eml` (.eml) — 3297 chars, quality: good
- `eml/email-inline-content-disposition.eml` (.eml) — 657 chars, quality: good
- `eml/email-no-html-content-1.eml` (.eml) — 7721 chars, quality: good
- `eml/email-no-utf8-2008-07-16.062410.eml` (.eml) — 31977 chars, quality: good
- `eml/email-no-utf8-2014-03-17.111517.eml` (.eml) — 14940 chars, quality: good
- `eml/email-replace-mime-encodings-error-1.eml` (.eml) — 16085 chars, quality: good
- `eml/email-replace-mime-encodings-error-2.eml` (.eml) — 26266 chars, quality: good
- `eml/email-replace-mime-encodings-error-3.eml` (.eml) — 56016 chars, quality: good
- `eml/email-replace-mime-encodings-error-4.eml` (.eml) — 34431 chars, quality: good
- `eml/email-replace-mime-encodings-error-5.eml` (.eml) — 14547 chars, quality: good
- `eml/email-with-image.eml` (.eml) — 292868 chars, quality: good
- `eml/empty.eml` (.eml) — 2 chars, quality: empty
- `eml/fake-email-attachment.eml` (.eml) — 1654 chars, quality: good
- `eml/fake-email-b64.eml` (.eml) — 979 chars, quality: good
- `eml/fake-email-header.eml` (.eml) — 1177 chars, quality: good
- `eml/fake-email-image-embedded.eml` (.eml) — 293293 chars, quality: good
- `eml/fake-email-malformed-encoding.eml` (.eml) — 874 chars, quality: good
- `eml/fake-email-utf-16-le.eml` (.eml) — 807 chars, quality: good
- `eml/fake-email-utf-16.eml` (.eml) — 807 chars, quality: good
- `eml/fake-email.eml` (.eml) — 806 chars, quality: good
- `eml/fake-encrypted.eml` (.eml) — 669 chars, quality: good
- `eml/family-day.eml` (.eml) — 1290 chars, quality: good
- `eml/mime-attach-mp3.eml` (.eml) — 70911 chars, quality: good
- `eml/mime-different-plain-html.eml` (.eml) — 1397 chars, quality: good
- `eml/mime-html-only.eml` (.eml) — 640 chars, quality: good
- `eml/mime-multi-to-cc-bcc.eml` (.eml) — 350 chars, quality: good
- `eml/mime-multipart-digest.eml` (.eml) — 721 chars, quality: good
- `eml/mime-no-body.eml` (.eml) — 985 chars, quality: good
- `eml/mime-no-subject.eml` (.eml) — 162 chars, quality: good
- `eml/mime-no-to.eml` (.eml) — 264 chars, quality: good
- `eml/mime-simple.eml` (.eml) — 452 chars, quality: good
- `eml/mime-word-encoded-subject.eml` (.eml) — 261 chars, quality: good
- `eml/rfc822-no-date.eml` (.eml) — 232 chars, quality: good
- `eml/signed-doc.p7s` (.p7s) — 493 chars, quality: good
- `eml/simple-rfc-822.eml` (.eml) — 679 chars, quality: good
- `eml/test-invalid-date.eml` (.eml) — 161 chars, quality: good
- `eml/test-iso-8601-date.eml` (.eml) — 135 chars, quality: good
- `eml/test-rfc2822-date.eml` (.eml) — 151 chars, quality: good
- `language-docs/eng_spa_mult.doc` (.doc) — 3089 chars, quality: good
- `language-docs/eng_spa_mult.eml` (.eml) — 7025 chars, quality: good
- `language-docs/eng_spa_mult.org` (.org) — 3090 chars, quality: good
- `language-docs/eng_spa_mult.ppt` (.ppt) — 3313 chars, quality: partial
- `language-docs/eng_spa_mult.rtf` (.rtf) — 168374 chars, quality: good
- `unsupported/factbook.xsl` (.xsl) — 758 chars, quality: good

### Expected to succeed but FAILED

- `CantinaBand3.wav` (.wav) — HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - AudioConverter threw UnknownValueError with message: 

- `book-war-and-peace-1225p.txt` (.txt) — HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PlainTextConverter threw UnicodeDecodeError with message: 'ascii' codec can't
- `img/bmp_24.bmp` (.bmp) — HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not sup
- `img/layout-parser-paper-combined.tiff` (.tiff) — HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not sup
- `img/layout-parser-paper-fast.tiff` (.tiff) — HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter attempted a conversion, suggesting that the filetype is simply not sup
- `pdf/invalid-pdf-structure-pdfminer-entire-doc.pdf` (.pdf) — HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConverter threw PSSyntaxError with message: Invalid dictionary construct: 
- `pdf/pdf-bad-color-space.pdf` (.pdf) — HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConverter threw KeyError with message: 'N'


## 7. Raw Results

| # | File | Ext | Size | Category | Status | Quality | Output Len | Gold Sim | Error |
|---|------|-----|------|----------|--------|---------|------------|----------|-------|
| 1 | `2023-half-year-analyses-by-segment.xlsx` | `.xlsx` | 38KB | supported-format | success | good | 11695 |  |  |
| 2 | `CantinaBand3.wav` | `.wav` | 129KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - AudioCo |
| 3 | `README-w-include.rst` | `.rst` | 1KB | supported-format | success | good | 944 |  |  |
| 4 | `README.md` | `.md` | 1KB | supported-format | success | good | 859 |  |  |
| 5 | `README.rst` | `.rst` | 1KB | supported-format | success | good | 903 |  |  |
| 6 | `book-war-and-peace-1225p.txt` | `.txt` | 3190KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PlainTe |
| 7 | `book-war-and-peace-1p.txt` | `.txt` | 3KB | supported-format | success | good | 3045 |  |  |
| 8 | `category-level.docx` | `.docx` | 11KB | supported-format | success | partial | 1587 |  |  |
| 9 | `codeblock.md` | `.md` | 1KB | supported-format | success | good | 606 |  |  |
| 10 | `contains-pictures.docx` | `.docx` | 93KB | supported-format | success | partial | 783 |  |  |
| 11 | `csv-with-escaped-commas.csv` | `.csv` | 0KB | supported-format | success | good | 101 |  |  |
| 12 | `csv-with-line-delimiter.csv` | `.csv` | 0KB | supported-format | success | good | 56 |  |  |
| 13 | `csv-with-long-lines.csv` | `.csv` | 52KB | supported-format | success | good | 63949 |  |  |
| 14 | `docx-hdrftr.docx` | `.docx` | 21KB | supported-format | success | partial | 13 |  |  |
| 15 | `docx-shapes.docx` | `.docx` | 6KB | supported-format | success | partial | 166 |  |  |
| 16 | `docx-tables.docx` | `.docx` | 12KB | supported-format | success | partial | 349 |  |  |
| 17 | `duplicate-paragraphs.docx` | `.docx` | 36KB | supported-format | success | partial | 101 |  |  |
| 18 | `emoji.xlsx` | `.xlsx` | 5KB | supported-format | success | partial | 39 |  |  |
| 19 | `empty.txt` | `.txt` | 0KB | supported-format | success | empty |  |  |  |
| 20 | `empty.xlsx` | `.xlsx` | 8KB | supported-format | success | partial | 16 |  |  |
| 21 | `example-10k-1p.html` | `.html` | 44KB | supported-format | success | partial | 4838 |  |  |
| 22 | `example-10k-230p.html` | `.html` | 12067KB | supported-format | success | partial | 212050 |  |  |
| 23 | `example-10k-utf-16.html` | `.html` | 4798KB | supported-format | success | partial | 212050 |  |  |
| 24 | `example-10k.html` | `.html` | 2413KB | supported-format | success | partial | 212050 |  |  |
| 25 | `example-list-items-multiple.docx` | `.docx` | 18KB | supported-format | success | partial | 620 |  |  |
| 26 | `example-steelJIS-datasheet-utf-16.html` | `.html` | 24KB | supported-format | success | partial | 3606 |  |  |
| 27 | `example-steelJIS-datasheet.html` | `.html` | 12KB | supported-format | success | good | 3606 |  |  |
| 28 | `example-with-scripts.html` | `.html` | 114KB | supported-format | success | good | 44802 |  |  |
| 29 | `factbook-utf-16.xml` | `.xml` | 1KB | supported-format | success | good | 669 |  |  |
| 30 | `factbook.xml` | `.xml` | 1KB | supported-format | success | good | 669 |  |  |
| 31 | `fake-doc-emphasized-text.docx` | `.docx` | 13KB | supported-format | success | partial | 213 |  |  |
| 32 | `fake-email.txt` | `.txt` | 1KB | supported-format | success | good | 812 |  |  |
| 33 | `fake-html-cp1252.html` | `.html` | 1KB | supported-format | success | good | 829 |  |  |
| 34 | `fake-html-lang-de.html` | `.html` | 0KB | supported-format | success | good | 71 |  |  |
| 35 | `fake-html-pre.htm` | `.htm` | 459KB | supported-format | success | good | 455447 |  |  |
| 36 | `fake-html-with-base64-image.html` | `.html` | 9KB | supported-format | success | partial | 58 |  |  |
| 37 | `fake-html-with-duplicate-elements.html` | `.html` | 0KB | supported-format | success | good | 116 |  |  |
| 38 | `fake-html-with-footer-and-header.html` | `.html` | 0KB | supported-format | success | good | 39 |  |  |
| 39 | `fake-html-with-image-from-url.html` | `.html` | 0KB | supported-format | success | good | 92 |  |  |
| 40 | `fake-html.html` | `.html` | 1KB | supported-format | success | good | 370 |  |  |
| 41 | `fake-incomplete-json.txt` | `.txt` | 0KB | supported-format | success | good | 207 |  |  |
| 42 | `fake-power-point-malformed.pptx` | `.pptx` | 36KB | supported-format | success | partial | 62 |  |  |
| 43 | `fake-power-point-many-pages.pptx` | `.pptx` | 34KB | supported-format | success | partial | 92 |  |  |
| 44 | `fake-power-point-table.pptx` | `.pptx` | 39KB | supported-format | success | partial | 194 |  |  |
| 45 | `fake-power-point.pptx` | `.pptx` | 38KB | supported-format | success | partial | 236 |  |  |
| 46 | `fake-text-all-whitespace.txt` | `.txt` | 0KB | supported-format | success | empty | 2 |  |  |
| 47 | `fake-text-utf-16-be.txt` | `.txt` | 0KB | supported-format | success | good | 169 |  |  |
| 48 | `fake-text-utf-16-le.txt` | `.txt` | 0KB | supported-format | success | good | 188 |  |  |
| 49 | `fake-text-utf-16.txt` | `.txt` | 0KB | supported-format | success | good | 188 |  |  |
| 50 | `fake-text-utf-32.txt` | `.txt` | 1KB | supported-format | success | good | 188 |  |  |
| 51 | `fake-text.txt` | `.txt` | 0KB | supported-format | success | good | 169 |  |  |
| 52 | `fake.docx` | `.docx` | 36KB | supported-format | success | partial | 27 |  |  |
| 53 | `fake_table.docx` | `.docx` | 12KB | supported-format | success | partial | 124 |  |  |
| 54 | `grid_offset_error.docx` | `.docx` | 810KB | supported-format | success | partial | 53 |  |  |
| 55 | `group-shapes-nested.pptx` | `.pptx` | 37KB | supported-format | success | partial | 47 |  |  |
| 56 | `handbook-1p-no-rendered-page-breaks.docx` | `.docx` | 10KB | supported-format | success | good | 3483 |  |  |
| 57 | `handbook-1p.docx` | `.docx` | 10KB | supported-format | success | good | 3483 |  |  |
| 58 | `hebrew-text-base64-iso88598i.txt` | `.txt` | 0KB | supported-format | success | good | 56 |  |  |
| 59 | `hlink-meta.docx` | `.docx` | 12KB | supported-format | success | partial | 420 |  |  |
| 60 | `ideas-page.html` | `.html` | 6KB | supported-format | success | partial | 1200 |  |  |
| 61 | `more-than-1k-cells.xlsx` | `.xlsx` | 7KB | supported-format | success | good | 4473 |  |  |
| 62 | `norwich-city.txt` | `.txt` | 48KB | supported-format | success | good | 47725 |  |  |
| 63 | `not-unstructured-payload.json` | `.json` | 0KB | supported-format | success | good | 94 |  |  |
| 64 | `page-breaks.docx` | `.docx` | 14KB | supported-format | success | partial | 568 |  |  |
| 65 | `picture.pptx` | `.pptx` | 20KB | supported-format | success | partial | 61 |  |  |
| 66 | `sample-presentation.pptx` | `.pptx` | 41KB | supported-format | success | partial | 715 |  |  |
| 67 | `science-exploration-1p.pptx` | `.pptx` | 1206KB | supported-format | success | partial | 711 |  |  |
| 68 | `science-exploration-369p.pptx` | `.pptx` | 7199KB | supported-format | success | partial | 245170 |  |  |
| 69 | `semicolon-delimited.csv` | `.csv` | 0KB | supported-format | success | good | 208 |  |  |
| 70 | `simple-table.md` | `.md` | 0KB | supported-format | success | good | 82 |  |  |
| 71 | `simple.docx` | `.docx` | 36KB | supported-format | success | partial | 183 |  |  |
| 72 | `simple.epub` | `.epub` | 30920KB | supported-format | success | partial | 10823 |  |  |
| 73 | `simple.json` | `.json` | 4KB | supported-format | success | good | 4447 |  |  |
| 74 | `simple.ndjson` | `.ndjson` | 3KB | supported-format | success | good | 3144 |  |  |
| 75 | `simple.pptx` | `.pptx` | 34KB | supported-format | success | partial | 224 |  |  |
| 76 | `simple.yaml` | `.yaml` | 0KB | supported-format | success | good | 318 |  |  |
| 77 | `simple.zip` | `.zip` | 3KB | supported-format | success | good | 1459 |  |  |
| 78 | `single-column.csv` | `.csv` | 0KB | supported-format | success | good | 215 |  |  |
| 79 | `spring-weather.html.json` | `.json` | 40KB | supported-format | success | good | 39567 |  |  |
| 80 | `spring-weather.html.ndjson` | `.ndjson` | 31KB | supported-format | success | good | 31253 |  |  |
| 81 | `stanley-cups-utf-16.csv` | `.csv` | 0KB | supported-format | success | good | 145 |  |  |
| 82 | `stanley-cups-with-emoji.csv` | `.csv` | 0KB | supported-format | success | good | 171 |  |  |
| 83 | `stanley-cups-with-emoji.tsv` | `.tsv` | 0KB | supported-format | success | good | 104 |  |  |
| 84 | `stanley-cups.csv` | `.csv` | 0KB | supported-format | success | good | 145 |  |  |
| 85 | `stanley-cups.tsv` | `.tsv` | 0KB | supported-format | success | good | 84 |  |  |
| 86 | `stanley-cups.xlsx` | `.xlsx` | 6KB | supported-format | success | partial | 381 |  |  |
| 87 | `table-multi-row-column-cells-actual.csv` | `.csv` | 0KB | supported-format | success | good | 431 |  |  |
| 88 | `table-semicolon-delimiter.csv` | `.csv` | 0KB | supported-format | success | good | 88 |  |  |
| 89 | `tables-with-incomplete-rows.docx` | `.docx` | 17KB | supported-format | success | partial | 418 |  |  |
| 90 | `teams_chat.docx` | `.docx` | 1KB | supported-format | success | partial | 136 |  |  |
| 91 | `test-image-jpg-mime.pptx` | `.pptx` | 33KB | supported-format | success | partial | 43 |  |  |
| 92 | `tests-example.xls` | `.xls` | 16KB | supported-format | success | partial | 1937 |  |  |
| 93 | `umlauts-non-utf8.md` | `.md` | 0KB | supported-format | success | good | 24 |  |  |
| 94 | `umlauts-utf8.md` | `.md` | 0KB | supported-format | success | good | 24 |  |  |
| 95 | `vodafone.xlsx` | `.xlsx` | 12KB | supported-format | success | partial | 1571 |  |  |
| 96 | `winter-sports.epub` | `.epub` | 205KB | supported-format | success | good | 350048 |  |  |
| 97 | `xlsx-subtable-cases.xlsx` | `.xlsx` | 9KB | supported-format | success | partial | 1362 |  |  |
| 98 | `eml/fake-email.txt` | `.txt` | 1KB | supported-format | success | good | 807 |  |  |
| 99 | `img/DA-1p.jpg` | `.jpg` | 273KB | supported-format | success | empty |  |  |  |
| 100 | `img/DA-1p.png` | `.png` | 195KB | supported-format | success | empty |  |  |  |
| 101 | `img/bmp_24.bmp` | `.bmp` | 117KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 102 | `img/chi_sim_image.jpeg` | `.jpeg` | 20KB | supported-format | success | empty |  |  |  |
| 103 | `img/double-column-A.jpg` | `.jpg` | 280KB | supported-format | success | empty |  |  |  |
| 104 | `img/double-column-B.jpg` | `.jpg` | 297KB | supported-format | success | empty |  |  |  |
| 105 | `img/embedded-images-tables.jpg` | `.jpg` | 251KB | supported-format | success | empty |  |  |  |
| 106 | `img/english-and-korean.png` | `.png` | 298KB | supported-format | success | empty |  |  |  |
| 107 | `img/example.jpg` | `.jpg` | 32KB | supported-format | success | empty |  |  |  |
| 108 | `img/jpn-vert.jpeg` | `.jpeg` | 34KB | supported-format | success | empty |  |  |  |
| 109 | `img/layout-parser-paper-10p.jpg` | `.jpg` | 5070KB | supported-format | success | empty |  |  |  |
| 110 | `img/layout-parser-paper-combined.tiff` | `.tiff` | 3794KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 111 | `img/layout-parser-paper-fast.jpg` | `.jpg` | 93KB | supported-format | success | empty |  |  |  |
| 112 | `img/layout-parser-paper-fast.tiff` | `.tiff` | 1894KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 113 | `img/layout-parser-paper-with-table.jpg` | `.jpg` | 162KB | supported-format | success | empty |  |  |  |
| 114 | `img/table-multi-row-column-cells.png` | `.png` | 78KB | supported-format | success | empty |  |  |  |
| 115 | `language-docs/UDHR_first_article_all.txt` | `.txt` | 119KB | supported-format | success | good | 93255 |  |  |
| 116 | `language-docs/eng_afr_spa.txt` | `.txt` | 2KB | supported-format | success | good | 2071 |  |  |
| 117 | `language-docs/eng_spa.txt` | `.txt` | 2KB | supported-format | success | good | 1886 |  |  |
| 118 | `language-docs/eng_spa.xlsx` | `.xlsx` | 6KB | supported-format | success | partial | 932 |  |  |
| 119 | `language-docs/eng_spa_mult.docx` | `.docx` | 6KB | supported-format | success | good | 3089 |  |  |
| 120 | `language-docs/eng_spa_mult.epub` | `.epub` | 2KB | supported-format | success | good | 3189 |  |  |
| 121 | `language-docs/eng_spa_mult.html` | `.html` | 3KB | supported-format | success | good | 3089 |  |  |
| 122 | `language-docs/eng_spa_mult.md` | `.md` | 3KB | supported-format | success | good | 3090 |  |  |
| 123 | `language-docs/eng_spa_mult.pptx` | `.pptx` | 45KB | supported-format | success | partial | 3341 |  |  |
| 124 | `language-docs/eng_spa_mult.rst` | `.rst` | 3KB | supported-format | success | good | 3090 |  |  |
| 125 | `language-docs/eng_spa_mult.txt` | `.txt` | 3KB | supported-format | success | good | 3090 |  |  |
| 126 | `language-docs/eng_spa_mult.xml` | `.xml` | 3KB | supported-format | success | good | 3408 |  |  |
| 127 | `language-docs/fr_olap.pdf` | `.pdf` | 424KB | supported-format | success | partial | 36041 |  |  |
| 128 | `pdf/DA-1p.pdf` | `.pdf` | 431KB | supported-format | success | partial | 2730 |  |  |
| 129 | `pdf/a1977-backus-p21.pdf` | `.pdf` | 98KB | supported-format | success | partial | 10975 |  |  |
| 130 | `pdf/all-number-table.pdf` | `.pdf` | 16KB | supported-format | success | partial | 95 |  |  |
| 131 | `pdf/chevron-page.pdf` | `.pdf` | 889KB | supported-format | success | partial | 835 |  |  |
| 132 | `pdf/copy-protected.pdf` | `.pdf` | 264KB | supported-format | success | partial | 6911 |  |  |
| 133 | `pdf/embedded-cmap-cidfont.pdf` | `.pdf` | 2KB | supported-format | success | partial | 22 |  |  |
| 134 | `pdf/embedded-images-tables.pdf` | `.pdf` | 107KB | supported-format | success | partial | 2048 |  |  |
| 135 | `pdf/embedded-images.pdf` | `.pdf` | 163KB | supported-format | success | partial | 1228 |  |  |
| 136 | `pdf/embedded-link.pdf` | `.pdf` | 15KB | supported-format | success | partial | 377 |  |  |
| 137 | `pdf/emphasis-text.pdf` | `.pdf` | 16KB | supported-format | success | partial | 42 |  |  |
| 138 | `pdf/failure-after-repair.pdf` | `.pdf` | 1073KB | supported-format | success | partial | 108949 |  |  |
| 139 | `pdf/fake-bold-sample.pdf` | `.pdf` | 2KB | supported-format | success | good | 448 |  |  |
| 140 | `pdf/fake-memo-with-duplicate-page.pdf` | `.pdf` | 11KB | supported-format | success | partial | 415 |  |  |
| 141 | `pdf/fake-memo.pdf` | `.pdf` | 13KB | supported-format | success | partial | 207 |  |  |
| 142 | `pdf/header-test-doc.pdf` | `.pdf` | 25KB | supported-format | success | partial | 66 |  |  |
| 143 | `pdf/interface-config-guide-p93.pdf` | `.pdf` | 102KB | supported-format | success | partial | 2147 |  |  |
| 144 | `pdf/invalid-pdf-structure-pdfminer-entire-doc.pdf` | `.pdf` | 5892KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConv |
| 145 | `pdf/invalid-pdf-structure-pdfminer-one-page.pdf` | `.pdf` | 1228KB | supported-format | success | partial | 10754 |  |  |
| 146 | `pdf/korean-text-with-tables.pdf` | `.pdf` | 86KB | supported-format | success | partial | 2060 |  |  |
| 147 | `pdf/layout-parser-paper-fast.pdf` | `.pdf` | 168KB | supported-format | success | partial | 6919 |  |  |
| 148 | `pdf/layout-parser-paper-with-empty-pages.pdf` | `.pdf` | 278KB | supported-format | success | partial | 5628 |  |  |
| 149 | `pdf/layout-parser-paper-with-table.pdf` | `.pdf` | 168KB | supported-format | success | partial | 4587 |  |  |
| 150 | `pdf/layout-parser-paper.pdf` | `.pdf` | 4576KB | supported-format | success | partial | 55258 |  |  |
| 151 | `pdf/list-item-example.pdf` | `.pdf` | 48KB | supported-format | success | partial | 2850 |  |  |
| 152 | `pdf/loremipsum-flat.pdf` | `.pdf` | 496KB | supported-format | success | empty |  |  |  |
| 153 | `pdf/multi-column-2p.pdf` | `.pdf` | 190KB | supported-format | success | partial | 16134 |  |  |
| 154 | `pdf/multi-column.pdf` | `.pdf` | 375KB | supported-format | success | good | 116871 |  |  |
| 155 | `pdf/negative-coords.pdf` | `.pdf` | 117KB | supported-format | success | partial | 2013 |  |  |
| 156 | `pdf/pdf-bad-color-space.pdf` | `.pdf` | 185KB | supported-format | error |  |  |  | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - PdfConv |
| 157 | `pdf/pdf-with-ocr-text.pdf` | `.pdf` | 436KB | supported-format | success | partial | 1303 |  |  |
| 158 | `pdf/reliance.pdf` | `.pdf` | 284KB | supported-format | success | partial | 14302 |  |  |
| 159 | `pdf/single_table.pdf` | `.pdf` | 77KB | supported-format | success | empty |  |  |  |
| 160 | `pdf/table-multi-row-column-cells.pdf` | `.pdf` | 88KB | supported-format | success | empty |  |  |  |
| 161 | `README-w-include.org` | `.org` | 1KB | expected-to-fail | success | good | 930 |  |  |
| 162 | `README.org` | `.org` | 1KB | expected-to-fail | success | good | 889 |  |  |
| 163 | `duplicate-paragraphs.doc` | `.doc` | 18KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 164 | `fake-doc-emphasized-text.doc` | `.doc` | 27KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 165 | `fake-doc.rtf` | `.rtf` | 0KB | expected-to-fail | success | good | 408 |  |  |
| 166 | `fake-email-attachment.msg` | `.msg` | 16KB | expected-to-fail | success | partial | 265 |  |  |
| 167 | `fake-email-multiple-attachments.msg` | `.msg` | 4218KB | expected-to-fail | success | partial | 208 |  |  |
| 168 | `fake-email-with-cc-and-bcc.msg` | `.msg` | 14KB | expected-to-fail | success | partial | 195 |  |  |
| 169 | `fake-email.eml` | `.eml` | 1KB | expected-to-fail | success | good | 806 |  |  |
| 170 | `fake-email.msg` | `.msg` | 12KB | expected-to-fail | success | partial | 219 |  |  |
| 171 | `fake-power-point.ppt` | `.ppt` | 594KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 172 | `fake.doc` | `.doc` | 18KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 173 | `fake.go` | `.go` | 0KB | expected-to-fail | success | good | 70 |  |  |
| 174 | `fake.odt` | `.odt` | 14KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 175 | `file_we_dont_want_imported` | `(none)` | 0KB | expected-to-fail | success | empty | 6 |  |  |
| 176 | `logger.py` | `.py` | 1KB | expected-to-fail | success | good | 538 |  |  |
| 177 | `simple.doc` | `.doc` | 16KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 178 | `simple.odt` | `.odt` | 7KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 179 | `eml/email-equals-attachment-filename.eml` | `.eml` | 3KB | expected-to-fail | success | good | 3297 |  |  |
| 180 | `eml/email-inline-content-disposition.eml` | `.eml` | 1KB | expected-to-fail | success | good | 657 |  |  |
| 181 | `eml/email-no-html-content-1.eml` | `.eml` | 8KB | expected-to-fail | success | good | 7721 |  |  |
| 182 | `eml/email-no-utf8-2008-07-16.062410.eml` | `.eml` | 32KB | expected-to-fail | success | good | 31977 |  |  |
| 183 | `eml/email-no-utf8-2014-03-17.111517.eml` | `.eml` | 15KB | expected-to-fail | success | good | 14940 |  |  |
| 184 | `eml/email-replace-mime-encodings-error-1.eml` | `.eml` | 16KB | expected-to-fail | success | good | 16085 |  |  |
| 185 | `eml/email-replace-mime-encodings-error-2.eml` | `.eml` | 26KB | expected-to-fail | success | good | 26266 |  |  |
| 186 | `eml/email-replace-mime-encodings-error-3.eml` | `.eml` | 56KB | expected-to-fail | success | good | 56016 |  |  |
| 187 | `eml/email-replace-mime-encodings-error-4.eml` | `.eml` | 34KB | expected-to-fail | success | good | 34431 |  |  |
| 188 | `eml/email-replace-mime-encodings-error-5.eml` | `.eml` | 15KB | expected-to-fail | success | good | 14547 |  |  |
| 189 | `eml/email-with-image.eml` | `.eml` | 290KB | expected-to-fail | success | good | 292868 |  |  |
| 190 | `eml/empty.eml` | `.eml` | 0KB | expected-to-fail | success | empty | 2 |  |  |
| 191 | `eml/fake-email-attachment.eml` | `.eml` | 2KB | expected-to-fail | success | good | 1654 |  |  |
| 192 | `eml/fake-email-b64.eml` | `.eml` | 1KB | expected-to-fail | success | good | 979 |  |  |
| 193 | `eml/fake-email-header.eml` | `.eml` | 1KB | expected-to-fail | success | good | 1177 |  |  |
| 194 | `eml/fake-email-image-embedded.eml` | `.eml` | 290KB | expected-to-fail | success | good | 293293 |  |  |
| 195 | `eml/fake-email-malformed-encoding.eml` | `.eml` | 1KB | expected-to-fail | success | good | 874 |  |  |
| 196 | `eml/fake-email-utf-16-be.eml` | `.eml` | 2KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 197 | `eml/fake-email-utf-16-le.eml` | `.eml` | 2KB | expected-to-fail | success | good | 807 |  |  |
| 198 | `eml/fake-email-utf-16.eml` | `.eml` | 2KB | expected-to-fail | success | good | 807 |  |  |
| 199 | `eml/fake-email.eml` | `.eml` | 1KB | expected-to-fail | success | good | 806 |  |  |
| 200 | `eml/fake-encrypted.eml` | `.eml` | 1KB | expected-to-fail | success | good | 669 |  |  |
| 201 | `eml/family-day.eml` | `.eml` | 1KB | expected-to-fail | success | good | 1290 |  |  |
| 202 | `eml/mime-attach-mp3.eml` | `.eml` | 70KB | expected-to-fail | success | good | 70911 |  |  |
| 203 | `eml/mime-different-plain-html.eml` | `.eml` | 1KB | expected-to-fail | success | good | 1397 |  |  |
| 204 | `eml/mime-html-only.eml` | `.eml` | 1KB | expected-to-fail | success | good | 640 |  |  |
| 205 | `eml/mime-multi-to-cc-bcc.eml` | `.eml` | 0KB | expected-to-fail | success | good | 350 |  |  |
| 206 | `eml/mime-multipart-digest.eml` | `.eml` | 1KB | expected-to-fail | success | good | 721 |  |  |
| 207 | `eml/mime-no-body.eml` | `.eml` | 1KB | expected-to-fail | success | good | 985 |  |  |
| 208 | `eml/mime-no-subject.eml` | `.eml` | 0KB | expected-to-fail | success | good | 162 |  |  |
| 209 | `eml/mime-no-to.eml` | `.eml` | 0KB | expected-to-fail | success | good | 264 |  |  |
| 210 | `eml/mime-simple.eml` | `.eml` | 0KB | expected-to-fail | success | good | 452 |  |  |
| 211 | `eml/mime-word-encoded-subject.eml` | `.eml` | 0KB | expected-to-fail | success | good | 261 |  |  |
| 212 | `eml/rfc822-no-date.eml` | `.eml` | 0KB | expected-to-fail | success | good | 232 |  |  |
| 213 | `eml/signed-doc.p7s` | `.p7s` | 0KB | expected-to-fail | success | good | 493 |  |  |
| 214 | `eml/simple-rfc-822.eml` | `.eml` | 1KB | expected-to-fail | success | good | 679 |  |  |
| 215 | `eml/test-invalid-date.eml` | `.eml` | 0KB | expected-to-fail | success | good | 161 |  |  |
| 216 | `eml/test-iso-8601-date.eml` | `.eml` | 0KB | expected-to-fail | success | good | 135 |  |  |
| 217 | `eml/test-rfc2822-date.eml` | `.eml` | 0KB | expected-to-fail | success | good | 151 |  |  |
| 218 | `img/DA-1p.heic` | `.heic` | 94KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: File conversion failed after 1 attempts:
 - AudioCo |
| 219 | `language-docs/eng_spa_mult.doc` | `.doc` | 6KB | expected-to-fail | success | good | 3089 |  |  |
| 220 | `language-docs/eng_spa_mult.eml` | `.eml` | 7KB | expected-to-fail | success | good | 7025 |  |  |
| 221 | `language-docs/eng_spa_mult.odt` | `.odt` | 17KB | expected-to-fail | error |  |  |  | HTTP 422: Extraction failed: Could not convert stream to Markdown. No converter  |
| 222 | `language-docs/eng_spa_mult.org` | `.org` | 3KB | expected-to-fail | success | good | 3090 |  |  |
| 223 | `language-docs/eng_spa_mult.ppt` | `.ppt` | 52KB | expected-to-fail | success | partial | 3313 |  |  |
| 224 | `language-docs/eng_spa_mult.rtf` | `.rtf` | 165KB | expected-to-fail | success | good | 168374 |  |  |
| 225 | `unsupported/factbook.xsl` | `.xsl` | 1KB | expected-to-fail | success | good | 758 |  |  |
| 226 | `fake-encrypted.msg` | `.msg` | 14KB | skipped-encrypted | skipped |  |  |  |  |
| 227 | `handbook-872p.docx` | `.docx` | 472KB | skipped-too-large | skipped |  |  |  |  |
| 228 | `password_protected.xlsx` | `.xlsx` | 8KB | skipped-encrypted | skipped |  |  |  |  |
| 229 | `pdf/DA-619p.pdf` | `.pdf` | 2836KB | skipped-too-large | skipped |  |  |  |  |
| 230 | `pdf/password.pdf` | `.pdf` | 14KB | skipped-encrypted | skipped |  |  |  |  |
| 231 | `pdf/pdf2image-memory-error-test-400p.pdf` | `.pdf` | 3513KB | skipped-too-large | skipped |  |  |  |  |
