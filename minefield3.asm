;===============================================================================
; Traženje puta kroz minsko polje.
;===============================================================================

	jr	code
	db	"Mine Field V3.0",0
code:

   	ld	sp,$7700	; Inicijalizacija steka
   	im	1		
   	ei
	
	; Animacija igrača na početnom ekranu koji ide sa leva na desno
	; (taman da se umetne nešto u prazan prostor pre interapt rutine):

	ld	hl,middle	; Pozicioniraj se na sredinu table
	inc	hl		; Preskoči nevidljivo polje
	ld	b,15		; Brojač pozicija za koje će se igrač animirati
	
	; Sihnronizacija sa interaptom da se prikaže inicijalna tabla i
	; omogući smeštanje očitanih tastera u last_btns i curr_btns varijable:
	
	halt
	
anim_loop:
	ld	(hl),1		; Kod 1 - stavi simbol igrača koji traži izlaz
	halt			; Sačekaj 1/10s (2x1/20s)
	halt
	ld	(hl),3		; Kod 3 - označi da je igrač tuda prošao
	inc	hl		; Pređi na sledeće polje
	djnz	anim_loop	; Ponavljaj do kraja reda
	ld	(hl),7		; Kod 7 - stavi simbol igrača koji je našao izlaz
	
	; Čekaj na pritisak bilo kog tastera da se R registar dovede
	; na slučajnu vrednost kako bi seed_random radio kako treba:
		
	call	read_keys
	call	seed_random
	
	jp	main		; Idemo na glavni deo...
	
;------------------------------------------------------------------------------- 
; Interapt routina. Očitava tastere i iscrtava trenutno stanje na tabli.
;------------------------------------------------------------------------------- 

   	forg	$0038
	org	$0038

interrupt:
	
	push	af
	push	bc
	push	de
	push	hl
	
	; Očitavanje tastera:
	
	ld	a,(curr_btns)	; Uzmi stanje tastera koje je bilo prethodni interapt
	ld	b,a		; Pomeri ga u B
	in	a,(0)		; Očitaj trenutno stanje tastera
	ld	(curr_btns),a	; Smesti ga u trenutno stanje tastera
	cp	b		; Da li je isto kao i prethodni put?
	jr	z,.skip		; Ako je isto preskoči upis u last_btns
	ld	(last_btns),a	; Ako se razlikuje osveži last_btns
.skip:
	; Iscrtavanje sadržaja table na ekran:
	
	ld	hl,finish	; Adresa prvog bajta sa definicijom vidljive table za igru
	dec	hl		; Vrati jedno polje u prethodni red na poziciju desnog okvira
				; da bi dupli INC HL u glavnoj petlji radio kako treba
	ld	de,$7800	; Adresa prvog bajta VRAM
	ld	b,16		; Brojač vidljivih redova na tabli

.row_loop:
	inc	hl		; Preskoči desni okvir
	inc	hl		; Presloči levi okvir, sada je na prvom vidljivom polju u redu
	ld	c,16		; Brojač vidljivih kolona na tabli
.col_loop:	
	ld	a,(hl)		; Učitaj u A kod simbola koji treba prikazati
	sla	a		; Pomnoži sa 8 da se izračuna ofset u tabeli simbola
	sla	a
	sla	a
	
	; Priprema adrese definicije simbola za ispisivanje:
	
	push	hl		; Skloni privremeno HL
	push	de		; Skloni privremeno DE
	
	ld	hl,sym_table	; Početak tabele sa definicijom simbola
	ld	d,0		; Spremi DE kao 16-bitni ofset za dodavanje na HL
	ld	e,a
	add	hl,de		; Izračunaj ofset simbola koji treba prikazati
	pop	de		; Vrati DE da pokazuje na trenutnu adresu u VRAM

	; Prepisivanje osam bajtova definicije simbola u VRAM:
	
	push	bc		; Skloni BC da se sačuvaju brojači
	ld	b,8		; Spremi brojač za 8 bajtova
