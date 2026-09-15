"""A filing's own XBRL: the presentation, the labels, the calculation tree and the dimensions.

Five things we need exist only here, in the files the company itself filed, and in none of the
summary feeds we download:

* the **newest quarter's** dimensioned values (the SEC's quarterly data sets are a quarter or two
  behind, and company facts publishes undimensioned facts only);
* the **label** a company printed on a line it broke out by dimension (the data sets' `pre` table
  names a tag once, with one label, and never mentions the members);
* the **calculation tree**, in which the company declares what each line adds into, with the weight;
* the **note tables**, the debt maturity schedule among them;
* the document itself, which we hold because we claim its numbers.

An XBRL filing is an instance document (the facts, each pointing at a context that carries the
period and the dimensions) plus four linkbases that say nothing about values and everything about
meaning: `_lab` the labels, `_pre` the order lines appear in, `_cal` what adds into what, `_def`
which axes apply where. This module reads all five and nothing else; fetching and storing them is
`documents.py`, turning them into statements is `sync_statements.py`.

Everything here is a pure function over bytes, so it is tested against fixtures rather than the
network, and a filing parses the same way in ten years as it does today.
"""

from __future__ import annotations

import io
import logging
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

LINK = "http://www.xbrl.org/2003/linkbase"
XLINK = "http://www.w3.org/1999/xlink"
XBRLI = "http://www.xbrl.org/2003/instance"
XBRLDI = "http://xbrl.org/2006/xbrldi"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"

_HREF = f"{{{XLINK}}}href"
_LABEL = f"{{{XLINK}}}label"
_FROM = f"{{{XLINK}}}from"
_TO = f"{{{XLINK}}}to"
_ROLE = f"{{{XLINK}}}role"

# Roles an extended link can carry. EDGAR names them "<sort> - <kind> - <title>", e.g.
# "0000003 - Statement - CONSOLIDATED BALANCE SHEETS". The kind is how we tell a statement from a
# note or a disclosure without guessing from the title.
STATEMENT = "Statement"
DISCLOSURE = "Disclosure"
DOCUMENT = "Document"


@dataclass(frozen=True, slots=True)
class Arc:
    """One parent-child relationship inside one extended link role.

    `weight` is set on calculation arcs only (+1 adds, -1 subtracts); `preferred_label` on
    presentation arcs only (it is why a line prints as "Total revenue" rather than "Revenue", and
    why some lines print negated).
    """

    role: str
    parent: str
    child: str
    order: float
    weight: float | None = None
    preferred_label: str | None = None


@dataclass(frozen=True, slots=True)
class RoleDefinition:
    """An extended link role as EDGAR names it in the filing's own schema."""

    role: str
    sort: str
    kind: str
    title: str

    @property
    def is_statement(self) -> bool:
        return self.kind == STATEMENT


@dataclass(frozen=True, slots=True)
class Context:
    """The period and the dimensions a fact is reported under.

    `dimensions` is the whole of what the data sets flatten into their `segments` column: an ordered
    tuple of (axis, member) qnames. A fact with no dimensions is the total; a fact with dimensions
    is one of the parts. Both are real lines and neither is derived from the other.
    """

    id: str
    entity: str
    start: str | None
    end: str | None
    instant: str | None
    dimensions: tuple[tuple[str, str], ...] = ()

    @property
    def is_instant(self) -> bool:
        return self.instant is not None

    @property
    def is_dimensioned(self) -> bool:
        return bool(self.dimensions)


@dataclass(frozen=True, slots=True)
class Fact:
    """One reported value, exactly as filed.

    `value` is the text the company put in the document, kept verbatim: it is the evidence. `number`
    is that text read as a number where it is one, for arithmetic. `decimals` says how far the
    company vouches for it ("-6" means they rounded to millions), which is what a tolerance should
    be built from rather than a guess.
    """

    concept: str
    context: str
    value: str | None
    number: float | None
    unit: str | None
    decimals: str | None


@dataclass(frozen=True, slots=True)
class Instance:
    contexts: dict[str, Context]
    units: dict[str, str]
    facts: tuple[Fact, ...]

    def facts_for(self, concept: str) -> tuple[Fact, ...]:
        return tuple(f for f in self.facts if f.concept == concept)


def _parse(data: bytes) -> tuple[ET.Element, dict[str, str]]:
    """Parse, keeping the namespace prefixes: a fact's element name is a qname and we need both
    halves of it (`us-gaap:Revenues` and `aapl:IPhoneMember` mean different things by their prefix).
    ElementTree throws prefixes away, so collect them from the parse events."""
    prefixes: dict[str, str] = {}
    root: ET.Element | None = None
    for event, payload in ET.iterparse(io.BytesIO(data), events=("start-ns", "start")):
        if event == "start-ns":
            prefix, uri = payload
            prefixes.setdefault(uri, prefix)
        elif root is None:
            root = payload
    if root is None:
        raise ValueError("empty XML document")
    return root, prefixes


