
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

SM0_EXECCTRL    = const(0x00CC)
SM0_ADDR        = const(0x00D4)
SM0_INSTR       = const(0x00D8)

class PV(object):
    VAR = 0x06
    CTS = 0x09
    DATA = 0x15
    VER  = 0x2D
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
            yield self.chksum_lsb
            yield self.chksum_msb

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

    def __str__(self):
        return "<{0} type {1} data {2} from machine {4} chksum {3}>".format(type(self).__name__, self.getname(self.cid), hex(self.data), hex((self.chksum_lsb, self.chksum_msb)), hex(self.mid))

    

class VID(object):
    REAL,LIST,MATR,YVAR,STR ,PROG = (0x00,0x01,0x02,0x03,0x04,0x05)
    PROT,PIC ,GDB ,WIN1,CPLX,CLST = (0x06,0x07,0x08,0x0B,0x0C,0x0D)
    WNS2,SWNS,TSET,BAK ,DELF,AVAR = (0x0F,0x10,0x11,0x13,0x14,0x15)
    GRP ,DIR ,OS  ,APP ,IDL ,CERT,CLK = (0x17,0x19,0x23,0x24,0x26,0x27,0x29)
    tostrdict = { 0x00 : "REAL",0x01 : "LIST",0x02 : "MATR",0x03 : "YVAR",0x04 : "STR ",0x05 : "PROG",0x06 : "PROT",0x07 : "PIC ",0x08 : "GDB ",0x0B : "WIN1",0x0C : "CPLX",0x0D : "CLST",0x0F : "WNS2",0x10 : "SWNS",0x11 : "TSET",0x13 : "BAK ",0x14 : "DELF",0x15 : "AVAR",0x17 : "GRP ",0x19 : "DIR ",0x23 : "OS  ",0x24 : "APP ",0x26 : "IDL ",0x27 : "CERT",0x29 : "CLK " }
    @classmethod
    def tostring(cls,t):    #Receives var type, returns in string if possible
        return cls.tostrdict[t] if t in cls.tostrdict else "!{0}".format(hex(t))


