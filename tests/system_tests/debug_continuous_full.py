#!/usr/bin/env python3
def encode_i_type(opcode, rd, funct3, rs1, imm):
    imm = imm & 0xFFF
    return (imm << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_b_type(opcode, funct3, rs1, rs2, imm):
    imm = imm & 0x1FFF
    imm_12 = (imm >> 12) & 0x1
    imm_10_5 = (imm >> 5) & 0x3F
    imm_4_1 = (imm >> 1) & 0xF
    imm_11 = (imm >> 11) & 0x1
    return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

def ADDI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x0, rs1, imm)

def BNE(rs1, rs2, imm):
    return encode_b_type(0x63, 0x1, rs1, rs2, imm)

def JAL(rd, imm):
    return encode_j_type(0x6F, rd, imm)

def encode_j_type(opcode, rd, imm):
    imm = imm & 0x1FFFFF
    imm_20 = (imm >> 20) & 0x1
    imm_10_1 = (imm >> 1) & 0x3FF
    imm_11 = (imm >> 11) & 0x1
    imm_19_12 = (imm >> 12) & 0xFF
    return (imm_20 << 31) | (imm_10_1 << 21) | (imm_11 << 20) | \
           (imm_19_12 << 12) | (rd << 7) | opcode

def HALT():
    return JAL(0, 0)

# My program
instructions = [
    ADDI(5, 0, 0),       # sum = 0 (x5)
    ADDI(1, 0, 0),       # counter = 0 (x1)
    ADDI(6, 0, 20),      # max = 20 (x6)
    # Simple loop (PC = 0x0C)
    ADDI(5, 5, 1),       # sum++
    ADDI(1, 1, 1),       # counter++
    BNE(1, 6, -8),       # if counter != 20, loop back to 0x0C
    # Done
    HALT()
]

print("My program encodings:")
for i, instr in enumerate(instructions):
    pc = i * 4
    print(f"[{i:2d}] PC=0x{pc:02x}: 0x{instr:08x}")

print("\n\nLogged instructions from test:")
logged = [
    (0, 0x00000000, 0x00000293),
    (1, 0x00000004, 0x00000093),
    (2, 0x00000008, 0x01400313),
    (5, 0x00000014, 0xfe609ce3),
    (6, 0x00000018, 0x0000006f),
]

for idx, pc, instr in logged:
    print(f"[{idx:2d}] PC=0x{pc:02x}: 0x{instr:08x}")

# Decode instruction 2
instr = 0x01400313
imm = (instr >> 20) & 0xFFF
rs1 = (instr >> 15) & 0x1F
rd = (instr >> 7) & 0x1F
if imm & 0x800:
    imm = imm - 0x1000
print(f"\nDecoding 0x01400313:")
print(f"  ADDI x{rd}, x{rs1}, {imm}")
print(f"  Expected: ADDI x6, x0, 20")
print(f"  Actual: ADDI x6, x0, {imm}")
