#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REGISTER_BITS = {
    'B': 0,
    'C': 1,
    'D': 2,
    'E': 3,
    'H': 4,
    'L': 5,
    'A': 7,
}

DIRECTIVES = {'ORG', 'FORG', 'DB', 'DW', 'DS', 'EQU'}
INSTRUCTION_RE = re.compile(r'^\s*([A-Z].+?)\s{2,}(\d+)\s{2,}([A-Za-z0-9+* ]+?)\s{2,}')
LABEL_RE = re.compile(r"^\s*([A-Za-z_.$][A-Za-z0-9_.$']*):")
NUMBER_SUFFIX_HEX_RE = re.compile(r'^[0-9A-F]+H$', re.IGNORECASE)
INDEXED_RE_TEMPLATE = r'^\(\s*{register}\s*([+-]\s*.+)\)$'


class AssemblerError(Exception):
    pass


@dataclass(frozen=True)
class InstructionTemplate:
    mnemonic: str
    operands: tuple[str, ...]
    size: int
    opcode_tokens: tuple[str, ...]


@dataclass
class Statement:
    line_no: int
    raw: str
    label: str | None
    scope: str | None
    kind: str
    name: str
    args: list[str]


@dataclass
class MatchResult:
    template: InstructionTemplate
    formula_values: dict[str, int]
    byte_tasks: list[tuple[str, str]]


def split_comment(line: str) -> str:
    in_string = False
    result: list[str] = []
    for char in line:
        if char == '"':
            in_string = not in_string
        if char == ';' and not in_string:
            break
        result.append(char)
    return ''.join(result).strip()


