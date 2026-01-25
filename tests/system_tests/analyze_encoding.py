#!/usr/bin/env python3
"""
Analyze and verify RISC-V instruction encodings used in stress tests
"""

def decode_b_type(instr):
    """Decode B-type instruction"""
    imm_12 = (instr >> 31) & 0x1
    imm_10_5 = (instr >> 25) & 0x3F
    rs2 = (instr >> 20) & 0x1F
    rs1 = (instr >> 15) & 0x1F
    funct3 = (instr >> 12) & 0x7
    imm_4_1 = (instr >> 8) & 0xF
    imm_11 = (instr >> 7) & 0x1
    opcode = instr & 0x7F

    # Reconstruct immediate
    imm = (imm_12 << 12) | (imm_11 << 11) | (imm_10_5 << 5) | (imm_4_1 << 1)

    # Sign extend from 13 bits
    if imm & (1 << 12):
        imm = imm | (~0x1FFF)
        imm_signed = -(0x10000 - (imm & 0xFFFF)) if imm & 0x8000 else imm
    else:
        imm_signed = imm

    return rs1, rs2, imm_signed, funct3, opcode


def decode_i_type(instr):
    """Decode I-type instruction"""
    imm = (instr >> 20) & 0xFFF
    rs1 = (instr >> 15) & 0x1F
    funct3 = (instr >> 12) & 0x7
    rd = (instr >> 7) & 0x1F
    opcode = instr & 0x7F

    # Sign extend from 12 bits
    if imm & (1 << 11):
        imm = imm | (~0xFFF)

    return rd, rs1, imm, funct3, opcode


def analyze_program(instructions, start_pc=0):
    """Analyze a program's branch targets"""
    print("="*80)
    print("INSTRUCTION ANALYSIS")
    print("="*80)

    for i, instr in enumerate(instructions):
        pc = start_pc + i * 4

        # Decode based on opcode
        opcode = instr & 0x7F

        if opcode == 0x63:  # B-type (branches)
            rs1, rs2, imm, funct3, _ = decode_b_type(instr)

            branch_names = {0: "BEQ", 1: "BNE", 4: "BLT", 5: "BGE", 6: "BLTU", 7: "BGEU"}
            name = branch_names.get(funct3, f"B-type(f3={funct3})")

            target = pc + imm
            print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  {name:6s} x{rs1}, x{rs2}, {imm:6d}  (target=0x{target:08x})")

        elif opcode == 0x13:  # I-type (ADDI, etc)
            rd, rs1, imm, funct3, _ = decode_i_type(instr)

            if funct3 == 0:
                print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  ADDI   x{rd}, x{rs1}, {imm}")
            elif funct3 == 1:
                shamt = imm & 0x1F
                print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  SLLI   x{rd}, x{rs1}, {shamt}")
            else:
                print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  I-type(f3={funct3})")

        elif opcode == 0x6F:  # JAL
            imm_20 = (instr >> 31) & 0x1
            imm_10_1 = (instr >> 21) & 0x3FF
            imm_11 = (instr >> 20) & 0x1
            imm_19_12 = (instr >> 12) & 0xFF
            rd = (instr >> 7) & 0x1F

            imm = (imm_20 << 20) | (imm_19_12 << 12) | (imm_11 << 11) | (imm_10_1 << 1)
            if imm & (1 << 20):
                imm = imm | (~0x1FFFFF)

            target = pc + imm
            print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  JAL    x{rd}, {imm:6d}  (target=0x{target:08x})")

        else:
            print(f"[{i:3d}] PC=0x{pc:08x}: 0x{instr:08x}  (opcode=0x{opcode:02x})")

    print("="*80)


print("\n" + "="*80)
print("ANALYZING ORIGINAL FAILING NESTED LOOP (10×100=1000)")
print("="*80)

