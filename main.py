
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

class PACKET(PV):
    data = {0x06:"VAR",0x15:"DATA",0x36:"SK/E",0x88:"DEL",0xA2:"S-REQ",0xC9:"RTS"}
    bare = {0x09:"CTS",0x2D:"VER",0x56:"ACK",0x5A:"ERR",0x68:"RDY",0x6D:"SCR",0x92:"EOT"}
    def __init__(self,macid,cmdid,data=bytearray()):
        self.mid = macid
        self.cid = cmdid
        self.data = data
        if data:
            s,c = (len(data),sum(data))
        else:
            s,c = (0,0)
        self.size_lsb = s & 255
        self.size_msb = (s >> 8) & 255
        self.chksum_lsb = c & 255
        self.chksum_msb = (c >> 8) & 255
        self.name = self.getname(self.cid)
        self.base = bytearray([self.mid, self.cid, self.size_lsb, self.size_msb])

    def tobytes(self):
        if self.data:
            return self.base + bytearray(self.data) + bytearray( [self.chksum_lsb, self.chksum_msb])
        else:
            return self.base

    def tobytesgen(self):
        for i in self.base:
            yield i
        if self.data:
            for i in self.data:
                yield i

    @classmethod
    def getname(cls,cid):
        packettype = cls.gettype(cid)
        if packettype < 0:
            return "UNK ({:02X})".format(packettype)
        elif packettype:
            return cls.data[cid]
        else:
            return cls.bare[cid]

    #0 == bare, 1 == contains data, -1 == unknown
    @classmethod
    def gettype(cls,cid):
        if cid in cls.bare:
            return 0
        elif cid in cls.data:
            return 1
        else:
            return -1

    @classmethod
    def formheader(cls,ftype, fname, isarchived = False, ver1 = 0, ver2 = 0):
        #Create the header necessary for the data represented.
        #TODO: Also consider supporting backup and FLASH headers
        pass

    

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


#Create header object which can return compact notation but also retains
#easy-to-retrieve data such as types.
#Alternative constructor format allows you to import packet data and
#the class will init an instance with easy-to-retrieve data filled out
class HEADER(object):
    def __init__(self, ftype_or_packetdata, fname = None, size = 0, isarc = 0, ver1 = 0, ver2 = 0):
        if fname is None:
            self = self.__class__.fromheader(ftype_or_packetdata)
        else:
            self.ftype = ftype_or_packetdata
            self.fname = fname
            self.isarc = True if isarc else False
            self.ver1  = ver1
            self.ver2  = ver2
            self.size  = size

    def toheader(self):
        if self.ftype > 0x22 and self.ftype < 0x28:
            raise Exception("Creating flash header not supported")
        elif self.ftype == 0x13:
            raise Exception("Creating backup header not supported")
        else:
            b = bytearray(13)
            b[:2] = (self.size&255, (self.size>>8)&255 )
            b[2]  = self.ftype
            b[3:len(self.fname)] = self.fname.encode('ascii')
            b[11] = self.ver1
            b[12] = self.ver2&127 + (128 if self.isarc else 0)
        return b

    #Alternate constructor that creates a HEADER object from the data
    #of a VAR packet
    @classmethod
    def fromheader(cls,packet):
        header = packet.data
        t = header[2]
        if t > 0x22 and t < 0x28:
            raise Exception("Reading flash header not supported")
        elif t == 0x13:
            raise Exception("Reading backup header not supported")
        else:
            s = header[0]+header[1]*256
            n = header[3:11].decode().strip('\x00')
            a = True if header[12] & 128 else False
            v1= header[11]
            v2= header[12] & 127
            obj = cls.__new__(cls)
            obj.__init__(t,n,s,a,v1,v2)
            return obj
        

