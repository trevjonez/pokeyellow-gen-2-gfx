InitGbcMode:: ; Sets double speed
	ld a, $01
	; Set double speed mode
	ldh [rSPD], a
	stop
	ret

ResetGbcState::
; Init runs this on every boot, including a soft reset, which skips _Start.
; Init only clears WRAM bank 1 and VRAM bank 0, so the overworld's color state
; and tile attributes would otherwise leak into the intro. LCD is off here.
	ldh a, [hOnCGB]
	and a
	ret z
	ld a, 1
	ldh [rVBK], a
	ld hl, STARTOF(VRAM)
	ld bc, SIZEOF(VRAM)
	xor a
	call FillMemory
	xor a
	ldh [rVBK], a
	; Clear memory (banks 2-7)
	ld d, 7
.clearBank
	ld a, d
	ldh [rWBK], a
	xor a
	ld hl, W2_BgPaletteData
	ld bc, $0f00 ; Leave a bit of space for the stack
	call FillMemory
	dec d
	ld a, d
	dec a
	jr nz, .clearBank

	xor a
	ldh [rWBK], a
	ret