.copy_symbol:
	ld	a,(hl)		; Uzmi bajt definicije simbola
	ld	(de),a		; Prepiši u VRAM
	inc	hl		; Sledeći bajt simbola
	inc	de		; Sledeći bajt u VRAM
	djnz	.copy_symbol	; Nastavi za sve bajtove u definiciji simbola
		
	pop	bc		; Vrati BC da se vrate brojači
	pop	hl		; Vrati HL da se vrati 
	
	; Prelazak na sledeće polje u tekućem redu table:
	
	inc	hl		; Pomeri na sledeće polje u redu
	dec	c		; Smanji brojač polja u redu
	jr	nz,.col_loop	; Ako nije nula

	; Prelazak na sledeći red na tabli:
	
	djnz	.row_loop	; Smanji brojč redova i nastavi ako nije nula

	; Kraj rutine:
.exit:	
	pop	hl
	pop	de
	pop	bc
	pop	af
	ei
   	reti

;------------------------------------------------------------------------------- 
; Glavna petlja igre.
;------------------------------------------------------------------------------- 

main:		
	; Glavna petlja igre:
.start:	
	call	show_level
	call	initialize
	call	hide_mines
	call	read_keys
	
.move_loop:
	call	count_mines
	call	auto_mark
	call	read_keys

	; Provera pomeranja igrača na NEWS:
	
	bit	1,a		; Da li ide na sever?
	ld	bc,-18		; Ofset za pomeranje na poziciju iznad
	call	z,move_player	; Ako ide pomeri na sever
	bit	2,a		; Da li ide na istok?
	ld	bc,1		; Ofset za pomeranje na poziciju desno
	call	z,move_player	; Ako ide pomeri na istok
	bit	3,a		; Da li ide na jug?
	ld	bc,18		; Ofset za pomeranje na poziciju ispod	
	call	z,move_player	; Ako ide pomeri na jug
	bit	4,a		; Da li ide na zapad?
	ld	bc,-1		; Ofset za pomeranje na poziciju levo	
	call	z,move_player	; Ako ide pomeri na zapad
	
	; Markiranje mina ako se istovremeno pritisne ABC ("cheat code" :): 
	
	cp	%00011111	; Da li su pritisnuti ABC?
	call	z,show_mines	; Ako jeste
		
	ld	a,(game_over)	; Učitaj stanje igre
	cp	1		; Da li je kraj igre?
	jr	nz,.move_loop	; Ako nije nastavi
	
	call	show_mines	; Ako je kraj igre prikaži gde su bile mine
	halt			; Sinhronizuj sa interaptom da se prikaže tabla
	call	read_keys	; Sačekaj bilo koji taster
	jr	.start		; Kreni iz početka
	
;------------------------------------------------------------------------------- 
; Prebrojavanje mina ispred igrača i prikaz na LED ekranu. 
;------------------------------------------------------------------------------- 

count_mines:

	push	af
	push	bc
	push	de
	push	hl
	
	ld	c,0		; Inicijalizacija brojača mina
	ld	b,3		; Inicijalizacija brojača pozicija 
	ld	hl,(player_pos)	; Trenutna pozicija igrača
	ld	de,-19		; Ofset gornjeg levog polja
	add	hl,de		; Pozicija polja (NW)
	
	; Prebrojavanje mina u redu iznad igrača:
.loop:
	ld	a,(hl)		; Učitaj sadržaj polja
	cp	4		; Kod 4 - da li se tu nalazi skrivena mina?
	call	z,.inc_counter	; Ako nalazi uvećaj brojač mina
	cp	5		; Kod 5 - da li se tu nalazi vidljiva mina?
	call	z,.inc_counter	; Ako se nalazi uvećaj brojač mina
	inc	hl		; Sledeće polje u desno
	djnz	.loop		; Nastavi za sva polja

	; Prikaz jačine signala na LED ekranu:

	ld	a,c
	cp	0
	jr	z,.led_0
	cp	1
	jr	z,.led_1
	cp	2
	jr	z,.led_2
	cp	3
	jr	z,.led_3

	; Ako nije ništa od očekivanih onda je greška, prikaži "E" (za debug):

	ld	a,%01111001
	jr	.exit
	
.led_0:
	ld	a,%00000000	; Ništa na displeju
	jr	.exit	
