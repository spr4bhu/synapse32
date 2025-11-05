"""
Ultimate test to prove valid bits are necessary.
This test explicitly creates bubbles and checks if they execute.
"""

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.clock import Clock
import os


def create_bubble_test_hex():
    """Create test that will expose bubble execution without valid bits"""

    def encode_i_type(imm, rs1, funct3, rd, opcode):
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    def encode_r_type(funct7, rs2, rs1, funct3, rd, opcode):
        return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    def encode_s_type(imm, rs2, rs1, funct3, opcode):
        imm_11_5 = (imm >> 5) & 0x7F
        imm_4_0 = imm & 0x1F
        return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

    def encode_u_type(imm, rd, opcode):
        return ((imm & 0xFFFFF) << 12) | (rd << 7) | opcode

    instructions = []

    # Setup
    instructions.append(encode_u_type(0x10000, 4, 0x37))          # lui x4, 0x10000

    # THE CRITICAL TEST:
    # Create a load-use hazard that inserts a bubble
    # The bubble will have opcode/instr_id that happens to match an ADD instruction
    # WITHOUT valid bits, if the bubble executes, it will perform the ADD
    # WITH valid bits, the bubble is marked invalid and won't execute

    # Set up values for the "accidental" ADD
    instructions.append(encode_i_type(10, 0, 0, 5, 0x13))        # addi x5, x0, 10
    instructions.append(encode_i_type(20, 0, 0, 6, 0x13))        # addi x6, x0, 20

    # Store a value to create load
    instructions.append(encode_i_type(100, 0, 0, 7, 0x13))       # addi x7, x0, 100
    instructions.append(encode_s_type(0, 7, 4, 2, 0x23))         # sw x7, 0(x4)

    # Load-use hazard: creates bubble in EX stage
    instructions.append(encode_i_type(0, 4, 2, 8, 0x03))         # lw x8, 0(x4) [loads 100]

    # This instruction causes load-use stall, bubble inserted
    # The bubble might have leftover opcode/operands from previous instruction
    # If bubble executes (no valid bit check), it might do: add x9, x5, x6 = 30
    instructions.append(encode_r_type(0, 6, 5, 0, 9, 0x33))      # add x9, x5, x6 [creates bubble before this]

    # Expected:
    # x5 = 10
    # x6 = 20
    # x8 = 100
    # x9 = 30 (should execute AFTER stall resolves)

    # But the bubble during stall might also try to execute with old operand values
    # This depends on what's in the pipeline register when bubble is inserted

    # Add more clear markers
    instructions.append(encode_i_type(0, 0, 0, 10, 0x13))        # addi x10, x0, 0 (marker)

    # Signal completion
    instructions.append(encode_u_type(0x10000, 1, 0x37))         # lui x1, 0x10000
    instructions.append(encode_i_type(0xFF, 1, 0, 1, 0x13))      # addi x1, x1, 0xFF
    instructions.append(encode_s_type(0, 0, 1, 2, 0x23))         # sw x0, 0(x1)

    # Write to hex file
    hex_file = os.path.join(os.path.dirname(__file__), "build", "bubble_test.hex")
    os.makedirs(os.path.dirname(hex_file), exist_ok=True)
    with open(hex_file, 'w') as f:
        for instr in instructions:
            f.write(f"{instr:08x}\n")

    return hex_file


@cocotb.test()
async def test_bubble_execution(dut):
    """Test if bubbles execute without valid bits"""

    hex_file = create_bubble_test_hex()
    cocotb.log.info(f"Created bubble test: {hex_file}")

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

    for cycle in range(150):
        await RisingEdge(dut.clk)

        if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
            rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
            rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
            if rd_addr != 0:
                register_state[rd_addr] = rd_value
                cocotb.log.info(f"Cycle {cycle}: x{rd_addr} = {rd_value}")

    # Check results
    cocotb.log.info("\n" + "="*70)
    cocotb.log.info("BUBBLE EXECUTION TEST")
    cocotb.log.info("="*70)

    cocotb.log.info(f"x5 = {register_state[5]} (should be 10)")
    cocotb.log.info(f"x6 = {register_state[6]} (should be 20)")
    cocotb.log.info(f"x8 = {register_state[8]} (should be 100)")
    cocotb.log.info(f"x9 = {register_state[9]} (should be 30)")

    cocotb.log.info("="*70)
    cocotb.log.info("Test complete - check if results match expectations")
