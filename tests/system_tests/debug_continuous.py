#!/usr/bin/env python3
def decode_b_type(instr):
    imm_12 = (instr >> 31) & 0x1
    imm_10_5 = (instr >> 25) & 0x3F
    rs2 = (instr >> 20) & 0x1F
    rs1 = (instr >> 15) & 0x1F
    funct3 = (instr >> 12) & 0x7
    imm_4_1 = (instr >> 8) & 0xF
    imm_11 = (instr >> 7) & 0x1

    # Reconstruct immediate
    imm = (imm_12 << 11) | (imm_11 << 10) | (imm_10_5 << 4) | imm_4_1
    imm = imm << 1

    # Sign extend from 13 bits
    if imm & (1 << 12):
        imm = imm | (~0x1FFF)
        if imm & 0x8000:
            imm = -(0x10000 - (imm & 0xFFFF))

    return rs1, rs2, imm

print("Decoding BNE at PC=0x14:")
print("Instruction: 0xfe609ce3")
rs1, rs2, offset = decode_b_type(0xfe609ce3)
print(f"BNE x{rs1}, x{rs2}, {offset}")
print(f"Target: 0x14 + {offset} = 0x{0x14 + offset:02x}")

print("\nExpected: BNE x1, x6, -8")
print("Should jump to: 0x14 + (-8) = 0x0C")
