"""Tests for brace-aware and macro-expanding Toontrack config AST parser."""

from __future__ import annotations

import pytest

from sd3_forge.config_parser import expand_templates, parse_config_ast, strip_comments


def test_strip_comments_preserves_quotes() -> None:
    src = '''
    # top comment
    description "Kick #1 In" # trailing comment
    value 42
    '''
    cleaned = strip_comments(src)
    assert "top comment" not in cleaned
    assert "trailing comment" not in cleaned
    assert 'description "Kick #1 In"' in cleaned
    assert "value 42" in cleaned


def test_expand_templates_positional_and_nested() -> None:
    src = """
    TEMPLATE Inner
      prefix_$1 $2
    END

    TEMPLATE Outer
      close $1
      pads {
        pad_$2 P1 "Label $2"
        USE Inner $2 99
      }
    END

    USE Outer Oh-Dyn 3
    """
    expanded = expand_templates(src)
    assert "TEMPLATE" not in expanded
    assert "close Oh-Dyn" in expanded
    assert 'pad_3 P1 "Label 3"' in expanded
    assert "prefix_3 99" in expanded


def test_expand_templates_guards_missing_and_cycles() -> None:
    with pytest.raises(ValueError, match="Undefined template"):
        expand_templates("USE MissingTpl 1")

    cyclic = """
    TEMPLATE LoopA
      USE LoopB
    END
    TEMPLATE LoopB
      USE LoopA
    END
    USE LoopA
    """
    with pytest.raises(ValueError, match="depth"):
        expand_templates(cyclic, max_depth=4)


def test_parse_config_ast_same_line_and_next_line_braces() -> None:
    src = """
    Product "Superior Drummer 3"

    name "Shaker Pad"
    {
      prio 1
      note 2
      note 4
    }

    positions {
      Cymbal1 9 {
        description "Crash 1"
        pads {
          crash1 CR "Crash"
        }
        cym1 CR "17^ Crash"
      }
    }
    """
    nodes = parse_config_ast(src)
    name_blocks = [n for n in nodes if n.head == "name"]
    assert len(name_blocks) == 1
    assert name_blocks[0].tokens == ["name", "Shaker Pad"]
    assert [s for s in name_blocks[0].find_statements("note")] == [["note", "2"], ["note", "4"]]

    pos_blocks = [n for n in nodes if n.head == "positions"]
    assert len(pos_blocks) == 1
    cym1 = pos_blocks[0].children[0]
    assert cym1.tokens == ["Cymbal1", "9"]
    assert len(cym1.find_blocks("pads")) == 1
    # Top-level piece statement inside Cymbal1 wasn't swallowed by pads {}
    cym_stmts = cym1.find_statements("cym1")
    assert cym_stmts == [["cym1", "CR", "17^ Crash"]]