#Create header object which can return compact notation but also retains
#easy-to-retrieve data such as types.
#Alternative constructor format allows you to import packet data and
#the class will init an instance with easy-to-retrieve data filled out
#The Flash header format listed in the guide does not match what we have
#here. That's because we're receiving directory listings with this class,
#not forming packets with that data.
class HEADER(object):
    def __init__(self, ftype_or_packetdata, fname = None, size = 0, isarc = 0, ver1 = 0, ver2 = 0):
        if fname is None:
            self.h = ftype_or_packetdata.data
            h = self.h
            self.size  = h[0]+h[1]*256
            self.ftype = int(h[2])  #No matter the header style, type is always here.
            self.fname = h[3:11].decode().strip('\x00')
            if self.ftype > 0x22 and self.ftype < 0x28:
                self.isarc = True
                self.ver1  = 0
                self.ver1  = 0
            elif self.ftype == 0x13:
                raise Exception("Reading backup header not supported")
            else:
                self.isarc = True if h[12] & 128 else False
                self.ver1= h[11]
                self.ver2= h[12] & 127
        else:
            self.h = bytearray(13)
            self.ftype = ftype_or_packetdata
            self.size  = size
            self.fname = fname
            self.isarc = True if isarc else False
            self.ver1  = ver1
            self.ver2  = ver2
            self.size  = size
            if self.ftype > 0x22 and self.ftype < 0x28:
                self.toflashheader()
            elif self.ftype == 0x13:
                raise Exception("Creating backup header not supported")
            else:
                self.h[:2] = bytearray((self.size&255, (self.size>>8)&255 ))
                self.h[2]  = self.ftype
                self.h[3:3+len(self.fname)] = self.fname.encode('ascii')
                self.h[11] = self.ver1
                self.h[12] = (self.ver2&127) + (128 if self.isarc else 0)

    def updatesize(self,newsize):
        self.h[:2] = bytearray((newsize&255, newsize>>8&255))


    def toheader(self):
        #Reinforce the name in case it gets overwritten in flash call
        self.h[3:3+len(self.fname)] = self.fname.encode('ascii')
        return memoryview(self.h)[:13]

    #Exists for when you need to perform an actual flash transfer, which
    #allows for modified packets involving page offsets and page numbers.
    def toflashheader(self,pageoffset = None, pagenumber = None):
        if pageoffset is not None and pagenumber is not None:
            self.h[6] = pageoffset & 255
            self.h[7] = pageoffset>>8 & 255
            self.h[8] = pagenumber & 255
            self.h[9] = pagenumber>>8 & 255
            return memoryview(self.h)[:10]
        else:
            self.h[3:3+len(self.fname)] = self.fname.encode('ascii')
            return memoryview(self.h)[:11]

    def isflash(self):
        if self.ftype > 0x22 and self.ftype < 0x28:
            return True
        else:
            return False
    def isbackup(self):
        if self.ftype == 0x13:
            return True
        else:
            return False

    def __str__(self):
        return "<{0} at {1}: file {2} of type {3}>".format(type(self).__name__, "?", self.fname, VID.tostring(self.ftype))
    
    def __repr__(self):
        return self.__str__()


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
            'freq': 900000,
            'in_base': pin0, 'set_base': pin0, 'sideset_base': pin0, 'jmp_pin': pin1,
            'in_shiftdir': PIO.SHIFT_RIGHT, 'out_shiftdir': PIO.SHIFT_RIGHT,
        }
        self.sm = rp2.StateMachine(statemachine,TISERIAL.pio,**self.SMINIT)
        self.sm.active(1)
        return

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
            

    def piobase(self):
        return 0x50300000 if self.core else 0x50200000
    #Returns address based on sm0 offset. Valid for CLKDIV to PINCTRL.
    def smreg(self,sm0offset):
        sm0offset -= 0x00C8 #SM0_CLKDIV
        return (0x503000C8 if self.core else 0x502000C8) + 0x18*self.id + sm0offset
    ## REMOVE THE DEBUG FUNCTIONS WHEN DONE TESTING
    def dbg_printadr(self,ending='\n'):

        if ending=='\n':
            print("Stalled?  "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>31&1 else False))
            print("SIDE_EN?  "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>30&1 else False))
            print("S_PINDIR? "+str(True if machine.mem32[self.smreg(SM0_EXECCTRL)]>>29&1 else False))
        print("Curinst:  {i} @ adr {a}       ".format(i=decode_pio(machine.mem32[self.smreg(SM0_INSTR)],2,True),a=hex(machine.mem32[self.smreg(SM0_ADDR)])),end=ending)
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
        if 'machineid' in kwargs:
            self.machineid = kwargs['machineid']
        else:
            self.machineid = 0x73
        self.ackpacket = PACKET(self.machineid,PV.ACK)
        self.dirlist = list()
        self.varhead = None
        self.vardata = None

    def getpacket(self,start_timeout = 2000):
        mid = self.get(start_timeout)
        cid = self.get(start_timeout)
        time.sleep_ms(1)
        lsb = self.get(start_timeout)
        msb = self.get(start_timeout)
        base = (mid,cid,lsb,msb)
        if any((i == -1 for i in base)):
            print("Packet incomplete. Got {0}".format(str(base)))
            raise Exception("Incomplete packet received.")
        size = lsb+msb*256
        if size > 27000:
            raise Exception("Large data packets (>27000) not supported yet")
        if PACKET.gettype(cid) == 1:
            p = PACKET(mid, cid, bytearray((self.get(start_timeout) for i in range(size))))
            lo,hi = (self.get(start_timeout) for i in range(2))
            if (p.chksum_lsb,p.chksum_msb) != (lo,hi):
                raise Exception("Checksum error on {0}".format(str(p)))
            return p
        else:
            return PACKET(mid,cid)

    #Send either a PACKET type object, or a command (4byte) packet specified by cid
    def sendpacket(self, packet, machineid = None):
        self.sm.restart()
        if machineid is None:
            machineid = self.machineid
        if isinstance(packet,int):
            packet = PACKET(machineid,packet)
        start_timeout = 2000
        for i in packet.tobytesgen():
            v = self.put(i,start_timeout)
            #print("Sending {0}, success? {1}".format(i, True if not v else False))
            start_timeout = 2000

    def sendack(self):
        self.sendpacket(self.ackpacket)
    
    def getvarlist(self,filter = -1, depth = 0):
        self.sm.restart()
        #
        # Variable request packets:
        # PI -> 83 : REQ type DIR (other data in no-care state)
        # PI <- 83 : ACK
        # PI <- 83 : DATA [two bytes indicating amount of free RAM]
        # PI -> 83 : ACK
        # [...]
        #
        p = PACKET(self.machineid,PV.REQ,HEADER(VID.DIR,"").toheader())
        print("Sending data: "+str(p))
        self.sendpacket(p)
        p = self.getpacket()
        if p.cid != PV.ACK:
            raise Exception("No ACK on get directory request")
        p = self.getpacket()
        print("Free RAM reported: "+str(int(p.data[0])+int(p.data[1])*256))
        print("Sending ackpacket: "+str(self.ackpacket))
        self.sendack()
        self.dirlist = []
        #
        # For each variable on the calculator:
        # PI <- 83 : VAR (full variable data)
        # PI -> 83 : ACK
        #
        # When there's no more left to get:
        # PI <- 83 : EOT
        # PI -> 83 : ACK
        #
        while p.cid != PV.EOT:
            p = self.getpacket()
            print("Received: "+str(p))
            if p.cid == PV.VAR:
                self.sendack()
                h = HEADER(p)
                if filter < 0 or h.ftype == filter:
                    print("Found file: {n}, of type {t}".format(n = h.fname, t = VID.tostring(h.ftype)))
                    self.dirlist.append(h)
                continue
            if p.cid != PV.EOT:
                raise Exception("Unrecognized packet received. Aborting.")
        self.sendack()
        print("End of transmission. No more variables to receive.")

    def findvar(self, name, ftype = -1):
        for header in self.dirlist:
            if header.fname == name:
                if ftype < 0 or ftype == header.ftype:
                    return header
        return None

    def getvar(self,header:HEADER):
        self.sm.restart()
        if header.isflash():
            #
            # Do flash receivey things
            #
            raise Exception("Flash receive not implemented yet.")
            self.sendpacket(PACKET(self.machineid, PV.VAR, header.toflashheader()))
        elif header.isbackup():
            raise Exception("Backup receive not implemented. WONTFIX.")
        else:
            self.sendpacket(PACKET(self.machineid, PV.REQ, header.toheader()))
            p = self.getpacket()    #Step 2
            if p.cid == PV.SKIP:
                self.sendack()
                raise Exception("Oopsie poopsie. {0} not exist.".format(header))
            if p.cid != PV.ACK:
                raise Exception("Var request not acknowledged.")
            p = self.getpacket()    #Step 3
            if p.cid != PV.VAR:
                raise Exception("Oopsie poopsie. Didn't actually get var data.")
            header2 = HEADER(p)
            if header.fname != header2.fname or header.ftype != header2.ftype:
                self.sendpacket(PACKET(self.machineid, PV.SKIP, bytearray([1])))
                self.getpacket()    #Should get an acknowledgement. Maybe.
                raise Exception("Oopsie poopsie. We aren't receiving the expected variable.")
            self.sendack()          #Step 4
            time.sleep_ms(1)        #I think we need a delay?
            self.sendpacket(PV.CTS) #Step 5
            p = self.getpacket()    #Step 6
            if p.cid != PV.ACK:
                raise Exception("Oopsie poopsie. CTS not acknowledged.")
            p = self.getpacket()    #Step 7. DATA get
            if p.cid != PV.DATA:
                raise Exception("Oopsie poopsie. Did not receive DATA packet.")
            self.sendack()          #Step 8. Acknowledge data. We are done.
            self.varhead = header
            self.vardata = p.data
            print("Variable {0} of type {1} received.".format(header.fname, VID.tostring(header.ftype)))
            return 0

    @classmethod
    def fromfile(cls,filename):
        with open(filename,"rb") as f:
            f.read(8+3+42+2+2+2) #skip head,sig,comment,filedatsize,hlen,isize
            ftype = f.read(1)[0]
            fname = f.read(8).decode()
            ver = f.read(1)[0]
            ver2 = f.read(1)[0]
            isarc = True if ver2 & 128 else False
            ver2 &= 127
            h = f.read(2)
            size = h[0] + h[1] * 256
            data = f.read(size)
            return (HEADER(ftype,fname,size,isarc,ver, ver2), data)


    def sendvar(self,header,data = None):
        self.sm.restart()
        if data is None:    #header is actually the name of a .8x file on the pi.
            header,data = self.fromfile(header)
        if header.isflash():
            raise Exception("Cannot send flashapps and OS files yet.")
        elif header.isbackup():
            raise Exception("Sending backups not supported. WONTFIX.")
        else:
            self.sendpacket(PACKET(self.machineid, PV.RTS, header.toheader()))
            p = self.getpacket()
            print(p)
            if p.cid != PV.ACK:
                raise Exception("RTS not acknowledged. Exiting.")
            time.sleep_ms(100)
            p = self.getpacket()
            print(p)
            if p.cid == PV.SKIP:
                raise Exception("Transmission canceled.")
            elif p.cid != PV.CTS:
                raise Exception("Wasn't cleared to send. Canceling.")
            self.sendack()
            time.sleep_ms(1)
            self.sendpacket(PACKET(self.machineid, PV.DATA, data))
            if self.getpacket().cid != PV.ACK:
                raise Exception("Transmission of data not acknowledged.")
            self.sendpacket(PV.EOT)







t = TIPROTO()
    
def emugraylink():
    import micropython,select,sys
    global t
    #print("Begin graylink emulation. REPL being disabled.")
    micropython.kbd_intr(-1)     #Allows stdin/out to be used as terminal
    while True:
        while sys.stdin in select.select([sys.stdin], [],[],0)[0]:
            c = sys.stdin.buffer.read(1)
            if len(c) == 1:
                #print(c[0])
                t.put(c[0],50)
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

test = lambda : t.sendvar("linktest.8xp")
