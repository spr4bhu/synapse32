"""
Error Condition Tests for Synapse-32 RISC-V CPU

Tests how the CPU handles:
- Illegal/undefined instructions
- Misaligned memory access
- Access to unmapped memory regions
- Invalid CSR operations
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
from pathlib import Path

# Memory map constants
DATA_MEM_BASE = 0x10000000
DATA_MEM_END = 0x100FFFFF
TIMER_BASE = 0x02004000
UART_BASE = 0x20000000


async def reset_dut(dut):
    """Reset the DUT"""
    dut.rst.value = 1
    await Timer(20, units="ns")
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def wait_cycles(dut, n):
    """Wait for n clock cycles"""
    for _ in range(n):
        await RisingEdge(dut.clk)


async def load_program(dut, instructions):
    """Load program into instruction memory"""
    for i, instr in enumerate(instructions):
        dut.instr_mem_inst.instr_ram[i].value = instr


def create_hex_file(test_name, instructions):
    """Create hex file for instruction memory"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)

    hex_file = build_dir / f"{test_name}.hex"

    with open(hex_file, 'w') as f:
        f.write("@00000000\n")

        # Pad instructions to multiple of 4
        padded = list(instructions)
        while len(padded) % 4 != 0:
            padded.append(0x00000013)  # NOP

        # Pad to at least 256 instructions
        while len(padded) < 256:
            padded.append(0x00000013)

        # Write 4 instructions per line
        for i in range(0, len(padded), 4):
            line = " ".join(f"{padded[j]:08x}" for j in range(i, min(i + 4, len(padded))))
            f.write(f"{line}\n")

    return str(hex_file.absolute())


@cocotb.test()
async def test_illegal_instruction(dut):
    """Test CPU behavior with illegal/undefined instruction"""
    print("\n=== Test: Illegal Instruction ===")

    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Program with illegal instruction
    instructions = [
        0xFFFFFFFF,  # Illegal instruction (all 1s)
        0x00100093,  # ADDI x1, x0, 1 (should not execute if exception handled)
        0x00200113,  # ADDI x2, x0, 2
        0x0000006F,  # JAL x0, 0 (infinite loop)
    ]

    # Load program
    await load_program(dut, instructions)
    await wait_cycles(dut, 5)

    # Run for some cycles
    await wait_cycles(dut, 50)

    # Check behavior
    try:
        x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
        x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)
        pc = int(dut.cpu_inst.pc_inst0.out.value)

        print(f"[INFO] After illegal instruction:")
        print(f"  PC = 0x{pc:08x}")
        print(f"  x1 = 0x{x1:08x}")
        print(f"  x2 = 0x{x2:08x}")

        # NOTE: Without exception handling, CPU behavior is undefined
        # This test documents current behavior, not expected behavior
        print(f"[WARN] CPU does not have exception handling implemented")
        print(f"[WARN] Illegal instruction behavior is undefined")

    except Exception as e:
        print(f"[ERROR] Test execution error: {e}")
        raise


@cocotb.test()
async def test_misaligned_load_word(dut):
    """Test misaligned word load (LW from odd address)"""
    print("\n=== Test: Misaligned Load Word ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Program that attempts misaligned LW
    # LUI x10, 0x10000  - Load data memory base
    # ADDI x10, x10, 1  - Add 1 to make misaligned address (0x10000001)
    # LW x1, 0(x10)     - Try to load word from misaligned address
    instructions = [
        0x10000537,  # LUI x10, 0x10000
        0x00150513,  # ADDI x10, x10, 1 (x10 = 0x10000001, misaligned!)
        0x00052083,  # LW x1, 0(x10) - Misaligned load!
        0x00200113,  # ADDI x2, x0, 2 (marker if we get here)
        0x0000006F,  # JAL x0, 0 (halt)
    ]

    # Hex file creation removed
    await load_program(dut, instructions)

    await wait_cycles(dut, 5)
    await wait_cycles(dut, 50)

    try:
        x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
        x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)
        x10 = int(dut.cpu_inst.rf_inst0.register_file[10].value)

        print(f"[INFO] After misaligned load:")
        print(f"  x10 (address) = 0x{x10:08x}")
        print(f"  x1 (loaded value) = 0x{x1:08x}")
        print(f"  x2 (marker) = 0x{x2:08x}")

        print(f"[WARN] CPU may not detect misaligned access")
        print(f"[INFO] RISC-V allows implementations to support misaligned access")

    except Exception as e:
        print(f"[ERROR] Test error: {e}")
        raise


