"""
Test stall + flush interaction - the exact scenario described:
"During a stall, special logic asserts a 'stall' signal that disables
the pipeline registers for the IF and ID stages. At the same time,
a 'flush' signal might be used to force a NOP into the EX stage,
which acts as a bubble that moves through the pipeline."

This tests whether valid bits properly track bubbles through stalls and flushes.
"""

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.clock import Clock
import os


def create_stall_flush_test_hex():
    """Create test that specifically exercises stall + flush interaction"""

    def encode_i_type(imm, rs1, funct3, rd, opcode):
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    def encode_b_type(imm, rs2, rs1, funct3, opcode):
        imm_12 = (imm >> 12) & 0x1
        imm_10_5 = (imm >> 5) & 0x3F
        imm_4_1 = (imm >> 1) & 0xF
        imm_11 = (imm >> 11) & 0x1
        return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

    def encode_s_type(imm, rs2, rs1, funct3, opcode):
        imm_11_5 = (imm >> 5) & 0x7F
        imm_4_0 = imm & 0x1F
        return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

    def encode_u_type(imm, rd, opcode):
        return ((imm & 0xFFFFF) << 12) | (rd << 7) | opcode

    instructions = []

    # Setup
    instructions.append(encode_u_type(0x10000, 4, 0x37))          # lui x4, 0x10000 (data base)

    # TEST 1: Load-use stall creates bubble, then immediate flush
    # This is THE critical test case
    #
    # Cycle N:   lw x5, 0(x4)          [in EX - will create stall]
    # Cycle N+1: add x6, x5, x5        [in ID - load-use detected, STALL asserted]
    #            Bubble inserted into EX (valid=0)
    #            IF and ID stages freeze
    # Cycle N+2: beq x0, x0, target    [THIS instruction should be in IF when stall happens]
    #            Stall continues... but then branch executes
    #            FLUSH occurs while bubble is in pipeline!
    #
    # Critical question: Does the bubble maintain valid=0 through the flush?
    # Do the stalled instructions get properly flushed?

    instructions.append(encode_i_type(100, 0, 0, 7, 0x13))       # addi x7, x0, 100
    instructions.append(encode_s_type(0, 7, 4, 2, 0x23))         # sw x7, 0(x4) [store 100]

    instructions.append(encode_i_type(0, 4, 2, 5, 0x03))         # lw x5, 0(x4) [load 100, creates stall]
    instructions.append(encode_i_type(0, 5, 0, 6, 0x13))         # addi x6, x5, 0 [load-use stall]
    instructions.append(encode_b_type(12, 0, 0, 0, 0x63))        # beq x0, x0, +12 [branch during/after stall]
    instructions.append(encode_i_type(999, 0, 0, 10, 0x13))      # addi x10, x0, 999 [MUST BE FLUSHED]
    instructions.append(encode_i_type(888, 0, 0, 11, 0x13))      # addi x11, x0, 888 [MUST BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(42, 0, 0, 12, 0x13))       # addi x12, x0, 42 [target]

    # Expected results:
    # x5 = 100 (loaded successfully)
    # x6 = 100 (add executed after stall resolved)
    # x10 = 0 (flushed, must NOT execute)
    # x11 = 0 (flushed, must NOT execute)
    # x12 = 42 (branch target, must execute)

    # TEST 2: Multiple stalls with flush in middle
    instructions.append(encode_i_type(200, 0, 0, 8, 0x13))       # addi x8, x0, 200
    instructions.append(encode_s_type(4, 8, 4, 2, 0x23))         # sw x8, 4(x4)

    instructions.append(encode_i_type(4, 4, 2, 13, 0x03))        # lw x13, 4(x4) [load 200]
    instructions.append(encode_i_type(0, 13, 0, 14, 0x13))       # addi x14, x13, 0 [stall 1]
    instructions.append(encode_i_type(0, 14, 0, 15, 0x13))       # addi x15, x14, 0 [stall 2?]
    instructions.append(encode_b_type(8, 0, 0, 0, 0x63))         # beq x0, x0, +8 [flush during stalls]
    instructions.append(encode_i_type(777, 0, 0, 16, 0x13))      # addi x16, x0, 777 [MUST BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(55, 0, 0, 17, 0x13))       # addi x17, x0, 55

    # Expected:
    # x13 = 200
    # x14 = 200
    # x15 = 200
    # x16 = 0 (flushed)
    # x17 = 55 (target)

    # TEST 3: Bubble propagation through multiple stages during flush
    # Create a long dependency chain that creates multiple bubbles
    instructions.append(encode_i_type(50, 0, 0, 9, 0x13))        # addi x9, x0, 50
    instructions.append(encode_s_type(8, 9, 4, 2, 0x23))         # sw x9, 8(x4)

    instructions.append(encode_i_type(8, 4, 2, 18, 0x03))        # lw x18, 8(x4)
    instructions.append(encode_i_type(1, 18, 0, 19, 0x13))       # addi x19, x18, 1 [stall, then x19=51]
    instructions.append(encode_i_type(1, 19, 0, 20, 0x13))       # addi x20, x19, 1 [x20=52]
    instructions.append(encode_b_type(8, 0, 0, 0, 0x63))         # beq x0, x0, +8 [branch]
    instructions.append(encode_i_type(666, 0, 0, 21, 0x13))      # addi x21, x0, 666 [FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(1, 20, 0, 22, 0x13))       # addi x22, x20, 1 [x22=53]

    # Expected:
    # x18 = 50
    # x19 = 51
    # x20 = 52
    # x21 = 0 (flushed)
    # x22 = 53

    # Signal completion
    instructions.append(encode_u_type(0x10000, 1, 0x37))         # lui x1, 0x10000
    instructions.append(encode_i_type(0xFF, 1, 0, 1, 0x13))      # addi x1, x1, 0xFF
    instructions.append(encode_s_type(0, 0, 1, 2, 0x23))         # sw x0, 0(x1) (CPU_DONE)

    # Write to hex file
    hex_file = os.path.join(os.path.dirname(__file__), "build", "stall_flush_test.hex")
    os.makedirs(os.path.dirname(hex_file), exist_ok=True)
    with open(hex_file, 'w') as f:
        for instr in instructions:
            f.write(f"{instr:08x}\n")

    return hex_file


