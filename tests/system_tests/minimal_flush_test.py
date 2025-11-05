import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
import struct

def encode_i_type(imm, rs1, funct3, rd, opcode):
    """Encode I-type instruction"""
    instr = (imm & 0xFFF) << 20
    instr |= (rs1 & 0x1F) << 15
    instr |= (funct3 & 0x7) << 12
    instr |= (rd & 0x1F) << 7
    instr |= opcode & 0x7F
    return instr

def encode_b_type(imm, rs2, rs1, funct3, opcode):
    """Encode B-type instruction"""
    instr = ((imm >> 12) & 0x1) << 31
    instr |= ((imm >> 5) & 0x3F) << 25
    instr |= (rs2 & 0x1F) << 20
    instr |= (rs1 & 0x1F) << 15
    instr |= (funct3 & 0x7) << 12
    instr |= ((imm >> 1) & 0xF) << 8
    instr |= ((imm >> 11) & 0x1) << 7
    instr |= opcode & 0x7F
    return instr

@cocotb.test()
async def minimal_flush_test(dut):
    """Minimal test to debug branch flush behavior"""

    # Start clock
    cocotb.start_soon(Clock(dut.clk, 10, units='ns').start())

    # Generate minimal test program
    instructions = []

    # Test: Branch that flushes pipeline
    instructions.append(encode_i_type(5, 0, 0, 9, 0x13))         # addi x9, x0, 5
    instructions.append(encode_i_type(5, 0, 0, 10, 0x13))        # addi x10, x0, 5
    instructions.append(encode_b_type(12, 10, 9, 0, 0x63))       # beq x9, x10, +12 (skip 3 instrs)
    instructions.append(encode_i_type(999, 0, 0, 11, 0x13))      # addi x11, x0, 999 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(888, 0, 0, 12, 0x13))      # addi x12, x0, 888 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(777, 0, 0, 13, 0x13))      # addi x13, x0, 777 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(42, 0, 0, 11, 0x13))       # addi x11, x0, 42 [TARGET - SHOULD EXECUTE]
    instructions.append(encode_i_type(0, 1, 0, 0, 0x23))         # sw x0, 0(x1) - trigger done

    # Write instructions to hex file
    hex_file = "/home/shashvat/synapse32/tests/system_tests/build/minimal_flush.hex"
    with open(hex_file, 'w') as f:
        for i, instr in enumerate(instructions):
            f.write(f"{instr:08x}\n")

    cocotb.log.info(f"Created minimal test hex: {hex_file}")

    # Reset
    dut.rst.value = 1
    await Timer(50, units='ns')
    dut.rst.value = 0
    await Timer(10, units='ns')

    # Run for enough cycles
    for _ in range(100):
        await RisingEdge(dut.clk)

    # Check results via register write tracking
    cocotb.log.info("Test completed - check debug output above")
