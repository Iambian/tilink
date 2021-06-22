import uctypes
import rp2
import time
from machine import Pin
from rp2 import PIO

## TODO: REVERSE BITTINGS OF SIDESET BECAUSE 1=OUT, 0=IN. WHEN IN, DRIVES LINE HIGH
#Try to configure pins to open-drain state
INIT_ASM_STATE = {
    'out_init' : (PIO.IN_HIGH,PIO.IN_HIGH),
    'sideset_init' : (PIO.IN_HIGH,PIO.IN_HIGH),
    'autopull' : True,
    'pull_thresh' : 8,
    'autopush' : True,
    'push_thresh' : 8
}
#Configure output mode to low. When pin is sent to input mode, hi-z makes it go hi
pin0 = Pin(0,mode=Pin.OUT,value=0)
pin1 = Pin(1,mode=Pin.OUT,value=0)
pin0 = Pin(0,mode=Pin.IN)
pin1 = Pin(1,mode=Pin.IN)

#Note: Inverted sideset bits to comply with open-drain method
@rp2.asm_pio(**INIT_ASM_STATE)
def ti_rx():
    jmp("ti_rxstart")
    label("ti_rxerr")
    irq(block,0)
    label("ti_rxget1")
    wait(1,pin,1)      .side(1)
    set(x,1)           .side(0)
    jmp("ti_rxret")
    label("ti_rxget0")
    wait(1,pin,0)      .side(2)
    set(x,0)           .side(0)
    label("ti_rxret")
    in_(x,1)
    wrap_target()
    label("ti_rxstart")
    mov(x,pins)
    jmp(x_dec,"ti_rxerr")
    jmp(x_dec,"ti_rxget1")
    jmp(x_dec,"ti_rxget0")
    wrap()

#Note: Inverted sideset bits to comply with open-drain method
@rp2.asm_pio(**INIT_ASM_STATE)
def ti_tx():
    #label("ti_txerr")
    #irq(block,1)
    wrap_target()
    label("ti_txstart")
    out(x,1)
    jmp(x_dec,"ti_tx0")
    label("ti_tx1")
    wait(0,pin,0)       .side(2)
    wait(1,pin,0)       .side(0)
    jmp("ti_txstart")
    label("ti_tx0")
    wait(0,pin,1)       .side(1)
    wait(1,pin,1)       .side(0)
    wrap()

#Manual configure of PIO routines. See rp2.py for use of constants.
ti_tx[3] |= 1 << 29     #Sets bit SIDE_PINDIR of reg EXECCTRL
ti_rx[3] |= 1 << 29     #Sets bit SIDE_PINDIR of reg EXECCTRL

#Configure state machines
INIT_SM_STATE = {
    'freq' : 100000,
    'in_base' : pin0,
    'sideset_base' : pin0,
    'set_base' : pin0,
    'in_shiftdir' : None,
    'out_shiftdir' : None,
    'push_thresh' : 8,
    'pull_thresh' : 8
}

pio = rp2.PIO(0)
sm_rx = rp2.StateMachine(0,ti_rx,**INIT_SM_STATE)
sm_tx = rp2.StateMachine(1,ti_tx,**INIT_SM_STATE)

getmem = list(uctypes.bytes_at(0x50200000 + 0x0EC, 32*4))
getints = [0]*int(len(getmem)/4)
for power in range(4):
    for i in range(len(getints)):
        getints[i] += getmem[power::4][i]<<(8*power)
print(str([hex(i) for i in getints]))


def init_tilink():
    pass

#Returns 0 for success, -1 for timeout error
def ti_sendbyte(octet):
    global sm_rx,sm_tx
    #Will put in proper blocking later. Requires access to OSR state.
    sm_rx.active(False)
    sm_tx.restart()
    sm_tx.put(octet)
    return 0

#Returns received byte for success, -1 for timeout error
def ti_getbyte():
    global sm_rx,sm_tx
    #Will put in proper blocking later. Requires access to OSR state.
    sm_tx.active(False)
    sm_rx.restart()
    return sm_rx.get()




'''
sendbytes = [0x23,0x87,0xA6,0x00]   #Command: Key "M"
for i in sendbytes:
    ti_sendbyte(i)
    pass
print("Data sent")
time.sleep(3)

bytesgot = []
for i in range(8):
    #bytesgot.append(ti_getbyte())    #Get acknowledgement
    pass
print("Data received")
print(str(bytesgot))
'''

pin0 = Pin(0,mode=Pin.OUT,value=0)
pin1 = Pin(1,mode=Pin.OUT,value=0)
print("Pins now low")
input()
pin0 = Pin(0,mode=Pin.IN)
pin1 = Pin(1,mode=Pin.IN)
print("Pins brought high again")
input()
print("Program ended")
