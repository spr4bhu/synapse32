"""
Debug test for ADD chain issue
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

def encode_s_type(opcode, funct3, rs1, rs2, imm):
    imm = imm & 0xFFF
    imm_11_5 = (imm >> 5) & 0x7F
    imm_4_0 = imm & 0x1F
    return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

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
    return encode_s_type(0x23, 0x2, rs1, rs2, imm)

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
async def test_add_chain_simple(dut):
    """Test simple ADD chain without loads"""
    log.info("=== Test: Simple ADD Chain (no loads) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Simple ADD chain: x5 = 1 + 2 + 3 + 4
    program = [
        ADDI(5, 0, 0),      # x5 = 0
        ADDI(1, 0, 1),      # x1 = 1
        ADD(5, 5, 1),       # x5 = 0 + 1 = 1
        ADDI(2, 0, 2),      # x2 = 2
        ADD(5, 5, 2),       # x5 = 1 + 2 = 3
        ADDI(3, 0, 3),      # x3 = 3
        ADD(5, 5, 3),       # x5 = 3 + 3 = 6
        ADDI(4, 0, 4),      # x4 = 4
        ADD(5, 5, 4),       # x5 = 6 + 4 = 10
        HALT(),
    ]
    await load_program(dut, program)

    await ClockCycles(dut.clk, 100)

    x5 = get_register(dut, 5)
    log.info(f"Result: x5 = {x5}")

    assert x5 == 10, f"ADD chain failed: expected 10, got {x5}"
    log.info("Simple ADD chain test PASSED")


@cocotb.test()
async def test_add_chain_with_loads(dut):
    """Test ADD chain WITH loads (reproduces bug)"""
    log.info("=== Test: ADD Chain WITH Loads ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Same pattern as failing test
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = DATA_MEM_BASE

        # Store values 1, 2, 3, 4
        ADDI(1, 0, 1),
        SW(10, 1, 0),
        ADDI(1, 0, 2),
        SW(10, 1, 4),
        ADDI(1, 0, 3),
        SW(10, 1, 8),
        ADDI(1, 0, 4),
        SW(10, 1, 12),

        # Load and sum
        ADDI(5, 0, 0),                   # x5 = 0
        LW(1, 10, 0),                    # x1 = 1
        ADD(5, 5, 1),                    # x5 = 1
        LW(2, 10, 4),                    # x2 = 2
        ADD(5, 5, 2),                    # x5 = 3
        LW(3, 10, 8),                    # x3 = 3
        ADD(5, 5, 3),                    # x5 = 6
        LW(4, 10, 12),                   # x4 = 4
        ADD(5, 5, 4),                    # x5 = 10
        HALT(),
    ]
    await load_program(dut, program)

    await ClockCycles(dut.clk, 150)

    x1 = get_register(dut, 1)
    x2 = get_register(dut, 2)
    x3 = get_register(dut, 3)
    x4 = get_register(dut, 4)
    x5 = get_register(dut, 5)

    log.info(f"Loaded values: x1={x1}, x2={x2}, x3={x3}, x4={x4}")
    log.info(f"Sum: x5={x5}")

    assert x1 == 1, f"Load 1 failed: expected 1, got {x1}"
    assert x2 == 2, f"Load 2 failed: expected 2, got {x2}"
    assert x3 == 3, f"Load 3 failed: expected 3, got {x3}"
    assert x4 == 4, f"Load 4 failed: expected 4, got {x4}"
    assert x5 == 10, f"Sum failed: expected 10, got {x5}"

    log.info("ADD chain with loads test PASSED")


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
        module="test_add_chain_debug",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
    )

if __name__ == "__main__":
    runCocotbTests()