.led_1:
	ld	a,%00001000	; Jedan bar |
	jr	.exit	
.led_2:
	ld	a,%01001000	; Dva bara ||
	jr	.exit	
.led_3:
	ld	a,%01001001	; Tri bara |||

	; Kraj rutine:
.exit:
	out	(0),a		; Prikaži spremljeni prikaz na LED ekranu
	pop	hl
	pop	de
	pop	bc
	pop	af
	ret
	
.inc_counter:
	inc	c		; Uvećaj brojač mina
	ret
	
;------------------------------------------------------------------------------- 
; Automatsko označavanje mina kada je jasno gde su, da ne mora da se pamti.
; To je sučaj kada se ispred igrača nalazi samo skrivene mine (KOD 4),
; vidljive mine (KOD 5), sigurna polja koja je prošao (KOD 3) ili okvir oko 
; table (KOD 0) kada nema dileme da je jasno gde su mine.
;------------------------------------------------------------------------------- 

auto_mark:

	push	af
	push	bc
	push	de
	push	hl
	
	ld	c,0		; Inicijalizacija brojača
	ld	b,3		; Inicijalizacija brojača pozicija 
	ld	hl,(player_pos)	; Trenutna pozicija igrača
	ld	de,-19		; Ofset gornjeg levog polja
	add	hl,de		; Pozicija polja (NW)
	
	; Prebrojavanje polja koja zadovoljavaju uslov u gornjem redu:
.loop_count:
	ld	a,(hl)		; Učitaj sadržaj polja
	cp	0		; Kod 0 - da je okvir oko table?
	call	z,.inc_counter	; Ako jeste uvećaj brojač
	cp	3		; Kod 3 - da li je polje koje je već prošao?
	call	z,.inc_counter	; Ako jeste uvećaj brojač
	cp	4		; Kod 4 - da li je skrivena mina?
	call	z,.inc_counter	; Ako jeste uvećaj brojač
	cp	5		; Kod 4 - da li je vidljiva mina?
	call	z,.inc_counter	; Ako jeste uvećaj brojač

	inc	hl		; Sledeće polje u desno
	djnz	.loop_count	; Nastavi za sva polja

	; Zamena skrivenih mina ako je uslov zadovoljen:
	
	ld	a,c		; Prebaci brojač u A da se
	cp	3		; uporedi sa 3
	jr	nz,.exit	; Ako nije 3 uslov nije zadovoljen

	ld	b,3		; Inicijalizacija brojača pozicija 
	ld	hl,(player_pos)	; Trenutna pozicija igrača
	ld	de,-19		; Ofset gornjeg levog polja
	add	hl,de		; Pozicija polja (NW)
.loop_replace:
	ld	a,(hl)		; Učitaj stanje polja
	cp	4		; Da li je skrivena mina?
	call	z,.unhide_mine	; Zameni nevidljivu minu vidljivom 
	inc	hl		; Sledeće polje u desno
	djnz	.loop_replace	; Nastavi za sva polja
	
	; Kraj rutine:
.exit:
	pop	hl
	pop	de
	pop	bc
	pop	af
	ret
	
.inc_counter:
	inc	c		; Uvećaj brojač
	ret
	
.unhide_mine:
	ld	(hl),5		; Stavi vidljivu minu
	ret

;------------------------------------------------------------------------------- 
; Pomeranje igrača po tabli.
; Ulaz: BC - ofset parametar koji određuje smer 
;------------------------------------------------------------------------------- 
	
move_player:
	push	af
	push	hl
	
	; Da li je udario u okvir:

	ld	hl,(player_pos)	; Trenutna adresa igrača na tabli
	add	hl,bc		; Pripremi novu poziciju na osnovu ofseta
	ld	a,(hl)		; Učitaj šta se tamo nalazi
	cp	0		; Kod 0 - da li je polje oko table na koje se ne može stati?
	jr	z,.exit		; Ako jeste preskoči upis pomeranja i izađi	
	
	; Da li je nagazio na minu:
	
	cp	4		; Kod 4 - da li je nagazio na skrivenu minu?
	jr	z,.player_rip	; Ako jeste kraj igre
	cp	5		; Kod 5 - da li je nagazio na vidljivu minu?
	jr	z,.player_rip	; Ako jeste kraj igre
	
	; Ako je sve u redu, onda pomeri:
.move:
	ld	hl,(player_pos)	; Osveži trenutnu adresu igrača na tabli
	ld	(hl),3		; Kod 3 - upis pozicije na kojoj je bio
	add	hl,bc		; Pripremi novu poziciju na osnovu ofseta
	ld	a,(hl)		; Učitaj kod polja na koji treba da stane
	cp	8		; Da li je stigao u ciljni red?
	jr	z,.finish	; Ako jeste igra je gotova
	ld	(hl),1		; Kod 1 - ako nije smesti simbol igrača na novu poziciju
	ld	(player_pos),hl	; Smesti novu poziciju u varijablu
	jr	.exit
	
.player_rip:
	ld	hl,(player_pos)	; Osveži trenutnu adresu igrača na tabli
	ld	(hl),3		; Kod 3 - upis pozicije na kojoj je bio
	add	hl,bc		; Pripremi novu poziciju na osnovu ofseta
	ld	(hl),6		; Kod 6 - smesti oznaku gde je nagazio na minu
	ld	(player_pos),hl	; Smesti novu poziciju u varijablu

	ld	a,1		; Oznaka da je igra gotova
	ld	(game_over),a	; Upiši da je igra gotova
	
	; Prošaraj ekran da izgleda kao eksplozija:
	
	ld	h,10		; Brojač ponavljanja za pola sekunde eksplozije
.rip_explode:
	call	generate_random	; Random bitovi za prikaz na LED i
	and	%01111111	; brisanje bita 7 za tačku
	out	(0),a		; Prikaži random šaru na LED-u
	halt			; Mala pauza 1/20s
	dec	h
	jr	nz,.rip_explode
	ld	a,0		; Obriši LED
	out	(0),a		;
	
	jr	.exit
	
.finish:
	ld	hl,(player_pos)	; Osveži trenutnu adresu igrača na tabli
	ld	(hl),3		; Kod 3 - upis pozicije na kojoj je bio
	add	hl,bc		; Pripremi novu poziciju na osnovu ofseta
	ld	(hl),7		; Kod 7 - oznaka da je stigao živ na cilj
	ld	(player_pos),hl	; Smesti novu poziciju u varijablu

	ld	a,1		; Oznaka da je igra gotova
	ld	(game_over),a	; Upiši da je igra gotova
	
	ld	a,(game_level)	; Učitaj trenutni nivo igre
	cp	max_level	; Da li je već na maksimumu?
	jr	z,.exit		; Ako jeste nema dalje
	inc	a		; Ako nije uvećaj nivo
	ld	(game_level),a	; i snimi u varijablu
	
	; Kraj rutine:
.exit:
	pop	hl
	pop	af
	ret

;------------------------------------------------------------------------------- 
; Inicijalizacija prazne table za igru i parametara.
;------------------------------------------------------------------------------- 
	
initialize:

	push	af
	push	bc
	push	de
	push	hl
	
	; Inicijalizacija varijabli:
	
	ld	a,0	
	ld	(game_over),a
	
	; Priprema prazne table:
	
	ld	hl,top		; Adresa prvog bajta sa definicijom table za igru
	ld	bc,324		; Brojač za prolaz kroz sva polja
.clear_loop:
	ld	(hl),0		; Inicijalizuj kodom 0 (polja na koja se ne može stati)
	dec	bc		; Smanji brojač polja za inicijalizaciju
	ld	a,b		; Proveri da li je BC nula
	or	c
	jr	nz,.clear_loop	; Ako nije nastavi za sva polja
	
	; Priprema prvog i poslednjeg reda:

	ld	de,start	; Adresa početnog reda na tabli	
	ld	hl,finish	; Adresa ciljnog reda na tabli
	inc	de		; Preskoči prvu kolonu početnog reda
	inc	hl		; Preskoči prvu kolonu ciljnog reda
	ld	b,16		; Spremi brojač srednjih kolona koji su ceo table