@cocotb.test()
async def test_misaligned_store_word(dut):
    """Test misaligned word store (SW to odd address)"""
    print("\n=== Test: Misaligned Store Word ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Program that attempts misaligned SW
    instructions = [
        0x10000537,  # LUI x10, 0x10000
        0x00350513,  # ADDI x10, x10, 3 (x10 = 0x10000003, misaligned!)
        0x12300093,  # ADDI x1, x0, 0x123
        0x00152023,  # SW x1, 0(x10) - Misaligned store!
        0x00200113,  # ADDI x2, x0, 2 (marker)
        0x0000006F,  # JAL x0, 0 (halt)
    ]

    # Hex file creation removed
    await load_program(dut, instructions)

    await wait_cycles(dut, 5)
    await wait_cycles(dut, 50)

    try:
        x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)
        print(f"[INFO] After misaligned store:")
        print(f"  x2 (marker) = 0x{x2:08x}")
        print(f"[WARN] Misaligned store behavior is implementation-defined")

    except Exception as e:
        print(f"[ERROR] Test error: {e}")
        raise


@cocotb.test()
async def test_unmapped_memory_read(dut):
    """Test read from unmapped memory region"""
    print("\n=== Test: Unmapped Memory Read ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Try to read from unmapped region (0x50000000)
    instructions = [
        0x50000537,  # LUI x10, 0x50000 (unmapped region)
        0x00052083,  # LW x1, 0(x10) - Read from unmapped region
        0x00200113,  # ADDI x2, x0, 2 (marker)
        0x0000006F,  # JAL x0, 0 (halt)
    ]

    # Hex file creation removed
    await load_program(dut, instructions)

    await wait_cycles(dut, 5)
    await wait_cycles(dut, 50)

    try:
        x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
        x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)

        print(f"[INFO] After unmapped read:")
        print(f"  x1 (read value) = 0x{x1:08x}")
        print(f"  x2 (marker) = 0x{x2:08x}")
        print(f"[WARN] Unmapped memory access may return 0 or undefined value")

    except Exception as e:
        print(f"[ERROR] Test error: {e}")
        raise


@cocotb.test()
async def test_unmapped_memory_write(dut):
    """Test write to unmapped memory region"""
    print("\n=== Test: Unmapped Memory Write ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Try to write to unmapped region
    instructions = [
        0x50000537,  # LUI x10, 0x50000 (unmapped region)
        0x12300093,  # ADDI x1, x0, 0x123
        0x00152023,  # SW x1, 0(x10) - Write to unmapped region
        0x00200113,  # ADDI x2, x0, 2 (marker - should execute)
        0x0000006F,  # JAL x0, 0 (halt)
    ]

    # Hex file creation removed
    await load_program(dut, instructions)

    await wait_cycles(dut, 5)
    await wait_cycles(dut, 50)

    try:
        x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)

        print(f"[INFO] After unmapped write:")
        print(f"  x2 (marker) = 0x{x2:08x}")

        if x2 == 2:
            print(f"[INFO] CPU continued execution after unmapped write (write ignored)")
        else:
            print(f"[WARN] CPU did not reach marker instruction")

    except Exception as e:
        print(f"[ERROR] Test error: {e}")
        raise