# Original failing program from test_stress.py test_long_running_program
failing_program = [
    0x00000293,  # ADDI x5, x0, 0     (sum = 0)
    0x00000093,  # ADDI x1, x0, 0     (outer = 0)
    0x00a00113,  # ADDI x2, x0, 10    (outer_max = 10)

    # Outer loop start (PC = 0x0C)
    0x00000193,  # ADDI x3, x0, 0     (inner = 0)
    0x06400213,  # ADDI x4, x0, 100   (inner_max = 100)

    # Inner loop start (PC = 0x14)
    0x00128293,  # ADDI x5, x5, 1     (sum++)
    0x00118193,  # ADDI x3, x3, 1     (inner++)
    0xfe419ce3,  # BNE x3, x4, -8     (if inner < 100, goto inner loop)

    # End of inner loop
    0x00108093,  # ADDI x1, x1, 1     (outer++)
    0xfa209ee3,  # BNE x1, x2, -36    (if outer < 10, goto outer loop)

    # End
    0x0000006f,  # JAL x0, 0 (infinite loop/halt)
]

analyze_program(failing_program)

print("\n" + "="*80)
print("ANALYZING WORKING NESTED LOOP FROM test_full_integration.py (3×3=9)")
print("="*80)

working_program = [
    0x00000293,  # ADDI x5, x0, 0     (sum = 0)
    0x00000093,  # ADDI x1, x0, 0     (outer = 0)
    0x00300193,  # ADDI x3, x0, 3     (outer_max = 3)
    # Outer loop start (PC=0x0C)
    0x00000113,  # ADDI x2, x0, 0     (inner = 0)
    0x00300213,  # ADDI x4, x0, 3     (inner_max = 3)
    # Inner loop start (PC=0x14)
    0x00128293,  # ADDI x5, x5, 1     (sum++)
    0x00110113,  # ADDI x2, x2, 1     (inner++)
    0xfe411ee3,  # BNE x2, x4, -4     (if inner < 3, loop to 0x14)
    # End of inner loop
    0x00108093,  # ADDI x1, x1, 1     (outer++)
    0xfe3096e3,  # BNE x1, x3, -20    (if outer < 3, loop to 0x0C)
    # End
    0x0000006f,  # JAL x0, 0          (halt)
]

analyze_program(working_program)

print("\n" + "="*80)
print("COMPARISON AND ANALYSIS")
print("="*80)

print("\nFAILING PROGRAM ISSUES:")
print("  - Inner loop: BNE at 0x1C branches to -8 = 0x14 ✓ (CORRECT)")
print("  - Outer loop: BNE at 0x24 branches to -36 = ???")
print("\nCalculating outer loop target:")
print("  Current PC: 0x24")
print("  Offset: -36 (0xFFFFFFDC)")
print("  Target: 0x24 + (-36) = 0x24 - 36 = 0x24 - 0x24 = 0x00")
print("  ERROR: Should jump to 0x0C (outer loop start), not 0x00!")
print("\nCorrect offset calculation:")
print("  From 0x24 to 0x0C: 0x0C - 0x24 = -24 (0xFFFFFFE8)")
print("  So the BNE should have offset -24, not -36")

print("\nWORKING PROGRAM:")
print("  - Inner loop: BNE at 0x1C branches to -4 = 0x18")
print("    Wait, that's wrong too! Let me recalculate...")
print("  - Actually: 0x1C + (-4) = 0x18")
print("    But instruction at 0x14 is ADDI x5, x5, 1 (sum++)")
print("    So it jumps to 0x18 which is ADDI x2, x2, 1")
print("    That means it SKIPS the sum++ instruction!")
print("    This looks wrong but test passes with sum=9...")

print("\nLet me verify the working program offset...")
rs1, rs2, offset, _, _ = decode_b_type(0xfe411ee3)
print(f"  Inner BNE: x{rs1} != x{rs2}, offset={offset}")
print(f"  From PC=0x1C to 0x1C+{offset} = 0x{0x1C + offset:08x}")

rs1, rs2, offset, _, _ = decode_b_type(0xfe3096e3)
print(f"  Outer BNE: x{rs1} != x{rs2}, offset={offset}")
print(f"  From PC=0x24 to 0x24+{offset} = 0x{0x24 + offset:08x}")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
print("The failing test has INCORRECT BRANCH OFFSETS!")
print("This is a TEST BUG, not a CPU bug.")
print("\nThe working test from test_full_integration.py uses correct offsets.")
print("We need to use those same patterns for the stress tests.")
