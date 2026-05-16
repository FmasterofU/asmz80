# asmz80

Simple Z80 assembler for the instruction list and sample program in this repository.

## Usage

```bash
python3 asmz80.py /home/runner/work/asmz80/asmz80/minefield3.asm -o /home/runner/work/asmz80/asmz80/minefield.bin
```

## Notes

- `asmz80.py` reads opcode definitions from `Z80 instructions list.txt`.
- Supported directives used by the sample source are `org`, `forg`, `db`, `dw`, `ds`, and `equ`.
- `minefield.bin` is the assembled output for `minefield3.asm`.
