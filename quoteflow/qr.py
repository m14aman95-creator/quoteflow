"""Minimal QR Code generator: byte mode, error-correction level M, versions 1-10, output as inline SVG.
No dependencies. Used to print a QR code for the customer portal link."""

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]

# version -> (ec codewords per block, [(block count, data codewords per block), ...]) for level M
_M = {1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
      6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
      10: (26, [(4, 43), (1, 44)])}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
          9: [6, 26, 46], 10: [6, 28, 50]}


def _mul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _generator(deg):
    g = [1]
    for i in range(deg):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= c
            ng[j + 1] ^= _mul(c, _EXP[i])
        g = ng
    return g


def _remainder(data, deg):
    gen = _generator(deg)
    rem = [0] * deg
    for b in data:
        factor = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(deg):
            rem[i] ^= _mul(gen[i + 1], factor)
    return rem


def _data_codewords(version):
    return sum(n * d for n, d in _M[version][1])


def _bit(v, i):
    return (v >> i) & 1 == 1


def _codewords(payload: bytes, version: int):
    cap = _data_codewords(version)
    bits = "0100" + format(len(payload), "08b" if version <= 9 else "016b") + "".join(format(b, "08b") for b in payload)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = 0
    while len(data) < cap:
        data.append(0xEC if pad % 2 == 0 else 0x11)
        pad += 1
    ec_len, groups = _M[version]
    blocks, pos = [], 0
    for count, size in groups:
        for _ in range(count):
            blocks.append(data[pos:pos + size])
            pos += size
    ecs = [_remainder(b, ec_len) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        for b in blocks:
            if i < len(b):
                out.append(b[i])
    for i in range(ec_len):
        for e in ecs:
            out.append(e[i])
    return out


class _Matrix:
    def __init__(self, version):
        self.v = version
        self.n = 17 + 4 * version
        self.m = [[False] * self.n for _ in range(self.n)]
        self.f = [[False] * self.n for _ in range(self.n)]
        n = self.n
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = _ALIGN[version]
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)
        self._format(0)                       # reserve the format areas
        if version >= 7:
            rem = version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = version << 12 | rem
            for i in range(18):
                a, b = n - 11 + i % 3, i // 3
                self._set(a, b, _bit(bits, i))
                self._set(b, a, _bit(bits, i))

    def _set(self, x, y, dark):
        self.m[y][x] = dark
        self.f[y][x] = True

    def _format(self, mask):
        n = self.n
        data = (0 << 3) | mask                 # level M = 00
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        for i in range(6):
            self._set(8, i, _bit(bits, i))
        self._set(8, 7, _bit(bits, 6))
        self._set(8, 8, _bit(bits, 7))
        self._set(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self._set(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self._set(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, _bit(bits, i))
        self._set(8, n - 8, True)

    def place(self, codewords):
        n, i = self.n, 0
        total = len(codewords) * 8
        for right in range(n - 1, 0, -2):
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    y = n - 1 - vert if ((right + 1) & 2) == 0 else vert
                    if not self.f[y][x] and i < total:
                        self.m[y][x] = _bit(codewords[i >> 3], 7 - (i & 7))
                        i += 1

    def mask(self, k):
        for y in range(self.n):
            for x in range(self.n):
                inv = [(x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
                       x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0][k]
                if inv and not self.f[y][x]:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self):
        n, m, score = self.n, self.m, 0
        rows = ["".join("1" if c else "0" for c in r) for r in m]
        cols = ["".join("1" if m[y][x] else "0" for y in range(n)) for x in range(n)]
        for line in rows + cols:
            run = 1
            for a in range(1, n):
                if line[a] == line[a - 1]:
                    run += 1
                else:
                    score += 3 + run - 5 if run >= 5 else 0
                    run = 1
            score += 3 + run - 5 if run >= 5 else 0
            for pat in ("10111010000", "00001011101"):
                start = line.find(pat)
                while start != -1:
                    score += 40
                    start = line.find(pat, start + 1)
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(r.count("1") for r in rows)
        score += abs(dark * 100 // (n * n) - 50) // 5 * 10
        return score


def qr_matrix(text: str):
    payload = text.encode("utf-8")
    version = next((v for v in range(1, 11)
                    if len(payload) <= (_data_codewords(v) * 8 - 4 - (8 if v <= 9 else 16)) // 8), None)
    if version is None:
        raise ValueError("text too long for this QR generator")
    words = _codewords(payload, version)
    best = None
    for k in (0, 2, 3, 4, 5, 6, 7):          # any of the 8 masks is valid; mask 1 is skipped (some scanners are fussy with it)
        mx = _Matrix(version)
        mx.place(words)
        mx.mask(k)
        mx._format(k)
        score = mx.penalty()
        if best is None or score < best[0]:
            best = (score, mx.m)
    return best[1]


def qr_svg(text: str, quiet: int = 4) -> str:
    """The QR code for `text` as an inline SVG string ('' if the text is too long)."""
    try:
        m = qr_matrix(text)
    except ValueError:
        return ""
    n = len(m)
    path = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                path.append(f"M{start + quiet},{y + quiet}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    size = n + 2 * quiet
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges" '
            f'role="img" aria-label="QR code"><rect width="{size}" height="{size}" fill="#fff"/>'
            f'<path d="{"".join(path)}" fill="#000"/></svg>')
