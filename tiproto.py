
import micropython
micropython.alloc_emergency_exception_buf(200)
from micropython import const, schedule
import uctypes,rp2,time,machine,random,array,collections,sys,os, uio
from machine import Pin
from rp2 import PIO
import builtins
import gc

PACKET_DEBUG = True


def hex(value):
    try:
        if type(value) is int:
            return builtins.hex(value)
        if type(value) is str and len(value)>0:
            return str([builtins.hex(ord(i)) for i in value])
        if iter(value) and len(value) > 0:
            return str([builtins.hex(i) for i in value])
        return str([])
    except:
        return "<NO REPR>"

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
    wdat = {0x06:"VAR",0x15:"DATA",0x36:"SK/E",0x88:"DEL",0xA2:"S-REQ",0xC9:"RTS"}
    bare = {0x09:"CTS",0x2D:"VER",0x56:"ACK",0x5A:"ERR",0x68:"RDY",0x6D:"SCR",0x92:"EOT"}
    def __init__(self,macid,cmdid,data=bytearray(),datasize = None):
        self.mid = macid
        self.cid = cmdid
        self.data = data
        if datasize:    #This is defined only if data is a stream/file-like object
            s = datasize
        else:
            if data:
                s = len(data)
            else:
                s = 0
        self.size = s
        self.size_lsb = s & 255
        self.size_msb = (s >> 8) & 255
        self.name = self.getname(self.cid)
        self.base = bytearray([self.mid, self.cid, self.size_lsb, self.size_msb])

    def tobytesgen(self):
        for i in self.base:
            yield i
        if self.data:
            chksum = 0
            for _,i in zip(range(self.size),self.data):
                chksum += i
                yield i
            yield chksum & 255
            yield (chksum >> 8) & 255

    @classmethod
    def getname(cls,cid):
        packettype = cls.gettype(cid)
        if packettype < 0:
            return "UNK ({:02X})".format(packettype)
        elif packettype:
            return cls.wdat[cid]
        else:
            return cls.bare[cid]

    #0 == bare, 1 == contains data, -1 == unknown
    @classmethod
    def gettype(cls,cid):
        if cid in cls.bare:
            return 0
        elif cid in cls.wdat:
            return 1
        else:
            return -1

    @classmethod
    def formheader(cls,ftype, fname, isarchived = False, ver1 = 0, ver2 = 0):
        #Create the header necessary for the data represented.
        #TODO: Also consider supporting backup and FLASH headers
        pass

    def __str__(self):
        return "<{0} type {1} data {2} from machine {3}>".format(type(self).__name__, self.getname(self.cid), hex(self.data), hex(self.mid))

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
            self.h[2] = self.ftype
            self.h[4] = 0
            self.h[3] = 0
            self.h[5] = 0
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

class MEMFILE(object):
    #Conveinence class. Should use only for SMALL (<256bytes) OBJECTS
    #obj must be of types bytearray() or memoryview()
    #skip arg is used to exclude leading writes in case of writing to
    #logs where some initial bytes needs to be ignored.
    def __init__(self,obj,skip=0): #obj must support getitem
        self.o,self.p,self.l,self.s = (obj,0,len(obj),skip)
    def read(self,s=-1):
        p=self.p
        self.p=self.l if (s is None or s<0) else p+s
        return memoryview(self.o)[p:p+(self.l if s<0 else s)]
    def readinto(self,b):
        b[:] = self.read(len(b))
        return len(b)
    def seek(self,o=0,w=0):
        self.p = (w+self.p if o<2 else self.l-1+w) if o else w
        return self.p
    def tell(self):
        return self.p
    def write(self,d):
        ld=len(d)
        if ld+self.p>=self.l:
            return 0
        if self.s>ld:
            self.s-=ld
            return 0
        self.o[self.p:self.p+ld] = d[:]
        self.p += ld
        return ld

