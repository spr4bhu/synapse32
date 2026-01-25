#!/usr/bin/env python3
# Debug the nested loop encoding

def encode_b_type(opcode, funct3, rs1, rs2, imm):
    imm = imm & 0x1FFF
    imm_12 = (imm >> 12) & 0x1
    imm_10_5 = (imm >> 5) & 0x3F
    imm_4_1 = (imm >> 1) & 0xF
    imm_11 = (imm >> 11) & 0x1
    return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

def BNE(rs1, rs2, imm):
    return encode_b_type(0x63, 0x1, rs1, rs2, imm)

def ADDI(rd, rs1, imm):
    imm = imm & 0xFFF
    return (imm << 20) | (rs1 << 15) | (0x0 << 12) | (rd << 7) | 0x13

# Generate the nested loop program
instructions = [
    ADDI(5, 0, 0),       # sum = 0
    ADDI(1, 0, 0),       # outer = 0
    ADDI(3, 0, 10),      # outer_limit = 10
    # Outer loop start (PC=0x0C)
    ADDI(2, 0, 0),       # inner = 0
    ADDI(4, 0, 100),     # inner_limit = 100
    # Inner loop start (PC=0x14)
    ADDI(5, 5, 1),       # sum++
    ADDI(2, 2, 1),       # inner++
    BNE(2, 4, -8),       # if inner != 100, goto 0x14
    # End of inner loop
    ADDI(1, 1, 1),       # outer++
    BNE(1, 3, -24),      # if outer != 10, goto 0x0C
]

print("Nested Loop Program Encodings:")
for i, instr in enumerate(instructions):
    pc = i * 4
    print(f"PC=0x{pc:02x}: 0x{instr:08x}")

# Decode the BNE instructions
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
    imm = imm << 1  # Shift left 1 (bit 0 is always 0)

    # Sign extend from 13 bits
    if imm & (1 << 12):
        imm = imm | (~0x1FFF)
        # Convert to signed
        if imm & 0x8000:
            imm = -(0x10000 - (imm & 0xFFFF))

    return rs1, rs2, imm

print("\nBNE Decoding:")
inner_bne = instructions[7]
rs1, rs2, offset = decode_b_type(inner_bne)
print(f"Inner BNE (PC=0x1C): BNE x{rs1}, x{rs2}, {offset}")
print(f"  Target: 0x1C + {offset} = 0x{0x1C + offset:02x}")

outer_bne = instructions[9]
rs1, rs2, offset = decode_b_type(outer_bne)
print(f"Outer BNE (PC=0x24): BNE x{rs1}, x{rs2}, {offset}")
print(f"  Target: 0x24 + {offset} = 0x{0x24 + offset:02x}")
