import struct

try:
    from Cryptodome.Cipher import AES
except ImportError:
    from Crypto.Cipher import AES  # https://www.dlitz.net/software/pycrypto/


def unpack64bit(s):
    return struct.unpack(">Q", s)[0]


def pack64bit(s):
    return struct.pack(">Q", s)


def AESUnwrap(kek=None, wrapped=None):
    key = kek

    C = []
    for i in range(len(wrapped) // 8):
        C.append(unpack64bit(wrapped[i*8:i*8+8]))
    n = len(C) - 1
    R = [0] * (n + 1)
    A = C[0]

    for i in range(1, n + 1):
        R[i] = C[i]

    for j in reversed(range(0, 6)):
        for i in reversed(range(1, n + 1)):
            todec = pack64bit(A ^ (n*j+i))
            todec += pack64bit(R[i])
            B = AES.new(key, AES.MODE_ECB).decrypt(todec)
            A = unpack64bit(B[:8])
            R[i] = unpack64bit(B[8:])

    if A != 0xa6a6a6a6a6a6a6a6:
        return None
    res = b"".join(map(pack64bit, R[1:]))
    return res


def removePadding(blocksize, s):
    'Remove RFC1423 padding from string.'

    n = s[-1]  # last byte contains number of padding bytes

    if n > blocksize or n > len(s):
        raise Exception('invalid padding')

    return s[:-n]


def AESdecryptCBC(data, key, iv=b'\x00'*16, padding=False):
    todec = data

    if len(data) % 16:
        todec = data[0:(len(data) // 16) * 16]

    dec = AES.new(key, AES.MODE_CBC, iv).decrypt(todec)

    if padding:
        return removePadding(16, dec)

    return dec


def loopTLVBlocks(blob):
    i = 0
    while i + 8 <= len(blob):
        tag = blob[i:i+4]
        length = struct.unpack(">L", blob[i+4:i+8])[0]
        data = blob[i+8:i+8+length]
        yield (tag, data)
        i += 8 + length