.fill_sf:
	ld	a,2		; Kod 0 - bezbedno polje na kome nema mine u startnom redu
	ld	(de),a		; Stavi kod za bezbedno polje u početni red
	ld	a,8		; Kod 8 - bezbedno polje na kome nema mine u ciljnom redu
	ld	(hl),a		; Stavi kod za bezbedno polje u ciljnom redu
	inc	de		; Sledeća kolona u početnom redu
	inc	hl		; Sledeća kolona u ciljnom redu
	djnz	.fill_sf	; Nastavi za sve kolone
		
	; Priprema glavog dela table:
	
	ld	hl,board	; Adresa prvog bajta glavnog dela table	
	ld	b,14		; Brojač redova glavnog dela table
.fill_row:
	inc	hl		; Preskoči krajnje levo polje
	ld	c,16		; Brojač kolona table na koje se stavlja simbol
.fill_col:
	ld	(hl),2		; Kod 2 - polje na kome igrač nije bio a može biti mina
	inc	hl		; Prelaz na sledeće polje
	dec	c		; Smanji brojač kolona
	jr	nz,.fill_col	; Nastavi za sve kolone
	inc	hl		; Preskoči krajnje desno polje
	djnz	.fill_row	; Nastavi za sve redove
	
	; Postavljanje inicijalne pozicije igrača:

	ld	hl,start	; Adresa početnog reda na tabli
	call	rnd_offset	; Generiši random ofset u DE
	add	hl,de		; Adresa na koju treba staviti igrača
	ld	(hl),1		; Kod 1 - simbol za igrača
	ld	(player_pos),hl	; Reset varijable sa pozicijom igrača
	
	; Kraj rutine:
.exit:
	pop	hl
	pop	de
	pop	bc
	pop	af
	ret
	
;------------------------------------------------------------------------------- 
; Generisanje glavnog dela table za igru, sakrivanje slučajno raspoređenih mina.
;------------------------------------------------------------------------------- 

hide_mines:

	push	af
	push	bc
	push	de
	push	hl
	
	; Raspoređivanje mina na tablu:
	
	ld	hl,board	; Adresa početnog reda dela table sa minama
	ld	b,14		; Brojač redova table sa minama

	; Rasporedi mine u svaki red, od 1 do 3 zavisno od izabrane težine igre:

.prepare_row:
	ld	a,(game_level)	; Učitaj nivo za težinu igre
.prepare_mine:
	call	rnd_offset	; Generiši random ofset u DE
	push	hl		; Sačuvaj poziciju početka reda
	add	hl,de		; Izračunaj poziciju mine
	ld	(hl),4		; Kod 4 - skrivena mina na izračunatu poziciju
	pop	hl		; Obnovi poziciju početka reda
	dec	a
	jr	nz,.prepare_mine

	ld	de,18		; Dodaj ofset za prelaz u sledeći red
	add	hl,de		; Pređi u sledeći red
	djnz	.prepare_row

	; Kraj rutine:

	pop	hl
	pop	de
	pop	bc
	pop	af
	ret

;------------------------------------------------------------------------------- 
; Zamena svih skrivenih mina vidljivim na kraju da se vidi gde su bile.
; Radi se na svim poljima, svejedno je jer se zamenjuju samo skrivene mine.
;------------------------------------------------------------------------------- 

show_mines:

	push	af
	push	bc
	push	de
	push	hl
	
	ld	hl,top		; Početna pozicija table
	ld	bc,324		; Brojač svih polja
.loop:
	ld	a,(hl)		; Uzmi trenutno polje
	cp	4		; Da li je tu skrivena mina?
	jr	nz,.skip	; Ako nije preskoči zamenu
	ld	(hl),5		; Ako jeste zameni vidljivom minom
.skip:
	inc	hl		; Sledeće polje za zamenu
	dec	bc		; Smanji brojač polja
	ld	a,b		; Proveri da li je BC nula
	or	c
	jp	nz,.loop	; Ako nije nastavi za sva polja
	
	pop	hl
	pop	de
	pop	bc
	pop	af
	ret
	
;------------------------------------------------------------------------------- 
; Generisanje random ofset u jednom redu u intervalu 1..16. Ofset je za
; srednjih 16 polja u redu od 18 polja, otuda je ofset 1..16 a ne 0..15. 
; Rezultat: DE - vrednost ofseta
;------------------------------------------------------------------------------- 

