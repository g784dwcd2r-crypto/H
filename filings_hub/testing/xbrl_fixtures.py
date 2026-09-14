"""A small but real-shaped XBRL filing, for tests that must not touch the network.

Modelled on Triumph Financial's quarterly report, which is the filing that exposed the defect this
machinery exists to fix: its fee income is presented as several lines that share one base tag and
are told apart only by a product/service dimension, with no undimensioned value anywhere. A parser
that reads the base tag alone collapses them into nothing.
"""

from __future__ import annotations

US_GAAP = "https://xbrl.fasb.org/us-gaap/2026/elts/us-gaap-2026.xsd"
COMPANY = "tfin-20260630.xsd"

INCOME_ROLE = "http://triumphfin.com/role/ConsolidatedStatementsOfIncome"
DEBT_ROLE = "http://triumphfin.com/role/LongTermDebtMaturities"

SCHEMA = f"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:link="http://www.xbrl.org/2003/linkbase">
  <xs:annotation><xs:appinfo>
    <link:roleType roleURI="{INCOME_ROLE}" id="Income">
      <link:definition>0000004 - Statement - CONSOLIDATED STATEMENTS OF INCOME</link:definition>
      <link:usedOn>link:presentationLink</link:usedOn>
    </link:roleType>
    <link:roleType roleURI="{DEBT_ROLE}" id="Debt">
      <link:definition>0000031 - Disclosure - Long-Term Debt - Maturities (Details)</link:definition>
      <link:usedOn>link:presentationLink</link:usedOn>
    </link:roleType>
    <link:roleType roleURI="http://triumphfin.com/role/Cover" id="Cover">
      <link:definition>0000001 - Document - Cover Page</link:definition>
      <link:usedOn>link:presentationLink</link:usedOn>
    </link:roleType>
  </xs:appinfo></xs:annotation>
</xs:schema>
""".encode()

LABELS = f"""<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax" xlink:label="rev"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_NoninterestIncome" xlink:label="noni"/>
    <link:loc xlink:type="locator" xlink:href="{COMPANY}#tfin_GainOnSaleOfLoans" xlink:label="gain"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_IncomeStatementAbstract" xlink:label="root"/>
    <link:label xlink:type="resource" xlink:label="rev_l" xlink:role="http://www.xbrl.org/2003/role/label">Fee income</link:label>
    <link:label xlink:type="resource" xlink:label="rev_t" xlink:role="http://www.xbrl.org/2003/role/terseLabel">Fees</link:label>
    <link:label xlink:type="resource" xlink:label="noni_l" xlink:role="http://www.xbrl.org/2003/role/label">Noninterest income</link:label>
    <link:label xlink:type="resource" xlink:label="noni_tot" xlink:role="http://www.xbrl.org/2003/role/totalLabel">Total noninterest income</link:label>
    <link:label xlink:type="resource" xlink:label="gain_l" xlink:role="http://www.xbrl.org/2003/role/label">Gain on sale of loans</link:label>
    <link:label xlink:type="resource" xlink:label="gain_old" xlink:role="http://www.xbrl.org/2003/role/label">Gains on loans sold</link:label>
    <link:label xlink:type="resource" xlink:label="root_l" xlink:role="http://www.xbrl.org/2003/role/label">Income Statement [Abstract]</link:label>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="rev" xlink:to="rev_l"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="rev" xlink:to="rev_t"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="noni" xlink:to="noni_l"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="noni" xlink:to="noni_tot"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="gain" xlink:to="gain_l"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="gain" xlink:to="gain_old" use="prohibited"/>
    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" xlink:from="root" xlink:to="root_l"/>
  </link:labelLink>
</link:linkbase>
""".encode()

PRESENTATION = f"""<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:presentationLink xlink:type="extended" xlink:role="{INCOME_ROLE}">
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_IncomeStatementAbstract" xlink:label="root"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax" xlink:label="rev"/>
    <link:loc xlink:type="locator" xlink:href="{COMPANY}#tfin_GainOnSaleOfLoans" xlink:label="gain"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_NoninterestIncome" xlink:label="noni"/>
    <link:presentationArc xlink:type="arc" xlink:from="root" xlink:to="rev" order="1"/>
    <link:presentationArc xlink:type="arc" xlink:from="root" xlink:to="gain" order="2"/>
    <link:presentationArc xlink:type="arc" xlink:from="root" xlink:to="noni" order="3"
                          preferredLabel="http://www.xbrl.org/2003/role/totalLabel"/>
  </link:presentationLink>
</link:linkbase>
""".encode()

CALCULATION = f"""<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:calculationLink xlink:type="extended" xlink:role="{INCOME_ROLE}">
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_NoninterestIncome" xlink:label="noni"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax" xlink:label="rev"/>
    <link:loc xlink:type="locator" xlink:href="{COMPANY}#tfin_GainOnSaleOfLoans" xlink:label="gain"/>
    <link:loc xlink:type="locator" xlink:href="{US_GAAP}#us-gaap_NoninterestExpense" xlink:label="expense"/>
    <link:calculationArc xlink:type="arc" xlink:from="noni" xlink:to="rev" weight="1" order="1"/>
    <link:calculationArc xlink:type="arc" xlink:from="noni" xlink:to="gain" weight="1" order="2"/>
    <link:calculationArc xlink:type="arc" xlink:from="noni" xlink:to="expense" weight="-1" order="3" use="prohibited"/>
  </link:calculationLink>
</link:linkbase>
""".encode()

# Fee income exists only broken out by product: two dimensioned values and no total, which is the
# case the summary feeds cannot express and the one that used to vanish.
INSTANCE = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:us-gaap="http://fasb.org/us-gaap/2026"
      xmlns:tfin="http://triumphfin.com/20260630">
  <xbrli:context id="Q2">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001539638</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="Q2-deposit">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001539638</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:DepositAccountMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="Q2-card">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001539638</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:ProductOrServiceAxis">us-gaap:CreditAndDebitCardMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="AtJune">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0001539638</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2026-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
  <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
  <xbrli:unit id="usdPerShare">
    <xbrli:divide>
      <xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>
      <xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator>
    </xbrli:divide>
  </xbrli:unit>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="Q2-deposit" unitRef="usd" decimals="-3">1212000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="Q2-card" unitRef="usd" decimals="-3">1960000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
  <tfin:GainOnSaleOfLoans contextRef="Q2" unitRef="usd" decimals="-3">87000</tfin:GainOnSaleOfLoans>
  <us-gaap:NoninterestIncome contextRef="Q2" unitRef="usd" decimals="-3">3259000</us-gaap:NoninterestIncome>
  <us-gaap:EarningsPerShareBasic contextRef="Q2" unitRef="usdPerShare" decimals="2">1.23</us-gaap:EarningsPerShareBasic>
  <us-gaap:Assets contextRef="AtJune" unitRef="usd" decimals="-3">6500000000</us-gaap:Assets>
  <us-gaap:Goodwill contextRef="AtJune" unitRef="usd" xsi:nil="true"/>
  <us-gaap:OtherAssets contextRef="Missing" unitRef="usd" decimals="-3">1000</us-gaap:OtherAssets>
</xbrl>
"""