@cocotb.test()
async def test_stall_flush_interaction(dut):
    """Test that stalls + flushes work correctly with valid bits"""

    hex_file = create_stall_flush_test_hex()
    cocotb.log.info(f"Created stall-flush interaction test: {hex_file}")

    # Start clock
    cocotb.start_soon(Clock(dut.clk, 10, units='ns').start())

    # Reset
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Track register writes
    register_state = {i: 0 for i in range(32)}
    cpu_inst = dut.top_inst.cpu_inst

    for cycle in range(300):
        await RisingEdge(dut.clk)

        # Track writes
        if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
            rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
            rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
            if rd_addr != 0:
                register_state[rd_addr] = rd_value
                if rd_addr >= 5:  # Only log our test registers
                    cocotb.log.info(f"Cycle {cycle}: x{rd_addr} = {rd_value}")

    # Check results
    cocotb.log.info("\n" + "="*70)
    cocotb.log.info("STALL + FLUSH INTERACTION TEST RESULTS")
    cocotb.log.info("="*70)

    failures = []
    checks = [
        # TEST 1: Load-use stall with flush
        (5, 100, "Load should complete"),
        (6, 100, "Add after load-use stall should execute"),
        (10, 0, "CRITICAL: Flushed during/after stall (x10 should be 0)"),
        (11, 0, "CRITICAL: Flushed during/after stall (x11 should be 0)"),
        (12, 42, "Branch target should execute"),

        # TEST 2: Multiple stalls with flush
        (13, 200, "Load should complete"),
        (14, 200, "First dependent should execute"),
        (15, 200, "Second dependent should execute"),
        (16, 0, "CRITICAL: Flushed during multiple stalls (x16 should be 0)"),
        (17, 55, "Branch target should execute"),

        # TEST 3: Bubble propagation
        (18, 50, "Load should complete"),
        (19, 51, "First dependent should execute"),
        (20, 52, "Second dependent should execute"),
        (21, 0, "CRITICAL: Flushed (x21 should be 0)"),
        (22, 53, "Branch target with dependency should execute"),
    ]

    for reg, expected, description in checks:
        actual = register_state[reg]
        if actual == expected:
            cocotb.log.info(f"✅ x{reg} = {actual} - {description}")
        else:
            cocotb.log.error(f"❌ x{reg} = {actual} (expected {expected}) - {description}")
            failures.append((reg, actual, expected, description))

    cocotb.log.info("="*70)

    if failures:
        cocotb.log.error("\n🔥 FAILURES:")
        for reg, actual, expected, desc in failures:
            cocotb.log.error(f"  x{reg}: got {actual}, expected {expected} - {desc}")

        # Count critical failures (flushed instructions that executed)
        critical = [f for f in failures if "CRITICAL" in f[3]]
        if critical:
            cocotb.log.error(f"\n⚠️  {len(critical)} CRITICAL failures where flushed instructions executed!")
            cocotb.log.error("This indicates valid bits are not working correctly during stall+flush!")

        assert False, f"{len(failures)} failures ({len(critical)} critical)"
    else:
        cocotb.log.info("✅ All checks passed!")
        cocotb.log.info("Stall + flush interaction with valid bits is working correctly!")
