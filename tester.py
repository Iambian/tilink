import time
import rp2

@rp2.asm_pio()
def test():
    wrap_target()
    nop()   [31]
    nop()   [31]
    nop()   [31]
    nop()   [31]
    irq(block,0)
    nop()   [31]
    nop()   [31]
    nop()   [31]
    nop()   [31]
    irq(1)
    wrap()

def isr(pio):
    print(pio.irq().flags(),end='')


rp2.PIO(0).irq(isr)

sm = rp2.StateMachine(0,test,freq=2000)
sm.active(1)
time.sleep(1)
sm.active(0)

