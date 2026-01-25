"""
Detailed debug test for sum chain issue
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
import logging

log = logging.getLogger("cocotb.test")

DATA_MEM_BASE = 0x10000000

def encode_i_type(opcode, rd, funct3, rs1, imm):
    imm = imm & 0xFFF
    return (imm << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_r_type(opcode, rd, funct3, rs1, rs2, funct7):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_u_type(opcode, rd, imm):
    imm = imm & 0xFFFFF
    return (imm << 12) | (rd << 7) | opcode

def ADDI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x0, rs1, imm)

def ADD(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x0, rs1, rs2, 0x00)

def LUI(rd, imm):
    return encode_u_type(0x37, rd, imm)

def LW(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x2, rs1, imm)

def SW(rs1, rs2, imm):
    imm = imm & 0xFFF
    imm_11_5 = (imm >> 5) & 0x7F
    imm_4_0 = imm & 0x1F
    return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (0x2 << 12) | (imm_4_0 << 7) | 0x23

def HALT():
    return 0x00000073

async def reset_dut(dut):
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

async def load_program(dut, instructions):
    for i, instr in enumerate(instructions):
        dut.instr_mem_inst.instr_ram[i].value = instr

def get_register(dut, reg_num):
    if reg_num == 0:
        return 0
    return int(dut.cpu_inst.rf_inst0.register_file[reg_num].value)

@cocotb.test()
async def test_sum_step_by_step(dut):
    """Test sum chain step by step with intermediate checks"""
    log.info("=== Test: Sum Chain Step by Step ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Program: store 1,2,3,4 then load and sum
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = DATA_MEM_BASE

        # Store values
        ADDI(1, 0, 1),
        SW(10, 1, 0),                    # MEM[0] = 1
        ADDI(1, 0, 2),
        SW(10, 1, 4),                    # MEM[4] = 2
        ADDI(1, 0, 3),
        SW(10, 1, 8),                    # MEM[8] = 3
        ADDI(1, 0, 4),
        SW(10, 1, 12),                   # MEM[12] = 4

        # Initialize sum
        ADDI(5, 0, 0),                   # x5 = 0

        # First pair: load and add
        LW(1, 10, 0),                    # x1 = 1
        ADD(5, 5, 1),                    # x5 = 0 + 1 = 1

        # Second pair
        LW(2, 10, 4),                    # x2 = 2
        ADD(5, 5, 2),                    # x5 = 1 + 2 = 3

        # Third pair
        LW(3, 10, 8),                    # x3 = 3
        ADD(5, 5, 3),                    # x5 = 3 + 3 = 6

        # Fourth pair
        LW(4, 10, 12),                   # x4 = 4
        ADD(5, 5, 4),                    # x5 = 6 + 4 = 10

        HALT(),
    ]
    await load_program(dut, program)

    # Run stores + sum initialization
    await ClockCycles(dut.clk, 30)

    x5 = get_register(dut, 5)
    log.info(f"After initialization: x5 = {x5} (should be 0)")

    # Run first pair (LW + ADD)
    await ClockCycles(dut.clk, 10)
    x1 = get_register(dut, 1)
    x5 = get_register(dut, 5)
    log.info(f"After 1st pair: x1={x1}, x5={x5} (should be x1=1, x5=1)")

    # Run second pair
    await ClockCycles(dut.clk, 10)
    x2 = get_register(dut, 2)
    x5 = get_register(dut, 5)
    log.info(f"After 2nd pair: x2={x2}, x5={x5} (should be x2=2, x5=3)")

    # Run third pair
    await ClockCycles(dut.clk, 10)
    x3 = get_register(dut, 3)
    x5 = get_register(dut, 5)
    log.info(f"After 3rd pair: x3={x3}, x5={x5} (should be x3=3, x5=6)")

    # Run fourth pair
    await ClockCycles(dut.clk, 10)
    x4 = get_register(dut, 4)
    x5 = get_register(dut, 5)
    log.info(f"After 4th pair: x4={x4}, x5={x5} (should be x4=4, x5=10)")

    # Run a few more cycles to ensure completion
    await ClockCycles(dut.clk, 20)
    x5_final = get_register(dut, 5)
    log.info(f"Final: x5={x5_final} (should be 10)")

    assert x5_final == 10, f"Sum failed: expected 10, got {x5_final}"
    log.info("Sum chain test PASSED!")


def runCocotbTests():
    from cocotb_test.simulator import run
    import os

    root_dir = os.getcwd()
    while not os.path.exists(os.path.join(root_dir, "rtl")):
        if os.path.dirname(root_dir) == root_dir:
            raise FileNotFoundError("rtl directory not found")
        root_dir = os.path.dirname(root_dir)

    rtl_dir = os.path.join(root_dir, "rtl")
    incl_dir = os.path.join(rtl_dir, "include")

    sources = []
    for root, _, files in os.walk(rtl_dir):
        for file in files:
            if file.endswith(".v"):
                sources.append(os.path.join(root, file))

    run(
        verilog_sources=sources,
        toplevel="top",
        module="test_sum_debug",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
    )

if __name__ == "__main__":
    runCocotbTests()