rnd_offset:

	push	af

.generate:
	call	generate_random	; Generiši random broj u A
	and	%00001111	; Ostavi samo donja četiri bita za ofset 0..15
	inc	a
	ld	d,0		; Pripremi ofset u DE
	ld	e,a

	pop	af
	ret

;-------------------------------------------------------------------------------
; Prikazuje nivo na LED ekranu.
;-------------------------------------------------------------------------------

show_level:

	push	af
	push	de
	push	hl
	
	ld	a,(game_level)	; Učitaj trenutni nivo
	dec	a		; Smanji A da se nivo pretvori u ofset
	ld	e,a		; Priprema ofseta u DE
	ld	d,0
	ld	hl,led_digits	; Početna adresa tabele sa definicijma cifara
	add	hl,de		; Pozicioniranje na potrebnu cifru
	ld	a,(hl)		; Učitaj izgled cifre za prikaz
	out	(0),a		; Prikaži na LED ekranu
.exit:
	pop	hl
	pop	de
	pop	af
	ret

;------------------------------------------------------------------------------- 
; Čekanje da se pritisne neki taster.
; Rezultat: A - kombinacija pritisnutih tastera (0=pritisnuto)
;------------------------------------------------------------------------------- 

read_keys:
	push	hl
	
	ld	hl,last_btns	; Adresa varijable gde se nalazi nova kombinacija tastera
.wait_keys:
	ld	a,(hl)		; Učitaj poslednju kombnaciju pritisnutih tastera
	cp	%11111111	; Da li ništa nije pritisnuto?
	jr	z,.wait_keys	; Ako nije nastavi da čekaš da se nešto pritisne
	ld	(hl),255	; Poništi last_btns kao indikaciju da je taster očitan

	pop	hl
	ret
	
;==============================================================================
; lib_random.asm
; Originally appeared as a post by Patrik Rak on WoSF.
;
; generateRandom - generates random number
; seedRandom - seeds random number generator
;===============================================================================

;------------------------------------------------------------------------------- 
; Generates random number.
;
; Input: 
;   NONE
; Output: 
;   A  - generated random number
;------------------------------------------------------------------------------- 

generate_random:

	push	hl
	push	de
	
_rnd:	ld	hl,0xA280   ; xz -> yw
	ld	de,0xC0DE   ; yw -> zt

	ld	(_rnd+1),de ; x = y, z = w
	ld 	a,e         ; w = w ^ ( w << 3 )
	add	a,a
	add	a,a
	add	a,a
	xor	e
	ld	e,a
	ld	a,h         ; t = x ^ (x << 1)
	add	a,a
	xor	h
	ld	d,a
	rra                 ; t = t ^ (t >> 1) ^ w
	xor	d
	xor	e
	ld	h,l         ; y = z
	ld	l,a         ; w = t
	ld	(_rnd+4),hl

	pop	de
	pop	hl
	ret
		
;------------------------------------------------------------------------------- 
; Seeds random number generator with R register. Not originally posted by
; Patrik Rak, added later by Ivan Glisin to provide different initial values. 
;
; Input: 
;   NONE
; Output: 
;   NONE
;------------------------------------------------------------------------------- 

seed_random:

	push	af
	ld	a,r
	ld	(_rnd+4),a
	pop	af
	ret

;------------------------------------------------------------------------------- 
; Smeštanje podataka.
;------------------------------------------------------------------------------- 

max_level:	equ	5	; Maksimalni nivo težine igre
game_level:	db	1	; Inicijalni i trenutni nivo težine igre
game_over:	db	0	; Indikator da je igra završena	
last_btns:	db	0	; Poslednja promena pritisnutih tastera (osvežava se samo pri promeni)
curr_btns:	db	0	; Trenutno stanje pritisnutih tastera (stalno se osvežava)
player_pos:	dw	0	; Trenutna pozicija igrača, adresa polja na tabli na kome se nalazi

led_digits:	db	%00000110 ; 1
		db	%01011011 ; 2
		db	%01001111 ; 3
		db	%01100110 ; 4
		db	%01101101 ; 5