''' 
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
'''
class TISERIAL(object):
    # PIO initializations
    PININIT = (PIO.OUT_LOW,PIO.OUT_LOW)
    PIOINIT = {
        'out_init':PININIT, 'set_init':PININIT,'sideset_init':PININIT,
        'autopull': False, 'pull_thresh': 8,
        'autopush': True, 'push_thresh': 8,
    }
    @rp2.asm_pio(**PIOINIT)
    def pio():
        wrap_target()
        label("0")
        set(y, 7)               .side(0)      # 0
        label("1")
        mov(x, status)          .side(0)      # 1
        jmp(not_x, "22")                      # 2
        mov(osr, pins)          .side(0)      # 3
        out(x, 1)                             # 4
        jmp(not_x, "10")                      # 5
        jmp(pin, "1")                         # 6
        label("7")
        wait(1, pin, 1)         .side(1)      # 7
        wait(1, pin, 0)         .side(0)      # 8
        jmp("14")                             # 9
        label("10")
        jmp(pin, "12")                        # 10
        jmp("31")                             # 11
        label("12")
        wait(1, pin, 0)         .side(2)      # 12
        wait(1, pin, 1)         .side(0)      # 13
        label("14")
        in_(x, 1)                             # 14
        jmp(y_dec, "17")                      # 15
        jmp("0")                              # 16
        label("17")
        mov(osr, pins)                        # 17
        out(x, 1)                             # 18
        jmp(not_x, "10")                      # 19
        jmp(pin, "17")                        # 20
        jmp("7")                              # 21
        label("22")
        pull(block)                           # 22
        label("23")
        out(x, 1)                             # 23
        jmp(not_x, "27")                      # 24
        wait(0, pin, 0)         .side(2)      # 25
        jmp("29")                             # 26
        label("27")
        wait(0, pin, 1)         .side(1)      # 27
        wait(1, pin, 1)         .side(0)      # 28
        label("29")
        wait(1, pin, 0)         .side(0)      # 29
        jmp(y_dec, "23")                      # 30
        wrap()
        label("31")
        jmp("31")                             # 31
    pio[3] |= (1 << 29) + 1    #Sets sideset mode to pindirs. Set status_n to 1

    statemachines = dict()  #Contains all initialized state machines

    def __init__(self,statemachine = -1, basepin = -1):
        #
        # Check if we already instantiated this. If so, reuse, else init.
        #
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
        #
        # State machine now chosen. Put together the rest of everything.
        #
        self.id = statemachine & 3
        self.core = (statemachine & 8) >> 3     #NOT IMPLEMENTED. FOR FUTURE USE
        if basepin < 0:
            basepin = self.id * 2 + (8 if self.core else 0)
        pin0 = machine.Pin(basepin+0,mode=Pin.IN, pull=Pin.PULL_UP)
        pin1 = machine.Pin(basepin+1,mode=Pin.IN, pull=Pin.PULL_UP)
        self.SMINIT = {
            'freq': 300000,
            'in_base': pin0, 'set_base': pin0, 'sideset_base': pin0, 'jmp_pin': pin1,
            'in_shiftdir': PIO.SHIFT_RIGHT, 'out_shiftdir': PIO.SHIFT_RIGHT,
        }
        self.sm = rp2.StateMachine(statemachine,TISERIAL.pio,**self.SMINIT)
        self.sm.active(1)
        return




    def piobase(self):
        return 0x50300000 if self.core else 0x50200000
    #Returns address based on sm0 offset. Valid for CLKDIV to PINCTRL.
    def smreg(self,sm0offset):
        sm0offset -= 0x00C8 #SM0_CLKDIV
        return (0x503000C8 if self.core else 0x502000C8) + 0x18*self.id + sm0offset
    #Returns fifo address
    def tx_fifo(self,value):
        machine.mem32[(0x50300010 if self.core else 0x50200010) + 4 * self.id] = value
    def rx_fifo(self):
        return machine.mem32[(0x50300020 if self.core else 0x50200020) + 4 * self.id]


    def get(self,timeout_ms = -1):
        starttime = time.ticks_ms()
        #If in tx mode, set to rx mode and proceed to wait for incoming data
        while True:
            if self.sm.rx_fifo() > 0:
                return self.sm.get()>>24&255
            if time.ticks_diff(time.ticks_ms(),starttime) > timeout_ms:
                #self.sm.restart()
                return -1

    def put(self,byte,timeout_ms = -1):
        starttime = time.ticks_ms()
        while True:
            if self.sm.tx_fifo() < 1:
                self.sm.put(byte)
                return 0
            if time.ticks_diff(time.ticks_ms(),starttime) > timeout_ms:
                #self.sm.restart()
                return -1
            
    ## REMOVE THE DEBUG FUNCTIONS WHEN DONE TESTING
    def dbg_printadr(self,ending='\n'):
        if ending=='\n':
            print("Stalled?  "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>31&1 else False))
            print("SIDE_EN?  "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>30&1 else False))
            print("S_PINDIR? "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>29&1 else False))
            print("")
        print("Curinst: {i} @ adr {a}       ".format(i=decode_pio(machine.mem32[self.smreg(SM0_INSTR)],2,True),a=hex(machine.mem32[self.smreg(SM0_ADDR)])),end=ending)
    def dbg(self):
        while True:
            self.dbg_printadr('\r')
            
