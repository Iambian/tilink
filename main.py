import micropython
micropython.alloc_emergency_exception_buf(100)
from micropython import const
import uctypes,rp2,time,machine,random,array,collections
from machine import Pin
from rp2 import PIO
import builtins
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
        'freq' : 50000,
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
        if not fstat & const(1<<8):     #Check if rxf0empty. Get byte if not.
            if TILINK.rxsize < 127:
                TILINK.rxsize += 1
                TILINK.rxbuf[TILINK.rxbuftail] = machine.mem32[PIO0_BASE+PIO_RXF0] >> 24
                TILINK.rxbuftail = TILINK.rxbuftail+1 & 127
        else:
            print("Data dropped with fstat condition code"+hex(fstat))
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
            print("Sent: "+hex(data[i:i+4]))
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
        cls.rxbufhead += 1
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

    #Note: prevcommand and prevdata is set if you send an initial request
    #and use this function to complete the transaction. Action indicates what
    #you want to do with the transaction if the other two arguments do not
    #supply enough information to make it obvious of what to do
    @classmethod
    def protocol_get(cls,prevcommand = 0, prevdata=[],action = 0):
        state = 0       #Recieve state. Receiving packet and/or data
        packet = bytearray(4)
        arr = bytearray()
        arr2 = bytearray()
        machineid = 0
        commandid = 0
        delay = 999999  #Wait a really long time for that first packet
        while True:
            if 0==state:    #Receiving packet.
                arr = cls.getbytes(4,delay)
                delay = 2000    #Go back to waiting 2 secs between each packet.
                if len(arr)<4:
                    raise Exception("Truncated base packet. Received "+hex(arr))
                machineid = arr[0]
                commandid = arr[1]
                datalen = arr[2] + arr[3]*256
                if datalen and commandid in (0x06,0x15,0x36,0x88,0xA2,0xC9):
                    arr2 = cls.getbytes(datalen)
                    if arr2 == -1:
                        raise Exception("Truncated data section. Expected "+hex(datalen)+" bytes, received "+str(arr2))
                    arr3 = cls.getbytes(2)
                    if arr2 == -1 or len(arr2) < 2:
                        raise Exception("Checksum bytes not sent. Recieved: "+str(arr3))
                    checksum = arr3[0] + arr3[1]*256
                    if sum(arr2) != checksum:
                        print("Expected checksum "+str(sum(arr2)+", got "+str(checksum)))
                        raise Exception("Recieved data does not match checksum.")
                else:
                    arr2 = bytearray()
                state = 1
                print("Recieved base packet: "+hex(arr))
                if arr2:
                    print("Also recieved data: "+hex(arr2))
            if 1==state:    #Process recieved packet
                if machineid not in (0x02,0x03,0x23,0x73,0x82,0x83):
                    raise Exception("Invalid machine ID. Received: "+str(machineid))
                if 0x09 == commandid:
                    print("CTS received")
                    state=0
                elif 0x06 == commandid:
                    print("Variable header received: "+str(arr2))
                    prevdata = arr2[:]
                    prevcommand = commandid
                    cls.send([0x73,0x56,0x00,0x00]) #ACK
                    cls.send([0x73,0x09,0x00,0x00]) #CTS
                    state=0
                elif 0x15 == commandid:
                    print("DATA packet recieved: "+str(arr2))
                    state=0
                elif 0x36 == commandid:
                    print("Skip/Exit packet received: "+str(arr2))
                    print("Note: Rejection codes: 0x1=EXIT, 0x2=SKIP, 0x3=NOMEM")
                    state=0
                elif 0x56 == commandid:
                    print("ACK packet received.")
                    state=0
                elif 0x5A == commandid:
                    print("Checksum error packet received.")
                    state=0
                elif 0x68 == commandid:
                    print("RDY packet received.")
                    cls.send([0x73,0x56,0x00,0x00])
                    state=0
                elif 0x6D == commandid:
                    print("Silent screeshot request packet received.")
                    state=0
                elif 0x88 == commandid:
                    print("Silent delete variable request packet received.")
                    print("Name of variable to delete: "+str(arr2))
                    state=0
                elif 0x92 == commandid:
                    print("End of transmission packet recieved.")
                    return 0
                elif 0xA2 == commandid:
                    print("Silent request variable request received.")
                    print("Name of variable being requested: "+str(arr2))
                    state=0
                elif 0xC9 == commandid:
                    print("Silent request to send variable request received")
                    print("Name of variable being sent: "+str(arr2))
                    state=0
                else:
                    print("Unrecognized command byte recieved: "+str(commandid))
                    state=0
            pass    #End of 1==state statement
        pass        #End of endless while loop
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