sym_table:

border:	db	%00000000	; Kod 0 - polja oko table na koje se ne može stati
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000

player:	db	%01111110	; Kod 1 - simbol igrača
	db	%11110011
	db	%10110011
	db	%10111111
	db	%10111111
	db	%10110011
	db	%11110011
	db	%01111110
	
field:	db	%00000000	; Kod 2 - polja na kojima igrač nije bio
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	
path:	db	%10001000	; Kod 3 - polja na kojima je igrač bio i nema mine
	db	%00000000
	db	%00100010
	db	%00000000
	db	%10001000
	db	%00000000
	db	%00100010
	db	%00000000
	
h_mine:	db	%00000000	; Kod 4 - polja na kojima se nalazi skrivena mina
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000
	db	%00000000

v_mine:	db	%00000000	; Kod 5 - polja na kojima se nalazi mina za prikaz
	db	%00111100
	db	%01000010
	db	%01011010
	db	%01011010
	db	%01000010
	db	%00111100
	db	%00000000
	
rip:	db	%00000000	; Kod 6 - igrač je nagazio na minu
	db	%00001100
	db	%00001100
	db	%11111111
	db	%11111111
	db	%00001100
	db	%00001100
	db	%00000000
	
alive:	db	%01111110	; Kod 7 - stigao živ u ciljni red
	db	%11010011
	db	%10110011
	db	%10111111
	db	%10111111
	db	%10110011
	db	%11010011
	db	%01111110
	
safe:	db	%10001000	; Kod 8 - ciljni red na koji kada stane igra je gotova
	db	%00000000
	db	%00100010
	db	%00000000
	db	%10001000
	db	%00000000
	db	%00100010
	db	%00000000
	
block:	db	%01111100	; Kod 9 - blok za veliki tekst na uvodnom ekranu
	db	%11111110
	db	%11111110
	db	%11111110
	db	%11111110
	db	%11111110
	db	%01111100
	db	%00000000
		
	; Prostor za smeštanje table za igru i da se vidi struktura.
	; Tabela sa podacima je 18x18=324 polja, ali se igra u centralnih 16x16=256 polja.
	; Ovo je napravljeno tako da postoji nevidljivi red oko table, pa algoritam za
	; pomeranje po tabli i brojanje okolnih mina ne mora da ima izuzetke na ivicama
	; i u uglovima table, što pojednostavljuje kod:
	
top:	ds	18	; Gornji nevidljivi red u koji nije deo table
finish:	ds	18	; Ciljni red u koji treba stići u kome nema mina

	; Glavni deo table od 14 redova po 18 polja u kome se sakrivaju mine,
	; uključujući i nevidiljiva polja levo i desno koja su uvek 0.
	; Prosto je iskorišćen za uvodnu blok grafiku sa imenom igre.
	; Ukupni rezervisani prostor je 252 bajta (14 redova sa 18 polja):  

board:	db	0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	db	0,9,0,0,0,9,0,5,0,9,9,0,0,0,9,0,0,0
	db	0,9,9,0,9,9,0,0,0,9,0,9,0,9,0,9,0,0
	db	0,9,0,9,0,9,0,9,0,9,0,9,0,9,9,9,0,0
	db	0,9,0,0,0,9,0,9,0,9,0,9,0,9,0,0,0,0
	db	0,9,0,0,0,9,0,9,0,9,0,9,0,0,9,9,0,0
	db	0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
middle:	db	0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	db	0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
	db	0,9,9,9,0,5,0,0,9,0,0,9,0,0,0,9,0,0
	db	0,9,0,0,0,0,0,9,0,9,0,9,0,0,9,9,0,0
	db	0,9,9,9,0,9,0,9,9,9,0,9,0,9,0,9,0,0
	db	0,9,0,0,0,9,0,9,0,0,0,9,0,9,0,9,0,0
	db	0,9,0,0,0,9,0,0,9,9,0,9,0,0,9,9,0,0

start:	ds	18	; Startni red iz koga se kreće u kome nikada nema mina
bottom:	ds	18	; Donji nevidljivi red koji nije deo table
