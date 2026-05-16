#!/usr/bin/env python3
"""
asmz80.py - Z80 Assembler

Usage: python3 asmz80.py <input.asm> [-o <output.bin>]

Supports all standard Z80 instructions plus directives:
  org, forg, equ, db/defb, dw/defw, ds/defs
"""

import sys
import re
import argparse

# ── Register tables ─────────────────────────────────────────────────────────
# 8-bit register codes (B=0, C=1, D=2, E=3, H=4, L=5, A=7)
R8 = {'B': 0, 'C': 1, 'D': 2, 'E': 3, 'H': 4, 'L': 5, 'A': 7}

# 16-bit register pair codes (BC=0, DE=1, HL=2, SP=3)
RP = {'BC': 0, 'DE': 1, 'HL': 2, 'SP': 3}

# PUSH/POP register pair codes (BC=0, DE=1, HL=2, AF=3)
PP = {'BC': 0, 'DE': 1, 'HL': 2, 'AF': 3}

# Condition codes (NZ=0, Z=1, NC=2, C=3, PO=4, PE=5, P=6, M=7)
CC = {'NZ': 0, 'Z': 1, 'NC': 2, 'C': 3, 'PO': 4, 'PE': 5, 'P': 6, 'M': 7}

# JR-valid condition codes (subset)
JR_CC = {'NZ': 0, 'Z': 1, 'NC': 2, 'C': 3}


class AsmError(Exception):
    pass


# ── Expression evaluator ─────────────────────────────────────────────────────

def _tokenize(s):
    """Tokenize an expression string into a list of token strings."""
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        # 0x… hex literal
        if c == '0' and i + 1 < len(s) and s[i + 1].lower() == 'x':
            j = i + 2
            while j < len(s) and s[j] in '0123456789abcdefABCDEF':
                j += 1
            tokens.append(s[i:j])
            i = j
            continue
        # $… hex literal ($ followed by hex digit)
        if c == '$' and i + 1 < len(s) and s[i + 1] in '0123456789abcdefABCDEF':
            j = i + 1
            while j < len(s) and s[j] in '0123456789abcdefABCDEF':
                j += 1
            tokens.append(s[i:j])
            i = j
            continue
        # $ alone = current PC
        if c == '$':
            tokens.append('$')
            i += 1
            continue
        # %… binary literal (% followed by 0/1)
        if c == '%' and i + 1 < len(s) and s[i + 1] in '01':
            j = i + 1
            while j < len(s) and s[j] in '01':
                j += 1
            tokens.append(s[i:j])
            i = j
            continue
        # Decimal integer
        if c.isdigit():
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            tokens.append(s[i:j])
            i = j
            continue
        # Identifier / label (may start with . or _)
        if c.isalpha() or c in '._':
            j = i + 1
            while j < len(s) and (s[j].isalnum() or s[j] in '._'):
                j += 1
            tokens.append(s[i:j])
            i = j
            continue
        # Single-character operators and grouping
        if c in '+-*/&|^~()':
            tokens.append(c)
            i += 1
            continue
        raise AsmError(f"Unexpected character {c!r} in expression: {s!r}")
    return tokens


def eval_expr(s, lookup, pc=0, pass_num=2):
    """
    Evaluate an arithmetic expression.

    Parameters
    ----------
    s        : expression string
    lookup   : callable(name) -> int | None  (symbol lookup)
    pc       : current program counter (for $ literal)
    pass_num : 1 or 2; undefined symbols return 0 in pass 1
    """
    s = s.strip()
    if not s:
        raise AsmError("Empty expression")

    tokens = _tokenize(s)
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume():
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_primary():
        t = peek()
        if t is None:
            raise AsmError(f"Unexpected end of expression: {s!r}")
        consume()
        if t == '-':
            return -parse_primary()
        if t == '+':
            return parse_primary()
        if t == '~':
            return ~parse_primary()
        if t == '(':
            v = parse_top()
            if peek() != ')':
                raise AsmError(f"Missing ')' in: {s!r}")
            consume()
            return v
        if t == '$':
            return pc
        if t.startswith('$'):
            return int(t[1:], 16)
        if t.lower().startswith('0x'):
            return int(t[2:], 16)
        if t.startswith('%'):
            return int(t[1:], 2)
        if re.match(r'^\d+$', t):
            return int(t)
        # Symbol / label
        v = lookup(t)
        if v is not None:
            return v
        if pass_num == 1:
            return 0          # placeholder; resolved in pass 2
        raise AsmError(f"Undefined symbol: {t!r}")

    def parse_mul():
        left = parse_primary()
        while peek() in ('*', '/'):
            op = consume()
            right = parse_primary()
            left = left * right if op == '*' else int(left / right)
        return left

    def parse_add():
        left = parse_mul()
        while peek() in ('+', '-'):
            op = consume()
            right = parse_mul()
            left = left + right if op == '+' else left - right
        return left

    def parse_bitand():
        left = parse_add()
        while peek() == '&':
            consume()
            left &= parse_add()
        return left

    def parse_bitxor():
        left = parse_bitand()
        while peek() == '^':
            consume()
            left ^= parse_bitand()
        return left

    def parse_top():
        left = parse_bitxor()
        while peek() == '|':
            consume()
            left |= parse_bitxor()
        return left

    result = parse_top()
    if pos[0] < len(tokens):
        raise AsmError(f"Unexpected token {tokens[pos[0]]!r} in: {s!r}")
    return result


