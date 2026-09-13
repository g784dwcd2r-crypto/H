"""Invented ownership observations for isolated browser acceptance. Never seed a live lake."""

from datetime import date, timedelta

from filings_hub.ingest.edgar_client import EdgarClient
from filings_hub.ownership.ingest import filing_metadata
from filings_hub.ownership.parse import parse_filing
from filings_hub.ownership.store import OwnershipStore


def insider_xml(day="2026-09-10", owner=9000001, name="Jordan Avery (synthetic)", after="1100", code="P"):
    return f"""<ownershipDocument><documentType>4</documentType><periodOfReport>{day}</periodOfReport>
    <issuer><issuerCik>320193</issuerCik><issuerName>Synthetic company fixture</issuerName></issuer>
    <reportingOwner><reportingOwnerId><rptOwnerCik>{owner}</rptOwnerCik><rptOwnerName>{name}</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship></reportingOwner>
    <nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common stock</value></securityTitle>
    <transactionDate><value>{day}</value></transactionDate><transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>12.50</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>{"D" if code == "S" else "A"}</value></transactionAcquiredDisposedCode></transactionAmounts>
    <postTransactionAmounts><sharesOwnedFollowingTransaction><value>{after}</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
    </nonDerivativeTransaction></nonDerivativeTable><remarks>Synthetic acceptance data only.</remarks></ownershipDocument>""".encode()


def institution_xml(period, shares):
    cover = f"""<edgarSubmission><headerData><submissionType>13F-HR</submissionType><filerInfo><filer><credentials><cik>9000900</cik></credentials></filer></filerInfo></headerData>
    <formData><coverPage><reportCalendarOrQuarter>{period}</reportCalendarOrQuarter><filingManager><name>Northstar Research Partners (synthetic)</name></filingManager>
    <isAmendment>false</isAmendment><reportType>13F HOLDINGS REPORT</reportType></coverPage><summaryPage><tableEntryTotal>1</tableEntryTotal><isConfidentialOmitted>false</isConfidentialOmitted></summaryPage></formData></edgarSubmission>""".encode()
    table = f"""<informationTable><infoTable><nameOfIssuer>Synthetic company fixture</nameOfIssuer><titleOfClass>Common stock</titleOfClass><cusip>037833100</cusip>
    <value>125000</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt><investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>{shares}</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable></informationTable>""".encode()
    return cover, table


def event_xml(day="2026-09-10"):
    return f"""<edgarSubmission><headerData><submissionType>SCHEDULE 13D</submissionType></headerData><formData>
    <coverPageHeader><issuerInfo><issuerCik>320193</issuerCik><issuerName>Synthetic company fixture</issuerName><issuerCusipNumber>037833100</issuerCusipNumber></issuerInfo>
    <securitiesClassTitle>Common stock</securitiesClassTitle><dateOfEvent>{day}</dateOfEvent></coverPageHeader>
    <reportingPersons><reportingPersonInfo><reportingPersonCik>9000800</reportingPersonCik><reportingPersonName>Harbor Capital (synthetic)</reportingPersonName>
    <aggregateAmountOwned>120000</aggregateAmountOwned><percentOfClass>6.2</percentOfClass></reportingPersonInfo></reportingPersons>
    <items1To7><item4><transactionPurpose>Synthetic fixture: investment purposes, no activist conclusion.</transactionPurpose></item4></items1To7></formData></edgarSubmission>""".encode()


def seed_ownership(index, storage):
    store = OwnershipStore(index, storage)
    today = date.today()

    def add(number, form, raws, filer=320193, filed=None):
        accession = f"0000320193-26-{980000 + number:06d}"
        meta = filing_metadata(filer, accession, form, (filed or today).isoformat())
        documents = [
            {
                "filename": filename,
                "content": raw,
                "source_url": EdgarClient.primary_doc_url(filer, accession, filename),
            }
            for filename, raw in raws
        ]
        return store.ingest(parse_filing(form, documents, meta), documents)

    add(
        1,
        "4",
        [("synthetic-insider.xml", insider_xml(str(today - timedelta(days=3)), after="1000"))],
        filed=today - timedelta(days=2),
    )
    add(2, "4", [("synthetic-insider.xml", insider_xml(str(today - timedelta(days=1))))])
    add(
        3,
        "4",
        [
            (
                "synthetic-insider.xml",
                insider_xml(str(today - timedelta(days=1)), 9000002, "Morgan Reed (synthetic)", "500", "S"),
            )
        ],
    )
    for number in range(4, 25):
        add(
            number,
            "4",
            [
                (
                    "synthetic-insider.xml",
                    insider_xml(
                        str(today - timedelta(days=1)),
                        9000000 + number,
                        f"Fixture Director {number:02d} (synthetic)",
                        "1000",
                    ),
                )
            ],
        )
    # Mapping is proven by this structured synthetic subject disclosure; no company-name inference.
    add(30, "SCHEDULE 13D", [("synthetic-schedule.xml", event_xml(str(today - timedelta(days=1))))])
    for number, period, shares in [(31, "2026-03-31", "8000"), (32, "2026-06-30", "10000")]:
        cover, table = institution_xml(period, shares)
        add(number, "13F-HR", [("synthetic-cover.xml", cover), ("synthetic-positions.xml", table)], filer=9000900)
    return store
