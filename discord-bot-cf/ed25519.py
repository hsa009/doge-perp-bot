import hashlib

p = (1 << 255) - 19
d = -121665 * pow(121666, p - 2, p) % p
I = pow(2, (p - 1) // 4, p)
Bx = 15112221349535807909032904464607456136274713599662279240055906836809290888532
By = 46316835694926478169428394003475163141307993866256225615783033603165251855960
l = (1 << 252) + 27742317777372353535851937790883648493


def modp(q):
    return q % p


def recover_x(y, sign):
    x2 = (y * y - 1) * pow(d * y * y + 1, p - 2, p) % p
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * I % p
    if x % 2 != sign:
        x = p - x
    return x


def decodepoint(s):
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = recover_x(y, sign)
    return x, y, 1, x * y % p


def point_add(P, Q):
    x1, y1, z1, t1 = P
    x2, y2, z2, t2 = Q
    A = (y1 - x1) * (y2 - x2) % p
    B = (y1 + x1) * (y2 + x2) % p
    C = t1 * 2 * d * t2 % p
    D = z1 * 2 * z2 % p
    E = B - A
    F = D - C
    G = D + C
    H = B + A
    return E * F % p, G * H % p, F * G % p, E * H % p


def point_mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = point_add(Q, P)
        P = point_add(P, P)
        s >>= 1
    return Q


def decodeint(s):
    return int.from_bytes(s, "little")


def encodeint(n):
    return n.to_bytes(32, "little")


def encodepoint(P):
    x, y, z, _ = P
    zi = pow(z, p - 2, p)
    return encodeint(y * zi % p)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    if len(public_key) != 32 or len(signature) != 64:
        return False
    A = decodepoint(public_key)
    r = decodeint(signature[:32])
    s = decodeint(signature[32:])
    if s >= l:
        return False
    h = hashlib.sha512(signature[:32] + public_key + message).digest()
    h = int.from_bytes(h, "little") % l
    B = (Bx, By, 1, Bx * By % p)
    sB = point_mul(s, B)
    hA = point_mul(h, A)
    neg_hA = (hA[0], modp(-hA[1]), hA[2], modp(-hA[3]))
    R_check = point_add(sB, neg_hA)
    return encodepoint(R_check) == encodeint(r)
