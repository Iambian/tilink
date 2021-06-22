.program TILINK_RECEIVE2
.side_set 2 opt
;Config IN map to 2 pins. MOV and WAIT uses this mapping
;Lines can only go low. Going high requires both devices to go high
;Use this fact to cooperatively side-set in the manner calc does.
;
    jmp receive2_loop
recieve2_error:
    irq wait 0              ;halt. calling routine should reset this
receive2_get1:              ;white was low
    wait 1 pin, 1 side 0b10 ;bring red low, wait for white to go hi
    set x,1       side 0b11 ;bring red high again.
    jmp recieve2_return
receive2_get0:              ;red was low
    wait 1 pin, 0 side 0b01 ;bring white low, wait for red to go hi
    set x,0       side 0b11 ;bring white high again.
recieve2_return:
    in x,1                  ;move bit set in recv0/1 into ISR.
.wrap_target
receive2_loop:
    mov x,pins
    jmp x--, recieve2_error ;if 00, error condition
    jmp x--, receive2_get1  ;if 01 (white low), receive 1
    jmp x--, receive2_get0  ;if 10 (red low), receive 0
    ;otherwise continue looping until a bit is being received
.wrap


.program TILINK_XMIT
.side_set 2 opt
;Config IN map to 2 pins. MOV and WAIT uses this mapping
;Lines can only go low. Going high requires both devices to go high
;Use this fact to cooperatively side-set in the manner calc does.

.wrap_target
xmit_sendagain:
    out x,1                 ;get one bit from OSR. Stalls if empty
    jmp x--,xmit_send0      ;was 0, send 0.
xmit_send1:
    wait 0 pin, 0 side 0b01 ;white goes low, wait for red to go low
    wait 1 pin, 0 side 0b11 ;bring white high, wait for red to go hi
    jmp xmit_sendagain
xmit_send0:
    wait 0 pin, 1 side 0b10 ;red goes low, wait for white to go low
    wait 1 pin, 1 side 0b11 ;bring red high, wait for white to go hi
.wrap