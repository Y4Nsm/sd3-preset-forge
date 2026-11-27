"""Brace-aware and macro-expanding AST parser for Toontrack SD3 config files."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ConfigNode:
    """AST node representing either a flat statement or a braced block."""

    tokens: list[str]
    children: list[ConfigNode] | None = None

    @property
    def head(self) -> str:
        return self.tokens[0] if self.tokens else ""

    @property
    def is_block(self) -> bool:
        return self.children is not None

    def find_blocks(self, head: str) -> list[ConfigNode]:
        if not self.children:
            return []
        return [c for c in self.children if c.is_block and c.head == head]

    def find_statements(self, head: str) -> list[list[str]]:
        if not self.children:
            return []
        return [c.tokens for c in self.children if not c.is_block and c.head == head]


def strip_comments(text: str) -> str:
    """Strip `#` comments outside double-quoted strings."""
    out_lines: list[str] = []
    for line in text.splitlines():
        in_quotes = False
        cut_idx: int | None = None
        for idx, ch in enumerate(line):
            if ch == '"':
                in_quotes = not in_quotes
            elif ch == "#" and not in_quotes:
                cut_idx = idx
                break
        out_lines.append(line[:cut_idx] if cut_idx is not None else line)
    return "\n".join(out_lines)


def _split_tokens(line: str) -> list[str]:
    """Split one line (or macro argument list) into quote-aware tokens."""
    tokens: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and line[j] != '"':
                j += 1
            tokens.append(line[i + 1 : j])
            i = j + 1
            continue
        if ch in "{}":
            tokens.append(ch)
            i += 1
            continue
        j = i
        while j < n and not line[j].isspace() and line[j] not in '{}"':
            j += 1
        tokens.append(line[i:j])
        i = j
    return tokens


def expand_templates(text: str, max_depth: int = 16) -> str:
    """Parse `TEMPLATE <Name> ... END` blocks and expand `USE <Name> [args...]` directives."""
    cleaned = strip_comments(text)
    lines = cleaned.splitlines()
    templates: dict[str, list[str]] = {}
    body_lines: list[str] = []

    i = 0
    while i < len(lines):
        m = re.match(r"^\s*TEMPLATE\s+(\S+)\s*$", lines[i])
        if m:
            tpl_name = m.group(1)
            tpl_body: list[str] = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*END\s*$", lines[i]):
                tpl_body.append(lines[i])
                i += 1
            templates[tpl_name] = tpl_body
            i += 1
            continue
        body_lines.append(lines[i])
        i += 1

    def _expand_lines(src_lines: list[str], depth: int) -> list[str]:
        if depth > max_depth:
            raise ValueError(f"Template expansion exceeded max_depth ({max_depth})")
        out: list[str] = []
        for ln in src_lines:
            um = re.match(r"^\s*USE\s+(\S+)(.*)$", ln)
            if not um:
                out.append(ln)
                continue
            tpl_name = um.group(1)
            if tpl_name not in templates:
                raise ValueError(f"Undefined template in USE directive: {tpl_name!r}")
            args = _split_tokens(um.group(2))
            sub_lines: list[str] = []
            for tline in templates[tpl_name]:
                replaced = tline
                for arg_idx in range(len(args), 0, -1):
                    replaced = replaced.replace(f"${arg_idx}", args[arg_idx - 1])
                sub_lines.append(replaced)
            out.extend(_expand_lines(sub_lines, depth + 1))
        return out

    return "\n".join(_expand_lines(body_lines, 0))


def _lex(text: str) -> list[tuple[str, str]]:
    """Lex config text into `(kind, value)` tokens where `kind` is WORD, LBRACE, RBRACE, or NL."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "\r\n":
            tokens.append(("NL", "\n"))
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 2
            else:
                i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            tokens.append(("LBRACE", "{"))
            i += 1
            continue
        if ch == "}":
            tokens.append(("RBRACE", "}"))
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 1
            tokens.append(("WORD", text[i + 1 : j]))
            i = j + 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in '{}"\r\n':
            j += 1
        tokens.append(("WORD", text[i:j]))
        i = j
    return tokens


def parse_config_ast(text: str, *, expand_macros: bool = True) -> list[ConfigNode]:
    """Parse a Toontrack config file into a tree of `ConfigNode` objects."""
    prepared = expand_templates(text) if expand_macros else strip_comments(text)
    lexemes = _lex(prepared)

    root_children: list[ConfigNode] = []
    stack: list[tuple[list[str], list[ConfigNode]]] = [([], root_children)]
    cur_tokens: list[str] = []

    def flush_statement() -> None:
        nonlocal cur_tokens
        if cur_tokens:
            stack[-1][1].append(ConfigNode(tokens=cur_tokens, children=None))
            cur_tokens = []

    for kind, val in lexemes:
        if kind == "NL":
            flush_statement()
        elif kind == "WORD":
            cur_tokens.append(val)
        elif kind == "LBRACE":
            if cur_tokens:
                header = cur_tokens
                cur_tokens = []
            elif stack[-1][1] and not stack[-1][1][-1].is_block:
                header = stack[-1][1].pop().tokens
            else:
                header = []
            stack.append((header, []))
        elif kind == "RBRACE":
            flush_statement()
            if len(stack) == 1:
                raise ValueError("Unexpected closing brace '}' in config text")
            header, children = stack.pop()
            stack[-1][1].append(ConfigNode(tokens=header, children=children))

    flush_statement()
    if len(stack) > 1:
        raise ValueError("Unclosed block '{' in config text")
    return root_children
