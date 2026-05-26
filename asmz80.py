#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


REG8 = {"b": 0, "c": 1, "d": 2, "e": 3, "h": 4, "l": 5, "(hl)": 6, "a": 7}
REG16 = {"bc": 0, "de": 1, "hl": 2, "sp": 3}
PUSHPOP = {"bc": 0, "de": 1, "hl": 2, "af": 3}
COND_JR = {"nz": 0x20, "z": 0x28, "nc": 0x30, "c": 0x38}
COND_JP_CALL = {"nz": 0x00, "z": 0x08, "nc": 0x10, "c": 0x18, "po": 0x20, "pe": 0x28, "p": 0x30, "m": 0x38}
EQU_RESOLUTION_BUFFER = 5

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(\.[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)")


class AsmError(Exception):
    pass


@dataclass
class Entry:
    line_no: int
    address: int
    text: str
    global_label: Optional[str]


def strip_comment(line: str) -> str:
    in_str = False
    out: List[str] = []
    for ch in line:
        if ch == '"':
            in_str = not in_str
            out.append(ch)
        elif ch == ';' and not in_str:
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def split_operands(s: str) -> List[str]:
    parts: List[str] = []
    cur: List[str] = []
    depth = 0
    in_str = False
    for ch in s:
        if ch == '"':
            in_str = not in_str
            cur.append(ch)
        elif ch == ',' and not in_str and depth == 0:
            part = "".join(cur).strip()
            if part:
                parts.append(part)
            cur = []
        else:
            if ch == '(' and not in_str:
                depth += 1
            elif ch == ')' and not in_str:
                depth = max(0, depth - 1)
            cur.append(ch)
    part = "".join(cur).strip()
    if part:
        parts.append(part)
    return parts


def parse_number(token: str) -> Optional[int]:
    t = token.strip().lower()
    if not t:
        return None
    sign = 1
    if t.startswith("-"):
        sign = -1
        t = t[1:]
    elif t.startswith("+"):
        t = t[1:]

    if t.startswith("$"):
        return sign * int(t[1:], 16)
    if t.startswith("%"):
        return sign * int(t[1:], 2)
    if t.startswith("0x"):
        return sign * int(t, 16)
    if t.isdigit():
        return sign * int(t, 10)
    return None


def expand_local_symbol(name: str, current_global: Optional[str], line_no: int) -> str:
    if name.startswith("."):
        if not current_global:
            raise AsmError(f"line {line_no}: local label '{name}' has no global scope")
        return f"{current_global}{name}"
    return name


def normalize_expr(expr: str, current_global: Optional[str], line_no: int) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        return expand_local_symbol(token, current_global, line_no)

    return TOKEN_RE.sub(repl, expr)


def eval_expr(expr: str, symbols: Dict[str, int], current_global: Optional[str], line_no: int) -> int:
    normalized = normalize_expr(expr, current_global, line_no)
    s = normalized.replace(" ", "")
    if not s:
        raise AsmError(f"line {line_no}: empty expression")

    i = 0
    total = 0
    sign = 1
    while i < len(s):
        if s[i] == '+':
            sign = 1
            i += 1
            continue
        if s[i] == '-':
            sign = -1
            i += 1
            continue

        j = i
        if s[j] in ('$','%'):
            j += 1
            while j < len(s) and s[j] in "0123456789ABCDEFabcdef":
                j += 1
        elif s.startswith("0x", j):
            j += 2
            while j < len(s) and s[j] in "0123456789ABCDEFabcdef":
                j += 1
        else:
            while j < len(s) and (s[j].isalnum() or s[j] in "._"):
                j += 1

        token = s[i:j]
        if not token:
            raise AsmError(f"line {line_no}: invalid expression near '{s[i:]}'")

        value = parse_number(token)
        if value is None:
            if token not in symbols:
                raise AsmError(f"line {line_no}: unknown symbol '{token}'")
            value = symbols[token]

        total += sign * value
        sign = 1
        i = j

    return total


def to_u8(v: int, line_no: int) -> int:
    if not -128 <= v <= 0xFF:
        raise AsmError(f"line {line_no}: byte out of range: {v}")
    return v & 0xFF


def to_u16(v: int, line_no: int) -> int:
    if not -0x8000 <= v <= 0xFFFF:
        raise AsmError(f"line {line_no}: word out of range: {v}")
    return v & 0xFFFF


def parse_mem(op: str) -> Optional[str]:
    t = op.strip().lower()
    if t.startswith("(") and t.endswith(")"):
        return t[1:-1].strip()
    return None


def instruction_size(line_no: int, text: str) -> int:
    if not text:
        return 0
    parts = text.split(None, 1)
    op = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    args = split_operands(rest)

    if op in ("org", "forg", "equ"):
        return 0
    if op == "db":
        n = 0
        for a in args:
            a = a.strip()
            if a.startswith('"') and a.endswith('"') and len(a) >= 2:
                n += len(a[1:-1].encode("latin1"))
            else:
                n += 1
        return n
    if op == "dw":
        return 2 * len(args)
    if op == "ds":
        # resolved later in pass 1 where symbols may exist
        return -1

    if op in ("ei", "halt", "ret", "rra"):
        return 1
    if op == "reti":
        return 2
    if op == "im":
        return 2
    if op in ("jr",):
        return 2
    if op == "djnz":
        return 2
    if op in ("jp", "call"):
        return 3

    if op in ("inc", "dec"):
        return 1

    if op == "add":
        return 1

    if op == "ld":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: ld expects 2 operands")
        a0 = args[0].strip().lower()
        a1 = args[1].strip().lower()
        m0 = parse_mem(a0)
        m1 = parse_mem(a1)
        if a0 in REG16 and m1 is None:
            return 3
        if a0 in REG8 and a1 in REG8:
            return 1
        if a0 in REG8 and m1 == "hl":
            return 1
        if a0 == "(hl)" and a1 in REG8:
            return 1
        if a0 in REG8 and m1 is None:
            return 2
        if a0 == "(hl)" and m1 is None:
            return 2
        if m0 is not None and a1 == "a":
            if m0 in ("bc", "de"):
                return 1
            return 3
        if a0 == "a" and m1 is not None:
            if m1 in ("bc", "de"):
                return 1
            return 3
        if m0 is not None and a1 in ("hl", "bc", "de", "sp"):
            return 3 if a1 == "hl" else 4
        if a0 in ("hl", "bc", "de", "sp") and m1 is not None:
            return 3 if a0 == "hl" else 4
        if a0 == "a" and a1 == "r":
            return 2
        raise AsmError(f"line {line_no}: unsupported ld form: {args[0]}, {args[1]}")

    if op in ("cp", "and", "or", "xor"):
        if len(args) != 1:
            raise AsmError(f"line {line_no}: {op} expects 1 operand")
        a = args[0].strip().lower()
        return 1 if a in REG8 else 2

    if op in ("push", "pop"):
        return 1

    if op == "sla":
        return 2

    if op == "bit":
        return 2

    if op in ("in", "out"):
        return 2

    raise AsmError(f"line {line_no}: unsupported opcode '{op}'")


def encode_instruction(entry: Entry, symbols: Dict[str, int]) -> List[int]:
    line_no = entry.line_no
    pc = entry.address
    text = entry.text
    parts = text.split(None, 1)
    op = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    args = split_operands(rest)

    if op in ("org", "forg", "equ"):
        return []

    if op == "db":
        out: List[int] = []
        for a in args:
            a = a.strip()
            if a.startswith('"') and a.endswith('"') and len(a) >= 2:
                out.extend(a[1:-1].encode("latin1"))
            else:
                out.append(to_u8(eval_expr(a, symbols, entry.global_label, line_no), line_no))
        return out

    if op == "dw":
        out = []
        for a in args:
            val = to_u16(eval_expr(a, symbols, entry.global_label, line_no), line_no)
            out.extend([val & 0xFF, (val >> 8) & 0xFF])
        return out

    if op == "ds":
        n = eval_expr(args[0], symbols, entry.global_label, line_no)
        if n < 0:
            raise AsmError(f"line {line_no}: ds size must be non-negative")
        return [0] * n

    if op == "ei":
        return [0xFB]
    if op == "halt":
        return [0x76]
    if op == "ret":
        return [0xC9]
    if op == "reti":
        return [0xED, 0x4D]
    if op == "rra":
        return [0x1F]
    if op == "im":
        mode = eval_expr(args[0], symbols, entry.global_label, line_no)
        if mode != 1:
            raise AsmError(f"line {line_no}: only 'im 1' is supported")
        return [0xED, 0x56]

    if op in ("push", "pop"):
        r = args[0].strip().lower()
        if r not in PUSHPOP:
            raise AsmError(f"line {line_no}: unsupported {op} register '{r}'")
        base = 0xC5 if op == "push" else 0xC1
        return [base + (PUSHPOP[r] << 4)]

    if op in ("inc", "dec"):
        r = args[0].strip().lower()
        if r in REG8:
            base = 0x04 if op == "inc" else 0x05
            return [base + (REG8[r] << 3)]
        if r in REG16:
            base = 0x03 if op == "inc" else 0x0B
            return [base + (REG16[r] << 4)]
        raise AsmError(f"line {line_no}: unsupported {op} operand '{r}'")

    if op == "add":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: add expects 2 operands")
        a0 = args[0].strip().lower()
        a1 = args[1].strip().lower()
        if a0 == "hl" and a1 in REG16:
            return [0x09 + (REG16[a1] << 4)]
        if a0 == "a" and a1 in REG8:
            return [0x80 + REG8[a1]]
        raise AsmError(f"line {line_no}: unsupported add form '{args[0]}, {args[1]}'")

    if op == "ld":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: ld expects 2 operands")
        a0 = args[0].strip().lower()
        a1 = args[1].strip().lower()
        m0 = parse_mem(a0)
        m1 = parse_mem(a1)

        if a0 in REG8 and a1 in REG8:
            return [0x40 + (REG8[a0] << 3) + REG8[a1]]

        if a0 in REG16 and m1 is None:
            val = to_u16(eval_expr(a1, symbols, entry.global_label, line_no), line_no)
            return [0x01 + (REG16[a0] << 4), val & 0xFF, (val >> 8) & 0xFF]

        if a0 == "a" and a1 == "r":
            return [0xED, 0x5F]

        if a0 in REG8 and m1 is None and a1 not in REG8:
            val = to_u8(eval_expr(a1, symbols, entry.global_label, line_no), line_no)
            return [0x06 + (REG8[a0] << 3), val]

        if a0 == "(hl)" and m1 is None and a1 not in REG8:
            val = to_u8(eval_expr(a1, symbols, entry.global_label, line_no), line_no)
            return [0x36, val]

        if m0 is not None and a1 == "a":
            if m0 == "bc":
                return [0x02]
            if m0 == "de":
                return [0x12]
            addr = to_u16(eval_expr(m0, symbols, entry.global_label, line_no), line_no)
            return [0x32, addr & 0xFF, (addr >> 8) & 0xFF]

        if a0 == "a" and m1 is not None:
            if m1 == "bc":
                return [0x0A]
            if m1 == "de":
                return [0x1A]
            addr = to_u16(eval_expr(m1, symbols, entry.global_label, line_no), line_no)
            return [0x3A, addr & 0xFF, (addr >> 8) & 0xFF]

        if m0 is not None and a1 in ("hl", "bc", "de", "sp"):
            addr = to_u16(eval_expr(m0, symbols, entry.global_label, line_no), line_no)
            if a1 == "hl":
                return [0x22, addr & 0xFF, (addr >> 8) & 0xFF]
            opmap = {"bc": 0x43, "de": 0x53, "sp": 0x73}
            return [0xED, opmap[a1], addr & 0xFF, (addr >> 8) & 0xFF]

        if a0 in ("hl", "bc", "de", "sp") and m1 is not None:
            addr = to_u16(eval_expr(m1, symbols, entry.global_label, line_no), line_no)
            if a0 == "hl":
                return [0x2A, addr & 0xFF, (addr >> 8) & 0xFF]
            opmap = {"bc": 0x4B, "de": 0x5B, "sp": 0x7B}
            return [0xED, opmap[a0], addr & 0xFF, (addr >> 8) & 0xFF]

        raise AsmError(f"line {line_no}: unsupported ld form: {args[0]}, {args[1]}")

    if op == "jr":
        if len(args) == 1:
            target = eval_expr(args[0], symbols, entry.global_label, line_no)
            disp = target - (pc + 2)
            if not -128 <= disp <= 127:
                raise AsmError(f"line {line_no}: jr target out of range")
            return [0x18, disp & 0xFF]
        if len(args) == 2:
            cond = args[0].strip().lower()
            if cond not in COND_JR:
                raise AsmError(f"line {line_no}: unsupported jr condition '{cond}'")
            target = eval_expr(args[1], symbols, entry.global_label, line_no)
            disp = target - (pc + 2)
            if not -128 <= disp <= 127:
                raise AsmError(f"line {line_no}: jr target out of range")
            return [COND_JR[cond], disp & 0xFF]
        raise AsmError(f"line {line_no}: invalid jr syntax")

    if op == "djnz":
        target = eval_expr(args[0], symbols, entry.global_label, line_no)
        disp = target - (pc + 2)
        if not -128 <= disp <= 127:
            raise AsmError(f"line {line_no}: djnz target out of range")
        return [0x10, disp & 0xFF]

    if op in ("jp", "call"):
        base = 0xC3 if op == "jp" else 0xCD
        if len(args) == 1:
            addr = to_u16(eval_expr(args[0], symbols, entry.global_label, line_no), line_no)
            return [base, addr & 0xFF, (addr >> 8) & 0xFF]
        if len(args) == 2:
            cond = args[0].strip().lower()
            if cond not in COND_JP_CALL:
                raise AsmError(f"line {line_no}: unsupported {op} condition '{cond}'")
            addr = to_u16(eval_expr(args[1], symbols, entry.global_label, line_no), line_no)
            return [base + COND_JP_CALL[cond], addr & 0xFF, (addr >> 8) & 0xFF]
        raise AsmError(f"line {line_no}: invalid {op} syntax")

    if op in ("cp", "and", "or", "xor"):
        a = args[0].strip().lower()
        if a in REG8:
            base = {"cp": 0xB8, "and": 0xA0, "or": 0xB0, "xor": 0xA8}[op]
            return [base + REG8[a]]
        imm = to_u8(eval_expr(a, symbols, entry.global_label, line_no), line_no)
        base = {"cp": 0xFE, "and": 0xE6, "or": 0xF6, "xor": 0xEE}[op]
        return [base, imm]

    if op == "bit":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: bit expects 2 operands")
        bitno = eval_expr(args[0], symbols, entry.global_label, line_no)
        reg = args[1].strip().lower()
        if reg not in REG8 or not (0 <= bitno <= 7):
            raise AsmError(f"line {line_no}: invalid bit operands")
        return [0xCB, 0x40 + (bitno << 3) + REG8[reg]]

    if op == "sla":
        reg = args[0].strip().lower()
        if reg not in REG8:
            raise AsmError(f"line {line_no}: invalid sla operand '{reg}'")
        return [0xCB, 0x20 + REG8[reg]]

    if op == "in":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: invalid in syntax")
        a0 = args[0].strip().lower()
        port = parse_mem(args[1])
        if a0 != "a" or port is None:
            raise AsmError(f"line {line_no}: only 'in a,(n)' is supported")
        p = to_u8(eval_expr(port, symbols, entry.global_label, line_no), line_no)
        return [0xDB, p]

    if op == "out":
        if len(args) != 2:
            raise AsmError(f"line {line_no}: invalid out syntax")
        port = parse_mem(args[0])
        a1 = args[1].strip().lower()
        if port is None or a1 != "a":
            raise AsmError(f"line {line_no}: only 'out (n),a' is supported")
        p = to_u8(eval_expr(port, symbols, entry.global_label, line_no), line_no)
        return [0xD3, p]

    raise AsmError(f"line {line_no}: unsupported opcode '{op}'")


def parse_source(source: str) -> Tuple[List[Entry], Dict[str, Tuple[str, int, Optional[str]]], Dict[str, int]]:
    entries: List[Entry] = []
    equ_expr: Dict[str, Tuple[str, int, Optional[str]]] = {}
    symbols: Dict[str, int] = {}
    pc = 0
    current_global: Optional[str] = None

    lines = source.splitlines()
    for line_no, raw in enumerate(lines, start=1):
        line = strip_comment(raw)
        if not line:
            continue

        label: Optional[str] = None
        m = re.match(r"^([A-Za-z_.][A-Za-z0-9_.]*)\s*:\s*(.*)$", line)
        if m:
            label = m.group(1)
            line = m.group(2).strip()

        if label is not None:
            expanded = expand_local_symbol(label, current_global, line_no)
            if label.startswith('.'):
                pass
            else:
                current_global = label
            if expanded in symbols:
                raise AsmError(f"line {line_no}: duplicate label '{expanded}'")
            symbols[expanded] = pc

        if not line:
            continue

        parts = line.split(None, 1)
        op = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if op in ("org", "forg"):
            pc = eval_expr(rest, symbols, current_global, line_no)
            if pc < 0:
                raise AsmError(f"line {line_no}: org address must be non-negative")
            entries.append(Entry(line_no, pc, line, current_global))
            continue

        if op == "equ":
            if label is None:
                raise AsmError(f"line {line_no}: equ must have a label")
            expanded = expand_local_symbol(label, current_global, line_no)
            equ_expr[expanded] = (rest, line_no, current_global)
            entries.append(Entry(line_no, pc, line, current_global))
            continue

        size = instruction_size(line_no, line)
        if size == -1:
            # ds needs expression evaluation
            args = split_operands(rest)
            if len(args) != 1:
                raise AsmError(f"line {line_no}: ds expects 1 operand")
            size = eval_expr(args[0], symbols, current_global, line_no)
            if size < 0:
                raise AsmError(f"line {line_no}: ds size must be non-negative")

        entries.append(Entry(line_no, pc, line, current_global))
        pc += size

    # Resolve EQU expressions after first pass labels are known.
    unresolved = dict(equ_expr)
    max_equ_passes = len(unresolved) + EQU_RESOLUTION_BUFFER
    for _ in range(max_equ_passes):
        if not unresolved:
            break
        progressed = False
        for name in list(unresolved.keys()):
            expr, expr_line_no, expr_global = unresolved[name]
            try:
                symbols[name] = eval_expr(expr, symbols, expr_global, expr_line_no)
                unresolved.pop(name)
                progressed = True
            except AsmError:
                pass
        if not progressed:
            break
    if unresolved:
        missing = ", ".join(sorted(unresolved.keys()))
        raise AsmError(f"could not resolve equ symbols: {missing}")

    return entries, equ_expr, symbols


def assemble(source: str) -> Tuple[bytes, int]:
    entries, _, symbols = parse_source(source)
    image: Dict[int, int] = {}
    lowest: Optional[int] = None
    highest = 0

    for e in entries:
        code = encode_instruction(e, symbols)
        for i, b in enumerate(code):
            addr = e.address + i
            image[addr] = b & 0xFF
        if code:
            if lowest is None or e.address < lowest:
                lowest = e.address
            highest = max(highest, e.address + len(code))

    if lowest is None:
        return b"", 0

    out = bytearray([0] * (highest - lowest))
    for addr, value in image.items():
        out[addr - lowest] = value
    return bytes(out), lowest


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Minimal Z80 assembler")
    p.add_argument("input", type=Path, help="Input assembly file")
    p.add_argument("-o", "--output", type=Path, default=Path("a.bin"), help="Output binary file")
    p.add_argument("--origin-out", type=Path, help="Optional file to write resulting start address")
    args = p.parse_args(argv)

    try:
        source = args.input.read_text(encoding="utf-8")
        binary, origin = assemble(source)
        args.output.write_bytes(binary)
        if args.origin_out:
            args.origin_out.write_text(f"{origin}\n", encoding="utf-8")
    except (OSError, AsmError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
