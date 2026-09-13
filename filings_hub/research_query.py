"""Bounded Boolean grammar and one exact-token vocabulary for every search backend."""

from __future__ import annotations

import re
from dataclasses import dataclass

WORDS = re.compile(r"[^\W_]+", re.UNICODE)
LEXER = re.compile(r'\s*("[^"\n]*"|\(|\)|[^\s()"]+)')


class QueryError(ValueError):
    """A query cannot be interpreted without guessing the user's meaning."""


def words(text: str) -> list[str]:
    return [m.group().casefold() for m in WORDS.finditer(text)]


@dataclass(frozen=True)
class Node:
    op: str
    terms: tuple[str, ...] = ()
    children: tuple[Node, ...] = ()


def parse_query(query: str) -> Node | None:
    """NOT > AND (including adjacency) > OR; quoted phrases use adjacent word tokens."""
    query = query.strip()
    if not query:
        return None
    if len(query) > 1000:
        raise QueryError("Use at most 1,000 characters in a query.")
    tokens, pos = [], 0
    while pos < len(query):
        match = LEXER.match(query, pos)
        if not match:
            raise QueryError("Close each quoted phrase with a double quote.")
        tokens.append(match[1])
        pos = match.end()
    if len(tokens) > 64:
        raise QueryError("Use at most 64 query terms and operators.")
    cursor = 0

    def peek() -> str | None:
        return tokens[cursor] if cursor < len(tokens) else None

    def atom(depth: int) -> Node:
        nonlocal cursor
        if depth > 12:
            raise QueryError("Use at most 12 levels of parentheses or NOT operators.")
        token = peek()
        if token == "NOT":
            cursor += 1
            return Node("not", children=(atom(depth + 1),))
        if token == "(":
            cursor += 1
            result = either(depth + 1)
            if peek() != ")":
                raise QueryError("Close each opening parenthesis.")
            cursor += 1
            return result
        if token is None or token in ("AND", "OR", ")"):
            raise QueryError("An operator must have a word, quoted phrase or group beside it.")
        cursor += 1
        terms = words(token)
        if not terms:
            raise QueryError("Search for words or numbers; punctuation alone is not searchable.")
        if len(terms) > 1 and not token.startswith('"'):
            raise QueryError('Put text with punctuation between words in double quotes, e.g. "non-GAAP".')
        if len(terms) > 16 or any(len(t) > 100 for t in terms):
            raise QueryError("A phrase may contain up to 16 words, each at most 100 characters.")
        return Node("phrase", terms=tuple(terms))

    def both(depth: int) -> Node:
        nonlocal cursor
        children = [atom(depth)]
        while peek() is not None and peek() not in ("OR", ")"):
            if peek() == "AND":
                cursor += 1
            children.append(atom(depth))
        return children[0] if len(children) == 1 else Node("and", children=tuple(children))

    def either(depth: int) -> Node:
        nonlocal cursor
        children = [both(depth)]
        while peek() == "OR":
            cursor += 1
            children.append(both(depth))
        return children[0] if len(children) == 1 else Node("or", children=tuple(children))

    node = either(0)
    if peek() is not None:
        raise QueryError("An unexpected closing parenthesis was found.")
    return node


def compile_query(node: Node) -> tuple[str, list[str]]:
    """Parameterized membership queries use the (term, version, position) inverted index."""
    if node.op == "phrase":
        joins = " ".join(
            f"JOIN research_terms t{i} ON t{i}.version_id=t0.version_id AND t{i}.position=t0.position+{i}"
            for i in range(1, len(node.terms))
        )
        where = " AND ".join(f"t{i}.term=?" for i in range(len(node.terms)))
        return f"v.version_id IN (SELECT t0.version_id FROM research_terms t0 {joins} WHERE {where})", list(node.terms)
    if node.op == "not":
        sql, params = compile_query(node.children[0])
        return f"NOT ({sql})", params
    parts, params = [], []
    for child in node.children:
        sql, values = compile_query(child)
        parts.append(f"({sql})")
        params.extend(values)
    return (" AND " if node.op == "and" else " OR ").join(parts), params


def positive_terms(node: Node | None, negative: bool = False) -> set[str]:
    if node is None:
        return set()
    if node.op == "phrase":
        return set() if negative else set(node.terms)
    if node.op == "not":
        return positive_terms(node.children[0], not negative)
    return set().union(*(positive_terms(child, negative) for child in node.children))


def snippet(text: str, node: Node | None) -> str:
    terms = positive_terms(node)
    start = next((m.start() for m in WORDS.finditer(text) if m.group().casefold() in terms), 0)
    a, b = max(0, start - 120), min(len(text), start + 260)
    return ("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")