# ── Source line parser ────────────────────────────────────────────────────────

def parse_line(line):
    """
    Parse one source line.

    Returns (label, mnemonic, ops_str):
      label    : str or None
      mnemonic : uppercase str or None
      ops_str  : operands string (may be empty)
    """
    # Strip trailing comment (but not inside quoted strings)
    in_str = False
    comment_at = -1
    for idx, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        if ch == ';' and not in_str:
            comment_at = idx
            break
    if comment_at >= 0:
        line = line[:comment_at]
    line = line.rstrip()
    if not line.strip():
        return None, None, ''

    label = None
    rest = line

    # A label is at column 0 and followed by ':'
    if line and not line[0].isspace():
        m = re.match(r'^([.\w]+)\s*:\s*(.*)', line)
        if m:
            label = m.group(1)
            rest = m.group(2).strip()
        else:
            # No colon – treat as un-labeled instruction at column 0
            rest = line.strip()
    else:
        rest = line.strip()

    if not rest:
        return label, None, ''

    parts = rest.split(None, 1)
    mnemonic = parts[0].upper()
    ops_str = parts[1].strip() if len(parts) > 1 else ''
    return label, mnemonic, ops_str


# ── Operand helpers ───────────────────────────────────────────────────────────

def split_ops(s):
    """Split operand string by commas not inside parentheses or quotes."""
    parts = []
    depth = 0
    in_str = False
    cur = []
    for ch in s:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif ch == '(' and not in_str:
            depth += 1
            cur.append(ch)
        elif ch == ')' and not in_str:
            depth -= 1
            cur.append(ch)
        elif ch == ',' and depth == 0 and not in_str:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = ''.join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


def unwrap(s):
    """If s is '(…)', return inner string; else return None."""
    s = s.strip()
    if s.startswith('(') and s.endswith(')'):
        return s[1:-1].strip()
    return None


def is_reg8(s):
    return s.upper() in R8


def is_reg16(s):
    return s.upper() in RP


def is_pp(s):
    return s.upper() in PP


def is_cc(s):
    return s.upper() in CC


def u8(v):
    """Mask to unsigned 8-bit."""
    return int(v) & 0xFF


def u16(v):
    """Mask to unsigned 16-bit."""
    return int(v) & 0xFFFF


# ── DB item parser ────────────────────────────────────────────────────────────

def parse_db_items(s):
    """
    Split a DB operand string into items, respecting quoted strings.
    Returns list of strings (each is either a quoted string or an expression).
    """
    items = []
    i = 0
    cur = []
    in_str = False
    while i < len(s):
        ch = s[i]
        if ch == '"' and not in_str:
            in_str = True
            cur.append(ch)
        elif ch == '"' and in_str:
            in_str = False
            cur.append(ch)
        elif ch == ',' and not in_str:
            items.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    tail = ''.join(cur).strip()
    if tail:
        items.append(tail)
    return items


# ── Instruction encoder ───────────────────────────────────────────────────────

