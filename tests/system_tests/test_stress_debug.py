"""
Debug version of stress tests to isolate CPU bugs vs test encoding issues

This file contains simplified versions of the failing stress tests
to help identify the root cause of failures.
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
import sys

async def reset_dut(dut, cycles=5):
    """Reset the DUT properly"""
    print(f"[DEBUG] Asserting hardware reset...")
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, cycles)
    print("[DEBUG] Reset held for {} cycles".format(cycles))

async def release_reset(dut):
    """Release reset after program is loaded"""
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    print("[DEBUG] Reset released, CPU executing from PC=0")

async def load_program(dut, instructions, start_addr=0):
    """Load program into instruction memory"""
    print(f"[DEBUG] Loading {len(instructions)} instructions at 0x{start_addr:08x}")
    instr_mem = dut.instr_mem_inst.instr_ram

    for i, instr in enumerate(instructions):
        word_addr = (start_addr // 4) + i
        try:
            instr_mem[word_addr].value = instr
            print(f"[DEBUG]   [{word_addr:3d}] 0x{start_addr + i*4:08x}: 0x{instr:08x}")
        except Exception as e:
            print(f"[ERROR] Failed to write instruction {i}: {e}")
            raise

    await release_reset(dut)

def read_register(dut, reg_num):
    """Read a register value"""
    if reg_num == 0:
        return 0
    try:
        return int(dut.cpu_inst.rf_inst0.register_file[reg_num].value)
    except Exception as e:
        print(f"[WARN] Could not read x{reg_num}: {e}")
        return None

async def wait_cycles(dut, n):
    """Wait n cycles"""
    for _ in range(n):
        await RisingEdge(dut.clk)


@cocotb.test()
async def test_simple_loop_debug(dut):
    """Simplified loop test: count from 0 to 10"""
    print("\n" + "="*80)
    print("=== DEBUG TEST 1: Simple Loop (Count to 10) ===")
    print("="*80)

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Simple loop: count from 0 to 10
    # This is the working pattern from test_full_integration.py test_nested_loop
    instructions = [
        0x00000093,  # ADDI x1, x0, 0    (counter = 0)
        0x00a00113,  # ADDI x2, x0, 10   (max = 10)
        # Loop start at PC=0x08
        0x00108093,  # ADDI x1, x1, 1    (counter++)
        0xfe209ee3,  # BNE x1, x2, -4    (if counter < 10, loop back to 0x08)
        # End
        0x00300193,  # ADDI x3, x0, 3    (marker = 3)
        0x0000006f,  # JAL x0, 0         (halt)
    ]

    await load_program(dut, instructions)

    print("\n[INFO] Running simple loop (0 to 10)...")
    print("[INFO] Expected: x1=10, x3=3")

    # Monitor execution
    max_cycles = 200
    for cycle in range(0, max_cycles, 10):
        await wait_cycles(dut, 10)
        pc = int(dut.pc_debug.value)
        x1 = read_register(dut, 1)

        if cycle % 50 == 0:
            print(f"[DEBUG] Cycle {cycle:4d}: PC=0x{pc:08x}, x1={x1}")

        if pc == 0x14:  # Halt address
            print(f"[INFO] Loop completed at cycle {cycle}")
            break

    # Check results
    x1 = read_register(dut, 1)
    x2 = read_register(dut, 2)
    x3 = read_register(dut, 3)

    print(f"\n[RESULT] Final values:")
    print(f"  x1 (counter) = {x1}")
    print(f"  x2 (max)     = {x2}")
    print(f"  x3 (marker)  = {x3}")

    assert x1 == 10, f"Expected x1=10, got {x1}"
    assert x3 == 3, f"Expected x3=3, got {x3}"

    print(f"[PASS] Simple loop works correctly! ✓\n")


@cocotb.test()
async def test_nested_loop_small_debug(dut):
    """Small nested loop: 3 outer × 3 inner = 9 iterations"""
    print("\n" + "="*80)
    print("=== DEBUG TEST 2: Small Nested Loop (3×3=9) ===")
    print("="*80)

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # This is EXACTLY from test_full_integration.py test_nested_loop which PASSES
    instructions = [
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

    await load_program(dut, instructions)

    print("\n[INFO] Running nested loop (3 outer × 3 inner)...")
    print("[INFO] Expected: sum=9, outer=3, inner=3")

    # Monitor execution with detail
    max_cycles = 500
    for cycle in range(0, max_cycles, 20):
        await wait_cycles(dut, 20)
        pc = int(dut.pc_debug.value)
        x1 = read_register(dut, 1)  # outer
        x2 = read_register(dut, 2)  # inner
        x5 = read_register(dut, 5)  # sum

        if cycle % 100 == 0:
            print(f"[DEBUG] Cycle {cycle:4d}: PC=0x{pc:08x}, outer={x1}, inner={x2}, sum={x5}")

        if pc == 0x28:  # Halt address
            print(f"[INFO] Nested loop completed at cycle {cycle}")
            break

    # Check results
    x1 = read_register(dut, 1)  # outer
    x2 = read_register(dut, 2)  # inner
    x5 = read_register(dut, 5)  # sum

    print(f"\n[RESULT] Final values:")
    print(f"  x5 (sum)   = {x5}")
    print(f"  x1 (outer) = {x1}")
    print(f"  x2 (inner) = {x2}")

    assert x5 == 9, f"Expected sum=9, got {x5}"
    assert x1 == 3, f"Expected outer=3, got {x1}"

    print(f"[PASS] Small nested loop works correctly! ✓\n")


@cocotb.test()
async def test_nested_loop_large_debug(dut):
    """Large nested loop: 10 outer × 10 inner = 100 iterations"""
    print("\n" + "="*80)
    print("=== DEBUG TEST 3: Larger Nested Loop (10×10=100) ===")
    print("="*80)

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Scale up the working nested loop pattern
    instructions = [
        0x00000293,  # ADDI x5, x0, 0     (sum = 0)
        0x00000093,  # ADDI x1, x0, 0     (outer = 0)
        0x00a00193,  # ADDI x3, x0, 10    (outer_max = 10)
        # Outer loop start (PC=0x0C)
        0x00000113,  # ADDI x2, x0, 0     (inner = 0)
        0x00a00213,  # ADDI x4, x0, 10    (inner_max = 10)
        # Inner loop start (PC=0x14)
        0x00128293,  # ADDI x5, x5, 1     (sum++)
        0x00110113,  # ADDI x2, x2, 1     (inner++)
        0xfe411ee3,  # BNE x2, x4, -4     (if inner < 10, loop to 0x14)
        # End of inner loop
        0x00108093,  # ADDI x1, x1, 1     (outer++)
        0xfe3096e3,  # BNE x1, x3, -20    (if outer < 10, loop to 0x0C)
        # End
        0x0000006f,  # JAL x0, 0          (halt)
    ]

    await load_program(dut, instructions)

    print("\n[INFO] Running nested loop (10 outer × 10 inner)...")
    print("[INFO] Expected: sum=100, outer=10")

    # Monitor with less frequent updates (it's longer)
    max_cycles = 3000
    for cycle in range(0, max_cycles, 100):
        await wait_cycles(dut, 100)
        pc = int(dut.pc_debug.value)
        x1 = read_register(dut, 1)  # outer
        x5 = read_register(dut, 5)  # sum

        if cycle % 500 == 0:
            print(f"[DEBUG] Cycle {cycle:4d}: PC=0x{pc:08x}, outer={x1}, sum={x5}")

        if pc == 0x28:  # Halt address
            print(f"[INFO] Nested loop completed at cycle {cycle}")
            break

    # Check results
    x1 = read_register(dut, 1)  # outer
    x5 = read_register(dut, 5)  # sum

    print(f"\n[RESULT] Final values:")
    print(f"  x5 (sum)   = {x5}")
    print(f"  x1 (outer) = {x1}")

    assert x5 == 100, f"Expected sum=100, got {x5}"
    assert x1 == 10, f"Expected outer=10, got {x1}"

    print(f"[PASS] Large nested loop (10×10) works correctly! ✓\n")


@cocotb.test()
async def test_memory_operations_debug(dut):
    """Debug memory store/load operations"""
    print("\n" + "="*80)
    print("=== DEBUG TEST 4: Memory Store/Load (4 values) ===")
    print("="*80)

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Simplified version: store 4 values, load them back, sum them
    # Expected sum: 1+2+3+4 = 10
    instructions = [
        # Setup base address
        0x10000537,  # LUI x10, 0x10000   (x10 = 0x10000000)

        # Store 4 values manually (no loop to simplify)
        0x00100093,  # ADDI x1, x0, 1     (x1 = 1)
        0x00152023,  # SW x1, 0(x10)      (MEM[0x10000000] = 1)

        0x00200093,  # ADDI x1, x0, 2     (x1 = 2)
        0x00152223,  # SW x1, 4(x10)      (MEM[0x10000004] = 2)

        0x00300093,  # ADDI x1, x0, 3     (x1 = 3)
        0x00152423,  # SW x1, 8(x10)      (MEM[0x10000008] = 3)

        0x00400093,  # ADDI x1, x0, 4     (x1 = 4)
        0x00152623,  # SW x1, 12(x10)     (MEM[0x1000000C] = 4)

        # Load them back and sum
        0x00000293,  # ADDI x5, x0, 0     (sum = 0)

        0x00052083,  # LW x1, 0(x10)      (x1 = MEM[0x10000000])
        0x001282b3,  # ADD x5, x5, x1     (sum += x1)

        0x00452083,  # LW x1, 4(x10)      (x1 = MEM[0x10000004])
        0x001282b3,  # ADD x5, x5, x1     (sum += x1)

        0x00852083,  # LW x1, 8(x10)      (x1 = MEM[0x10000008])
        0x001282b3,  # ADD x5, x5, x1     (sum += x1)

        0x00c52083,  # LW x1, 12(x10)     (x1 = MEM[0x1000000C])
        0x001282b3,  # ADD x5, x5, x1     (sum += x1)

        # End
        0x0000006f,  # JAL x0, 0          (halt)
    ]

    await load_program(dut, instructions)

    print("\n[INFO] Running memory store/load test...")
    print("[INFO] Storing 1,2,3,4 then loading and summing")
    print("[INFO] Expected sum = 10")

    # Monitor execution
    max_cycles = 300
    for cycle in range(0, max_cycles, 20):
        await wait_cycles(dut, 20)
        pc = int(dut.pc_debug.value)
        x5 = read_register(dut, 5)  # sum

        if cycle % 100 == 0:
            print(f"[DEBUG] Cycle {cycle:4d}: PC=0x{pc:08x}, sum={x5}")

        if pc == 0x4C:  # Halt address (adjusted)
            print(f"[INFO] Memory test completed at cycle {cycle}")
            break

    # Check results
    x5 = read_register(dut, 5)

    print(f"\n[RESULT] Final sum = {x5}")

    assert x5 == 10, f"Expected sum=10, got {x5}"

    print(f"[PASS] Memory operations work correctly! ✓\n")


# Pytest runner
import pytest
from cocotb_test.simulator import run
import os

def runCocotbTests():
    """Run debug tests"""
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
        module="test_stress_debug",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
    )

if __name__ == "__main__":
    runCocotbTests()
