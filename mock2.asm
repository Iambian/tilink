.program TILINK3
.side_set 2 opt pindirs

;set,sideset,in,out pins all point to the same base, whatever that may be.
;pin 0 = red wire , pin 1 = white wire. Assume dbus protocol
;in and out shiftdir are to be set to right.
;pull and push threshold is 8.

;Receiving is passive after starting mainloop. Data will appear on in FIFO
;Transmit by JMP START, put data on out FIFO, then JMP MAINLOOP.
;
start:
    jmp start           ;halts state machine until further instructions provided
startwait:
    set y,7
    irq wait 0          ;
mainloop:
    jmp !OSRE, xmitstart
recvstart:
    mov osr, pins
    out x,1
    out null, 32        ;clears OSR for mainloop
    jmp !x, get0
    jmp pin, mainloop
get1:
    wait 1, pin 1 side 1
    wait 1, pin 0 side 0
    jmp recvcont
get0:
    jmp pin, get0cont
    jmp error
get0cont:
    wait 1, pin 0 side 2
    wait 1, pin 1 side 0
recvcont:
    in x,1
    jmp y--,recvstart
    jmp startwait

;19 instructions so far
xmitstart:
    set y,7             ;loops 8 times
xmitloop:
    out x,1
    jmp !x, send0
send1:
    wait 0, pin 0 side 2
    wait 1, pin 0 side 0
    jmp xmitend
send0:
    wait 0, pin 1 side 1
    wait 1, pin 1 side 0
xmitend:
    jmp x--, xmitloop
    jmp startwait

error:
    jmp error
;11 instructions this segment. 2 words free.






