#!/usr/bin/env python3
"""Convert an EverDrive GB X snapshot (GBCSYS/SNAP/*.sav) into a BESS save state
that SameBoy (and other BESS emulators) can load.

Usage: tools/snap2bess.py SNAP.sav OUT.state [ROM.gbc]

Snapshot layout (reverse-engineered from a CGB game):
  0x0000 "SAVE", SP (le16), ?, ?, ?, ROM bank
  0x0200 VRAM bank 0      0x2200 WRAM banks 0-1   0x4200 $FE00-$FFFF (OAM, IO, HRAM, IE)
  0x4400 SRAM (32 KB)     0xC400 BG + OBJ palettes 0xC600 VRAM bank 1
  0xE600 WRAM banks 2-7
The cart's vblank hook takes the snapshot: the CPU's interrupt push (PC) sits on
the stack under AF, BC, DE, HL. We restore to the vblank vector with that PC
still pushed, so the game's own handler runs next, as it would have.
"""
import struct
import sys


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    s = open(sys.argv[1], 'rb').read()
    if s[:4] != b'SAVE':
        sys.exit('not an EverDrive snapshot')
    rom = open(sys.argv[3] if len(sys.argv) > 3 else 'pokeyellow.gbc', 'rb').read()
    sp = s[4] | s[5] << 8
    rom_bank = s[9]
    hi = s[0x4200:0x4400]                       # $FE00-$FFFF
    w = lambda a: hi[a - 0xfe00] | hi[a - 0xfe00 + 1] << 8 if a >= 0xfe00 else \
        s[0x2200 + a - 0xc000] | s[0x2200 + a - 0xc000 + 1] << 8
    hl, de, bc, af, pc = (w(sp + i) for i in range(0, 10, 2))

    ram = s[0x2200:0x4200] + s[0xe600:0x14600]
    vram = s[0x0200:0x2200] + s[0xc600:0xe600]
    sram = s[0x4400:0xc400]
    oam, io, hram = hi[:0xa0], bytearray(hi[0x100:0x180]), hi[0x180:0x1ff]
    pals = s[0xc400:0xc480]
    io[0x4c] = 0x80                              # KEY0: CGB mode
    io[0x50] = 1                                 # boot ROM unmapped

    out = bytearray()
    bufs = {}
    for name, data in (('ram', ram), ('vram', vram), ('sram', sram), ('oam', oam), ('hram', hram),
                       ('bgp', pals[:0x40]), ('obp', pals[0x40:])):
        bufs[name] = (len(data), len(out))
        out += data
    first = len(out)

    def block(tag, body):
        out.extend(tag + struct.pack('<I', len(body)) + body)

    block(b'NAME', b'EverDrive snapshot (snap2bess)')
    block(b'INFO', rom[0x134:0x144] + rom[0x14e:0x150])
    core = struct.pack('<HH4s', 1, 1, b'CC  ')
    # PC at the vblank vector, interrupt return address still on the stack, IME off
    core += struct.pack('<6H', 0x0040, af, bc, de, hl, sp + 8)
    core += bytes([0, hi[0x1ff], 0, 0]) + bytes(io)
    for k in ('ram', 'vram', 'sram', 'oam', 'hram', 'bgp', 'obp'):
        core += struct.pack('<II', *bufs[k])
    block(b'CORE', core)
    # MBC5: RAM disabled, ROM bank, RAM bank 0
    block(b'MBC ', struct.pack('<HBHBHBHB', 0x0000, 0, 0x2000, rom_bank, 0x3000, 0, 0x4000, 0))
    block(b'END ', b'')
    out += struct.pack('<I', first) + b'BESS'
    open(sys.argv[2], 'wb').write(out)
    print(f'PC {pc:04x} (resumes via vblank)  SP {sp + 10:04x}  AF {af:04x} BC {bc:04x} DE {de:04x} HL {hl:04x}  ROM bank {rom_bank}')


if __name__ == '__main__':
    main()