def _qname(element_tag: str, prefixes: dict[str, str]) -> str:
    if not element_tag.startswith("{"):
        return element_tag
    uri, _, local = element_tag[1:].partition("}")
    prefix = prefixes.get(uri)
    return f"{prefix}:{local}" if prefix else local


def concept_from_href(href: str) -> str:
    """`https://xbrl.fasb.org/us-gaap-2025.xsd#us-gaap_Revenues` -> `us-gaap:Revenues`.

    The id after the fragment is the qname with the colon written as an underscore, which is the
    only spelling allowed in an XML id. Company concepts look the same (`tfin_CardIncome`)."""
    fragment = href.rpartition("#")[2] or href
    prefix, sep, local = fragment.partition("_")
    return f"{prefix}:{local}" if sep else fragment


def role_suffix(role: str) -> str:
    """`http://www.xbrl.org/2003/role/totalLabel` -> `totalLabel`."""
    return role.rpartition("/")[2] or role


def _locators(link: ET.Element) -> dict[str, list[str]]:
    """xlink:label -> the concepts it points at. Usually one; a linkbase is allowed to point two
    locators at the same label, and dropping the duplicates would silently lose arcs."""
    found: dict[str, list[str]] = defaultdict(list)
    for loc in link.findall(f"{{{LINK}}}loc"):
        label = loc.get(_LABEL)
        href = loc.get(_HREF)
        if label and href:
            found[label].append(concept_from_href(href))
    return found


def _arcs(data: bytes, link_tag: str, arc_tag: str) -> tuple[Arc, ...]:
    root, _ = _parse(data)
    out: list[Arc] = []
    for link in root.iter(f"{{{LINK}}}{link_tag}"):
        role = link.get(_ROLE) or ""
        locators = _locators(link)
        for arc in link.findall(f"{{{LINK}}}{arc_tag}"):
            if arc.get("use") == "prohibited":  # an override, deleting an inherited relationship
                continue
            weight = arc.get("weight")
            for parent in locators.get(arc.get(_FROM) or "", ()):
                for child in locators.get(arc.get(_TO) or "", ()):
                    out.append(
                        Arc(
                            role=role,
                            parent=parent,
                            child=child,
                            order=float(arc.get("order") or 0),
                            weight=float(weight) if weight is not None else None,
                            preferred_label=arc.get("preferredLabel"),
                        )
                    )
    return tuple(out)


def parse_presentation(data: bytes) -> tuple[Arc, ...]:
    """The `_pre` linkbase: the order the company prints its lines in, per statement."""
    return _arcs(data, "presentationLink", "presentationArc")


def parse_calculation(data: bytes) -> tuple[Arc, ...]:
    """The `_cal` linkbase: what each line adds into, and with which sign.

    This is the thing the SEC's summary data sets drop, and without it a subtotal check is a
    positional guess. With it, "does this statement add up" is answerable from the company's own
    declaration of how it adds up."""
    return _arcs(data, "calculationLink", "calculationArc")


def parse_definition(data: bytes) -> tuple[Arc, ...]:
    """The `_def` linkbase: which axes apply to which lines, and which members are allowed."""
    return _arcs(data, "definitionLink", "definitionArc")


@dataclass(frozen=True, slots=True)
class Linkbases:
    """The four linkbases of one filing, wherever the filing keeps them."""

    labels: dict[str, dict[str, str]] = field(default_factory=dict)
    presentation: tuple[Arc, ...] = ()
    calculation: tuple[Arc, ...] = ()
    definition: tuple[Arc, ...] = ()

    @property
    def present(self) -> tuple[str, ...]:
        return tuple(n for n in ("labels", "presentation", "calculation", "definition") if getattr(self, n))


def linkbases_in(data: bytes) -> Linkbases:
    """Every linkbase one document carries.

    A `_pre.xml` carries one kind. A schema usually carries none, only the `linkbaseRef`s that point
    at the four files. But some filer agents embed all four inside the schema's appinfo instead
    (Microsoft, Prologis, Royal Bank of Canada and Toyota in the reader set): no `_lab.xml` exists on
    EDGAR, and the filing is complete with two files. The parsers walk the whole document, so the
    schema is read for links like any other file and this returns what it holds."""
    return Linkbases(parse_labels(data), parse_presentation(data), parse_calculation(data), parse_definition(data))