def encode(mne, ops_str, pc, lookup, pass_num):  # noqa: C901  (long but clear)
    """
    Encode one instruction or data directive.

    Returns list of byte values (ints 0–255).
    """
    ops = split_ops(ops_str) if ops_str.strip() else []
    nops = len(ops)

    def E(expr):
        """Evaluate expression, return int."""
        return eval_expr(expr, lookup, pc, pass_num)

    def lo(v):
        return u8(v)

    def hi(v):
        return u8(v >> 8)

    def nn(expr):
        v = E(expr)
        return [lo(v), hi(v)]

    def rel(expr):
        """Compute signed relative offset for JR / DJNZ."""
        target = E(expr)
        off = u8(target - (pc + 2))
        if pass_num == 2:
            signed = off if off < 128 else off - 256
            if not (-128 <= signed <= 127):
                raise AsmError(f"Relative branch out of range: {signed}")
        return off

    # ── Implicit (no-operand) instructions ──────────────────────────────────
    simple = {
        'NOP': [0x00], 'HALT': [0x76], 'EI': [0xFB], 'DI': [0xF3],
        'EXX': [0xD9], 'CPL': [0x2F], 'DAA': [0x27], 'CCF': [0x3F],
        'SCF': [0x37], 'RLCA': [0x07], 'RRCA': [0x0F], 'RLA': [0x17],
        'RRA': [0x1F], 'NEG': [0xED, 0x44], 'RETI': [0xED, 0x4D],
        'RETN': [0xED, 0x45],
    }
    if mne in simple:
        return simple[mne]

    # ── IM ──────────────────────────────────────────────────────────────────
    if mne == 'IM':
        m = E(ops[0])
        return {0: [0xED, 0x46], 1: [0xED, 0x56], 2: [0xED, 0x5E]}[m]

    # ── EX ──────────────────────────────────────────────────────────────────
    if mne == 'EX':
        a, b = ops[0].upper().strip(), ops[1].upper().strip()
        if a == 'AF' and b == "AF'":
            return [0x08]
        if a == 'DE' and b == 'HL':
            return [0xEB]
        if a == '(SP)' and b == 'HL':
            return [0xE3]
        if a == '(SP)' and b == 'IX':
            return [0xDD, 0xE3]
        if a == '(SP)' and b == 'IY':
            return [0xFD, 0xE3]
        raise AsmError(f"Unknown EX form: {ops_str}")

    # ── PUSH / POP ──────────────────────────────────────────────────────────
    if mne in ('PUSH', 'POP'):
        r = ops[0].upper().strip()
        base = 0xC5 if mne == 'PUSH' else 0xC1
        if r == 'IX':
            return [0xDD, base]
        if r == 'IY':
            return [0xFD, base]
        if r not in PP:
            raise AsmError(f"Invalid {mne} register: {r}")
        return [base | (PP[r] << 4)]

    # ── RET ─────────────────────────────────────────────────────────────────
    if mne == 'RET':
        if nops == 0:
            return [0xC9]
        c = ops[0].upper().strip()
        if c not in CC:
            raise AsmError(f"Unknown condition: {c}")
        return [0xC0 | (CC[c] << 3)]

    # ── JP ──────────────────────────────────────────────────────────────────
    if mne == 'JP':
        if nops == 1:
            op = ops[0].strip()
            up = op.upper()
            if up == '(HL)':
                return [0xE9]
            if up == '(IX)':
                return [0xDD, 0xE9]
            if up == '(IY)':
                return [0xFD, 0xE9]
            v = E(op)
            return [0xC3, lo(v), hi(v)]
        if nops == 2:
            c = ops[0].upper().strip()
            if c not in CC:
                raise AsmError(f"Unknown JP condition: {c}")
            v = E(ops[1])
            return [0xC2 | (CC[c] << 3), lo(v), hi(v)]
        raise AsmError("JP: wrong operand count")

    # ── JR ──────────────────────────────────────────────────────────────────
    if mne == 'JR':
        if nops == 1:
            return [0x18, rel(ops[0])]
        if nops == 2:
            c = ops[0].upper().strip()
            if c not in JR_CC:
                raise AsmError(f"Invalid JR condition: {c}")
            return [0x20 | (JR_CC[c] << 3), rel(ops[1])]
        raise AsmError("JR: wrong operand count")

    # ── DJNZ ────────────────────────────────────────────────────────────────
    if mne == 'DJNZ':
        return [0x10, rel(ops[0])]

    # ── CALL ────────────────────────────────────────────────────────────────
    if mne == 'CALL':
        if nops == 1:
            v = E(ops[0])
            return [0xCD, lo(v), hi(v)]
        if nops == 2:
            c = ops[0].upper().strip()
            if c not in CC:
                raise AsmError(f"Unknown CALL condition: {c}")
            v = E(ops[1])
            return [0xC4 | (CC[c] << 3), lo(v), hi(v)]
        raise AsmError("CALL: wrong operand count")

    # ── RST ─────────────────────────────────────────────────────────────────
    if mne == 'RST':
        n = E(ops[0])
        return [0xC7 | n]

    # ── IN ──────────────────────────────────────────────────────────────────
    if mne == 'IN':
        dst = ops[0].upper().strip()
        src = ops[1].strip()
        inner_src = unwrap(src)
        if inner_src is not None and inner_src.upper() == 'C':
            if dst not in R8:
                raise AsmError(f"IN r,(C): unknown register {dst}")
            return [0xED, 0x40 | (R8[dst] << 3)]
        if dst != 'A':
            raise AsmError("IN A,(n) requires destination A")
        return [0xDB, u8(E(inner_src if inner_src is not None else src))]

    # ── OUT ─────────────────────────────────────────────────────────────────
    if mne == 'OUT':
        port = ops[0].strip()
        src = ops[1].upper().strip()
        inner_port = unwrap(port)
        if inner_port is not None and inner_port.upper() == 'C':
            if src not in R8:
                raise AsmError(f"OUT (C),r: unknown register {src}")
            return [0xED, 0x41 | (R8[src] << 3)]
        if src != 'A':
            raise AsmError("OUT (n),A requires source A")
        return [0xD3, u8(E(inner_port if inner_port is not None else port))]

    # ── Arithmetic / logic ───────────────────────────────────────────────────

    # ADD
    if mne == 'ADD':
        dst, src = ops[0].upper().strip(), ops[1].strip()
        src_up = src.upper()
        if dst == 'A':
            if src_up == '(HL)':
                return [0x86]
            if is_reg8(src_up):
                return [0x80 | R8[src_up]]
            return [0xC6, u8(E(src))]
        if dst == 'HL':
            if src_up not in RP:
                raise AsmError(f"ADD HL,rr: unknown rr {src_up}")
            return [0x09 | (RP[src_up] << 4)]
        if dst == 'IX':
            rp_ix = {'BC': 0x09, 'DE': 0x19, 'IX': 0x29, 'SP': 0x39}
            return [0xDD, rp_ix[src_up]]
        if dst == 'IY':
            rp_iy = {'BC': 0x09, 'DE': 0x19, 'IY': 0x29, 'SP': 0x39}
            return [0xFD, rp_iy[src_up]]
        raise AsmError(f"Unknown ADD form: {ops_str}")

    # ADC
    if mne == 'ADC':
        dst, src = ops[0].upper().strip(), ops[1].strip()
        src_up = src.upper()
        if dst == 'A':
            if src_up == '(HL)':
                return [0x8E]
            if is_reg8(src_up):
                return [0x88 | R8[src_up]]
            return [0xCE, u8(E(src))]
        if dst == 'HL':
            return [0xED, 0x4A | (RP[src_up] << 4)]
        raise AsmError(f"Unknown ADC form: {ops_str}")

    # SUB
    if mne == 'SUB':
        src = ops[0].strip()
        src_up = src.upper()
        if src_up == '(HL)':
            return [0x96]
        if is_reg8(src_up):
            return [0x90 | R8[src_up]]
        return [0xD6, u8(E(src))]

    # SBC
    if mne == 'SBC':
        dst, src = ops[0].upper().strip(), ops[1].strip()
        src_up = src.upper()
        if dst == 'A':
            if src_up == '(HL)':
                return [0x9E]
            if is_reg8(src_up):
                return [0x98 | R8[src_up]]
            return [0xDE, u8(E(src))]
        if dst == 'HL':
            return [0xED, 0x42 | (RP[src_up] << 4)]
        raise AsmError(f"Unknown SBC form: {ops_str}")

    # AND / XOR / OR / CP  (single-operand acc ops)
    acc_ops = {'AND': (0xA0, 0xE6), 'XOR': (0xA8, 0xEE),
               'OR':  (0xB0, 0xF6), 'CP':  (0xB8, 0xFE)}
    if mne in acc_ops:
        base_r, base_n = acc_ops[mne]
        src = ops[0].strip()
        src_up = src.upper()
        if src_up == '(HL)':
            return [base_r | 6]
        if is_reg8(src_up):
            return [base_r | R8[src_up]]
        return [base_n, u8(E(src))]

    # ── INC / DEC ────────────────────────────────────────────────────────────
    if mne in ('INC', 'DEC'):
        r = ops[0].strip()
        r_up = r.upper()
        if r_up == '(HL)':
            return [0x34 if mne == 'INC' else 0x35]
        if is_reg8(r_up):
            base = 0x04 if mne == 'INC' else 0x05
            return [base | (R8[r_up] << 3)]
        if r_up in RP:
            base = 0x03 if mne == 'INC' else 0x0B
            return [base | (RP[r_up] << 4)]
        if r_up == 'IX':
            return [0xDD, 0x23 if mne == 'INC' else 0x2B]
        if r_up == 'IY':
            return [0xFD, 0x23 if mne == 'INC' else 0x2B]
        raise AsmError(f"Unknown {mne} operand: {r}")

    # ── CB-prefix rotate / shift ─────────────────────────────────────────────
    cb_ops = {'RLC': 0x00, 'RRC': 0x08, 'RL': 0x10, 'RR': 0x18,
              'SLA': 0x20, 'SRA': 0x28, 'SLL': 0x30, 'SRL': 0x38}
    if mne in cb_ops:
        r = ops[0].strip()
        r_up = r.upper()
        base = cb_ops[mne]
        if r_up == '(HL)':
            return [0xCB, base | 6]
        if is_reg8(r_up):
            return [0xCB, base | R8[r_up]]
        raise AsmError(f"Unknown {mne} operand: {r}")

    # ── BIT / SET / RES ──────────────────────────────────────────────────────
    bsr_base = {'BIT': 0x40, 'RES': 0x80, 'SET': 0xC0}
    if mne in bsr_base:
        b = E(ops[0])
        r = ops[1].strip()
        r_up = r.upper()
        base = bsr_base[mne] | (b << 3)
        if r_up == '(HL)':
            return [0xCB, base | 6]
        if is_reg8(r_up):
            return [0xCB, base | R8[r_up]]
        raise AsmError(f"Unknown {mne} register: {r}")

    # ── LD ───────────────────────────────────────────────────────────────────
    if mne == 'LD':
        if nops != 2:
            raise AsmError(f"LD needs 2 operands, got: {ops_str!r}")
        dst, src = ops[0].strip(), ops[1].strip()
        dst_up = dst.upper()
        src_up = src.upper()
        dst_in = unwrap(dst)       # inner of (…) or None
        src_in = unwrap(src)       # inner of (…) or None

        # Special registers A,I / A,R / I,A / R,A  (before general 8-bit cases)
        if dst_up == 'A' and src_up == 'I':
            return [0xED, 0x57]
        if dst_up == 'A' and src_up == 'R':
            return [0xED, 0x5F]
        if dst_up == 'I' and src_up == 'A':
            return [0xED, 0x47]
        if dst_up == 'R' and src_up == 'A':
            return [0xED, 0x4F]

        # LD r, r'  (register ↔ register, incl. (HL))
        src_is_r8 = is_reg8(src_up)
        dst_is_r8 = is_reg8(dst_up)
        if dst_is_r8 and src_is_r8:
            return [0x40 | (R8[dst_up] << 3) | R8[src_up]]

        # LD r, (HL)
        if dst_is_r8 and src_up == '(HL)':
            return [0x40 | (R8[dst_up] << 3) | 6]

        # LD (HL), r
        if dst_up == '(HL)' and src_is_r8:
            return [0x70 | R8[src_up]]

        # LD (HL), n
        if dst_up == '(HL)':
            return [0x36, u8(E(src))]

        # LD r, n  (only when src is a plain expression, not parenthesised indirect)
        if dst_is_r8 and src_in is None:
            return [0x06 | (R8[dst_up] << 3), u8(E(src))]

        # LD A, (BC) / (DE)
        if dst_up == 'A' and src_up == '(BC)':
            return [0x0A]
        if dst_up == 'A' and src_up == '(DE)':
            return [0x1A]

        # LD (BC)/( DE), A
        if dst_up == '(BC)' and src_up == 'A':
            return [0x02]
        if dst_up == '(DE)' and src_up == 'A':
            return [0x12]

        # LD A, (nn)   (src is (addr), not a register-indirect)
        _REGINDIRECT = {'BC', 'DE', 'HL', 'SP', 'C', 'IX', 'IY'}
        if dst_up == 'A' and src_in is not None and src_in.upper() not in _REGINDIRECT:
            v = E(src_in)
            return [0x3A, lo(v), hi(v)]

        # LD (nn), A
        if dst_in is not None and dst_in.upper() not in _REGINDIRECT and src_up == 'A':
            v = E(dst_in)
            return [0x32, lo(v), hi(v)]

        # LD HL, (nn)
        if dst_up == 'HL' and src_in is not None and src_in.upper() not in _REGINDIRECT:
            v = E(src_in)
            return [0x2A, lo(v), hi(v)]

        # LD (nn), HL
        if dst_in is not None and dst_in.upper() not in _REGINDIRECT and src_up == 'HL':
            v = E(dst_in)
            return [0x22, lo(v), hi(v)]

        # LD (nn), DE / BC / SP  (ED-prefixed)
        ed_store = {'BC': 0x43, 'DE': 0x53, 'SP': 0x73}
        if dst_in is not None and dst_in.upper() not in _REGINDIRECT and src_up in ed_store:
            v = E(dst_in)
            return [0xED, ed_store[src_up], lo(v), hi(v)]

        # LD rr, (nn)  BC/DE/SP — ED-prefixed
        ed_load = {'BC': 0x4B, 'DE': 0x5B, 'SP': 0x7B}
        if dst_up in ed_load and src_in is not None and src_in.upper() not in _REGINDIRECT:
            v = E(src_in)
            return [0xED, ed_load[dst_up], lo(v), hi(v)]

        # LD rr, nn  (16-bit immediate, src is not an (addr))
        if dst_up in RP and src_in is None:
            v = E(src)
            return [0x01 | (RP[dst_up] << 4), lo(v), hi(v)]

        # LD SP, HL
        if dst_up == 'SP' and src_up == 'HL':
            return [0xF9]

        # LD IX, nn / LD (nn), IX / LD IX, (nn)
        if dst_up == 'IX' and src_in is None:
            v = E(src)
            return [0xDD, 0x21, lo(v), hi(v)]
        if dst_up == 'IX' and src_in is not None:
            v = E(src_in)
            return [0xDD, 0x2A, lo(v), hi(v)]
        if dst_in is not None and dst_in.upper() not in _REGINDIRECT and src_up == 'IX':
            v = E(dst_in)
            return [0xDD, 0x22, lo(v), hi(v)]

        # LD IY, nn / LD (nn), IY / LD IY, (nn)
        if dst_up == 'IY' and src_in is None:
            v = E(src)
            return [0xFD, 0x21, lo(v), hi(v)]
        if dst_up == 'IY' and src_in is not None:
            v = E(src_in)
            return [0xFD, 0x2A, lo(v), hi(v)]
        if dst_in is not None and dst_in.upper() not in _REGINDIRECT and src_up == 'IY':
            v = E(dst_in)
            return [0xFD, 0x22, lo(v), hi(v)]

        raise AsmError(f"Unknown LD form: LD {dst},{src}")

    # ── Data directives ───────────────────────────────────────────────────────

    if mne in ('DB', 'DEFB'):
        result = []
        for item in parse_db_items(ops_str):
            item = item.strip()
            if item.startswith('"') and item.endswith('"'):
                text = item[1:-1]
                # Basic escape sequences
                text = text.replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                for ch in text:
                    result.append(ord(ch))
            else:
                result.append(u8(E(item)))
        return result

    if mne in ('DW', 'DEFW'):
        result = []
        for item in split_ops(ops_str):
            v = E(item.strip())
            result.extend([lo(v), hi(v)])
        return result

    if mne in ('DS', 'DEFS'):
        count = E(ops[0]) if nops >= 1 else 0
        fill  = u8(E(ops[1])) if nops >= 2 else 0
        return [fill] * count

    raise AsmError(f"Unknown mnemonic: {mne!r}")