''' 
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
'''
        

class TIPROTO(TISERIAL):
    def __init__(self,*args,**kwargs):
        super(TIPROTO,self).__init__(*args,**kwargs)
        self.machineid = 0x73

    def getpacket(self,start_timeout = 2000):
        mid = self.get(start_timeout)
        cid = self.get(100)
        lsb = self.get(100)
        msb = self.get(100)
        size = lsb+msb*256
        if size > 27000:
            raise Exception("Large data packets (>27000) not supported yet")
        if PACKET.gettype(cid) == 1:
            return PACKET(mid, cid, bytearray((self.get(1000) for i in range(size))))
        else:
            return PACKET(mid,cid)

    def sendpacket(self,packet):
        start_timeout = 2000
        for i in packet.tobytesgen():
            #print(i)
            self.put(i,start_timeout)
            start_timeout = 2000

    def sendack(self):
        self.sendpacket(PACKET(self.machineid,PV.ACK))
    



t = TIPROTO()
    
def emugraylink():
    import micropython,select,sys
    global t
    #print("Begin graylink emulation. REPL being disabled.")
    #micropython.kbd_intr(-1)     #Allows stdin/out to be used as terminal
    while True:
        while sys.stdin in select.select([sys.stdin], [],[],0)[0]:
            c = sys.stdin.buffer.read(1)
            if len(c) == 1:
                #print(c[0])
                t.put(c[0],2000)
        else:
            c = t.get()
            if c > -1:
                sys.stdout.buffer.write(bytes([c]))

def tightloop():
    a = []
    for i in range(ord('A'),ord('Q')+1):
        t.put(i,50)
        a.append(t.get())
    print(a)


def help():
    print("Helpful notes:")
    print("* Available classes:")
    print("  PV(object): List of packet commands")
    print("  PACKET(PV): Implements packets. init, tobytes, tobytesgen, #getname, #gettype, #formheader")
    print("  VID(object): List of variable types. #tostring")
    print("  HEADER(object): Constructs header data from variable stats. toheader, #fromheader")
    print("  TISERIAL(object): Implements TI DBUS protocol. init state machine, restart, get, put")
    print("  TIPROTO(TISERIAL): Implements rx/tx of packets")
    print("* TODO: Add functions to TIPROTO to perform actual actions (e.g. get var, get var list, send vars)")
    print("* Available functions and shorthand mappings")
    print("  t = TIPROTO() : Init and autoassigns to first mapping (0)")
    print("  emugraylink() -- Begin graylink emulator. [THIS DISABLES THE REPL. DISCONNECT FROM VSCODE AFTER USING]")
    print("* TODO: Fix emugraylink() to use new TISERIAL class")
    print("Debugging calls: ")
    print("t.dbg() : Infinite loop displaying current PIO instruction")
    print("t.dbg_printadr() : Prints the immediate address and if SM has stalled")
help()


