#!/usr/bin/env python3
"""
Test Store-to-Load Forwarding Hazard
Tests if CPU correctly handles immediate load after store to same address
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
from cocotb.runner import get_runner
import pytest
import os

@cocotb.test()
async def test_store_to_load_hazard(dut):
    """Test store-to-load forwarding"""
    print("=" * 70)
    print("TESTING STORE-TO-LOAD FORWARDING HAZARD")
    print("=" * 70)

    # Setup clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.module_instr_in.value = 0
    dut.module_read_data_in.value = 0
    dut.rst.value = 1
    dut.timer_interrupt.value = 0
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0

    await Timer(20, units="ns")
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Test program: Store then immediately load from same address
    instr_mem = [
        # Setup base address in x4 (data memory base = 0x10000000)
        0x10000237,  # lui x4, 0x10000      # x4 = 0x10000000

        # Test 1: Store x0 (value 0), then load
        0x00422023,  # sw x4, 0(x4)         # Store x4's value to addr 0
        0x00022503,  # lw x10, 0(x4)        # Load from addr 0 -> x10

        # Test 2: Store immediate value, then load
        0x08d00593,  # addi x11, x0, 141    # x11 = 141
        0x00b22223,  # sw x11, 4(x4)        # Store 141 to addr 4
        0x00422603,  # lw x12, 4(x4)        # Load from addr 4 -> x12 (should be 141!)

        # Test 3: Store, then load, then use
        0x00100693,  # addi x13, x0, 1      # x13 = 1
        0x00d22423,  # sw x13, 8(x4)        # Store 1 to addr 8
        0x00822703,  # lw x14, 8(x4)        # Load from addr 8 -> x14 (should be 1!)
        0x00170713,  # addi x14, x14, 1     # x14 = x14 + 1 (should be 2!)

        # Test 4: Back-to-back store-load-store
        0x00200793,  # addi x15, x0, 2      # x15 = 2
        0x00f22623,  # sw x15, 12(x4)       # Store 2 to addr 12
        0x00c22803,  # lw x16, 12(x4)       # Load from addr 12 -> x16 (should be 2!)
        0x00180813,  # addi x16, x16, 1     # x16 = x16 + 1 (should be 3!)
        0x01022623,  # sw x16, 12(x4)       # Store 3 back to addr 12

        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
    ]

    pc = 0
    cycle = 0
    max_cycles = 100

    print(f"\nRunning program for {max_cycles} cycles...")

    for cycle in range(max_cycles):
        # Feed instruction
        if pc < len(instr_mem) * 4:
            word_idx = pc // 4
            if word_idx < len(instr_mem):
                dut.module_instr_in.value = instr_mem[word_idx]

        # Handle memory reads
        if int(dut.module_mem_rd_en.value):
            addr = int(dut.module_read_addr.value)
            # Simple memory model - just return 0 (store buffer should override)
            dut.module_read_data_in.value = 0

        await RisingEdge(dut.clk)

        # Track PC
        try:
            new_pc = int(dut.module_pc_out.value)
            if new_pc != pc:
                print(f"Cycle {cycle:3d}: PC {pc:08x} -> {new_pc:08x}")
                pc = new_pc
        except:
            pass

    print("\n" + "=" * 70)
    print("CHECKING RESULTS")
    print("n" + "=" * 70)

    # Read register values
    results = {}
    for i in range(10, 17):
        try:
            val = int(dut.rf_inst0.register_file[i].value)
            results[i] = val
            print(f"x{i} = {val}")
        except:
            print(f"x{i} = ERROR reading")
            results[i] = -1

    print("\n" + "=" * 70)
    print("TEST RESULTS")
    print("=" * 70)

    # Expected values if store-to-load forwarding works
    expected = {
        10: 0x10000000,  # Should get stored value (x4's address)
        12: 141,         # Should get 141 from store buffer
        14: 2,           # Should get 1 from store, then +1 = 2
        16: 3,           # Should get 2 from store, then +1 = 3
    }

    passed = 0
    failed = 0

    for reg, expected_val in expected.items():
        actual_val = results.get(reg, -1)
        if actual_val == expected_val:
            print(f"✅ x{reg}: {actual_val} == {expected_val} PASS")
            passed += 1
        else:
            print(f"❌ x{reg}: {actual_val} != {expected_val} FAIL")
            failed += 1

    print("\n" + "=" * 70)
    if failed == 0:
        print(f"✅ ALL TESTS PASSED ({passed}/{passed + failed})")
        print("Store-to-load forwarding is WORKING!")
    else:
        print(f"❌ SOME TESTS FAILED ({passed}/{passed + failed} passed)")
        print("Store-to-load forwarding is BROKEN!")
        print("\nThis means the CPU has a CRITICAL BUG:")
        print("- Stores don't properly forward to immediately following loads")
        print("- Loads get stale data from memory instead of store buffer")
        print("- This breaks correctness for many programs!")
    print("=" * 70)

    # Fail the test if any register is wrong
    assert failed == 0, f"Store-to-load forwarding test failed: {failed} registers wrong"


def runCocotbTests():
    """Run the store-to-load test"""
    import sys
    sys.path.insert(0, os.path.dirname(__file__))

    sim = os.getenv("SIM", "verilator")

    # Find RTL directory
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(tests_dir))
    rtl_dir = os.path.join(root_dir, "rtl")

    # Collect all RTL files
    verilog_sources = []
    for root, dirs, files in os.walk(rtl_dir):
        for file in files:
            if file.endswith(".v") and not file.endswith("_tb.v"):
                verilog_sources.append(os.path.join(root, file))

    print(f"Found {len(verilog_sources)} Verilog source files")

    runner = get_runner(sim)
    runner.build(
        verilog_sources=verilog_sources,
        hdl_toplevel="riscv_cpu",
        always=True,
        build_dir="sim_build/store_to_load_test",
    )

    runner.test(
        hdl_toplevel="riscv_cpu",
        test_module="test_store_to_load",
        test_args=["--trace", "--trace-structs"]
    )


if __name__ == "__main__":
    runCocotbTests()
