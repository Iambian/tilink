import micropython
micropython.alloc_emergency_exception_buf(200)
from micropython import const
import uctypes,rp2,time,machine,random,array,collections,sys,os
from machine import Pin
from rp2 import PIO
import builtins
import gc

PACKET_DEBUG = True


def hex(value):
    if type(value) is int:
        return builtins.hex(value)
    if type(value) is str and len(value)>0:
        return str([builtins.hex(ord(i)) for i in value])
    if iter(value) and len(value) > 0:
        return str([builtins.hex(i) for i in value])
    return str([])

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

PIO0_BASE       = const(0x50200000)
PIO_CTRL        = const(0x0000)
PIO_CTRL_ENABLE = const(0)
PIO_CTRL_RESET  = const(4)
PIO_CTRL_CLKDIV_RESTART = const(8)
PIO_FSTAT       = const(0x0004)
PIO_RXFULL      = const(0)
PIO_RXEMPTY     = const(8)
PIO_TXFULL      = const(16)
PIO_TXEMPTY     = const(24)
PIO_FLEVEL      = const(0x000C)
PIO_TXF0        = const(0x0010)
PIO_RXF0        = const(0x0020)
PIO_IRQ         = const(0x0030)
PIO_IRQ_FORCE   = const(0x0034)
SM0_EXECCTRL    = const(0x00CC)
SM_EXEC_STALLED = const(31)
SM0_SHIFTCTRL   = const(0x00D0)
SM0_PINCTRL     = const(0x00DC)
SM0_ADDR        = const(0x00D4)
SM0_INSTR       = const(0x00D8)
PIO_IRQ0_INTE   = const(0x012C)

ATOMIC_NORMAL   = const(0x0000)
ATOMIC_XOR      = const(0x1000)
ATOMIC_OR       = const(0x02000)
ATOMIC_AND      = const(0x3000)

class PV(object):
    VAR = 0x06
    CTS = 0x09
    DATA = 0x15
    VER = 0x2D
    SKIP = 0x36
    ACK = 0x56
    ERR = 0x5A
    RDY = 0x68
    DEL = 0x88
    EOT = 0x92
    REQ = 0xA2
    RTS = 0xC9
    data = {0x06:"VAR",0x15:"DATA",0x36:"SK/E",0x88:"DEL",0xA2:"S-REQ",0xC9:"RTS"}
    bare = {0x09:"CTS",0x2D:"VER",0x56:"ACK",0x5A:"ERR",0x68:"RDY",0x6D:"SCR",0x92:"EOT"}
    
    def __init__(self,macid,cmdid,data=bytearray()):
        self.mid = macid
        self.cid = cmdid
        self.data = data
        if data:
            self.size = len(data)
            self.chksum = sum(data)
        else:
            self.size = 0
            self.chksum = 0

    def tobytes(self):
        a1 = bytearray([self.mid,self.cid,self.size & 255,(self.size>>8)*256])
        if self.data:
            return a1+bytearray(data)+bytearray([self.chksum&255,(self.chksum>>8)*256])
        else:
            return a1

    @classmethod
    def packettype(cls,cmdid):

class VID(object):
    REAL = 0x00
    LIST = 0x01
    MATR = 0x02
    YVAR = 0x03
    STR  = 0x04
    PROG = 0x05
    PROT = 0x06
    PIC  = 0x07
    GDB  = 0x08
    WIN1 = 0x0B
    CPLX = 0x0C
    CLST = 0x0D
    WNS2 = 0x0F
    SWNS = 0x10
    TSET = 0x11
    BAK  = 0x13
    DELF = 0x14
    AVAR = 0x15
    GRP  = 0x17
    DIR  = 0x19
    OS   = 0x23
    APP  = 0x24
    IDL  = 0x26
    CERT = 0x27
    CLK  = 0x29
    tostrdict = { 0x00 : "REAL",0x01 : "LIST",0x02 : "MATR",0x03 : "YVAR",0x04 : "STR ",0x05 : "PROG",0x06 : "PROT",0x07 : "PIC ",0x08 : "GDB ",0x0B : "WIN1",0x0C : "CPLX",0x0D : "CLST",0x0F : "WNS2",0x10 : "SWNS",0x11 : "TSET",0x13 : "BAK ",0x14 : "DELF",0x15 : "AVAR",0x17 : "GRP ",0x19 : "DIR ",0x23 : "OS  ",0x24 : "APP ",0x26 : "IDL ",0x27 : "CERT",0x29 : "CLK " }
    @classmethod
    def tostring(cls,value):
        if value in cls.tostrdict:
            return cls.tostrdict[value]
        else:
            return "!"+hex(value)






