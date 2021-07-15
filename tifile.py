import os,sys

print("Program start")
with open("linktest.8xp","rb") as f:
    header = f.read(8)
    if header.decode("ascii") != "**TI83F*":
        raise Exception("Incorrect file header")
    signature = f.read(3)
    if signature != bytearray([0x1A,0x0A,0x00]):
        raise Exception("Incorrect file signature")
    if len(f.read(42)) != 42:
        raise Exception("Truncated file: Missing comment section.")
    f.read(2)   #skip over file data section length
    if f.read(2) != bytearray([0x0D,0x00]):
        raise Exception("Header length is incorrect")
    f.read(2)   #skip over initial size field
    type = f.read(1)
    name = f.read(8)
    ver = f.read(1)
    ver2 = f.read(1)
    h = f.read(2)
    size = h[0] + h[1] * 256
    data = f.read(size)
    print("type, name:"+hex(type[0])+" : "+str(name))
    print("size: "+str(size))
    print("Data: "+str(data))

print("Program end")


    