class INTELLEC(object):
    DATA    = 0x00
    EOF     = 0x01
    ESA     = 0x02
    rectype = {-1:"NONE",DATA:"DATA",EOF:"EOF",ESA:"PAGE"}
    txt2num = {0x30:0,0x31:1,0x32:2,0x33:3,0x34:4,0x35:5,0x36:6,0x37:7,0x38:8,0x39:9,0x41:10,0x42:11,0x43:12,0x44:13,0x45:14,0x46:15}

    def texttobyte(self):
        a = self.txt2num[self.f.__next__()]
        return self.txt2num[self.f.__next__()]+a*16

    def __init__(self,f=None):
        self.f = f
        self.type = -1
        if f is None:   #If no input, returns an object init'd to type -1
            return      #This was added for loop control purposes
        try:
            while True:
                if f.__next__() == ord(':'):
                    break
            self.size   = self.texttobyte()
            self.addrHI = self.texttobyte()
            self.addrLO = self.texttobyte()
            self.addr   = self.addrHI*256+self.addrLO
            self.type   = self.texttobyte()
            self.data   = bytearray(self.size)
            for i in range(self.size):
                self.data[i] = self.texttobyte()
            self.chks   = 255 & (-(self.size + self.addrHI + self.addrLO + self.type + sum(self.data)))
            self.chksm  = self.texttobyte()
            if self.chks != self.chksm:
                self.type = -1
                raise Exception("Data section checksum does not match expected values")
        except StopIteration:
            print("EOF on INTELLEC read encountered.")
            pass
        return
    def __str__(self):
        return "<{0} at {1}: record type {2}>".format(type(self).__name__, "?", self.rectype(self.type))
    
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

    def __init__(self,statemachine = -1, basepin = -1, *args, **kwargs):
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
            self.machineid = 0x23
        self.ackpacket = PACKET(self.machineid,PV.ACK)
        self.dirlist = list()
        self.varhead = None
        self.vardata = None
        # Used to return header in fromfile() because it is (now) a generator
        self.curheader = HEADER(0,'')

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
            data = bytearray((self.get(start_timeout) for i in range(size)))
            p = PACKET(mid, cid, data)
            lo,hi = (self.get(start_timeout) for i in range(2))
            if sum(data) != lo+hi*256:
                raise Exception("Checksum error on {0}".format(str(p)))
            if PACKET_DEBUG:
                print("Packet received: {0}".format(p))
            return p
        else:
            p = PACKET(mid,cid)
            if PACKET_DEBUG:
                print("Packet received: {0}".format(p))
            return p

    #Send either a PACKET type object, or a command (4byte) packet specified by cid
    def sendpacket(self, packet, machineid = None):
        self.sm.restart()
        if machineid is None:
            machineid = self.machineid
        if isinstance(packet,int):
            packet = PACKET(machineid,packet)
        #if PACKET_DEBUG:
        #    print("Sending: "+str(packet))
        start_timeout = 2000
        for i in packet.tobytesgen():
            v = self.put(i,start_timeout)
            if PACKET_DEBUG:
                print("Sending {0} {2} {3}, success? {1}".format(i, True if not v else False,hex(i),chr(i) if i >=0x20 else "??"))
            start_timeout = 2000

    def sendack(self):
        self.sendpacket(self.ackpacket)
    
    def getvarlist(self,filter = -1, depth = 0):
        self.sm.restart()
        p = PACKET(self.machineid,PV.REQ,HEADER(VID.DIR,"").toheader())
        #print("Sending data: "+str(p))
        self.sendpacket(p)
        p = self.getpacket()
        if p.cid != PV.ACK:
            raise Exception("No ACK on get directory request")
        p = self.getpacket()
        #print("Free RAM reported: "+str(int(p.data[0])+int(p.data[1])*256))
        #print("Sending ackpacket: "+str(self.ackpacket))
        self.sendack()
        self.dirlist = []
        while p.cid != PV.EOT:
            p = self.getpacket()
            #print("Received: "+str(p))
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
            self.sendpacket(PACKET(self.machineid, PV.REQ, header.toflashheader()))
            time.sleep_ms(1)
            p = self.getpacket()
            if p.cid != PV.ACK:
                raise Exception("RTS not acknowledged. Got {0} instead.".format(str(p)))
            while True:
                p = self.getpacket()    #Getting a flash-style header here
                if p.cid == PV.EOT:
                    time.sleep_ms(1)
                    self.sendack()
                    print("End of transfer packet received.")
                    return 0
                if p.cid != PV.VAR:
                    raise Exception("Expected VAR reply. Got {0} instead.".format(str(p)))
                blksize = p.data[0]+p.data[1]*256
                pg_ofst = p.data[6]+p.data[7]*256
                pg_nmbr = p.data[8]+p.data[9]*256
                self.sendack()
                time.sleep_ms(1)
                self.sendpacket(PV.CTS)
                if self.getpacket().cid != PV.ACK:
                    raise Exception("CTS not acknowledged. Exiting.")
                p = self.getpacket()
                self.sendack()
                if p.cid != PV.DATA:
                    raise Exception("Expected DATA packet. Got {0} instead.".format(str(p)))
                print("Received app data size {0} offset {1} page {2}".format(hex(blksize),hex(pg_ofst), hex(pg_nmbr)))
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

    #Changing this to a generator that yields a file object
    #Initializing requires a dummy read
    def fromfile(self,filename):
        with open(filename,"rb") as f:
            ext = filename[-3:]
            print("File {0} opened.".format(filename))
            if ext == "8xk":
                if f.read(8).decode() != "**TIFL**":
                    raise Exception("Flash header incorrect (first 8 bytes)")
                revision    = f.read(2) #BCD coded: major.minor
                flags       = f.read(1) #Usually 0x00
                objtype     = f.read(1) #Usually 0x00
                date        = f.read(4) #BCD coded e.g. dd,mm,yy,yy (dd/mm/yyyy)
                namelen     = f.read(1) #Name length. Not exactly needed...
                fname       = f.read(8).decode().split('\0')[0]
                f.read(23)              #Filler. Unused.
                devicetype  = f.read(1)[0] #TI73:74h, 83p:73h, 89:98h, 92p:88h
                ftype       = f.read(1)[0]
                f.read(24)              #Filler. Unused
                # The documentation states that the following 4 bytes of size
                # indicates the number of intelhex characters in the file. The
                # app that I checked indicates that in pure size. For apps, this
                # value is probably ignorable as you'd parse each line
                # (yes, the data is in text mode. Windows-style in my case)
                fsize       = f.read(4) #Yesh.
                #Size of the file not known at this time since it will be sent
                #in blocks as defined in the file thinger.
                self.curheader = HEADER(ftype,fname,0,1,0,0)
                yield 0 #Dummy read to initialize things
                for i in f.read():
                    yield i
            elif ext in ('8xp','8xv'):
                f.read(8+3+42+2+2+2) #skip head,sig,comment,filedatsize,hlen,isize
                ftype = f.read(1)[0]
                fname = f.read(8).decode().split('\0')[0]
                ver = f.read(1)[0]
                ver2 = f.read(1)[0]
                isarc = True if ver2 & 128 else False
                ver2 &= 127
                h = f.read(2)
                size = h[0] + h[1] * 256
                #data = f.read(size)
                self.curheader = HEADER(ftype,fname,size,isarc,ver, ver2)
                print("CONSTR HDR: "+str(self.curheader))
                yield 0 #Dummy read to initialize things
                for i in f.read():
                    yield i
            else:
                raise Exception("Unknown file type .{0}".format(ext))

    def sendvarsub(self):
        pass

    def sendvar(self,header,data = None):
        self.sm.restart()
        starttime = time.ticks_ms()
        if data is None:    #header is actually the name of a .8x file on the pi.
            data = self.fromfile(header)
            data.__next__() #prime the sender so self.curheader gets init'd
            header = self.curheader
            print(header)
        if header.isflash():
            def flushchunk(chunkdata,header,page,address):
                pass
                h = header.toflashheader(address,page)
                self.sendpacket(PACKET(self.machineid, PV.VAR, h))
                if self.getpacket().cid != PV.ACK:
                    raise Exception("VAR req to send not acknowledged.")
                if self.getpacket().cid != PV.CTS:
                    raise Exception("VAR not cleared to send.")
                
                self.sendack()
                time.sleep_us(250)
                self.sendpacket(PACKET(self.machineid,PV.DATA,chunkdata))
                p = self.getpacket()
                if p.cid == PV.ERR:
                    raise Exception("Error occurred on data xmit page {0}, address {1}".format(page,address))
                if p.cid != PV.ACK:
                    raise Exception("Data packet not acknowleged.")
                print("Chunk @ {0:04X} page {1:02X}  flushed to i/o".format(address,page))
                pass
            if header.ftype != 0x24:
                raise Exception("Cannot handle non-app Flash types")
            print("File header: "+str(header))
            #Verify that the calc is ready to receive before trying
            
            self.sendpacket(PV.RDY)
            if self.getpacket().cid != PV.ACK:
                raise Exception("Receiver not ready")
            
            basepage = -1
            address = -1
            chunks = 0
            appdata = bytearray(0x80)
            header.updatesize(0x80) #block size
            while True:
                idata = INTELLEC(data)  #Read next data section
                if idata.type == -1:
                    print("Error or early EOF")
                    print("Exiting conds: pg {0}, adr {1}, chnk {2}, data {3}".format(basepage,address,chunks,appdata))
                    break
                elif idata.type == INTELLEC.ESA:
                    if chunks > 0:  #in case someone decides to leave out some data
                        flushchunk(appdata,header,basepage,address&0x7F80)
                        chunks = 0
                        appdata = bytearray(0x80)   #make a new one.
                        gc.collect()    #Do GC things while the calc is processing
                    basepage = idata.data[0]*256+idata.data[1]
                    address = -1
                    print("Basepage set to {0:02X}".format(basepage))
                    continue
                elif idata.type == INTELLEC.EOF:
                    print("EOF record retrieved.")
                    if chunks > 0:  #in case someone decides to leave out some data
                        flushchunk(appdata,header,basepage,address&0x7F80)
                    break
                elif idata.type == INTELLEC.DATA:
                    if address < 0 :
                        address = idata.addr
                    elif idata.addr-address != 0x20:
                        raise Exception("App data blocks must be contiguous. Found {0:04X}, expected {1:04X}".format(idata.addr,address+0x20))
                    subadr = idata.addr & 0x7F
                    appdata[subadr:subadr+idata.size] = idata.data
                    address = idata.addr
                    #print("Data record retrieved at address {0:04X}".format(address))
                    chunks += 1
                    if chunks == 4:
                        flushchunk(appdata,header,basepage,address&0x7F80)
                        chunks = 0
                        appdata = bytearray(0x80)   #make a new one.
                        gc.collect()    #Do GC things while the calc is processing
                    
            
            self.sendpacket(PV.EOT)
            if self.getpacket().cid != PV.ACK:
                raise Exception("EOT packet not acknowledged.")
            print("Transmission end. Time elapsed in ms: {0}".format(time.ticks_diff(time.ticks_ms(),starttime)))
            pass
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
            self.sendpacket(PACKET(self.machineid, PV.DATA, data, header.size))
            if self.getpacket().cid != PV.ACK:
                raise Exception("Transmission of data not acknowledged.")
            self.sendpacket(PV.EOT)