def merge_linkbases(first: Linkbases, second: Linkbases) -> Linkbases:
    """Both sets together. On the same concept and label role, `second` wins."""
    labels = {concept: dict(roles) for concept, roles in first.labels.items()}
    for concept, roles in second.labels.items():
        labels.setdefault(concept, {}).update(roles)
    return Linkbases(
        labels=labels,
        presentation=first.presentation + second.presentation,
        calculation=first.calculation + second.calculation,
        definition=first.definition + second.definition,
    )


def read_linkbases(
    schema: bytes | None,
    labels: bytes | None = None,
    presentation: bytes | None = None,
    calculation: bytes | None = None,
    definition: bytes | None = None,
) -> Linkbases:
    """The filing's four linkbases from the separate files and the schema together: what the schema
    embeds first, then the separate files on top. For a filing that keeps them in files the schema
    contributes nothing and this is the four parsers; for one that embeds them it is the only way
    to get a presentation at all."""
    from_files = Linkbases(
        labels=parse_labels(labels) if labels else {},
        presentation=parse_presentation(presentation) if presentation else (),
        calculation=parse_calculation(calculation) if calculation else (),
        definition=parse_definition(definition) if definition else (),
    )
    return merge_linkbases(linkbases_in(schema) if schema else Linkbases(), from_files)


def parse_labels(data: bytes) -> dict[str, dict[str, str]]:
    """The `_lab` linkbase: concept -> {role -> the company's own words}.

    Keyed by the short role (`label`, `terseLabel`, `totalLabel`, `negatedLabel`, ...) because that
    is what a presentation arc's `preferredLabel` selects."""
    root, _ = _parse(data)
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for link in root.iter(f"{{{LINK}}}labelLink"):
        locators = _locators(link)
        texts: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for label in link.findall(f"{{{LINK}}}label"):
            key = label.get(_LABEL)
            if key:
                texts[key].append((role_suffix(label.get(_ROLE) or "label"), label.text or ""))
        for arc in link.findall(f"{{{LINK}}}labelArc"):
            if arc.get("use") == "prohibited":
                continue
            for concept in locators.get(arc.get(_FROM) or "", ()):
                for role, text in texts.get(arc.get(_TO) or "", ()):
                    out[concept][role] = text
    return dict(out)


def label_for(labels: dict[str, dict[str, str]], concept: str, preferred: str | None = None) -> str | None:
    """The words to print for a line: the presentation's preferred role if the company defined one,
    else the standard label. Never invented, never a prettified tag name — if the company gave us
    nothing we say so by returning None and the caller decides."""
    roles = labels.get(concept)
    if not roles:
        return None
    if preferred:
        text = roles.get(role_suffix(preferred))
        if text:
            return text
    return roles.get("label") or roles.get("terseLabel") or roles.get("verboseLabel")


def parse_role_definitions(schema: bytes) -> dict[str, RoleDefinition]:
    """The filing's own `.xsd`: what each extended link role is called.

    EDGAR writes "0000003 - Statement - CONSOLIDATED BALANCE SHEETS", so the sort order, the kind
    and the title are all there and none of them has to be guessed from the role URI."""
    root, _ = _parse(schema)
    out: dict[str, RoleDefinition] = {}
    for role_type in root.iter(f"{{{LINK}}}roleType"):
        uri = role_type.get("roleURI")
        if not uri:
            continue
        definition = role_type.findtext(f"{{{LINK}}}definition") or ""
        parts = [p.strip() for p in definition.split(" - ")]
        sort, kind, title = "", "", definition.strip()
        if len(parts) >= 3:
            sort, kind, title = parts[0], parts[1], " - ".join(parts[2:])
        out[uri] = RoleDefinition(role=uri, sort=sort, kind=kind, title=title)
    return out


def statement_roles(definitions: dict[str, RoleDefinition]) -> list[RoleDefinition]:
    """The financial statements, in the order the filing prints them."""
    return sorted((d for d in definitions.values() if d.is_statement), key=lambda d: (d.sort, d.title))


@dataclass(frozen=True, slots=True)
class Line:
    """One line of a presentation tree: a concept, how deep it sits, and what to call it."""

    role: str
    concept: str
    depth: int
    order: float
    preferred_label: str | None
    label: str | None


