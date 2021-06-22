import uctypes,rp2,time,machine
from machine import Pin
from rp2 import PIO

INIT_ASM_STATE = {
    'out_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
    'set_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
    'sideset_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
    'autopull' : True,
    'pull_thresh' : 8,
    'autopush' : True,
    'push_thresh' : 8
}

pin0 = Pin(0)

@rp2.asm_pio(**INIT_ASM_STATE)
def test_pio():
    wrap_target()
    nop()
    wait(0,pin,1).side(0)   #waits until white goes low, no assert
    wait(1,pin,1).side(0)   #wait until white goes high again, no assert
    wait(0,pin,0).side(2)   #wait until red goes low, assert white low.
    wait(1,pin,0).side(0)   #wait until red goes high, no assert
    wrap()

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
test_pio[3] |= 1 << 29  #set sideset mode to pindirs

sm_test = rp2.StateMachine(0,test_pio,**INIT_SM_STATE)
sm_test.restart()
sm_test.active(True)

PIO0_BASE = 0x50200000
PIO_IRQ = 0x0030
SM0_EXECCTRL = 0x00CC
SM0_PINCTRL = 0x00DC
SM0_ADDR = 0x00D4
SM0_INSTR = 0x00D8
ATOMIC_NORMAL = 0x0000
ATOMIC_XOR = 0x1000
ATOMIC_OR = 0x02000
ATOMIC_AND = 0x3000

def decode_pio(uint16_val, sideset_bits = 0, sideset_opt = False):
    def decode_index(five_bit_value):
        s = str(five_bit_value & 7)
        if five_bit_value & 16:
            s += " REL"
        return s
    instr = (uint16_val >> 13) & 7
    delay_field = (uint16_val >> 8) & 31
    sidesetting = False
    if sideset_bits:
        bitting = sideset_bits + sideset_opt
        delay = delay_field & ((1 << (5-bitting)) - 1)
        if sideset_opt:
            if delay_field & 16:
                delay_field &= 15   #Clear sideset opt bit so the shift below...
                sidesetting = True
        else:
            sidesetting = True
        sideset = delay_field >> (5-bitting) #... does not contribute to the value
    else:
        sideset = 0
        delay = delay_field
    other = uint16_val & 255
    pushpullsel = (other >> 7) & 1
    output = ""
    if instr == 0:
        cond = (other >> 5) & 7
        output += "jmp "
        output += ["","!X ","X-- ","!Y ","Y-- ","X!=Y ","PIN ","!OSRE "][cond]
        output += hex(other&31)
    elif instr == 1:
        source = (other >> 5) & 3
        polarity = (other >> 7) & 1
        index = other & 31
        output += "wait " + str(polarity) + " " #encode polarity
        output += ["GPIO ","PIN ","IRQ ","<<ILLEGALSRC>>"][source]
        if source != 2:
            output += str(index)
        else:
            output += decode_index(index)
    elif instr == 2:
        source = (other >> 5) & 7
        bitcount = other & 31
        output += "IN "
        output += ["PINS ","X ","Y ","NULL ","<<ILLEGALSRC>>","<<ILLEGALSRC>>","ISR "," OSR "][source]
        output += str(bitcount)
    elif instr == 3:
        destination = (other >> 5) & 7
        bitcount = other & 31
        output += "OUT "
        output += ["PINS ","X ","Y ","NULL ","PINDIRS ","PC ","ISR "," EXEC "][destination]
        output += str(bitcount)
    elif (instr == 4) and (pushpullsel == 0):
        iffull = (other >> 6) & 1
        block  = (other >> 5) & 1
        output += "PUSH "
        output += ["","IFFULL "][iffull]
        output += ["NOBLOCK","BLOCK"][block]
    elif (instr == 4) and (pushpullsel == 1):
        ifempty = (other >> 6) & 1
        block  = (other >> 5) & 1
        output += "PULL "
        output += ["","IFEMPTY "][ifempty]
        output += ["NOBLOCK","BLOCK"][block]
    elif instr == 5:
        destination = (other >> 5) & 7
        oper = (other >> 3) & 3
        source = other & 7
        output += "MOV "
        output += ["PINS ","X ","Y ","<<ILLEGALDEST>>","EXEC ","PC ","ISR ","OSR "][destination]
        output += ["","~","::","<<ILLEGALOP>>"][oper]
        output += ["PINS","X","Y","NULL","<<ILLEGALSRC>>","STATUS","ISR","OSR"][source]
    elif instr == 6:
        clear = (other >> 6) & 1
        wait = (other >> 5) & 1 if clear == 0 else 0
        index = other & 31
        output += "IRQ "
        output += [" ","WAIT "][wait]
        output += [" ","CLEAR "][clear]
        output += decode_index(index)
    elif instr == 7:
        destination = (other >> 5) & 7
        data = other & 31
        si = "<<ILLEGALDAT>> "
        output += "SET "
        output += ["PINS ","X ","Y ",si,"PINDIRS ",si,si,si][destination]
        output += str(data)
    else:
        output = "NODECODE"
    #
    if sidesetting:
        output += " SIDE "+str(sideset)
    if delay:
        output += " ["+str(delay)+"]"
    return output

retrycount = 0
while True:
    data = machine.mem32[PIO0_BASE+SM0_INSTR]
    addr = machine.mem32[PIO0_BASE+SM0_ADDR]
    exctrl = machine.mem32[PIO0_BASE+SM0_EXECCTRL]
    pictrl = machine.mem32[PIO0_BASE+SM0_PINCTRL]
    instr = decode_pio(data,(pictrl >> 26) & 7,True if exctrl & (1<<30) else False)
    print(" Instr, PC, execreg, retry"+str([instr,hex(addr),hex(exctrl),hex(retrycount)]),end="\r")
    time.sleep_ms(200)
    retrycount += 1