EMBUF = MEMFILE(bytearray(1000))
t = TIPROTO(basepin = 2, machineid = 0x23)

def dump(f):
    chunksize = 16000
    p = int(f.p / chunksize) + ((f.p % chunksize) != 0)
    f.seek()
    for i in range(p):
        with open("logf{:02}.txt".format(i),"wb") as fo:
            fo.write(f.read(chunksize))

def flush(fobj,data,iodir):
    p = data.p
    data.seek(0)
    fobj.write(bytearray("\nTO83: " if iodir else "\nFR83: "))
    for i in data.read(p):
        fobj.write(bytearray('{0:02X}'.format(i)))
    data.seek(0)
    return
    
def emu(logging = False):
    import select
    global t,EMBUF
    data = MEMFILE(bytearray(25000))
    f = MEMFILE(bytearray(50000),20000)
    iodir = 1   #1=put, 0=get
    sensepin = Pin(0,Pin.IN,Pin.PULL_UP)

    micropython.kbd_intr(-1)     #Allows stdin/out to be used as terminal

    try:
        while True:
            if not sensepin.value():
                micropython.kbd_intr(3)
                if logging:
                    dump(f)
                return
            while sys.stdin in select.select([sys.stdin], [],[],0)[0]:
                c = sys.stdin.buffer.read(1)[0]
                t.put(c,2000)
                if logging:
                    if iodir != 1:
                        flush(f,data,iodir)
                        iodir = 1
                    data.write(bytearray([c]))
            else:
                c = t.get()
                if c > -1:
                    if logging:
                        if iodir != 0:
                            flush(f,data,iodir)
                            iodir = 0
                        data.write(bytearray([c]))
                    sys.stdout.buffer.write(bytes([c]))
    except Exception as e:
        if logging:
            try:
                dump(f)
                sys.print_exception(e, file=f)
                micropython.kbd_intr(3)
            except:
                with open("EMERGENCY.txt","wt") as em:
                    sys.print_exception(e,em)
                micropython.kbd_intr(3)
                return "ERROR"

