# Ownership parser source witnesses

`real-sources.json` records the original SEC URLs, filing identifiers/dates, capture timestamps and SHA-256 hashes for six bounded real filings and one associated information table. The XML files are exact captured public source bytes. Public EDGAR masks submission credentials (`XXXXXXXX`); these files contain no live application credentials. No remote requests run in the tests.

The independently selected literal expectations in `test_ownership_parse.py` cover:

- Apple Form 3: John Ternus's initial common holding of 34,155, with derivative award rows preserved separately.
- Apple Form 4: Jennifer Newstead's 1,438-share sale at 317.23, reported holding 34,352, and the source 10b5-1 footnote.
- Apple Form 5: Susan Wagner's 42-share inheritance transaction (code W), indirect bucket and separate direct holding. It is not an open-market purchase.
- Berkshire Hathaway's 13F: actual manager CIK 1067983, quarter 2026-06-30, 89 information-table rows, first reported value 577,211,815 USD and 12,561,737 shares. The subject issuer is not the manager.
- Apple's 13G: institutional rule 13d-1(b), CUSIP 037833100, 1,099,168,953 reported shares and 7.48 percent; the source reporting-person CIK is absent and remains null.
- Nuveen Quality Municipal Income Fund's 13D/A: subject CIK 1083839 and CUSIP 67066V812; reporting person Wells Fargo has CIK 72971 and reports 13.54 percent. The amendment does not imply activism or a letter.

Other cases constructed inline in the tests are explicitly synthetic. They exercise joint reporting, derivative/direct/indirect separation, exact signed decimals, unknown footnote-only quantities, amendments, current multiple-CUSIP declarations, declared institutional/passive/exempt categories, confidential omissions, old/current value units, notices, incomplete tables and hostile XML. Passing these witnesses is not a broad ownership-data accuracy measurement.

## Official sources used for implementation

- [SEC technical specifications](https://www.sec.gov/submit-filings/technical-specifications): Ownership XML 5.5 (18 March 2026), Schedule 13D/G XML 2.3 (15 April 2026) and Form 13F XML 1.9 (15 December 2025).
- [Ownership 5.5 specification](https://www.sec.gov/files/edgar/filer-information/specifications/ownershipxmltechspec-v5-5.zip).
- [Schedule 13D/G 2.3 schemas and examples](https://www.sec.gov/files/edgar/filer-information/specifications/schedule-13d-13g-tech-specs-23.zip): `issuerCusips/issuerCusipNumber` can repeat; `issuerCIK` and `issuerCik` differ by form; reporting-person and issuer nodes remain separate.
- [Form 13F 1.9 schemas and examples](https://www.sec.gov/files/edgar/filer-information/specifications/edgar-form-13f-xml-technical-specification-1-9.zip).
- [SEC Form 13F FAQs](https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f): submissions starting 3 January 2023 report values rounded to dollars; earlier submissions use thousands of dollars. The parser selects scale by filing date, not quarter date.

The parser rejects DTD/entity declarations using Expat handlers, including UTF-16 documents; it does not resolve network resources or stylesheets. Limits are 32 supplied documents, 32 MiB combined supplied bytes, 16 MiB per XML document, depth 64, 400,000 XML nodes and 25,000 normalized rows. Oversized or structurally unsupported filings fail explicitly. This parser is not a full SEC XSD validator. Legacy non-XML 13D/G is unsupported, not an empty ownership event. A missing 13F table or a cover/table count mismatch fails, rather than becoming an empty portfolio. 13F notices are unsupported non-position reports.

Insider `is_10b5_1` carries the filing checkbox with `plan_flag_scope="filing"`; it is not a determination that every transaction used a plan. Joint owner rows share `transaction_group_id`. `event.cusips` retains all listed identifiers; `event.cusip` is null when several were declared. Optional exhibit metadata comes only from explicit inventory document types, with no automatic letter classification.