class TISERIAL(object):
    # PIO initializations
    PININIT = (PIO.OUT_LOW,PIO.OUT_LOW)
    PIOINIT = {
        'out_init':PININIT, 'set_init':PININIT,'sideset_init':PININIT,
        'autopull': True, 'pull_thresh': 8,
        'autopush': True, 'push_thresh': 8,
    }
    @rp2.asm_pio(**PIOINIT)
    def pio():
        wrap_target()
        label("0")
        mov(osr, pins)          .side(0)      # 0
        out(x, 1)               .side(0)      # 1
        jmp(not_x, "7")         .side(0)      # 2
        jmp(pin, "0")           .side(0)      # 3
        wait(1, pin, 1)         .side(1)      # 4
        wait(1, pin, 0)         .side(0)      # 5
        jmp("11")                             # 6
        label("7")
        jmp(pin, "9")           .side(0)      # 7
        jmp("21")               .side(0)      # 8
        label("9")
        wait(1, pin, 0)         .side(2)      # 9
        wait(1, pin, 1)         .side(0)      # 10
        label("11")
        in_(x, 1)               .side(0)      # 11
        jmp("0")                .side(0)      # 12
        label("13")
        out(x, 1)               .side(0)      # 13
        jmp(not_x, "17")        .side(0)      # 14
        wait(0, pin, 0)         .side(2)      # 15
        jmp("19")               .side(0)      # 16
        label("17")
        wait(0, pin, 1)         .side(1)      # 17
        wait(1, pin, 0)         .side(0)      # 18
        label("19")
        wait(1, pin, 1)         .side(0)      # 19
        jmp("13")               .side(0)      # 20
        label("21")
        jmp("21")               .side(0)      # 21
        wrap()
    pio[3] |= 1 << 29    #Sets sideset mode to pindirs.

    statemachines = dict()  #Contains all initialized state machines

    def __init__(self,statemachine = -1, basepin = -1):
        #Check if we already instantiated this. If so, reuse, else init.
        if statemachine == -1:
            for i in range(4):
                if i not in TISERIAL.statemachines:
                    break
            else:
                raise Exception("No more state machines left to allocate.")
            TISERIAL.statemachines[i] = self
            statemachine = i    #Set statemachine to first one found.
        else:
            if statemachine in TISERIAL.statemachines:
                self = TISERIAL.statemachines[statemachine]
                return
            else:
                TISERIAL.statemachines[statemachine] = self
        self.id = statemachine & 3
        self.core = (statemachine & 8) >> 3     #NOT IMPLEMENTED. FOR FUTURE USE
        if basepin < 0:
            basepin = self.id * 2 + (8 if self.core else 0)
        pin0 = machine.Pin(basepin+0,mode=Pin.IN, pull=Pin.PULL_UP)
        pin1 = machine.Pin(basepin+1,mode=Pin.IN, pull=Pin.PULL_UP)
        SMINIT = {
            'freq': 750000,
            'in_base': pin0, 'set_base': pin0, 'sideset_base': pin0, 'jmp_pin': pin1,
            'in_shiftdir': PIO.SHIFT_RIGHT, 'out_shiftdir': PIO.SHIFT_RIGHT,
        }
        self.sm = rp2.StateMachine(statemachine,TISERIAL.pio,**SMINIT)
        self.pio_offset = TISERIAL.pio[2 if self.core else 1]
        self.smstop = self.pio_offset + len(TISERIAL.pio[0]) - 1
        self.smrx   = self.pio_offset + 0
        self.smtx   = self.pio_offset + 13  #From tx occurance of 'out x,1'
        self.rxbuf  = bytearray(16)
        self.rxbhead = 0
        self.rxbtail = 0

        self.restart()

    def piobase(self):
        return 0x503000C8 if self.core else 0x502000C8
    #Returns address based on sm0 offset. Valid for CLKDIV to PINCTRL.
    def smreg(self,sm0offset):
        return (0x503000C8 if self.core else 0x502000C8) + 0x18*self.id
    #Returns fifo address
    def tx_fifo(self,value):
        machine.mem32[(0x50300010 if self.core else 0x50200010) + 4 * self.id] = value
    def rx_fifo(self):
        return machine.mem32[(0x50300010 if self.core else 0x50200010) + 4 * self.id]

    def restart(self):
        machine.mem32[self.smreg(SM0_INSTR)] = 0x1F  #Halts state machine
        machine.mem32[self.piobase()+PIO_CTRL] = 1 << PIO_CTRL_RESET
        machine.mem32[self.smreg(SM0_INSTR)] = self.smrx

    def get(self,timeout_ms = -1):
        starttime = time.ticks_ms()
        #If in tx mode, set to rx mode and proceed to wait for incoming data
        if machine.mem32[self.smreg(SM0_ADDR)] >= self.smtx:
            machine.mem32[self.smreg(SM0_INSTR)] = self.smrx
        #Wait for incoming data
        while True:
            if time.ticks_diff(time.ticks_ms(),starttime) > timeout_ms:
                self.restart()
                return -1
            if not machine.mem32[self.piobase()+PIO_FSTAT] & (1 << (PIO_RXEMPTY+self.id)):
                return self.rx_fifo()

    def put(self,timeout_ms = -1):
        starttime = time.ticks_ms()
        #Check to see if we're in receive mode. If so, switch to transmit mode
        if machine.mem32[self.smreg(SM0_ADDR)] < self.smtx:
            machine.mem32[self.smreg(SM0_INSTR)] = self.smtx
        #If tx is full, start the timeout process
        if machine.mem32[self.piobase()+PIO_FSTAT] & (1 << (PIO_TXFULL+self.id)):
            starttime = time.ticks_ms()
            while True:
                if time.ticks_diff(time.ticks_ms(),starttime) > timeout_ms:
                    self.restart()
                    return -1
        return 0
        

class TIPROTO(TISERIAL):
    def __init__(self,*args,**kwargs):
        super(TIPROTO,self).__init__(*args,**kwargs)


    def getpacket(self):


    
def emugraylink():
    import micropython,select,sys
    print("Begin graylink emulation. REPL being disabled.")
    micropython.kbd_intr(-1)     #Allows stdin/out to be used as terminal
    while True:
        while sys.stdin in select.select([sys.stdin], [],[],0)[0]:
            c = sys.stdin.buffer.read(1)
            TILINK.sendchunk(c)
        else:
            c = TILINK.get(-1)
            if c > -1:
                sys.stdout.buffer.write(bytes([c]))


def help():
    print("Helpful notes:")
    print("t = TILINK")
    print("Available functions for using TILINK:")
    print("t.protocol_recvar()")
    print("t.getvarlist(reportonly = -1)")
    print("t.findvar(name,type = VID.PROG)")
    print("t.getvar(nameorvardat,type = -1)")
    print("t.sendvar(varheader,vardata)")
    print("t.delvar(varheader)")
    print("t.sendvar(*t.fromfile(name))")
    print("emugraylink() -- Begin graylink emulator")
help()
