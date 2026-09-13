"""Original SEC witnesses plus deliberately synthetic edge cases; no remote test calls."""

import base64
import hashlib
import json
from pathlib import Path

import pytest

from filings_hub.ownership import parse

FIXTURES = Path(__file__).parent / "fixtures" / "ownership"
SOURCES = json.loads((FIXTURES / "real-sources.json").read_text())
META = {
    "accession": "0000000001-26-000001",
    "filer_cik": 77,
    "filed_date": "2026-09-01",
    "source_url": "https://www.sec.gov/Archives/edgar/data/77/synthetic.xml",
}


def source(form):
    row = next(r for r in SOURCES if r["form"] == form)
    documents = []
    for r in [row] + ([row["table"]] if row.get("table") else []):
        raw = (FIXTURES / r["fixture"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == r["sha256"]
        documents.append({"filename": r["filename"], "source_url": r["source_url"], "content": raw})
    return documents, row


def run(form, xml, **metadata):
    return parse.parse_filing(
        form,
        [{"filename": "synthetic.xml", "content": xml.encode() if isinstance(xml, str) else xml}],
        {**META, **metadata},
    )


@pytest.mark.parametrize(
    "form,kind,count",
    [
        ("3", "insiders", 8),
        ("4", "insiders", 1),
        ("5", "insiders", 2),
        ("13F-HR", "positions", 89),
        ("SCHEDULE 13G", "events", 1),
        ("SCHEDULE 13D/A", "events", 2),
    ],
)
def test_real_original_sources(form, kind, count):
    docs, metadata = source(form)
    result = parse.parse_filing(form, docs, metadata)
    assert len(result["event"]["reporting_people"] if kind == "events" else result[kind]) == count
    assert result["filing"]["filed_date"] == metadata["filed_date"]
    json.dumps(result)  # No Decimal/Element/byte objects cross the storage contract.


def test_real_insider_facts_and_initial_holdings_are_not_purchases():
    rows = parse.parse_filing("3", *source("3"))["insiders"]
    assert rows[0]["owner_name"] == "Ternus John"
    assert rows[0]["owned_after"] == "34155"
    assert all(r["is_holding"] and r["transaction_code"] is None and r["shares"] is None for r in rows)
    assert any(r["is_derivative"] and r["underlying_shares"] is not None for r in rows)
    row = parse.parse_filing("4", *source("4"))["insiders"][0]
    assert (row["transaction_code"], row["shares"], row["price"], row["owned_after"]) == (
        "S",
        "1438",
        "317.23",
        "34352",
    )
    assert row["is_10b5_1"] and row["plan_flag_scope"] == "filing"
    assert "May 5, 2026" in row["footnotes"][0]
    row5 = parse.parse_filing("5", *source("5"))["insiders"][0]
    assert (row5["transaction_code"], row5["ownership_form"], row5["shares"]) == ("W", "I", "42")
    assert "inheritance" in row5["footnotes"][0]


def test_real_institution_values_and_reporting_identities_are_distinct():
    data = parse.parse_filing("13F-HR", *source("13F-HR"))
    assert data["filing"]["manager_cik"] == 1067983
    assert data["filing"]["issuer_cik"] is None
    assert data["filing"]["report_period"] == "2026-06-30"
    assert data["filing"]["value_units"] == "USD"
    assert data["positions"][0]["shares"] == "12561737"
    assert data["positions"][0]["value_usd"] == "577211815"
    assert len(data["filing"]["other_included_managers"]) == 14
    event = parse.parse_filing("SCHEDULE 13D/A", *source("SCHEDULE 13D/A"))["event"]
    assert event["issuer_cik"] == 1083839
    assert event["reporting_people"][0]["cik"] == 72971
    assert event["reporting_people"][0]["percent"] == "13.54"
    assert event["filing_category"] == "schedule_13d"  # No activist/letter inference.
    assert event["exhibits"] == []
    eventg = parse.parse_filing("SC13G", *source("SCHEDULE 13G"))["event"]
    assert eventg["issuer_cik"] == 320193 and eventg["cusip"] == "037833100"
    assert eventg["filing_category"] == "institutional"
    assert eventg["reporting_people"][0]["cik"] is None  # The source declares no reporting-person CIK.
    assert eventg["reporting_people"][0]["shares"] == "1099168953"


def insider_xml(form="4", amount="10.125", price="-0.0000000000000000000000000123"):
    return f"""<ownershipDocument><documentType>{form}</documentType><periodOfReport>2026-08-31</periodOfReport>
      <issuer><issuerCik>123</issuerCik><issuerName>Synthetic &amp; Co</issuerName></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerCik>77</rptOwnerCik><rptOwnerName>Owner One</rptOwnerName></reportingOwnerId>
       <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>true</isOfficer><isTenPercentOwner>0</isTenPercentOwner><officerTitle>CFO</officerTitle></reportingOwnerRelationship></reportingOwner>
      <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Class A</value></securityTitle>
       <transactionDate><value>2026-08-31</value></transactionDate><transactionCoding><transactionCode>P</transactionCode></transactionCoding>
       <transactionAmounts><transactionShares><value>{amount}</value></transactionShares><transactionPricePerShare><value>{price}</value><footnoteId id="F1"/></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
       <postTransactionAmounts><sharesOwnedFollowingTransaction><value>100.125</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
       <ownershipNature><directOrIndirectOwnership><value>I</value></directOrIndirectOwnership><natureOfOwnership><value>Trust</value></natureOfOwnership></ownershipNature>
      </nonDerivativeTransaction></nonDerivativeTable><footnotes><footnote id="F1">Synthetic qualification.</footnote></footnotes></ownershipDocument>"""


def test_exact_signed_decimals_roles_buckets_and_joint_reporting_groups():
    xml = insider_xml().replace(
        "<nonDerivativeTable>",
        """<reportingOwner><reportingOwnerId><rptOwnerCik>88</rptOwnerCik><rptOwnerName>Owner Two</rptOwnerName></reportingOwnerId><reportingOwnerRelationship><isOther>1</isOther><otherText>Trustee</otherText></reportingOwnerRelationship></reportingOwner><nonDerivativeTable>""",
    )
    rows = run("4", xml)["insiders"]
    assert len(rows) == 2 and rows[0]["id"] != rows[1]["id"]
    assert rows[0]["transaction_group_id"] == rows[1]["transaction_group_id"]
    assert rows[0]["joint_reporting"] and rows[0]["officer_title"] == "CFO"
    assert rows[0]["ownership_form"] == "I" and rows[0]["nature_of_ownership"] == "Trust"
    assert rows[0]["shares"] == "10.125" and rows[0]["price"] == "-0.0000000000000000000000000123"
    assert rows[1]["other_role"] == "Trustee"
    assert run("4", xml)["insiders"][0]["id"] == rows[0]["id"]


@pytest.mark.parametrize("form", ["3", "4", "5"])
def test_amendments_preserve_holdings_and_transaction_state(form):
    docs, metadata = source(form)
    docs[0]["content"] = docs[0]["content"].replace(
        f"<documentType>{form}</documentType>".encode(), f"<documentType>{form}/A</documentType>".encode()
    )
    result = parse.parse_filing(form + "/A", docs, metadata)
    assert result["filing"]["is_amendment"]
    if form == "3":
        assert all(row["is_holding"] for row in result["insiders"])


def test_footnote_only_number_is_unknown_not_zero():
    xml = insider_xml().replace("<value>-0.0000000000000000000000000123</value>", "")
    row = run("4", xml)["insiders"][0]
    assert row["price"] is None and row["footnote_ids"] == ["F1"]
    assert row["footnotes"] == ["[F1] Synthetic qualification."]
    with pytest.raises(ValueError, match="Form 3"):
        run("3", insider_xml("3"))


def institution_xml(
    form="13F-HR", amendment="false", amendment_type="", confidential="false", report="13F HOLDINGS REPORT"
):
    return f"""<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><headerData><submissionType>{form}</submissionType><filerInfo><filer><credentials><cik>456</cik></credentials></filer></filerInfo></headerData>
     <formData><coverPage><reportCalendarOrQuarter>12-31-2022</reportCalendarOrQuarter><isAmendment>{amendment}</isAmendment><amendmentNo>2</amendmentNo><amendmentInfo><amendmentType>{amendment_type}</amendmentType></amendmentInfo><filingManager><name>Synthetic Manager</name></filingManager><reportType>{report}</reportType></coverPage><summaryPage><tableEntryTotal>1</tableEntryTotal><tableValueTotal>123.456</tableValueTotal><isConfidentialOmitted>{confidential}</isConfidentialOmitted></summaryPage></formData></edgarSubmission>"""


TABLE = """<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"><infoTable><nameOfIssuer>Synthetic Issuer</nameOfIssuer><titleOfClass>Class B</titleOfClass><cusip>000000100</cusip><value>123.456</value><shrsOrPrnAmt><sshPrnamt>9007199254740993.125</sshPrnamt><sshPrnamtType>PRN</sshPrnamtType></shrsOrPrnAmt><putCall>PUT</putCall><investmentDiscretion>DFND</investmentDiscretion><otherManager>2,3</otherManager><votingAuthority><Sole>0</Sole><Shared>1</Shared><None>99</None></votingAuthority></infoTable></informationTable>"""


def institution(cover, **meta):
    return parse.parse_filing(
        "13F-HR/A" if "13F-HR/A" in cover else "13F-HR",
        [{"filename": "cover.xml", "content": cover.encode()}, {"filename": "table.xml", "content": TABLE.encode()}],
        {**META, **meta},
    )


@pytest.mark.parametrize("filed,value,scale", [("2022-12-31", "123456.000", "1000"), ("2023-01-03", "123.456", "1")])
def test_13f_scale_uses_submission_date_not_report_period(filed, value, scale):
    result = institution(institution_xml(), filed_date=filed)
    row = result["positions"][0]
    assert result["filing"]["manager_cik"] == 456 and result["filing"]["issuer_cik"] is None
    assert result["filing"]["value_scale"] == scale
    assert row["value_usd"] == value and row["shares"] == "9007199254740993.125"
    assert row["share_type"] == "PRN" and row["put_call"] == "PUT" and row["other_managers"] == ["2,3"]


@pytest.mark.parametrize("kind", ["RESTATEMENT", "NEW HOLDINGS"])
def test_13f_amendment_and_confidential_scope_remain_explicit(kind):
    result = institution(institution_xml("13F-HR/A", "true", kind, "true"))
    assert result["filing"]["amendment_type"] == kind
    assert result["filing"]["amendment_number"] == "2"
    assert result["filing"]["confidential_omitted"] is True
    assert "change" not in result["positions"][0]


def test_13f_incomplete_notice_and_count_mismatch_never_become_zero_portfolios():
    with pytest.raises(ValueError, match="missing"):
        run("13F-HR", institution_xml())
    with pytest.raises(ValueError, match="row count"):
        institution(institution_xml().replace("<tableEntryTotal>1", "<tableEntryTotal>2"))
    with pytest.raises(ValueError, match="notice"):
        institution(institution_xml(report="13F NOTICE"))
    with pytest.raises(ValueError, match="Unsupported"):
        run("13F-NT", institution_xml())
    with pytest.raises(ValueError, match="amendment flag"):
        institution(institution_xml(amendment="true"))


@pytest.mark.parametrize(
    "rule,category",
    [
        ("Rule 13d-1(b)", "institutional"),
        ("Rule 13d-1(c)", "passive"),
        ("Rule 13d-1(d)", "exempt"),
        ("", "unspecified"),
    ],
)
def test_current_multiple_cusips_and_declared_13g_categories(rule, category):
    docs, _metadata = source("SCHEDULE 13G")
    xml = (
        docs[0]["content"]
        .decode()
        .replace("Rule 13d-1(b)", rule)
        .replace("</issuerCusips>", "<issuerCusipNumber>037833200</issuerCusipNumber></issuerCusips>")
    )
    event = run("SC 13G", xml)["event"]
    assert event["cusip"] is None and event["cusips"] == ["037833100", "037833200"]
    assert event["filing_category"] == category
    assert event["issuer_cik"] != META["filer_cik"]


def test_optional_exhibits_do_not_invent_a_letter():
    docs, metadata = source("SCHEDULE 13D/A")
    docs.append(
        {
            "filename": "agreement.htm",
            "content": b"<p>Synthetic joint filing agreement</p>",
            "source_url": "https://www.sec.gov/Archives/synthetic-agreement.htm",
            "type": "EX-99.1",
            "description": "Joint filing agreement",
        }
    )
    event = parse.parse_filing("SC13D/A", docs, metadata)["event"]
    assert event["exhibits"][0]["title"] == "Joint filing agreement"
    assert event["filing_category"] == "schedule_13d"


@pytest.mark.parametrize(
    "payload",
    [
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
        b'<!DOCTYPE x [<!ENTITY e "huge">]><x>&e;</x>',
        '<!DOCTYPE x SYSTEM "https://example.test/x"><x/>'.encode("utf-16"),
        b"<x><y></x>",
    ],
)
def test_untrusted_xml_entities_and_malformed_content_are_rejected(payload):
    with pytest.raises(ValueError):
        run("4", payload)


def test_structural_and_byte_limits(monkeypatch):
    with pytest.raises(ValueError, match="structural"):
        run("4", "<x>" * 70 + "</x>" * 70)
    monkeypatch.setattr(parse, "MAX_NODES", 10)
    with pytest.raises(ValueError, match="structural"):
        run("4", "<x>" + "<y/>" * 11 + "</x>")
    monkeypatch.setattr(parse, "MAX_XML_BYTES", 20)
    with pytest.raises(ValueError, match="byte"):
        run("4", insider_xml())


@pytest.mark.parametrize("number", ["NaN", "Infinity", "1e99999", "1,23", "12.3.4"])
def test_invalid_quantities_do_not_silently_coerce(number):
    with pytest.raises(ValueError, match="decimal"):
        run("4", insider_xml(amount=number))


def test_ambiguous_scalar_duplicate_owner_and_invalid_documents_fail():
    with pytest.raises(ValueError, match="Ambiguous"):
        run(
            "4",
            insider_xml().replace("<issuerCik>123</issuerCik>", "<issuerCik>123</issuerCik><issuerCik>999</issuerCik>"),
        )
    with pytest.raises(ValueError, match="source document"):
        parse.parse_filing("4", [{"filename": "x.xml", "content": "not bytes"}], META)
    with pytest.raises(ValueError, match="primary document"):
        parse.parse_filing(
            "SCHEDULE 13D", [{"filename": "old.htm", "content": b"<p>legacy unstructured text</p>"}], META
        )


def test_document_total_and_row_limits(monkeypatch):
    docs = [{"filename": "x.xml", "content": b"<x/>"}] * 33
    with pytest.raises(ValueError, match="document count"):
        parse.parse_filing("4", docs, META)
    monkeypatch.setattr(parse, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(ValueError, match="byte limit"):
        parse.parse_filing("4", docs[:3], META)
    monkeypatch.setattr(parse, "MAX_TOTAL_BYTES", 32 * 1024 * 1024)
    monkeypatch.setattr(parse, "MAX_ROWS", 1)
    with pytest.raises(ValueError, match="row limit"):
        parse.parse_filing("3", *source("3"))


def test_joint_duplicate_identity_is_not_silently_overwritten():
    xml = insider_xml()
    owner = xml[xml.index("<reportingOwner>") : xml.index("</reportingOwner>") + len("</reportingOwner>")]
    with pytest.raises(ValueError, match="Duplicate reporting owner"):
        run("4", xml.replace("<nonDerivativeTable>", owner + "<nonDerivativeTable>"))


def test_embedded_information_table_and_duplicate_download_have_one_count():
    embedded = (
        "<documents><document><conformedDocumentType>INFORMATION TABLE</conformedDocumentType><contents>"
        + base64.b64encode(TABLE.encode()).decode()
        + "</contents></document></documents>"
    )
    xml = institution_xml().replace("</edgarSubmission>", embedded + "</edgarSubmission>")
    assert len(run("13F-HR", xml)["positions"]) == 1
    docs = [
        {"filename": "cover.xml", "content": xml.encode()},
        {"filename": "table.xml", "content": TABLE.encode()},
        {"filename": "duplicate.xml", "content": TABLE.encode()},
    ]
    assert len(parse.parse_filing("13F-HR", docs, META)["positions"]) == 1
    bad = xml.replace(base64.b64encode(TABLE.encode()).decode(), "not valid base64?")
    with pytest.raises(ValueError, match="embedded"):
        run("13F-HR", bad)


def test_13g_amendment_alias_and_unicode_minus_are_preserved():
    docs, meta = source("SCHEDULE 13G")
    docs[0]["content"] = docs[0]["content"].replace(
        b"<submissionType>SCHEDULE 13G</submissionType>", b"<submissionType>SCHEDULE 13G/A</submissionType>"
    )
    result = parse.parse_filing("SC 13G/A", docs, meta)
    assert result["filing"]["is_amendment"] and result["event"]["filing_category"] == "institutional"
    assert run("4", insider_xml(amount="−1.125"))["insiders"][0]["shares"] == "-1.125"


def test_13f_unrecognized_types_and_missing_required_count_are_not_partial_success():
    with pytest.raises(ValueError, match="report type"):
        institution(institution_xml(report="UNKNOWN"))
    with pytest.raises(ValueError, match="Missing required"):
        institution(institution_xml().replace("<tableEntryTotal>1</tableEntryTotal>", ""))
