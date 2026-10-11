_Start::
	cp BOOTUP_A_CGB
	jr z, .cgb
	xor a
	ldh [hOnCGB], a
	jp Init
.cgb
	ld a, TRUE
	ldh [hOnCGB], a
	xor a
	ldh [hLoadedROMBank], a
	ld [rROMB], a
	farcall InitGbcMode
	jp Init
