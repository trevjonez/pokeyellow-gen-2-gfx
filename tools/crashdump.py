#!/usr/bin/env python3
"""Decode the crash dump CrashHandler (color/crash.asm) leaves in a battery save.

Usage: tools/crashdump.py SAVE.srm [pokeyellow.sym]

When the game runs into $FF bytes it executes rst $38; the handler records the
registers, the stack and HRAM in sCrashDump (SRAM bank 0), turns the screen red
and stops. Reset the console so the save is written, then run this on the .srm.
Only the latest crash is kept.
Addresses are labelled with the nearest symbol from the .sym of the same build.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_syms(path):
    """(bank, addr) -> name, plus a sorted list per bank for nearest-symbol lookups."""
    by_bank = {}
    for line in open(path):
        parts = line.split()
        if len(parts) != 2 or ':' not in parts[0] or parts[0].startswith(';'):
            continue
        bank, addr = (int(x, 16) for x in parts[0].split(':'))
        by_bank.setdefault(bank, []).append((addr, parts[1]))
    for v in by_bank.values():
        v.sort()
    return by_bank


def label(syms, bank, addr):
    """Nearest symbol at or below addr: ROM0 below $4000, else the given ROMX bank."""
    if addr >= 0x8000:
        bank = 0
    elif addr < 0x4000:
        bank = 0
    best = None
    for a, name in syms.get(bank, []):
        if a > addr:
            break
        if addr < 0x4000 or a >= 0x4000:
            best = (a, name)
    if not best:
        return f'{bank:02x}:{addr:04x}'
    return f'{bank:02x}:{addr:04x} {best[1]}' + (f'+{addr - best[0]:#x}' if addr != best[0] else '')


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    data = open(sys.argv[1], 'rb').read()
    sym_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'pokeyellow.sym')
    syms = load_syms(sym_path)
    dump_addr = next(a for b in (0,) for a, n in syms.get(b, []) if n == 'sCrashDump')
    d = data[dump_addr - 0xa000: dump_addr - 0xa000 + 0x100]   # SRAM bank 0 starts the file
    if d[:4] != b'CRSH':
        sys.exit('No crash recorded in this save.')
    rom_bank, wbk, vbk, lcdc, stat, ly, ie, if_ = d[5:13]
    sp = d[13] | d[14] << 8
    stack = d[0x10:0x90]
    word = lambda i: stack[i] | stack[i + 1] << 8
    bc, de, hl, af = word(0), word(2), word(4), word(6)
    ret = word(8)
    print(f'ran into $FF at {label(syms, rom_bank, ret - 1)}   (ROM bank {rom_bank:#04x} was mapped)')
    print(f'AF={af:04x} BC={bc:04x} DE={de:04x} HL={hl:04x} SP={sp + 10:04x}')
    print(f'WRAM bank {wbk & 7 or 1}, VRAM bank {vbk & 1}, LCDC={lcdc:02x} STAT={stat:02x} LY={ly} IE={ie:02x} IF={if_:02x}')
    print('stack above the crash (likely return addresses labelled):')
    for i in range(10, len(stack) - 1, 2):
        w = word(i)
        note = ''
        if w < 0x8000:
            note = '  ' + label(syms, rom_bank, w)
        print(f'  {sp + i:04x}: {w:04x}{note}')
    print('HRAM $ff80-$ffdf:')
    hram = d[0x90:0xf0]
    for i in range(0, len(hram), 16):
        print(f'  {0xff80 + i:04x}: ' + ' '.join(f'{b:02x}' for b in hram[i:i + 16]))


if __name__ == '__main__':
    main()