def presentation_tree(arcs: tuple[Arc, ...], role: str, labels: dict[str, dict[str, str]] | None = None) -> list[Line]:
    """Walk one statement's presentation into the flat, ordered list of lines the company printed.

    Depth-first in `order`, which is exactly how a filing renders: a parent, then the lines that sit
    under it, then the next parent. Cycles (a malformed linkbase) are broken rather than followed."""
    children: dict[str, list[Arc]] = defaultdict(list)
    seen_as_child: set[str] = set()
    parents: set[str] = set()
    for arc in arcs:
        if arc.role != role:
            continue
        children[arc.parent].append(arc)
        seen_as_child.add(arc.child)
        parents.add(arc.parent)
    for kids in children.values():
        kids.sort(key=lambda a: (a.order, a.child))
    roots = sorted(parents - seen_as_child)

    lines: list[Line] = []
    labels = labels or {}

    def walk(concept: str, depth: int, order: float, preferred: str | None, path: set[str]) -> None:
        lines.append(
            Line(
                role=role,
                concept=concept,
                depth=depth,
                order=order,
                preferred_label=preferred,
                label=label_for(labels, concept, preferred),
            )
        )
        for arc in children.get(concept, ()):
            if arc.child in path:
                log.warning("presentation cycle at %s in %s", arc.child, role)
                continue
            walk(arc.child, depth + 1, arc.order, arc.preferred_label, path | {arc.child})

    for root_concept in roots:
        walk(root_concept, 0, 0.0, None, {root_concept})
    return lines


def calculation_children(arcs: tuple[Arc, ...]) -> dict[tuple[str, str], list[Arc]]:
    """(role, parent) -> the lines that add into it, in order, each with its sign.

    The input to a subtotal check that is not a heuristic: the company said these lines add to that
    one, so either they do or the filing or our copy of it is wrong."""
    out: dict[tuple[str, str], list[Arc]] = defaultdict(list)
    for arc in arcs:
        out[(arc.role, arc.parent)].append(arc)
    for kids in out.values():
        kids.sort(key=lambda a: (a.order, a.child))
    return dict(out)


def _context(element: ET.Element, prefixes: dict[str, str]) -> Context:
    entity = element.find(f"{{{XBRLI}}}entity")
    identifier = entity.findtext(f"{{{XBRLI}}}identifier") if entity is not None else None
    period = element.find(f"{{{XBRLI}}}period")
    start = end = instant = None
    if period is not None:
        start = period.findtext(f"{{{XBRLI}}}startDate")
        end = period.findtext(f"{{{XBRLI}}}endDate")
        instant = period.findtext(f"{{{XBRLI}}}instant")
    dimensions: list[tuple[str, str]] = []
    for member in element.iter(f"{{{XBRLDI}}}explicitMember"):
        axis = member.get("dimension")
        if axis and member.text:
            dimensions.append((axis.strip(), member.text.strip()))
    for member in element.iter(f"{{{XBRLDI}}}typedMember"):
        axis = member.get("dimension")
        value = "".join(child.text or "" for child in member) or (member.text or "")
        if axis:
            dimensions.append((axis.strip(), value.strip()))
    return Context(
        id=element.get("id") or "",
        entity=(identifier or "").strip(),
        start=start,
        end=end,
        instant=instant,
        dimensions=tuple(dimensions),
    )


def _unit(element: ET.Element) -> str:
    """ "iso4217:USD", or "shares", or "USD/shares" for a divided unit. The company's own measure,
    not a normalised one: a number without its unit is not a number."""
    divide = element.find(f"{{{XBRLI}}}divide")
    if divide is not None:
        numerator = divide.find(f"{{{XBRLI}}}unitNumerator")
        denominator = divide.find(f"{{{XBRLI}}}unitDenominator")
        top = numerator.findtext(f"{{{XBRLI}}}measure") if numerator is not None else None
        bottom = denominator.findtext(f"{{{XBRLI}}}measure") if denominator is not None else None
        return f"{(top or '').strip()}/{(bottom or '').strip()}"
    return (element.findtext(f"{{{XBRLI}}}measure") or "").strip()


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text.strip().replace(",", ""))
    except ValueError:
        return None


def parse_instance(data: bytes) -> Instance:
    """The instance document: every fact with its context, its unit and its precision.

    EDGAR publishes one for every inline filing (`{name}_htm.xml`), extracted from the document, so
    the facts can be read without parsing megabytes of presentation HTML."""
    root, prefixes = _parse(data)
    contexts = {c.id: c for c in (_context(e, prefixes) for e in root.iter(f"{{{XBRLI}}}context"))}
    units = {e.get("id") or "": _unit(e) for e in root.iter(f"{{{XBRLI}}}unit") if e.get("id")}
    facts: list[Fact] = []
    for element in root:
        tag = element.tag
        if not isinstance(tag, str) or tag.startswith(f"{{{XBRLI}}}") or tag.startswith(f"{{{LINK}}}"):
            continue
        context_ref = element.get("contextRef")
        if not context_ref:
            continue
        nil = element.get(f"{{{XSI}}}nil") in ("true", "1")
        value = None if nil else (element.text or "")
        facts.append(
            Fact(
                concept=_qname(tag, prefixes),
                context=context_ref,
                value=value,
                number=None if nil else _number(value),
                unit=element.get("unitRef"),
                decimals=element.get("decimals"),
            )
        )
    return Instance(contexts=contexts, units=units, facts=tuple(facts))


