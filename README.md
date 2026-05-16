# asmz80

Simple Z80 assembler for the instruction list and sample program in this repository.

## Usage

```bash
python3 asmz80.py minefield3.asm -o minefield.bin
```

## Notes

- `asmz80.py` reads opcode definitions from `Z80 instructions list.txt`.
- Supported directives used by the sample source are `ORG`, `FORG`, `DB`, `DW`, `DS`, and `EQU`.
- `minefield.bin` is the assembled output for `minefield3.asm`.
