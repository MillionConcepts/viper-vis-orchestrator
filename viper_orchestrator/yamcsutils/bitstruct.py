from cytoolz import take


class BitStruct:
    """
    Struct equivalent for bit-level data. example of usage:

    >>> PACKET_HEADER_SPEC = {'pvn': 3, 'type': 1, 'secflag': 1, 'apid': 11}
    >>> bstruct = BitStruct(PACKET_HEADER_SPEC)
    >>> print(bstruct)
    >>> print(bstruct.unpack(3075))

    BitStruct:
    pvn:     0b1110000000000000
    type:    0b0001000000000000
    secflag: 0b0000100000000000
    apid:    0b0000011111111111

    {'pvn': 0, 'type': 0, 'secflag': 1, 'apid': 1027}
    """
    def __init__(self, spec: dict[str, int]):
        size = sum(spec.values())
        if size % 8 != 0:
            raise ValueError("Spec is not byte-aligned.")
        pos, base, mod, exp, biterator = {}, {}, {}, {}, reversed(range(size))
        for k, v in spec.items():
            bits = tuple(take(v, biterator))
            pos[k] = sum(2 ** b for b in bits)
            exp[k] = 2 ** bits[-1]
            mod[k] = 2 ** v
        self.spec = spec
        self.positions = pos
        self.size = size
        self.exp = exp
        self.mod = mod

    def asbin(self) -> dict[str, str]:
        formatted = {}
        for k, v in self.positions.items():
            binstring = bin(v)[2:]
            missing = self.size - len(binstring)
            formatted[k] = f"0b{'0' * missing}{binstring}"
        return formatted

    def unpack(self, number: int) -> dict[str, int]:
        if number > 2 ** self.size - 1:
            raise ValueError(f"{number} is out of bounds for this structure.")
        return {
            k: max(((number & self.positions[k]) - (self.exp[k] - 1)), 0)
            for k, v in self.positions.items()
        }

    def pack(self, fields: dict[str, int]):
        if set(fields.keys()) != set(self.spec.keys()):
            raise ValueError("Fields are incompatible with this structure.")
        number = 0
        for k, v in fields.items():
            if v > self.mod[k]:
                raise ValueError(f"{v} too large for field {k}.")
            number += self.exp[k] * v
        return number

    def __str__(self) -> str:
        selfstring = "BitStruct:\n"
        asbin = self.asbin()
        minpad = max(map(len, asbin.keys())) + 1
        for k, v in asbin.items():
            padlen = minpad - len(k)
            selfstring += f"{k}:{' ' * padlen}{v}\n"
        return selfstring

    def __repr__(self) -> str:
        return self.__str__()