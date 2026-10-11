; INPUT:
; a = oam block index (each block is 4 oam entries)
; b = Y coordinate of upper left corner of sprite
; c = X coordinate of upper left corner of sprite
; de = base address of 4 tile number and attribute pairs
WriteOAMBlock::
	ld h, HIGH(wShadowOAM)
	swap a ; multiply by 16
	ld l, a
	call .writeOneEntry ; upper left
	push bc
	ld a, 8
	add c
	ld c, a
	call .writeOneEntry ; upper right
	pop bc
	ld a, 8
	add b
	ld b, a
	call .writeOneEntry ; lower left
	ld a, 8
	add c
	ld c, a
	                      ; lower right
.writeOneEntry
	ld [hl], b ; Y coordinate
	inc hl
	ld [hl], c ; X coordinate
	inc hl
	ld a, [de] ; tile number
	inc de
	ld [hli], a
	ld a, [de] ; attribute
	inc de
	ld [hli], a
	ret

; A holds the OAM flags. ColorOverworldSprite writes the colored flags,
; advances hl and e, and returns the original flags in A.
; The wrapper stays in ROM0 so the banked call can return.
_ColorOverworldSprite::
	ld b, a
	ldh a, [hLoadedROMBank]
	push af
	ld a, BANK(ColorOverworldSprite)
	call SetRomBank
	ld a, b
	call ColorOverworldSprite
	ld b, a
	pop af
	call SetRomBank
	ld a, b
	ret
