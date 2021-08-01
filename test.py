import sys,os,builtins

def hex(value):
    try:
        if type(value) is int:
            return builtins.hex(value)
        if type(value) is str and len(value)>0:
            return str([builtins.hex(ord(i)) for i in value])
        if iter(value) and len(value) > 0:
            return str([builtins.hex(i) for i in value])
        return str([])
    except Exception as e:
        sys.print_exception(e)
        return "<NO REPR>"

def dump(data):
    def chunk(data,chunksize):
        for i in range(0,len(data),chunksize):
            yield memoryview(data)[i:i+chunksize]
    for idx,i in enumerate(chunk(data,9)):
        print(hex(i))