def dimension_text(dimensions: tuple[tuple[str, str], ...]) -> str:
    """The dimensions written the way the SEC's data sets write them, so a filing we read ourselves
    can be compared line by line against the same filing as the data sets published it.

    The data sets drop the namespace prefix and the `Axis` / `Member` suffix:
    `us-gaap:ProductOrServiceAxis` / `us-gaap:DepositAccountMember` becomes
    `ProductOrService=DepositAccount;`.

    The spelling is theirs, not a standard, and at least one case is not yet confirmed: the lake
    shows `BusinessSegments` where this rule produces `StatementBusinessSegments`, so DERA may strip
    a leading `Statement` as well. Confirm against real `fsds_num.segments` rows before joining on
    axes that begin that way. This is a join key and a cross-check, never the stored truth — the
    stored truth is `Context.dimensions`, which keeps both qnames whole."""
    parts = []
    for axis, member in dimensions:
        parts.append(f"{_strip(axis, 'Axis')}={_strip(member, 'Member')};")
    return "".join(parts)


def _strip(qname: str, suffix: str) -> str:
    local = qname.rpartition(":")[2]
    if local.endswith(suffix) and len(local) > len(suffix):
        local = local[: -len(suffix)]
    return local


def iter_facts(instance: Instance) -> Iterator[tuple[Fact, Context]]:
    """Facts paired with their contexts, skipping any fact whose context the filing did not define
    (malformed, and a value with no period or entity is not evidence of anything)."""
    for fact in instance.facts:
        context = instance.contexts.get(fact.context)
        if context is None:
            log.warning("fact %s references missing context %s", fact.concept, fact.context)
            continue
        yield fact, context


@dataclass(frozen=True, slots=True)
class FileSet:
    """The five files of a filing's XBRL, picked out of everything the filing bundles.

    EDGAR names them off one base: `tfin-20260630.xsd`, `..._cal.xml`, `..._def.xml`, `..._lab.xml`,
    `..._pre.xml`, and the instance is `..._htm.xml` for an inline filing (EDGAR extracts it from
    the document so the facts can be read without the presentation HTML) or `....xml` for the older
    style. Matching on the suffix rather than on a guessed company prefix means a filing that names
    its files unusually still resolves.

    Some filings have only the schema and the instance because the four linkbases are embedded in
    the schema; `is_complete` and `missing` describe the files, and `read_linkbases` finds the
    content wherever it is."""

    instance: str | None = None
    schema: str | None = None
    labels: str | None = None
    presentation: str | None = None
    calculation: str | None = None
    definition: str | None = None

    @property
    def is_complete(self) -> bool:
        """Enough to build a statement: the facts, the order, and the words."""
        return bool(self.instance and self.presentation and self.labels)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("instance", "schema", "labels", "presentation", "calculation", "definition")
            if getattr(self, name) is None
        )


_LINKBASE_SUFFIXES = {
    "_lab.xml": "labels",
    "_pre.xml": "presentation",
    "_cal.xml": "calculation",
    "_def.xml": "definition",
}


def file_set(filenames: list[str]) -> FileSet:
    """Pick the XBRL file set out of a filing's list of documents."""
    found: dict[str, str] = {}
    candidates: list[str] = []
    for name in filenames:
        lower = name.lower()
        for suffix, role in _LINKBASE_SUFFIXES.items():
            if lower.endswith(suffix):
                found.setdefault(role, name)
                break
        else:
            if lower.endswith(".xsd"):
                found.setdefault("schema", name)
            elif lower.endswith("_htm.xml"):
                found["instance"] = name  # the extracted instance wins over a same-named older one
            elif lower.endswith(".xml"):
                candidates.append(name)
    if "instance" not in found:
        base = (found.get("schema") or "").rpartition(".")[0].lower()
        for name in candidates:
            if base and name.lower() == f"{base}.xml":
                found["instance"] = name
                break
        else:
            # no schema to match against: the instance is the one .xml that is not a linkbase
            plain = [n for n in candidates if not n.lower().endswith(("_ref.xml", "_htm.xml"))]
            if len(plain) == 1:
                found["instance"] = plain[0]
    return FileSet(**found)