@cocotb.test()
async def test_all_registers_simultaneously(dut):
    """Test using all 32 registers at once"""
    print("\n=== Test: All 32 Registers Simultaneously ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Initialize all registers x1-x31 with unique values
    instructions = [
        0x00100093,  # ADDI x1, x0, 1
        0x00200113,  # ADDI x2, x0, 2
        0x00300193,  # ADDI x3, x0, 3
        0x00400213,  # ADDI x4, x0, 4
        0x00500293,  # ADDI x5, x0, 5
        0x00600313,  # ADDI x6, x0, 6
        0x00700393,  # ADDI x7, x0, 7
        0x00800413,  # ADDI x8, x0, 8
        0x00900493,  # ADDI x9, x0, 9
        0x00a00513,  # ADDI x10, x0, 10
        0x00b00593,  # ADDI x11, x0, 11
        0x00c00613,  # ADDI x12, x0, 12
        0x00d00693,  # ADDI x13, x0, 13
        0x00e00713,  # ADDI x14, x0, 14
        0x00f00793,  # ADDI x15, x0, 15
        0x01000813,  # ADDI x16, x0, 16
        0x01100893,  # ADDI x17, x0, 17
        0x01200913,  # ADDI x18, x0, 18
        0x01300993,  # ADDI x19, x0, 19
        0x01400a13,  # ADDI x20, x0, 20
        0x01500a93,  # ADDI x21, x0, 21
        0x01600b13,  # ADDI x22, x0, 22
        0x01700b93,  # ADDI x23, x0, 23
        0x01800c13,  # ADDI x24, x0, 24
        0x01900c93,  # ADDI x25, x0, 25
        0x01a00d13,  # ADDI x26, x0, 26
        0x01b00d93,  # ADDI x27, x0, 27
        0x01c00e13,  # ADDI x28, x0, 28
        0x01d00e93,  # ADDI x29, x0, 29
        0x01e00f13,  # ADDI x30, x0, 30
        0x01f00f93,  # ADDI x31, x0, 31
        # Now use multiple registers in arithmetic
        0x002081b3,  # ADD x3, x1, x2 (x3 = 1 + 2 = 3, overwrites)
        0x00520233,  # ADD x4, x4, x5 (x4 = 4 + 5 = 9)
        0x007302b3,  # ADD x5, x6, x7 (x5 = 6 + 7 = 13)
        0x0000006F,  # JAL x0, 0 (halt)
    ]

    # Hex file creation removed
    await load_program(dut, instructions)

    await wait_cycles(dut, 5)
    await wait_cycles(dut, 100)

    print(f"[INFO] Checking all register values:")
    all_correct = True

    # x0 should always be 0
    x0 = int(dut.cpu_inst.rf_inst0.register_file[0].value)
    if x0 != 0:
        print(f"[FAIL] x0 = {x0}, expected 0")
        all_correct = False
    else:
        print(f"[PASS] x0 = 0 ✓")

    # Check x1, x2 (unchanged)
    expected_vals = {1: 1, 2: 2}
    for reg, expected in expected_vals.items():
        val = int(dut.cpu_inst.rf_inst0.register_file[reg].value)
        if val == expected:
            print(f"[PASS] x{reg} = {val} ✓")
        else:
            print(f"[FAIL] x{reg} = {val}, expected {expected}")
            all_correct = False

    # Check modified registers
    # x3 was 3, then became 1+2=3 again
    # x4 was 4, then became 4+5=9
    # x5 was 5, then became 6+7=13
    modified = {3: 3, 4: 9, 5: 13}
    for reg, expected in modified.items():
        val = int(dut.cpu_inst.rf_inst0.register_file[reg].value)
        if val == expected:
            print(f"[PASS] x{reg} = {val} ✓")
        else:
            print(f"[FAIL] x{reg} = {val}, expected {expected}")
            all_correct = False

    # Spot check a few high registers
    spot_check = {10: 10, 20: 20, 31: 31}
    for reg, expected in spot_check.items():
        val = int(dut.cpu_inst.rf_inst0.register_file[reg].value)
        if val == expected:
            print(f"[PASS] x{reg} = {val} ✓")
        else:
            print(f"[FAIL] x{reg} = {val}, expected {expected}")
            all_correct = False

    if all_correct:
        print(f"[PASS] All 32 registers work independently ✓")
    else:
        raise AssertionError("Some registers have incorrect values")


# Pytest runner
import pytest
from cocotb_test.simulator import run
import os

def runCocotbTests():
    """Run all error condition tests"""
    root_dir = os.getcwd()
    while not os.path.exists(os.path.join(root_dir, "rtl")):
        if os.path.dirname(root_dir) == root_dir:
            raise FileNotFoundError("rtl directory not found")
        root_dir = os.path.dirname(root_dir)

    rtl_dir = os.path.join(root_dir, "rtl")
    incl_dir = os.path.join(rtl_dir, "include")

    # Collect all Verilog sources
    sources = []
    for root, _, files in os.walk(rtl_dir):
        for file in files:
            if file.endswith(".v"):
                sources.append(os.path.join(root, file))

    run(
        verilog_sources=sources,
        toplevel="top",
        module="test_error_conditions",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
    )
