; rst $38 (see home/header.asm) jumps here with interrupts off, AF pushed on the
; stack above the rst's return address, and this bank in rROMB.
; Saves the machine state to sCrashDump in SRAM bank 0, turns the screen red and
; stops. tools/crashdump.py decodes the dump from a battery save.
;
; sCrashDump layout:
;   $00 "CRSH"   $04 unused        $05 hLoadedROMBank   $06 rWBK   $07 rVBK
;   $08 rLCDC    $09 rSTAT  $0a rLY  $0b rIE  $0c rIF  $0d SP (2, little endian)
;   $10 128 bytes from SP: BC DE HL AF, the rst's return address, then the stack
;   $90 HRAM $FF80-$FFDF
DEF CRASH_STACK_BYTES EQU $80
DEF CRASH_HRAM_BYTES  EQU $60

CrashHandler::
	push hl
	push de
	push bc
	ld a, BMODE_ADVANCED
	ld [rBMODE], a
	ld a, RAMG_SRAM_ENABLE
	ld [rRAMG], a
	xor a
	ld [rRAMB], a

	ld hl, sCrashDump
	ld a, $43 ; "C" in ASCII, for tools/crashdump.py
	ld [hli], a
	ld a, $52 ; "R" in ASCII, for tools/crashdump.py
	ld [hli], a
	ld a, $53 ; "S" in ASCII, for tools/crashdump.py
	ld [hli], a
	ld a, $48 ; "H" in ASCII, for tools/crashdump.py
	ld [hli], a
	inc hl
	ldh a, [hLoadedROMBank]
	ld [hli], a
	ldh a, [rWBK]
	ld [hli], a
	ldh a, [rVBK]
	ld [hli], a
	ldh a, [rLCDC]
	ld [hli], a
	ldh a, [rSTAT]
	ld [hli], a
	ldh a, [rLY]
	ld [hli], a
	ldh a, [rIE]
	ld [hli], a
	ldh a, [rIF]
	ld [hli], a
	ld d, h
	ld e, l
	ld hl, sp + 0
	ld a, l
	ld [de], a
	inc de
	ld a, h
	ld [de], a
	inc de
	inc de ; $10

	ld c, CRASH_STACK_BYTES
.stack
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .stack

	ld hl, STARTOF(HRAM)
	ld c, CRASH_HRAM_BYTES
.hram
	ld a, [hli]
	ld [de], a
	inc de
	dec c
	jr nz, .hram

	xor a
	ld [rRAMG], a
	ld [rBMODE], a

	; Red screen. Palette RAM only takes writes outside pixel transfer.
	ldh a, [rLCDC]
	bit B_LCDC_ENABLE, a
	jr z, .paint
.waitVBlank
	ldh a, [rLY]
	cp LY_VBLANK
	jr nz, .waitVBlank
.paint
	ld a, BGPI_AUTOINC
	ldh [rBGPI], a
	ldh [rOBPI], a
	ld b, 32
.red
	ld a, LOW(31) ; RGB 31, 0, 0
	ldh [rBGPD], a
	ldh [rOBPD], a
	xor a
	ldh [rBGPD], a
	ldh [rOBPD], a
	dec b
	jr nz, .red
.halt
	jr .halt
