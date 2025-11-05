"""
Strict test to prove valid bits are absolutely necessary.
This test specifically targets scenarios that MUST fail without valid bits.
"""

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.clock import Clock
import os


def create_strict_test_hex():
    """Create a test that will definitely fail without valid bits"""

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
    instructions.append(encode_i_type(0, 0, 0, 10, 0x13))        # addi x10, x0, 0 (clear x10)
    instructions.append(encode_i_type(0, 0, 0, 11, 0x13))        # addi x11, x0, 0 (clear x11)
    instructions.append(encode_i_type(0, 0, 0, 12, 0x13))        # addi x12, x0, 0 (clear x12)

    # CRITICAL TEST 1: Branch should flush BOTH instructions in pipeline
    # When branch executes, instruction after it is in ID, and instruction after that is in IF
    # Without valid bits, BOTH will execute (wrong!)
    instructions.append(encode_i_type(1, 0, 0, 5, 0x13))         # addi x5, x0, 1
    instructions.append(encode_i_type(1, 0, 0, 6, 0x13))         # addi x6, x0, 1
    instructions.append(encode_b_type(12, 6, 5, 0, 0x63))        # beq x5, x6, +12 (skip 2 instrs)
    instructions.append(encode_i_type(999, 0, 0, 10, 0x13))      # addi x10, x0, 999 [MUST BE FLUSHED]
    instructions.append(encode_i_type(888, 0, 0, 11, 0x13))      # addi x11, x0, 888 [MUST BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(42, 0, 0, 12, 0x13))       # addi x12, x0, 42 [MUST EXECUTE]

    # Expected: x10=0, x11=0, x12=42
    # Without valid bits: x10=999, x11=888, x12=42 (WRONG!)

    # Signal completion
    instructions.append(encode_u_type(0x10000, 1, 0x37))         # lui x1, 0x10000
    instructions.append(encode_i_type(0xFF, 1, 0, 1, 0x13))      # addi x1, x1, 0xFF
    instructions.append(encode_s_type(0, 0, 1, 2, 0x23))         # sw x0, 0(x1) (CPU_DONE)

    # Write to hex file
    hex_file = os.path.join(os.path.dirname(__file__), "build", "strict_valid_test.hex")
    os.makedirs(os.path.dirname(hex_file), exist_ok=True)
    with open(hex_file, 'w') as f:
        for instr in instructions:
            f.write(f"{instr:08x}\n")

    return hex_file


@cocotb.test()
async def test_strict_valid_bit_requirements(dut):
    """Test that absolutely requires valid bits"""

    hex_file = create_strict_test_hex()
    cocotb.log.info(f"Created strict test hex: {hex_file}")

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

    for cycle in range(200):
        await RisingEdge(dut.clk)

        # Track writes
        if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
            rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
            rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
            if rd_addr != 0:
                register_state[rd_addr] = rd_value
                if rd_addr in [10, 11, 12]:
                    cocotb.log.info(f"Cycle {cycle}: x{rd_addr} = {rd_value}")

    # Check results
    cocotb.log.info("\n" + "="*70)
    cocotb.log.info("STRICT VALID BIT TEST RESULTS")
    cocotb.log.info("="*70)

    failures = []

    # x10 should be 0 (flushed instruction should not execute)
    if register_state[10] != 0:
        failures.append(f"x10 = {register_state[10]}, expected 0 (flushed instruction executed!)")
        cocotb.log.error(f"❌ x10 = {register_state[10]} (expected 0)")
    else:
        cocotb.log.info(f"✅ x10 = 0 (flushed instruction correctly did not execute)")

    # x11 should be 0 (flushed instruction should not execute)
    if register_state[11] != 0:
        failures.append(f"x11 = {register_state[11]}, expected 0 (flushed instruction executed!)")
        cocotb.log.error(f"❌ x11 = {register_state[11]} (expected 0)")
    else:
        cocotb.log.info(f"✅ x11 = 0 (flushed instruction correctly did not execute)")

    # x12 should be 42 (branch target should execute)
    if register_state[12] != 42:
        failures.append(f"x12 = {register_state[12]}, expected 42 (branch target didn't execute!)")
        cocotb.log.error(f"❌ x12 = {register_state[12]} (expected 42)")
    else:
        cocotb.log.info(f"✅ x12 = 42 (branch target correctly executed)")

    cocotb.log.info("="*70)

    if failures:
        cocotb.log.error("\n🔥 CRITICAL FAILURES:")
        for fail in failures:
            cocotb.log.error(f"  - {fail}")
        cocotb.log.error("\nThis proves valid bits are ESSENTIAL!")
        assert False, f"{len(failures)} critical failures - valid bits are necessary!"
    else:
        cocotb.log.info("✅ All checks passed - valid bits are working correctly!")