# ── Two-pass assembler ────────────────────────────────────────────────────────

class Assembler:
    def __init__(self):
        self.symbols = {}        # full_name -> int
        self.pc = 0
        self.output = {}         # address -> byte
        self.global_label = None # last non-local label seen

    # ── Symbol helpers ────────────────────────────────────────────────────────

    def _full_name(self, name):
        """Expand local label '.foo' to 'global.foo'."""
        if name.startswith('.'):
            if not self.global_label:
                raise AsmError(f"Local label {name!r} without enclosing global label")
            return self.global_label + name
        return name

    def _define(self, name, value):
        """Define (or redefine) a symbol."""
        self.symbols[self._full_name(name)] = value

    def _lookup(self, name):
        """Return symbol value or None if undefined."""
        full = self._full_name(name)
        if full in self.symbols:
            return self.symbols[full]
        # Also try name as-is (for non-local absolute lookup)
        if name in self.symbols:
            return self.symbols[name]
        return None

    def _make_lookup(self, pc):
        """Return a lookup closure bound to current global_label and pc."""
        global_label = self.global_label
        symbols = self.symbols

        def lookup(name):
            if name.startswith('.'):
                if not global_label:
                    return None
                full = global_label + name
                return symbols.get(full)
            return symbols.get(name)

        return lookup

    # ── Main assembly ─────────────────────────────────────────────────────────

    def assemble(self, source):
        """
        Two-pass assembly.  Returns flat bytes starting from address 0.
        """
        lines = source.split('\n')
        errors = []

        for pass_num in (1, 2):
            self.pc = 0
            self.output = {}
            self.global_label = None

            for line_num, raw_line in enumerate(lines, 1):
                try:
                    self._process(raw_line, pass_num, line_num)
                except AsmError as exc:
                    if pass_num == 2:
                        errors.append(f"  Line {line_num}: {raw_line.rstrip()}")
                        errors.append(f"    {exc}")

        if errors:
            print("Assembly errors:", file=sys.stderr)
            for e in errors:
                print(e, file=sys.stderr)
            sys.exit(1)

        if not self.output:
            return b''
        min_addr = min(self.output)
        max_addr = max(self.output)
        buf = bytearray(max_addr - min_addr + 1)
        for addr, byte in self.output.items():
            buf[addr - min_addr] = byte
        return bytes(buf)

    def _process(self, raw_line, pass_num, line_num):
        label, mnemonic, ops_str = parse_line(raw_line)

        # Register label address (tentative, might be overridden by EQU)
        if label:
            if not label.startswith('.'):
                self.global_label = label
            self._define(label, self.pc)

        if mnemonic is None:
            return

        mne = mnemonic.upper()

        # ORG: set PC (fill gap with zeros when advancing)
        if mne == 'ORG':
            addr = eval_expr(ops_str, self._make_lookup(self.pc),
                             self.pc, pass_num)
            if pass_num == 2 and addr > self.pc:
                for a in range(self.pc, addr):
                    self.output[a] = self.output.get(a, 0)
            self.pc = addr
            return

        # FORG: fill from current PC to target with zeros, advance PC
        if mne == 'FORG':
            addr = eval_expr(ops_str, self._make_lookup(self.pc),
                             self.pc, pass_num)
            if pass_num == 2:
                for a in range(self.pc, addr):
                    self.output[a] = 0
            self.pc = addr
            return

        # EQU: (re)define symbol as a constant; does not advance PC
        if mne == 'EQU':
            val = eval_expr(ops_str, self._make_lookup(self.pc),
                            self.pc, pass_num)
            if label:
                self._define(label, val)
            return

        # All other mnemonics → encode bytes
        try:
            bytelist = encode(mne, ops_str, self.pc,
                              self._make_lookup(self.pc), pass_num)
        except AsmError:
            raise
        except Exception as exc:
            raise AsmError(str(exc)) from exc

        if pass_num == 2:
            for b in bytelist:
                self.output[self.pc] = b
                self.pc += 1
        else:
            self.pc += len(bytelist)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Z80 Assembler',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Example: python3 asmz80.py input.asm -o output.bin'
    )
    parser.add_argument('input', help='Input assembly source file')
    parser.add_argument('-o', '--output', default=None,
                        help='Output binary file (default: <input>.bin)')
    args = parser.parse_args()

    out_path = args.output or (args.input.rsplit('.', 1)[0] + '.bin')

    try:
        with open(args.input, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
    except OSError as exc:
        print(f"Error reading {args.input}: {exc}", file=sys.stderr)
        sys.exit(1)

    asm = Assembler()
    binary = asm.assemble(source)

    try:
        with open(out_path, 'wb') as f:
            f.write(binary)
    except OSError as exc:
        print(f"Error writing {out_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Assembled {len(binary)} bytes -> {out_path}")


if __name__ == '__main__':
    main()