def tightloop():
    a = []
    for i in range(ord('A'),ord('Q')+1):
        t.put(i,50)
        a.append(t.get())
    print(a)
def pkdb(val):
    global PACKET_DEBUG
    PACKET_DEBUG = val

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
    print("  emu() -- Begin graylink emulator. [THIS DISABLES THE REPL. DISCONNECT FROM VSCODE AFTER USING]")
    print("* TODO: Fix emugraylink() to use new TISERIAL class")
    print("Debugging calls: ")
    print("t.dbg() : Infinite loop displaying current PIO instruction")
    print("t.dbg_printadr() : Prints the immediate address and if SM has stalled")
    print("pkdb(true/false) : Turns on or off packet debugging")
help()

def showemergency():
    print("\nShowing contents of EMERGENCY.txt: \n\n")
    with open("EMERGENCY.txt","rt") as f:
        for line in f:
            print(line.strip())

def log(v=None):
    try:
        if v is None:
            r = 999
            v = 0
        else:
            r = v+1
        for i in range(v,r):
            print("Opening: logf{:02}.txt".format(i))
            with open("logf{:02}.txt".format(i),"rt") as fo:
                for line in fo:
                    print(line.strip())
        return
    except:
        return
test = lambda : t.sendvar("linktest.8xp")
pkdb(0)

# t.sendvar("MINES4.8xk")
