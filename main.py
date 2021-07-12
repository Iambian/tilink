import micropython
micropython.alloc_emergency_exception_buf(200)
from micropython import const
import uctypes,rp2,time,machine,random,array,collections,sys,os
from machine import Pin
from rp2 import PIO
import builtins
import gc

def hex(value):
    if type(value) is int:
        return builtins.hex(value)
    if type(value) is str and len(value)>0:
        return str([builtins.hex(ord(i)) for i in value])
    if iter(value) and len(value) > 0:
        return str([builtins.hex(i) for i in value])
    return str([])

PACKET_DEBUG = False

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
PIO_FSTAT       = const(0x0004)
PIO_FLEVEL      = const(0x000C)
PIO_TXF0        = const(0x0010)
PIO_RXF0        = const(0x0020)
PIO_IRQ         = const(0x0030)
PIO_IRQ_FORCE   = const(0x0034)
SM0_EXECCTRL    = const(0x00CC)
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



class PACKET(object):
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

class TILINK(object):
    print("Initializing TILINK class")
    pin0 = Pin(0)           #BASE PIN THAT OUR STATE MACHINE WILL USE
    pin1 = Pin(1)           #BASE PIN + 1 THAT IS USED FOR JMP_PIN
    PIO_INIT = {
        'out_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'set_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'sideset_init' : (PIO.OUT_LOW,PIO.OUT_LOW),
        'autopull' : True,
        'pull_thresh' : 8,
        'autopush' : True,
        'push_thresh' : 8
    }
    SM_INIT = {
        'freq' : 500000,
        'in_base' : pin0,
        'sideset_base' : pin0,
        'set_base' : pin0,
        'in_shiftdir' : PIO.SHIFT_RIGHT,
        'out_shiftdir' : PIO.SHIFT_RIGHT,
        'push_thresh' : 8,
        'pull_thresh' : 8,
        'jmp_pin' : pin1
    }
    @rp2.asm_pio(**PIO_INIT)
    def pio():
        wrap_target()
        label("0")
        jmp("0")                .side(0)      # 0
        label("1")
        irq(block,0)            .side(0)      # 1
        label("restartloop")
        set(y, 7)                             # 2
        label("3")
        jmp(not_osre, "xmit")                 # 3
        label("4")
        mov(osr, pins)                        # 4
        out(x, 1)                             # 5
        out(null, 31)                         # 6
        jmp(not_x, "12")                      # 7
        jmp(pin, "3")                         # 8
        wait(1, pin, 1)         .side(1)      # 9
        wait(1, pin, 0)         .side(0)      # 10
        jmp("16")                             # 11
        label("12")
        jmp(pin, "14")                        # 12
        jmp("error")                          # 13
        label("14")
        wait(1, pin, 0)         .side(2)      # 14
        wait(1, pin, 1)         .side(0)      # 15
        label("16")
        in_(x, 1)                             # 16
        jmp(y_dec, "4")                       # 17
        jmp("1")                              # 18 interrupt on recieve
        label("xmit")
        set(y, 7)                             # 19 should deprecate this instr
        label("xmitloop")
        out(x, 1)               .side(0)      # 20
        jmp(not_x, "send0")                   # 21
        label("send1")     
        wait(0, pin, 0)         .side(2)      # 22
        jmp("endxmit")                        # 24
        label("send0")
        wait(0, pin, 1)         .side(1)      # 25
        label("endxmit")
        wait(1, pin, 0)         .side(0) [3]  # 23
        wait(1, pin, 1)         .side(0) [3]  # 26
        jmp(y_dec, "xmitloop")           [3]  # 27
        jmp("restartloop")               [3]  # 28
        label("error")
        jmp("error")                          # 29
        wrap()
    

    pio[3] |= 1 << 29    #Sets sideset mode to pindirs
    sm = rp2.StateMachine(0,pio,**SM_INIT)
    sm.restart()
    sm.active(True)
    time.sleep_ms(100)
    smstop = machine.mem32[PIO0_BASE+SM0_INSTR]
    smgo   = smstop + 2     #Jump over the irq instruction
    machine.mem32[PIO0_BASE+SM0_INSTR] = smgo
    rxbuf = bytearray(256)
    rxbuftail = 0
    rxbufhead = 0
    rxsize = 0
    bytesgotten = 0
    bytessent = 0
    
    @classmethod
    def execonce(cls,instr):
        machine.mem32[PIO0_BASE+SM0_INSTR] = instr
        while machine.mem32[PIO0_BASE+SM0_INSTR] == instr:
            pass
    

    @classmethod
    def isr(cls,pio):   #triggers on byte sent or on byte received
        irq_state = machine.disable_irq()
        #Critical section begin
        #print("Trig at size: "+str(TILINK.rxsize))
        fstat = machine.mem32[PIO0_BASE+PIO_FSTAT]
        if (not fstat & const(1<<8)) and TILINK.rxsize < 127:     #Check if rxf0empty. Get byte if not.
            TILINK.rxsize += 1
            TILINK.rxbuf[TILINK.rxbuftail] = machine.mem32[PIO0_BASE+PIO_RXF0] >> 24
            TILINK.rxbuftail = TILINK.rxbuftail+1 & 127
        else:
            #print("Data dropped with fstat condition code"+hex(fstat))
            pass
        machine.enable_irq(irq_state)
        return

    rp2.PIO(0).irq(lambda pio: TILINK.isr(pio))

    @classmethod
    def sendchunk(cls,chunk):
        machine.mem32[PIO0_BASE+SM0_INSTR] = cls.smstop
        time.sleep_ms(1)
        machine.mem32[PIO0_BASE+SM0_INSTR] = 0xA0E3 #Fills OSR with all 0. Is full.
        time.sleep_ms(1)
        machine.mem32[PIO0_BASE+SM0_INSTR] = 0x7068 #Empties OSR, will stall.
        time.sleep_ms(1)
        for i in chunk:
            #print("Send byte "+hex(i))
            cls.sm.put(i)
        cls.execonce(0xA042) #nop. Allows time for autopull to fill OSR
        #print("instr: "+decode_pio(machine.mem32[PIO0_BASE+SM0_INSTR],2,True))
        curtime = time.ticks_ms()
        machine.mem32[PIO0_BASE+SM0_INSTR] = cls.smgo
        #Wait up to 2 seconds for the tx fifo to empty out and return to recv state
        #need both conditions to ensure consistent start and stop
        #cond1: if TXEMPTY bit is clear (not empty) or curaddress still in xmit section of code
        while (not machine.mem32[PIO0_BASE+PIO_FSTAT] & (1<<24)) or machine.mem32[PIO0_BASE+SM0_ADDR] >= (cls.smgo & 31) + 19:
            if time.ticks_diff(time.ticks_ms(),curtime) > 2000:
                print("Fstat state: "+str(machine.mem32[PIO0_BASE+PIO_FSTAT] & (1<<24)))
                curinst = machine.mem32[PIO0_BASE+SM0_INSTR]
                curaddr = machine.mem32[PIO0_BASE+SM0_ADDR]
                print("Current address: "+str(curaddr))
                print("Address threshhold: "+str((cls.smgo & 31) + 19))
                print("Instruction at address: "+decode_pio(curinst,2,True))
                return -1
        time.sleep_ms(1)
        return 0
        
    @classmethod
    def reset(cls):
        cls.sm.restart()
        cls.sm.active(1)
        machine.mem32[PIO0_BASE+SM0_INSTR] = cls.smgo

    @classmethod
    def send(cls,data):
        #Halt the state machine
        #Check if input data is a sequenceable object. Else assume it's a byte
        try:    data[0]
        except:
            darr = bytearray(1)
            darr[0] = data
            data = darr
        for i in range(0,len(data),4):
            #print("Sent: "+hex(data[i:i+4]))
            if cls.sendchunk(data[i:i+4]) < 0:
                return -1
        return 0

    @classmethod
    def get(cls,waittime_ms=2000):
        #Wait for data to come into the rxbuf
        data = -1
        curtime = time.ticks_ms()
        while not cls.rxsize:
            if time.ticks_diff(time.ticks_ms(),curtime) > waittime_ms:
                if machine.mem32[PIO0_BASE+SM0_ADDR] == 0x19:
                    print("Xmit error: Link entered error state. Resetting.")
                    cls.sm.restart()
                    cls.sm.active(1)
                    machine.mem32[PIO0_BASE+SM0_ADDR] = cls.smgo
                return -1
        irq_state = machine.disable_irq()
        #Critical section begins
        cls.rxsize -= 1
        data = cls.rxbuf[cls.rxbufhead]
        cls.rxbufhead = (cls.rxbufhead + 1) & 127
        #Critical section ends
        machine.enable_irq(irq_state)
        return data

    @classmethod
    def getbytes(cls,numbytes,waittime_ms=2000):
        arr = bytearray(numbytes)
        for matey in range(numbytes):
            pirate = cls.get(waittime_ms)
            if pirate < 0:
                if not arr:
                    return -1
                else:
                    return arr[0:matey]
            arr[matey] = pirate
        return arr
        
    packetsize = 0
    packetdata = bytearray(65536)

    datapackets = {0x06:"VAR",0x15:"DATA",0x36:"SK/E",0x88:"S-DEL",0xA2:"S-REQ",0xC9:"S-RTS"}
    barepackets = {0x09:"CTS",0x2D:"S-VER",0x56:"ACK",0x5A:"ERR",0x68:"RDY",0x6D:"S-SCR",0x92:"EOT"}
    @classmethod
    def sendpacket(cls,packettype,data=bytearray()):
        e = 0
        s = ''
        if packettype in cls.datapackets:
            #This packet contains data to send
            size = len(data)
            chksum = sum(data)
            e |= cls.send([0x73,packettype,size&255,(size>>8)&255])
            e |= cls.send(data)
            e |= cls.send([chksum&255,(chksum>>8)&255])
            if not e:
                cls.bytessent += 4+len(data)+2
            if PACKET_DEBUG:
                print("SENT "+cls.datapackets[packettype]+" WITH DATA "+hex(data))
        elif packettype in cls.barepackets:
            #Packet with no data
            e |= cls.send([0x73,packettype,0,0])
            if not e:
                cls.bytessent += 4
            if PACKET_DEBUG:
                print("SENT "+cls.barepackets[packettype])
        else:
            raise RuntimeError("Unrecognized packet type. You sent: "+hex(packettype))
        if e:
            raise RuntimeError("Error happened during transmit of above packet.")

    #Returns 3-tuple: (machineid,commandid,bytearray(data))
    @classmethod
    def getpacket(cls,delay=2000):
        retry,macid,comid,size = (0,0,0,0)
        arr2 = bytearray()
        while retry<4:
            arr1 = cls.getbytes(4,delay)
            if delay > 2000:    #IF we have an extralong first packet
                delay = 2000    #reduce the waiting time for other data incoming
            if (arr1 == -1) or (len(arr1)<4):
                raise RuntimeError("Recieved truncated packet. Got: "+hex(arr1))
            cls.bytesgotten += 4
            macid = arr1[0]
            comid = arr1[1]
            size = arr1[2]+arr1[3]*256
            if comid in cls.datapackets:
                #print("GETTING SIZE VAR "+hex(size))
                arr2 = cls.getbytes(size)
                if arr2 == -1 or len(arr2)<size:
                    print("Received bytes: "+hex(arr2))
                    raise RuntimeError("Incomplete data sent. Expected "+hex(size)+" bytes, got "+hex(len(arr2)))
                arr3 = cls.getbytes(2)
                if arr3 == -1 or len(arr3)<2:
                    raise RuntimeError("Checksum data did not receive")
                checksum = arr3[0] + arr3[1]*256
                actual = sum(arr2) & 0xFFFF
                cls.bytesgotten += size + 2
                if actual != checksum:
                    print("Checksum actual/recieved: "+hex([actual,checksum]))
                    print("Checksum error. Issuing checksum error packet for retry.")
                    retry += 1
                    cls.sendpacket(PV.ERR)
                    continue
            else:
                arr2 = bytearray()
            break
        if retry>=4:
            raise RuntimeError("Receive failure: Retried too many times")

        
        if comid in cls.datapackets:
            s = cls.datapackets[comid]
        elif comid in cls.barepackets:
            s = cls.barepackets[comid]
        else:
            s = "UNK ["+hex(arr1)+"] "
        s = "RECV "+s
        if arr2:
            s += " with data sized "+hex(len(arr2))
        if PACKET_DEBUG:
            print(s)
        
        return PACKET(macid,comid,arr2)

    #Note: prevcommand and prevdata is set if you send an initial request
    #and use this function to complete the transaction. Action indicates what
    #you want to do with the transaction if the other two arguments do not
    #supply enough information to make it obvious of what to do
    varfield = bytearray()
    vardata = bytearray()

    @classmethod
    def protocol_get(cls,action = 0):
        pass        #End of endless while loop
        return -1
    
    @classmethod
    def protocol_recvar(cls):
        # Upon calling, the calc should have recieved or about to receive
        # A request to send variable data from a TI (83+) calculator.
        # I cannot receive more than one variable. If any more than one is
        # sent, the prior buffer is discarded.
        p = cls.getpacket(99999)    #Long wait for first packet
        cls.bytesgotten = 0
        cls.bytessent = 0
        starttime = time.ticks_ms()
        if p.cid == PV.RDY:
            cls.sendpacket(PV.ACK)  #Acknolwedge RDY
        else:
            print("Did not receive RDY packet. Aborting.")
            return
        recv_var = False
        while True:
            p = cls.getpacket()     #Receiving whatever
            if p.cid == PV.RDY:
                cls.sendpacket(PV.ACK)
            if p.cid == PV.VAR:
                cls.varfield = p.data
                cls.sendpacket(PV.ACK)
                # At this point, you can examine the varfield data
                # and either send CTS packet, or send SKIP with error data
                cls.sendpacket(PV.CTS)
                recv_var = True #If CTS, set to receive variable data
            if p.cid == PV.DATA and recv_var == True:
                cls.vardata = p.data
                cls.sendpacket(PV.ACK)
                recv_var = False
            if p.cid == PV.EOT:
                cls.sendpacket(PV.ACK)
                try:
                    #Flash transfers sometimes sends two EOTs
                    p = cls.getpacket(200)
                    if p.cid == PV.EOT:
                        cls.sendpacket(PV.ACK)
                except:
                    pass
                print("Transfer complete.")
                print("Bytes received: "+hex(cls.bytesgotten))
                print("Bytes sent: "+hex(cls.bytessent))
                print("Time elapsed: "+str(time.ticks_diff(time.ticks_ms(),starttime)/1000))
                break
    @classmethod
    def formheader(cls,size,vartype,name,isarchived=False,version=0,type2=0):
        d = bytearray(13)
        d[0] = size & 255
        d[1] = (size >> 8) & 255
        d[2] = vartype
        d[3:3+len(name)] = bytearray(name)
        d[11] = version
        d[12] = (type2 & 127) | (128 if isarchived else 0)
        return d


    @classmethod
    def getvarlist(cls,reportonly = -1):
        cls.bytesgotten = 0
        cls.bytessent = 0
        starttime = time.ticks_ms()
        cls.sendpacket(PV.REQ,cls.formheader(0,VID.DIR,""))
        d = cls.getpacket()
        if d.cid != PV.ACK:
            print("Variable request failure. Request not acknowledged.")
            return -1
        d = cls.getpacket() #Should be data packet containing free RAM
        print("Free RAM reported: "+hex(d.data[0] + d.data[1] * 256))
        cls.sendpacket(PV.ACK)
        while True:
            d = cls.getpacket()
            if d.cid == PV.EOT:
                cls.sendpacket(PV.ACK)
                print("End of variable list")
                return 0
            elif d.cid == PV.VAR:
                cls.sendpacket(PV.ACK)
                name = d.data[3:3+8].decode().strip('\x00')
                size = d.data[0] + d.data[1]*256
                vtype = d.data[2]
                ver1 = d.data[11]
                ver2 = d.data[12] & 127
                isarc = True if d.data[12] & 128 else False
                isarcs = "ARCHIVED" if isarc else "IN RAM"
                if reportonly < 0 or reportonly == vtype:
                    print("VAR ["+hex(vtype)+"] ("+VID.tostring(vtype)+"): " + name + " , SIZE "+hex(size)+", IS "+isarcs)
            else:
                print("Unrecognized packet received. Aborting.")
                return -1


    print("TILINK class initialized")
    
t = TILINK
def get():
    databuf = []
    data = 0
    while True:
        data = TILINK.get()
        if data < 0:
            return databuf
        else:
            databuf.append(hex(data))
def reset():
    TILINK.sm.restart()
    TILINK.sm.active(1)
    machine.mem32[PIO0_BASE+SM0_INSTR] = TILINK.smgo

def debug():
    print("Start instruction: "+decode_pio(TILINK.smstop,2,True))
    print(decode_pio(machine.mem32[PIO0_BASE+SM0_INSTR],2,True))
    print("Is stalled? "+str(True if machine.mem32[PIO0_BASE+SM0_INSTR]>>31&1 else False))
def dbg():
    while True:
        print("Curinst: "+decode_pio(machine.mem32[PIO0_BASE+SM0_INSTR],2,True)+"       ",end='\r')
def getproto():
    TILINK.protocol_get()

print("Helpful notes:")
print("t = TILINK")
print("Available functions for using TILINK:")
print("protocol_recvar()")
print("getvarlist()")
