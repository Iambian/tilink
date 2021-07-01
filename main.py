
import uctypes,rp2,time,machine
from machine import Pin
from rp2 import PIO

def decode_pio(uint16_val, sideset_bits = 0, sideset_opt = False):
    def di(fbv):    return str(fbv&7)+(" REL" if fbv&16 else "")
    u=uint16_val
    o,ssb,sso,i,df,ss,ssg,z = (u&255,sideset_bits,sideset_opt==True,u>>13&7,u>>8&31,0,0,"###")
    if ssb:
        b=ssb+sso
        de=df&(1<<5-b)-1
        if sso and df&16:   df,ssg=(df&15,1)
        elif not sso:       ssg=1
        ss=df>>5-b
    else:   ss,de=(0,df)
    c,d=(o>>5&7,o&31)
    if i==0:    s="JMP "+("","!X ","X-- ","!Y ","Y-- ","X!=Y ","PIN ","!OSRE ")[c]+hex(d)
    elif i==1:  s="WAIT "+str(o>>7&1)+(" GPIO "," PIN "," IRQ ",z)[c&3]+str(d) if c&3^2 else di(d)
    elif i==2:  s="IN "+("PINS ","X ","Y ","NULL ",z,z,"ISR "," OSR ")[c]+str(d)
    elif i==3:  s="OUT "+("PINS ","X ","Y ","NULL ","PINDIRS ","PC ","ISR "," EXEC ")[c]+str(d)
    elif i==4:
        s,n=("PULL ",("","IFEMPTY ")) if o>>7%1 else ("PUSH ",("","IFFULL "))
        s+=n[o>>6&1]+("NO","")[o>>5&1]+"BLOCK"
    elif i==5:
        if c==2 and c==d:   s="NOP "
        else:   s="MOV "+("PINS ","X ","Y ",z,"EXEC ","PC ","ISR ","OSR ")[c]+("","~","::",z)[o>>3&3]+("PINS","X","Y","NULL",z,"STATUS","ISR","OSR")[o&7]
    elif i==6:
        q=o>>6&1
        w=o>>5&1 if q==0 else 0
        s="IRQ "+(" ","WAIT ")[w]+(" ","CLEAR ")[q]+di(d)
    elif i==7:  s="SET "+("PINS ","X ","Y ",z,"PINDIRS",z,z,z)[c]+str(d)
    else: s=z
    if ssg: s+=" SIDE "+str(ss)
    if de:  s+=" ["+str(de)+"]"
    return s

PIO0_BASE = 0x50200000
PIO_IRQ = 0x0030
PIO_IRQ_FORCE = 0x0034
SM0_EXECCTRL = 0x00CC
SM0_PINCTRL = 0x00DC
SM0_ADDR = 0x00D4
SM0_INSTR = 0x00D8
PIO_IRQ0_INTE = 0x012C

ATOMIC_NORMAL = 0x0000
ATOMIC_XOR = 0x1000
ATOMIC_OR = 0x02000
ATOMIC_AND = 0x3000

