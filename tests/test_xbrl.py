"""The filing's own XBRL, parsed from fixtures rather than the network."""

from filings_hub.ingest import xbrl
from filings_hub.testing import xbrl_fixtures as fx


def test_concept_from_href_reads_both_halves_of_the_qname():
    assert xbrl.concept_from_href("https://x/us-gaap-2026.xsd#us-gaap_Revenues") == "us-gaap:Revenues"
    assert xbrl.concept_from_href("tfin-20260630.xsd#tfin_CardIncome") == "tfin:CardIncome"


def test_labels_are_the_companys_own_words_per_role():
    labels = xbrl.parse_labels(fx.LABELS)
    rev = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    assert labels[rev]["label"] == "Fee income" and labels[rev]["terseLabel"] == "Fees"
    # a presentation arc asking for the total role gets the total wording, not the plain one
    assert xbrl.label_for(labels, "us-gaap:NoninterestIncome") == "Noninterest income"
    total = "http://www.xbrl.org/2003/role/totalLabel"
    assert xbrl.label_for(labels, "us-gaap:NoninterestIncome", total) == "Total noninterest income"
    # a role the company did not define falls back to the standard label rather than inventing one
    assert xbrl.label_for(labels, rev, total) == "Fee income"
    assert xbrl.label_for(labels, "us-gaap:NotInThisFiling") is None


def test_prohibited_arcs_are_overrides_and_are_not_followed():
    labels = xbrl.parse_labels(fx.LABELS)
    assert labels["tfin:GainOnSaleOfLoans"]["label"] == "Gain on sale of loans"
    parents = {a.child for a in xbrl.parse_calculation(fx.CALCULATION)}
    assert "us-gaap:NoninterestExpense" not in parents


def test_presentation_tree_is_the_order_the_company_prints():
    arcs = xbrl.parse_presentation(fx.PRESENTATION)
    labels = xbrl.parse_labels(fx.LABELS)
    lines = xbrl.presentation_tree(arcs, fx.INCOME_ROLE, labels)
    assert [line.concept for line in lines] == [
        "us-gaap:IncomeStatementAbstract",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "tfin:GainOnSaleOfLoans",
        "us-gaap:NoninterestIncome",
    ]
    assert [line.depth for line in lines] == [0, 1, 1, 1]
    assert lines[-1].label == "Total noninterest income"


def test_calculation_tree_says_what_adds_into_what_and_with_which_sign():
    children = xbrl.calculation_children(xbrl.parse_calculation(fx.CALCULATION))
    kids = children[(fx.INCOME_ROLE, "us-gaap:NoninterestIncome")]
    assert [(k.child, k.weight) for k in kids] == [
        ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 1.0),
        ("tfin:GainOnSaleOfLoans", 1.0),
    ]


def test_role_definitions_name_the_statements():
    definitions = xbrl.parse_role_definitions(fx.SCHEMA)
    income = definitions[fx.INCOME_ROLE]
    assert income.kind == "Statement" and income.title == "CONSOLIDATED STATEMENTS OF INCOME"
    assert definitions[fx.DEBT_ROLE].kind == "Disclosure"
    assert income.title.count(" - ") == 0
    assert [d.role for d in xbrl.statement_roles(definitions)] == [fx.INCOME_ROLE]


def test_instance_keeps_the_dimensions_that_the_summary_feeds_flatten_away():
    instance = xbrl.parse_instance(fx.INSTANCE)
    rev = instance.facts_for("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    # the case that started all of this: broken out by product, with no undimensioned total
    assert len(rev) == 2 and all(instance.contexts[f.context].is_dimensioned for f in rev)
    by_member = {instance.contexts[f.context].dimensions[0][1]: f.number for f in rev}
    assert by_member == {
        "us-gaap:DepositAccountMember": 1212000.0,
        "us-gaap:CreditAndDebitCardMember": 1960000.0,
    }
    total = instance.facts_for("us-gaap:NoninterestIncome")[0]
    assert total.number == sum(by_member.values()) + 87000.0


def test_instance_keeps_the_value_as_filed_with_its_unit_and_precision():
    instance = xbrl.parse_instance(fx.INSTANCE)
    eps = instance.facts_for("us-gaap:EarningsPerShareBasic")[0]
    assert eps.value == "1.23" and eps.decimals == "2"
    assert instance.units[eps.unit] == "iso4217:USD/xbrli:shares"
    assets = instance.facts_for("us-gaap:Assets")[0]
    assert instance.contexts[assets.context].is_instant
    assert instance.contexts[assets.context].instant == "2026-06-30"


def test_a_nil_fact_is_absent_not_zero():
    goodwill = xbrl.parse_instance(fx.INSTANCE).facts_for("us-gaap:Goodwill")[0]
    assert goodwill.value is None and goodwill.number is None


def test_a_fact_with_no_context_is_not_evidence_and_is_skipped():
    instance = xbrl.parse_instance(fx.INSTANCE)
    assert instance.facts_for("us-gaap:OtherAssets")  # kept in the raw list, nothing is dropped
    paired = {fact.concept for fact, _ in xbrl.iter_facts(instance)}
    assert "us-gaap:OtherAssets" not in paired


def test_dimension_text_drops_the_prefix_and_the_axis_and_member_suffixes():
    dimensions = (
        ("us-gaap:ProductOrServiceAxis", "us-gaap:DepositAccountMember"),
        ("us-gaap:StatementBusinessSegmentsAxis", "tfin:FactoringMember"),
    )
    # the second pair is the unconfirmed case: the lake spells it `BusinessSegments`, so whether
    # the data sets also strip a leading `Statement` has to be checked against real rows
    assert xbrl.dimension_text(dimensions) == ("ProductOrService=DepositAccount;StatementBusinessSegments=Factoring;")
    assert xbrl.dimension_text(()) == ""


def test_file_set_picks_the_xbrl_out_of_the_bundle():
    bundle = [
        "tfin-20260630.htm",
        "tfin-20260630.xsd",
        "tfin-20260630_cal.xml",
        "tfin-20260630_def.xml",
        "tfin-20260630_htm.xml",
        "tfin-20260630_lab.xml",
        "tfin-20260630_pre.xml",
        "ex-311.htm",
        "logo.jpg",
        "FilingSummary.xml",
        "R2.htm",
    ]
    found = xbrl.file_set(bundle)
    assert found.instance == "tfin-20260630_htm.xml"  # the extracted instance, not FilingSummary
    assert found.calculation == "tfin-20260630_cal.xml" and found.labels == "tfin-20260630_lab.xml"
    assert found.is_complete and found.missing == ()


def test_file_set_handles_a_pre_inline_filing_whose_instance_has_no_suffix():
    found = xbrl.file_set(
        [
            "tfin-20141231.xml",
            "tfin-20141231.xsd",
            "tfin-20141231_cal.xml",
            "tfin-20141231_lab.xml",
            "tfin-20141231_pre.xml",
        ]
    )
    assert found.instance == "tfin-20141231.xml" and found.is_complete
    assert found.missing == ("definition",)


def test_file_set_reports_what_is_missing_rather_than_guessing():
    found = xbrl.file_set(["ex-991.htm", "form8k.htm"])
    assert not found.is_complete and "instance" in found.missing
