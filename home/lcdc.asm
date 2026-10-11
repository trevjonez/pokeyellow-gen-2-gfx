LCDC::
	push af
	ldh a, [hLCDCPointer] ; doubles as enabling byte
	and a
	jr z, .noPointer
	push hl
	; [C700 + [rLY]] --> [FF00 + [hLCDCPointer]]
	ldh a, [rLY]
	ld l, a
	ld h, HIGH(wLYOverrides)
	ld h, [hl] ; h != not part of pointer
	ldh a, [hLCDCPointer]
	ld l, a
	ld a, h
	ld h, $ff
	ld [hl], a
	pop hl
.popAfReti
	pop af
	reti
.noPointer
	; Intro and surfing request hblank while the pointer is still 0.
	; Only line $6e prepares window colors. Any other line returns here,
	; without touching the WRAM bank, or that effect never finishes.
	ldh a, [rLY]
	cp $6e
	jr nz, .popAfReti
	; Drop the push in the bank that was current, then switch to bank 0
	; before pushing again. The real stack image lives in bank 1.
	pop af
	ldh [hSPTemp], a
	ldh a, [rWBK]
	ldh [hSPTemp + 1], a
	ld a, 0 ; preserves flags, unlike xor a
	ldh [rWBK], a
	ldh a, [hSPTemp]
	push af
	push hl
	push bc
	push de
	rst $10
	pop de
	pop bc
	pop hl
	pop af
	; hSPTemp still holds the interrupted A. Copying the saved WRAM bank
	; into rWBK overwrites A, and the interrupted code may be BankswitchCommon,
	; which uses A as the ROM bank.
	ldh a, [hSPTemp + 1]
	ldh [rWBK], a
	ldh a, [hSPTemp]
	reti