class TILINK(object):
    print("Loading class...")
    #Reimport due to some sort of uploading silliness
    pin0 = Pin(0)

    INIT_ASM_STATE = {
        'out_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'set_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'sideset_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'autopull' : False,
        'pull_thresh' : 8,
        'autopush' : True,
        'push_thresh' : 8
    }

    INIT_SM_STATE = {
        'freq' : 100000,
        'in_base' : pin0,
        'sideset_base' : pin0,
        'set_base' : pin0,
        'in_shiftdir' : PIO.SHIFT_RIGHT,
        'out_shiftdir' : PIO.SHIFT_LEFT,
        'push_thresh' : 8,
        'pull_thresh' : 8
    }
    @rp2.asm_pio(**INIT_ASM_STATE)
    def tilink_pio():
        label("start")
        jmp("start").side(0)    #08 waitloop. Also ensure pins are high
        set(y,7)
        jmp(not_osre,"xmit")
        #------------------------------

        label("rcv")
        mov(osr,pins)   #0B get pins into OSR, to allow testing one at a time
        out(null,30)    #discard upper 30 bits
        out(x,1)        #Test white pin
        jmp(not_x,"get1")   #White low. See if we can receive a '1'
        out(x,1)        #Test red pin
        jmp(not_x,"get0")   #Red low. We are receving a '0'
        jmp("rcv")

        label("get1")
        out(x,1)        #12
        jmp(not_x,"error")
        wait(1,pin,1)   .side(1)   #assert red low, wait for white high
        set(x,1)        .side(0)   #deassert red, white is high
        wait(1,pin,0)   .side(0)   #wait for red to go back high
        jmp("rcvcont")

        label("get0")   #18
        wait(1,pin,0)   .side(2)   #assert white low, wait for red high
        set(x,0)        .side(0)   #deassert white, red is high
        wait(1,pin,1)   .side(0)   #wait for white to go back high

        label("rcvcont")    #1B
        in_(x,1)                  #shift bit into ISR
        jmp(y_dec,"rcv")          #when out of bits, go back to start and wait
        jmp("start")              #else go back to receive loop
        #------------------------------
        '''
        label("send1")
        wait(0,pin,0)   .side(2)    #Assert white low, wait for red to go low too
        wait(1,pin,0)   .side(0)    #Deassert white, wait for red to go back high

        label("xmitcont")
        jmp(y_dec,"start")          #when sent all bits, go back to start and wait
        '''

        label("xmit")       #1E
        jmp("xmit")
        '''
        out(x,1)                    #get bit from OSR
        jmp(x_dec,"send1")
        label("send0")

        wait(0,pin,1)   .side(1)    #Assert red low, wait for white to go low too
        wait(1,pin,1)   .side(0)    #Deassert red, wait for white to go back high
        jmp("xmitcont")
        '''

        label("error")      #1F
        jmp("error")

    print(str(tilink_pio))
    tilink_pio[3] |= 1 << 29
    tilink_sm = rp2.StateMachine(0,tilink_pio,**INIT_SM_STATE)
    tilink_sm.restart()
    tilink_sm.active(True)
    time.sleep_ms(100)
    tilink_start_instr = machine.mem32[PIO0_BASE+SM0_INSTR] #Should be jmp [...]
    tilink_exec_begin = tilink_start_instr+1    #Increment address field

    #Returns False if idle, True if still executing
    @staticmethod
    def is_running():
        return machine.mem32[PIO0_BASE+SM0_INSTR] != TILINK.tilink_start_instr

    @staticmethod
    def run_now():
        machine.mem32[PIO0_BASE+SM0_INSTR] = TILINK.tilink_exec_begin
        return

    #Returns 0 on success, -1 on timeout
    @classmethod
    def put(cls,databyte):
        curtime = time.ticks_ms()
        while cls.is_running():
            if time.ticks_diff(time.ticks_ms(),curtime) > 2000:
                return -1
        cls.tilink_sm.put(databyte)
        cls.run_now()
        return 0

    #Returns [0x00-0xFF] on success, -1 on timeout
    @classmethod
    def get(cls):
        curtime = time.ticks_ms()
        while cls.is_running():
            if time.ticks_diff(time.ticks_ms(),curtime) > 2000:
                return -1
            print(decode_pio(machine.mem32[PIO0_BASE+SM0_INSTR]))
        cls.run_now()   #Start the machine in receive mode
        return cls.tilink_sm.get()

        

#Current test: Recieve data
def test():
    t = TILINK
    value = t.get()
    if (value == -1):
        print("Error: Link Timeout")
    else:
        print("Byte received: "+hex(value))
def debug():
    print("Start instruction: "+decode_pio(TILINK.tilink_start_instr,2,True))
    print(decode_pio(machine.mem32[PIO0_BASE+SM0_INSTR],2,True))
    print("Is stalled? "+str(True if machine.mem32[PIO0_BASE+SM0_INSTR]>>31&1 else False))
def reset():
    TILINK.tilink_sm.restart()
    TILINK.tilink_sm.active(True)
    machine.mem32[PIO0_BASE+SM0_INSTR] = TILINK.tilink_start_instr
def run(instr):
    i = rp2.asm_pio_encode(instr,2)
    machine.mem32[PIO0_BASE+SM0_INSTR] = i
def get():
    print(str(TILINK.get()))
def testloop():
    while True:
        test()