def split_csv(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for char in text:
        if char == '"':
            in_string = not in_string
            current.append(char)
            continue
        if not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == ',' and depth == 0:
                parts.append(''.join(current).strip())
                current = []
                continue
        current.append(char)
    parts.append(''.join(current).strip())
    return [part for part in parts if part]


def normalize_symbol(name: str, scope: str | None) -> str:
    if name.startswith('.'):
        if not scope:
            raise AssemblerError(f'Local label {name} used before a global label')
        return f'{scope}{name}'
    return name


def decode_string(token: str) -> list[int]:
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise AssemblerError(f'Invalid string literal: {token}')
    value = bytes(token[1:-1], 'utf-8').decode('unicode_escape')
    return list(value.encode('latin1'))


def parse_number(token: str) -> int | None:
    upper = token.upper()
    if token.startswith('$'):
        return int(token[1:], 16)
    if token.startswith('%'):
        return int(token[1:], 2)
    if token.startswith('0x') or token.startswith('0X'):
        return int(token, 16)
    if NUMBER_SUFFIX_HEX_RE.match(upper):
        return int(upper[:-1], 16)
    if re.fullmatch(r'\d+', token):
        return int(token, 10)
    return None


def tokenize_expression(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char in '+-()':
            tokens.append(char)
            i += 1
            continue
        if char == '$':
            j = i + 1
            while j < len(text) and text[j] in '0123456789abcdefABCDEF':
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        if char == '%':
            j = i + 1
            while j < len(text) and text[j] in '01':
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        if char.isdigit():
            j = i + 1
            while j < len(text) and text[j].isalnum():
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        if char.isalpha() or char in "._'":
            j = i + 1
            while j < len(text) and (text[j].isalnum() or text[j] in "._$'"):
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        raise AssemblerError(f'Unexpected character in expression: {char}')
    return tokens


def evaluate_expression(text: str, symbols: dict[str, int], scope: str | None) -> int:
    tokens = tokenize_expression(text)
    position = 0

    def parse_expr() -> int:
        nonlocal position
        value = parse_term()
        while position < len(tokens) and tokens[position] in {'+', '-'}:
            op = tokens[position]
            position += 1
            rhs = parse_term()
            value = value + rhs if op == '+' else value - rhs
        return value

    def parse_term() -> int:
        nonlocal position
        if position >= len(tokens):
            raise AssemblerError(f'Unexpected end of expression: {text}')
        token = tokens[position]
        if token == '+':
            position += 1
            return parse_term()
        if token == '-':
            position += 1
            return -parse_term()
        if token == '(':
            position += 1
            value = parse_expr()
            if position >= len(tokens) or tokens[position] != ')':
                raise AssemblerError(f"Missing ')' in expression: {text}")
            position += 1
            return value
        position += 1
        number = parse_number(token)
        if number is not None:
            return number
        name = normalize_symbol(token, scope)
        if name not in symbols:
            raise AssemblerError(f'Undefined symbol: {token}')
        return symbols[name]

    value = parse_expr()
    if position != len(tokens):
        raise AssemblerError(f'Could not parse expression: {text}')
    return value


def parse_instruction_list(path: Path) -> dict[str, list[InstructionTemplate]]:
    templates: dict[str, list[InstructionTemplate]] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = INSTRUCTION_RE.match(line)
        if not match:
            continue
        mnemonic_text, size_text, opcode_text = match.groups()
        parts = mnemonic_text.split(None, 1)
        mnemonic = parts[0].upper()
        operands = tuple(split_csv(parts[1])) if len(parts) > 1 else ()
        template = InstructionTemplate(
            mnemonic=mnemonic,
            operands=operands,
            size=int(size_text),
            opcode_tokens=tuple(opcode_text.split()),
        )
        templates.setdefault(mnemonic, []).append(template)
    return templates


def parse_source(source: str) -> list[Statement]:
    statements: list[Statement] = []
    current_global: str | None = None
    for line_no, raw_line in enumerate(source.splitlines(), 1):
        line = split_comment(raw_line)
        if not line:
            continue
        label: str | None = None
        rest = line
        match = LABEL_RE.match(rest)
        if match:
            label_name = match.group(1)
            label = normalize_symbol(label_name, current_global)
            if not label_name.startswith('.'):
                current_global = label_name
            rest = rest[match.end():].strip()
        scope = current_global
        if not rest:
            statements.append(Statement(line_no, raw_line, label, scope, 'EMPTY', '', []))
            continue
        parts = rest.split(None, 1)
        name = parts[0].upper()
        args = split_csv(parts[1]) if len(parts) > 1 else []
        kind = 'DIRECTIVE' if name in DIRECTIVES else 'INSTRUCTION'
        statements.append(Statement(line_no, raw_line, label, scope, kind, name, args))
    return statements


def is_parenthesized(text: str) -> bool:
    return text.startswith('(') and text.endswith(')')


def parse_index_displacement(operand: str, register: str) -> str | None:
    match = re.fullmatch(INDEXED_RE_TEMPLATE.format(register=register), operand.strip(), flags=re.IGNORECASE)
    return match.group(1).replace(' ', '') if match else None


def parse_literal_value(token: str) -> int | None:
    return parse_number(token)


def match_operand(
    spec: str,
    operand: str,
    scope: str | None,
    symbols: dict[str, int],
    line_no: int,
) -> tuple[dict[str, int], list[tuple[str, str]]] | None:
    operand_clean = operand.strip()
    operand_upper = operand_clean.upper().replace(' ', '')
    spec_upper = spec.upper().replace(' ', '')
    formula_values: dict[str, int] = {}

    if spec == 'r':
        if operand_upper in REGISTER_BITS:
            formula_values['rb'] = REGISTER_BITS[operand_upper]
            return formula_values, []
        return None
    if spec == 'b':
        value = evaluate_expression(operand_clean, symbols, scope)
        if not 0 <= value <= 7:
            raise AssemblerError(f'Bit index must be between 0 and 7 on line {line_no}: got {value}')
        formula_values['b'] = value
        return formula_values, []
    if spec == 'N':
        return formula_values, [('imm8', operand_clean)]
    if spec == 'NN':
        return formula_values, [('imm16', operand_clean)]
    if spec == 'n':
        return formula_values, [('rel8', operand_clean)]
    if spec_upper == '(N)':
        if is_parenthesized(operand_clean):
            return formula_values, [('imm8', operand_clean[1:-1].strip())]
        return None
    if spec_upper == '(NN)':
        if is_parenthesized(operand_clean):
            return formula_values, [('imm16', operand_clean[1:-1].strip())]
        return None
    if spec == '(IX+n)':
        displacement = parse_index_displacement(operand_clean, 'IX')
        return (formula_values, [('disp8', displacement)]) if displacement is not None else None
    if spec == '(IY+n)':
        displacement = parse_index_displacement(operand_clean, 'IY')
        return (formula_values, [('disp8', displacement)]) if displacement is not None else None

    spec_value = parse_literal_value(spec_upper)
    if spec_value is not None:
        try:
            return ({}, []) if evaluate_expression(operand_clean, symbols, scope) == spec_value else None
        except AssemblerError:
            return ({}, []) if operand_upper == spec_upper else None
    return ({}, []) if operand_upper == spec_upper else None


def match_template(
    template: InstructionTemplate,
    operands: list[str],
    scope: str | None,
    symbols: dict[str, int],
    line_no: int,
) -> MatchResult | None:
    if len(template.operands) != len(operands):
        return None
    formula_values: dict[str, int] = {}
    byte_tasks: list[tuple[str, str]] = []
    for spec, operand in zip(template.operands, operands):
        matched = match_operand(spec, operand, scope, symbols, line_no)
        if matched is None:
            return None
        spec_formula, spec_tasks = matched
        formula_values.update(spec_formula)
        byte_tasks.extend(spec_tasks)
    return MatchResult(template, formula_values, byte_tasks)


def operand_specificity(spec: str) -> int:
    spec_upper = spec.upper().replace(' ', '')
    if spec in {'N', 'NN', 'n'} or spec_upper in {'(N)', '(NN)'}:
        return 0
    if spec in {'r', 'b'}:
        return 1
    if spec in {'(IX+n)', '(IY+n)'}:
        return 2
    return 3


def opcode_formula_value(token: str, formula_values: dict[str, int]) -> int:
    total = 0
    for term in token.split('+'):
        product = 1
        for factor in term.split('*'):
            factor = factor.strip()
            if factor in formula_values:
                product *= formula_values[factor]
            else:
                product *= int(factor, 16)
        total += product
    return total & 0xFF


def encode_8bit(value: int) -> int:
    if not -128 <= value <= 255:
        raise AssemblerError(f'8-bit value out of range: {value}')
    return value & 0xFF


def encode_16bit(value: int) -> int:
    if not -32768 <= value <= 0xFFFF:
        raise AssemblerError(f'16-bit value out of range: {value}')
    return value & 0xFFFF


class Assembler:
    def __init__(self, instruction_path: Path):
        self.templates = parse_instruction_list(instruction_path)

    def find_match(self, statement: Statement, symbols: dict[str, int]) -> MatchResult:
        best_match: MatchResult | None = None
        best_score = -1
        for template in self.templates.get(statement.name, []):
            matched = match_template(template, statement.args, statement.scope, symbols, statement.line_no)
            if matched is not None:
                score = sum(operand_specificity(spec) for spec in template.operands)
                if score > best_score:
                    best_match = matched
                    best_score = score
        if best_match is not None:
            return best_match
        rendered = f" {', '.join(statement.args)}" if statement.args else ''
        raise AssemblerError(f'Unsupported instruction on line {statement.line_no}: {statement.name}{rendered}')

    def directive_size(self, statement: Statement, symbols: dict[str, int], location: int) -> int:
        if statement.name in {'ORG', 'FORG'}:
            target = evaluate_expression(statement.args[0], symbols, statement.scope)
            if target < location:
                raise AssemblerError(f'{statement.name} cannot move backwards on line {statement.line_no}')
            return target - location
        if statement.name == 'DB':
            size = 0
            for arg in statement.args:
                size += len(decode_string(arg)) if arg.startswith('"') else 1
            return size
        if statement.name == 'DW':
            return 2 * len(statement.args)
        if statement.name == 'DS':
            size = evaluate_expression(statement.args[0], symbols, statement.scope)
            if size < 0:
                raise AssemblerError(f'DS size must be non-negative on line {statement.line_no}')
            return size
        if statement.name == 'EQU':
            return 0
        raise AssemblerError(f'Unsupported directive on line {statement.line_no}: {statement.name}')

    def first_pass(self, statements: list[Statement]) -> dict[str, int]:
        symbols: dict[str, int] = {}
        pending_equ: list[tuple[str, str, str | None, int]] = []
        location = 0
        for statement in statements:
            symbols['*'] = location
            if statement.label and statement.name != 'EQU':
                if statement.label in symbols:
                    raise AssemblerError(f'Duplicate label on line {statement.line_no}: {statement.label}')
                symbols[statement.label] = location
            if statement.kind == 'EMPTY':
                continue
            if statement.kind == 'DIRECTIVE':
                if statement.name == 'EQU':
                    if not statement.label:
                        raise AssemblerError(f'EQU requires a label on line {statement.line_no}')
                    if statement.label in symbols:
                        raise AssemblerError(f'Duplicate label on line {statement.line_no}: {statement.label}')
                    pending_equ.append((statement.label, statement.args[0], statement.scope, statement.line_no))
                    continue
                location += self.directive_size(statement, symbols, location)
                continue
            match = self.find_match(statement, symbols)
            location += match.template.size

        changed = True
        while changed and pending_equ:
            changed = False
            remaining: list[tuple[str, str, str | None, int]] = []
            for label, expr, scope, line_no in pending_equ:
                try:
                    symbols[label] = evaluate_expression(expr, symbols, scope)
                    changed = True
                except AssemblerError:
                    remaining.append((label, expr, scope, line_no))
            pending_equ = remaining
        if pending_equ:
            label, _, _, line_no = pending_equ[0]
            raise AssemblerError(f'Could not resolve EQU for {label} on line {line_no}')
        symbols['*'] = location
        return symbols

    def encode_db(self, statement: Statement, symbols: dict[str, int]) -> list[int]:
        output: list[int] = []
        for arg in statement.args:
            if arg.startswith('"'):
                output.extend(decode_string(arg))
            else:
                output.append(encode_8bit(evaluate_expression(arg, symbols, statement.scope)))
        return output

    def encode_dw(self, statement: Statement, symbols: dict[str, int]) -> list[int]:
        output: list[int] = []
        for arg in statement.args:
            value = encode_16bit(evaluate_expression(arg, symbols, statement.scope))
            output.extend((value & 0xFF, value >> 8))
        return output

    def encode_instruction(self, statement: Statement, match: MatchResult, pc: int, symbols: dict[str, int]) -> list[int]:
        extra_bytes: list[int] = []
        for kind, expr in match.byte_tasks:
            value = evaluate_expression(expr, symbols, statement.scope)
            if kind == 'imm8':
                extra_bytes.append(encode_8bit(value))
            elif kind == 'imm16':
                word = encode_16bit(value)
                extra_bytes.extend((word & 0xFF, word >> 8))
            elif kind == 'disp8':
                if not -128 <= value <= 127:
                    raise AssemblerError(
                        f'Indexed displacement must be between -128 and 127 on line {statement.line_no}: got {value}'
                    )
                extra_bytes.append(value & 0xFF)
            elif kind == 'rel8':
                offset = value - (pc + match.template.size)
                if not -128 <= offset <= 127:
                    raise AssemblerError(f'Relative jump out of range on line {statement.line_no}: {expr}')
                extra_bytes.append(offset & 0xFF)
            else:
                raise AssemblerError(f'Unsupported byte task: {kind}')

        encoded: list[int] = []
        extra_index = 0
        for token in match.template.opcode_tokens:
            if token == 'XX':
                if extra_index >= len(extra_bytes):
                    raise AssemblerError(f'Missing immediate byte on line {statement.line_no}')
                encoded.append(extra_bytes[extra_index])
                extra_index += 1
            else:
                encoded.append(opcode_formula_value(token, match.formula_values))
        if len(encoded) != match.template.size:
            raise AssemblerError(
                f'Instruction size mismatch on line {statement.line_no}: expected {match.template.size}, got {len(encoded)}'
            )
        return encoded

    def second_pass(self, statements: list[Statement], symbols: dict[str, int]) -> bytes:
        output = bytearray()
        location = 0
        for statement in statements:
            symbols['*'] = location
            if statement.kind == 'EMPTY':
                continue
            if statement.kind == 'DIRECTIVE':
                if statement.name == 'EQU':
                    continue
                if statement.name in {'ORG', 'FORG'}:
                    target = evaluate_expression(statement.args[0], symbols, statement.scope)
                    if target < location:
                        raise AssemblerError(f'{statement.name} cannot move backwards on line {statement.line_no}')
                    output.extend(b'\x00' * (target - location))
                    location = target
                elif statement.name == 'DB':
                    data = self.encode_db(statement, symbols)
                    output.extend(data)
                    location += len(data)
                elif statement.name == 'DW':
                    data = self.encode_dw(statement, symbols)
                    output.extend(data)
                    location += len(data)
                elif statement.name == 'DS':
                    size = evaluate_expression(statement.args[0], symbols, statement.scope)
                    if size < 0:
                        raise AssemblerError(f'DS size must be non-negative on line {statement.line_no}')
                    output.extend(b'\x00' * size)
                    location += size
                else:
                    raise AssemblerError(f'Unsupported directive on line {statement.line_no}: {statement.name}')
                continue
            match = self.find_match(statement, symbols)
            data = self.encode_instruction(statement, match, location, symbols)
            output.extend(data)
            location += len(data)
        return bytes(output)

    def assemble(self, source: str) -> bytes:
        statements = parse_source(source)
        symbols = self.first_pass(statements)
        return self.second_pass(statements, symbols)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Simple Z80 assembler for this repository')
    parser.add_argument('source', help='Assembly source file')
    parser.add_argument('-o', '--output', help='Output binary path')
    parser.add_argument(
        '--instructions',
        default=str(Path(__file__).with_name('Z80 instructions list.txt')),
        help='Path to the Z80 instruction list',
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source)
    output_path = Path(args.output) if args.output else source_path.with_suffix('.bin')
    assembler = Assembler(Path(args.instructions))
    try:
        binary = assembler.assemble(source_path.read_text(encoding='utf-8'))
    except AssemblerError as exc:
        print(f'Assembly failed: {exc}', file=sys.stderr)
        return 1
    output_path.write_bytes(binary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
