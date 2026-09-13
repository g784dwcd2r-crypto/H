"""Bounded SEC ownership XML normalization; no network calls or ownership inference.

Source fields, classes and reporting identities stay separate. This is not an XSD
validator: unsupported/ambiguous document structures fail explicitly. See the SEC
specification URLs and original sample hashes in tests/fixtures/ownership/README.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from xml.etree.ElementTree import Element, TreeBuilder
from xml.parsers import expat

MAX_XML_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_DOCUMENTS = 32
MAX_NODES = 400_000
MAX_DEPTH = 64
MAX_ROWS = 25_000


def normalize_form(form: str) -> str:
    compact = re.sub(r"\s+", "", str(form).upper())
    for prefix in ("SCHEDULE", "SC"):
        if compact.startswith(prefix + "13"):
            return "SCHEDULE " + compact[len(prefix) :]
    return compact


def _xml(content: bytes) -> Element:
    if not isinstance(content, bytes) or not content or len(content) > MAX_XML_BYTES:
        raise ValueError("XML byte limit exceeded or content missing")
    builder = TreeBuilder()
    parser = expat.ParserCreate(namespace_separator="}")
    depth = nodes = 0

    def start(name, attrs):
        nonlocal depth, nodes
        depth += 1
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError("XML structural limit exceeded")
        # Local names are sufficient only after namespace parsing validates prefixes.
        builder.start(name.rsplit("}", 1)[-1].lower(), attrs)

    def end(name):
        nonlocal depth
        builder.end(name.rsplit("}", 1)[-1].lower())
        depth -= 1

    def forbidden(*_args):
        raise ValueError("DTD and entity declarations are not supported")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(content, True)
        return builder.close()
    except (expat.ExpatError, RecursionError) as exc:
        raise ValueError("Malformed ownership XML") from exc


def _at(node: Element | None, path: str) -> Element | None:
    for part in path.lower().split("/"):
        if node is None:
            return None
        matches = node.findall(part)
        if len(matches) > 1:
            raise ValueError(f"Ambiguous scalar XML field: {path}")
        node = matches[0] if matches else None
    return node


def _text(node: Element | None, path: str = "") -> str | None:
    node = _at(node, path) if path else node
    return "".join(node.itertext()).strip() or None if node is not None else None


def _required(node: Element, path: str) -> str:
    value = _text(node, path)
    if not value:
        raise ValueError(f"Missing required XML field: {path}")
    return value


def _cik(raw: str | int | None, *, required: bool = False) -> int | None:
    if raw is None or str(raw).strip() in ("", "0", "0000000000"):
        if required:
            raise ValueError("Missing reporting CIK")
        return None
    if not re.fullmatch(r"\d{1,10}", str(raw).strip()):
        raise ValueError("Invalid CIK")
    return int(str(raw).strip())


def _date(raw: str | None, *, required: bool = False) -> str | None:
    if not raw:
        if required:
            raise ValueError("Missing required reporting date")
        return None
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Invalid ownership reporting date")


def _bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    if raw.lower() in ("1", "true", "y", "yes"):
        return True
    if raw.lower() in ("0", "false", "n", "no"):
        return False
    raise ValueError("Invalid ownership boolean")


def _number(raw: str | None) -> str | None:
    if raw is None or raw.upper() in ("N/A", "NA", "NONE"):
        return None
    value = raw.replace("\u2212", "-")
    if len(value) > 100 or not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", value):
        raise ValueError("Invalid exact decimal in ownership XML")
    return format(Decimal(value.replace(",", "")), "f")


def _footnotes(node: Element, notes: dict) -> tuple[list[str], list[str]]:
    ids = list(dict.fromkeys(n.attrib.get("id", "") for n in node.iter("footnoteid")))
    return ids, [f"[{key}] {notes.get(key, 'Referenced footnote is missing from the source.')}" for key in ids]


def _insiders(root: Element, filing: dict) -> list[dict]:
    issuer = _at(root, "issuer")
    filing.update(
        issuer_cik=_cik(_text(issuer, "issuercik"), required=True),
        issuer_name=_required(root, "issuer/issuername"),
        report_period=_date(_text(root, "periodofreport"), required=True),
        original_filed_date=_date(_text(root, "dateoforiginalsubmission")),
        is_10b5_1=_bool(_text(root, "aff10b5one")),
        not_subject_to_section16=_bool(_text(root, "notsubjecttosection16")),
        remarks=_text(root, "remarks"),
    )
    notes = {}
    for item in root.findall("footnotes/footnote"):
        key = item.attrib.get("id")
        if not key or key in notes:
            raise ValueError("Duplicate or missing footnote identifier")
        notes[key] = _text(item) or ""
    owners = root.findall("reportingowner")
    if not owners or len(owners) > 100:
        raise ValueError("Missing or excessive reporting owners")
    owner_ids = [_cik(_text(o, "reportingownerid/rptownercik"), required=True) for o in owners]
    if len(set(owner_ids)) != len(owner_ids):
        raise ValueError("Duplicate reporting owner CIK")
    rows = []
    for table, derivative in (("nonderivativetable", False), ("derivativetable", True)):
        container = _at(root, table)
        if container is None:
            continue
        for ordinal, item in enumerate(container):
            if item.tag not in {
                "nonderivativetransaction",
                "derivativetransaction",
                "nonderivativeholding",
                "derivativeholding",
            }:
                raise ValueError("Unsupported insider table row")
            holding = item.tag.endswith("holding")
            if filing["form"].startswith("3") and not holding:
                raise ValueError("Form 3 may contain holdings, not transactions")
            group = hashlib.sha256(f"{filing['accession']}:{table}:{ordinal}".encode()).hexdigest()
            footnote_ids, footnotes = _footnotes(item, notes)
            base = {
                "issuer_cik": filing["issuer_cik"],
                "security_title": _required(item, "securitytitle/value"),
                "is_derivative": derivative,
                "ownership_form": _text(item, "ownershipnature/directorindirectownership/value"),
                "nature_of_ownership": _text(item, "ownershipnature/natureofownership/value"),
                "transaction_date": None if holding else _date(_text(item, "transactiondate/value"), required=True),
                "transaction_code": None if holding else _text(item, "transactioncoding/transactioncode"),
                "acquired_disposed": None
                if holding
                else _text(item, "transactionamounts/transactionacquireddisposedcode/value"),
                "shares": None if holding else _number(_text(item, "transactionamounts/transactionshares/value")),
                "price": None if holding else _number(_text(item, "transactionamounts/transactionpricepershare/value")),
                "owned_after": _number(_text(item, "posttransactionamounts/sharesownedfollowingtransaction/value")),
                "value_owned_after": _number(
                    _text(item, "posttransactionamounts/valueownedfollowingtransaction/value")
                ),
                "is_10b5_1": filing["is_10b5_1"],
                "plan_flag_scope": "filing",
                "footnotes": footnotes,
                "footnote_ids": footnote_ids,
                "is_holding": holding,
                "transaction_group_id": group,
                "joint_reporting": len(owners) > 1,
                "underlying_security_title": _text(item, "underlyingsecurity/underlyingsecuritytitle/value"),
                "underlying_shares": _number(_text(item, "underlyingsecurity/underlyingsecurityshares/value")),
                "exercise_price": _number(_text(item, "conversionorexerciseprice/value")),
                "exercise_date": _date(_text(item, "exercisedate/value")),
                "expiration_date": _date(_text(item, "expirationdate/value")),
            }
            if base["ownership_form"] not in (None, "D", "I") or base["acquired_disposed"] not in (None, "A", "D"):
                raise ValueError("Invalid insider ownership or acquisition/disposition code")
            for owner in owners:
                relation = _at(owner, "reportingownerrelationship")
                owner_cik = _cik(_text(owner, "reportingownerid/rptownercik"), required=True)
                rows.append(
                    {
                        **base,
                        "id": hashlib.sha256(f"{group}:{owner_cik}".encode()).hexdigest(),
                        "owner_cik": owner_cik,
                        "owner_name": _required(owner, "reportingownerid/rptownername"),
                        "officer_title": _text(relation, "officertitle"),
                        **{
                            name: _bool(_text(relation, tag))
                            for name, tag in (
                                ("is_director", "isdirector"),
                                ("is_officer", "isofficer"),
                                ("is_ten_percent_owner", "istenpercentowner"),
                                ("is_other", "isother"),
                            )
                        },
                        "other_role": _text(relation, "othertext"),
                    }
                )
                if len(rows) > MAX_ROWS:
                    raise ValueError("Ownership row limit exceeded")
    filing["footnotes"] = notes
    if len(owners) > 1:
        filing["warnings"].append(
            "Joint reporting owners share source transaction groups; rows are not separate trades."
        )
    if filing["is_10b5_1"]:
        filing["warnings"].append("The 10b5-1 checkbox describes the filing, not necessarily every transaction.")
    if not rows:
        filing["warnings"].append("No tabular holdings or transactions were reported; no zero holding is inferred.")
    return rows


def _institutions(root: Element, tables: list[Element], filing: dict) -> list[dict]:
    cover = _at(root, "formdata/coverpage")
    manager_cik = _cik(_text(root, "headerdata/filerinfo/filer/credentials/cik"))
    if manager_cik is None:
        manager_cik = _cik(filing.get("filer_cik"), required=True)
    filing.update(
        manager_cik=manager_cik,
        manager_name=_required(root, "formdata/coverpage/filingmanager/name"),
        report_period=_date(_text(cover, "reportcalendarorquarter"), required=True),
        amendment_type=_text(cover, "amendmentinfo/amendmenttype"),
        amendment_number=_text(cover, "amendmentno"),
        report_type=_required(root, "formdata/coverpage/reporttype"),
        confidential_omitted=_bool(_text(root, "formdata/summarypage/isconfidentialomitted")),
        table_entry_total=_number(_required(root, "formdata/summarypage/tableentrytotal")),
        table_value_total=_number(_text(root, "formdata/summarypage/tablevaluetotal")),
        other_included_managers_count=_number(_text(root, "formdata/summarypage/otherincludedmanagerscount")),
        other_included_managers=[
            {
                "sequence_number": _text(item, "sequencenumber"),
                "name": _text(item, "othermanager/name"),
                "cik": _cik(_text(item, "othermanager/cik")),
                "file_number": _text(item, "othermanager/form13ffilenumber"),
            }
            for item in root.findall("formdata/summarypage/othermanagers2info/othermanager2")
        ],
        is_notice=False,
    )
    if filing["report_type"] == "13F NOTICE":
        raise ValueError("13F notice is not a positions portfolio")
    if filing["report_type"] not in {"13F HOLDINGS REPORT", "13F COMBINATION REPORT"}:
        raise ValueError("Unsupported 13F report type")
    xml_amendment = _bool(_text(cover, "isamendment"))
    if xml_amendment is not None and xml_amendment != filing["is_amendment"]:
        raise ValueError("13F amendment flag disagrees with submission form")
    scale = "1" if date.fromisoformat(filing["filed_date"]) >= date(2023, 1, 3) else "1000"
    filing.update(value_scale=scale, value_units="USD" if scale == "1" else "USD thousands")
    rows = []
    for table in tables:
        for item in table:
            if item.tag != "infotable":
                raise ValueError("Unsupported 13F information-table row")
            value = _number(_required(item, "value"))
            with localcontext() as ctx:
                ctx.prec = 120
                value_usd = format(Decimal(value) * Decimal(scale), "f") if value is not None else None
            rows.append(
                {
                    "cusip": _required(item, "cusip").upper(),
                    "issuer_name": _required(item, "nameofissuer"),
                    "security_title": _required(item, "titleofclass"),
                    "shares": _number(_required(item, "shrsorprnamt/sshprnamt")),
                    "share_type": _required(item, "shrsorprnamt/sshprnamttype"),
                    "put_call": _text(item, "putcall"),
                    "value_usd": value_usd,
                    "reported_value": value,
                    "discretion": _text(item, "investmentdiscretion"),
                    "other_managers": [_text(n) for n in item.findall("othermanager")],
                    "voting_sole": _number(_text(item, "votingauthority/sole")),
                    "voting_shared": _number(_text(item, "votingauthority/shared")),
                    "voting_none": _number(_text(item, "votingauthority/none")),
                    "figi": _text(item, "figi"),
                }
            )
            if rows[-1]["share_type"] not in {"SH", "PRN"} or rows[-1]["put_call"] not in {
                None,
                "PUT",
                "CALL",
                "Put",
                "Call",
            }:
                raise ValueError("Invalid 13F share type or put/call designation")
            if len(rows) > MAX_ROWS:
                raise ValueError("Ownership row limit exceeded")
    if not tables:
        raise ValueError("13F information table is missing")
    if filing["table_entry_total"] is not None and Decimal(filing["table_entry_total"]) != len(rows):
        raise ValueError("13F information-table row count disagrees with the cover page")
    return rows


def _events(root: Element, filing: dict, documents: list[dict]) -> dict:
    form = _at(root, "formdata")
    header = _at(form, "coverpageheader")
    issuer = _at(header, "issuerinfo")
    issuer_cik = _cik(_text(issuer, "issuercik"), required=True)
    issuer_name = _required(root, "formdata/coverpageheader/issuerinfo/issuername")
    cusips = list(dict.fromkeys(_text(n).upper() for n in issuer.iter("issuercusipnumber") if _text(n)))
    if not cusips:
        old = _text(issuer, "issuercusip") or _text(header, "cusipnumber")
        cusips = [old.upper()] if old else []
    is_g = filing["form"].startswith("SCHEDULE 13G")
    people = []
    for person in (
        form.findall("coverpageheaderreportingpersondetails")
        if is_g
        else form.findall("reportingpersons/reportingpersoninfo")
    ):
        people.append(
            {
                "cik": _cik(_text(person, "reportingcik" if is_g else "reportingpersoncik")),
                "name": _required(person, "reportingpersonname"),
                "shares": _number(
                    _text(
                        person,
                        "reportingpersonbeneficiallyownedaggregatenumberofshares" if is_g else "aggregateamountowned",
                    )
                ),
                "percent": _number(_text(person, "classpercent" if is_g else "percentofclass")),
                "types": [_text(n) for n in person.findall("typeofreportingperson")],
                "member_of_group": _text(person, "memberofgroup"),
                "excludes_shares": _bool(_text(person, "isaggregateexcludeshares")),
                "comments": _text(person, "commentcontent"),
                **{
                    key: _number(
                        _text(person, ("reportingpersonbeneficiallyownednumberofshares/" if is_g else "") + tag)
                    )
                    for key, tag in (
                        ("voting_sole", "solevotingpower"),
                        ("voting_shared", "sharedvotingpower"),
                        ("dispositive_sole", "soledispositivepower"),
                        ("dispositive_shared", "shareddispositivepower"),
                    )
                },
            }
        )
    if not people:
        raise ValueError("No structured reporting people in beneficial ownership filing")
    if len(people) > MAX_ROWS:
        raise ValueError("Reporting people limit exceeded")
    rules = [_text(n) for n in header.iter("designaterulepursuantthisschedulefiled")]
    categories = {"Rule 13d-1(b)": "institutional", "Rule 13d-1(c)": "passive", "Rule 13d-1(d)": "exempt"}
    declared = list(dict.fromkeys(categories[r] for r in rules if r in categories))
    category = declared[0] if len(declared) == 1 else "mixed" if declared else "unspecified"
    event_date = _date(_text(header, "eventdaterequiresfilingthisstatement" if is_g else "dateofevent"))
    filing.update(
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        report_period=event_date,
        amendment_number=_text(header, "amendmentno"),
    )
    exhibits = []
    for doc in documents:
        doc_type = str(doc.get("document_type") or doc.get("doc_type") or doc.get("type") or "")
        if doc_type.upper().startswith("EX-"):
            exhibits.append(
                {
                    "filename": doc["filename"],
                    "source_url": doc.get("source_url"),
                    "title": doc.get("description") or doc["filename"],
                    "type": doc_type,
                }
            )
    return {
        "issuer_cik": issuer_cik,
        "issuer_name": issuer_name,
        "cusip": cusips[0] if len(cusips) == 1 else None,
        "cusips": cusips,
        "security_title": _text(header, "securitiesclasstitle"),
        "event_date": event_date,
        "reporting_people": people,
        "purpose": _text(form, "items1to7/item4/transactionpurpose") if not is_g else None,
        "contracts": _text(form, "items1to7/item6/contractdescription") if not is_g else None,
        "filing_category": category if is_g else "schedule_13d",
        "declared_rules": rules,
        "exhibits": exhibits,
        "exhibit_description": _text(form, "items1to7/item7/filedexhibits"),
    }


def parse_filing(form: str, documents: list[dict], metadata: dict) -> dict:
    """Parse one accession's untrusted XML, preserving source financial quantities exactly."""
    form = normalize_form(form)
    base = form.removesuffix("/A")
    if base not in {"3", "4", "5", "13F-HR", "SCHEDULE 13D", "SCHEDULE 13G"}:
        raise ValueError(f"Unsupported ownership form: {form}")
    if not isinstance(documents, list) or not documents or len(documents) > MAX_DOCUMENTS:
        raise ValueError("Ownership document count is outside bounds")
    if not isinstance(metadata, dict) or any(
        not isinstance(d, dict)
        or not isinstance(d.get("content"), bytes)
        or not isinstance(d.get("filename"), str)
        or not d["filename"]
        for d in documents
    ):
        raise ValueError("Invalid ownership metadata or source document")
    if sum(len(d.get("content", b"")) for d in documents) > MAX_TOTAL_BYTES:
        raise ValueError("Ownership document byte limit exceeded")
    filing = {
        **metadata,
        "form": form,
        "is_amendment": form.endswith("/A"),
        "amendment_type": None,
        "report_period": None,
        "issuer_cik": None,
        "issuer_name": None,
        "manager_cik": None,
        "manager_name": None,
        "confidential_omitted": None,
        "warnings": [],
    }
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", str(filing.get("accession", ""))):
        raise ValueError("Invalid accession")
    filing["filed_date"] = _date(filing.get("filed_date"), required=True)
    roots = []
    tables = []
    hashes = set()
    for doc in documents:
        if not str(doc.get("filename", "")).lower().endswith(".xml"):
            continue
        raw = doc.get("content")
        root = _xml(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if digest in hashes:
            continue
        hashes.add(digest)
        if root.tag == "informationtable":
            tables.append(root)
        elif root.tag == "ownershipdocument" or root.tag == "edgarsubmission":
            declared = _text(root, "documenttype") or _text(root, "headerdata/submissiontype")
            if normalize_form(declared or "") == form:
                roots.append(root)
    if len(roots) != 1:
        raise ValueError("Expected exactly one supported ownership XML primary document")
    root = roots[0]
    result = {
        "kind": "insiders" if base in {"3", "4", "5"} else "institutions" if base == "13F-HR" else "events",
        "filing": filing,
        "insiders": [],
        "positions": [],
        "event": None,
    }
    if result["kind"] == "insiders":
        result["insiders"] = _insiders(root, filing)
    elif result["kind"] == "institutions":
        if not tables:
            # SEC submission examples embed a base64 information table. Public EDGAR
            # normally supplies it as a separate document; never decode twice.
            for doc in root.findall("documents/document"):
                if _text(doc, "conformeddocumenttype") == "INFORMATION TABLE":
                    try:
                        raw = base64.b64decode(re.sub(r"\s+", "", _required(doc, "contents")), validate=True)
                    except ValueError as exc:
                        raise ValueError("Malformed embedded 13F information table") from exc
                    table = _xml(raw)
                    if table.tag != "informationtable":
                        raise ValueError("Unsupported embedded information table")
                    tables.append(table)
        result["positions"] = _institutions(root, tables, filing)
    else:
        result["event"] = _events(root, filing, documents)
    return result
