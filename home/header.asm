; rst vectors (unused)

SECTION "rst0", ROM0[$0000]
	rst $38

	ds $08 - @, 0 ; unused

SECTION "rst8", ROM0[$0008]
	rst $38

	ds $10 - @, 0 ; unused

; Line-$6e color prepare. Home is full, so the LCD handler reaches it
; through this slot instead of a farcall.
SECTION "rst10", ROM0[$0010]
	ld b, BANK(YellowLcdPrepare)
	ld hl, YellowLcdPrepare
	jp Bankswitch

SECTION "rst18", ROM0[$0018]
	rst $38

	ds $20 - @, 0 ; unused

SECTION "rst20", ROM0[$0020]
	rst $38

	ds $28 - @, 0 ; unused

SECTION "rst28", ROM0[$0028]
	rst $38

	ds $30 - @, 0 ; unused

; The rest of the rst $38 crash hook, which needs more than its own 8 bytes.
SECTION "rst30", ROM0[$0030]
	ld a, BANK(CrashHandler)
	ld [rROMB], a
	jp CrashHandler

; Running into $FF bytes (a wild jump) lands here. This used to call itself
; until the stack had overwritten all of RAM; now it records where the game
; was in SRAM (sCrashDump) and stops. See tools/crashdump.py.
SECTION "rst38", ROM0[$0038]
	di
	push af
	jr $0030

	ds $40 - @, 0 ; unused


; Game Boy hardware interrupts

SECTION "vblank", ROM0[$0040]
	jp VBlank

	ds $48 - @, 0 ; unused

SECTION "lcd", ROM0[$0048]
	jp LCDC

	ds $50 - @, 0 ; unused

SECTION "timer", ROM0[$0050]
	jp Timer

	ds $58 - @, 0 ; unused

SECTION "serial", ROM0[$0058]
	jp Serial

	ds $60 - @, 0 ; unused

SECTION "joypad", ROM0[$0060]
	reti


SECTION "Header", ROM0[$0100]

Start::
; Nintendo requires all Game Boy ROMs to begin with a nop ($00) and a jp ($C3)
; to the starting address.
	nop
	jp _Start

; The Game Boy cartridge header data is patched over by rgbfix.
; This makes sure it doesn't get used for anything else.

	ds $0150 - @

ENDSECTION
