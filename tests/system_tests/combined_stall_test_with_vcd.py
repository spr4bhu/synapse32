#!/usr/bin/env python3
"""
Combined Cache and Load-Use Stall Test WITH FULL VCD TRACING
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path
import sys

# Import hex creation from original test
sys.path.insert(0, str(Path(__file__).parent))
from combined_stall_test import create_combined_stall_hex

@cocotb.test()
async def test_combined_stall_with_vcd(dut):
    """Test with VCD generation enabled"""
    print("=== COMBINED STALL TEST WITH VCD TRACING ===")

    # Enable VCD dumping
    try:
        dut._log.info("VCD tracing should be enabled by simulator args")
    except:
        pass

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0

    metrics = {
        "register_values": {},
        "cycle_count": 0
    }

    print("Running for 400 cycles with full VCD tracing...")

    for cycle in range(400):
        await RisingEdge(dut.clk)
        metrics["cycle_count"] = cycle

        try:
            cpu_inst = dut.cpu_inst
            if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
                rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
                rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
                if rd_addr != 0:
                    metrics["register_values"][rd_addr] = rd_value
                    if rd_addr in [6, 8, 10, 13, 14]:
                        print(f"Cycle {cycle}: Register x{rd_addr} = {rd_value}")
        except:
            pass

    # Print results
    print(f"\n=== TEST RESULTS ===")
    print(f"Cycles executed: {metrics['cycle_count']}")

    expected_values = {
        6: 42,
        8: 142,
        10: 143,
        13: 701,
        14: 511
    }

    correct_values = 0
    print(f"\nRegister Verification:")
    for reg, expected in expected_values.items():
        if reg in metrics["register_values"]:
            actual = metrics["register_values"][reg]
            if actual == expected:
                print(f"  ✓ x{reg} = {actual}")
                correct_values += 1
            else:
                print(f"  ✗ x{reg} = {actual} (expected {expected})")
        else:
            print(f"  ✗ x{reg} = not written")

    print(f"\nVCD file should be in sim_build directory")
    print(f"Correct values: {correct_values}/5")

    # Don't fail - we expect bugs, just want the VCD
    return metrics


def runCocotbTests():
    """Run test with VCD enabled"""
    from cocotb_test.simulator import run
    import shutil
    import os

    hex_file = create_combined_stall_hex()
    print(f"Created test hex: {hex_file}")

    curr_dir = os.getcwd()
    root_dir = curr_dir
    while not os.path.exists(os.path.join(root_dir, "rtl")):
        root_dir = os.path.dirname(root_dir)

    sources = []
    rtl_dir = os.path.join(root_dir, "rtl")
    for root, _, files in os.walk(rtl_dir):
        for file in files:
            if file.endswith(".v"):
                sources.append(os.path.join(root, file))

    incl_dir = os.path.join(rtl_dir, "include")
    sim_build_dir = os.path.join(curr_dir, "sim_build", "combined_stall_vcd")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)

    print(f"\n{'='*70}")
    print("ENABLING FULL VCD TRACING")
    print(f"{'='*70}")
    print(f"Simulator: Verilator with --trace")
    print(f"Output: {sim_build_dir}")

    # Use Icarus Verilog for better VCD support
    run(
        verilog_sources=sources,
        toplevel="top",
        module="combined_stall_test_with_vcd",
        testcase="test_combined_stall_with_vcd",
        includes=[str(incl_dir)],
        simulator="icarus",  # Icarus has built-in VCD support
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        waves=True,
        force_compile=True,
    )

    print(f"\n{'='*70}")
    print("VCD GENERATION COMPLETE")
    print(f"{'='*70}")
    vcd_files = list(Path(sim_build_dir).glob("*.vcd")) + list(Path(sim_build_dir).glob("*.fst"))
    if vcd_files:
        print(f"Waveform file: {vcd_files[0]}")
    else:
        print("Warning: No VCD file found!")


if __name__ == "__main__":
    runCocotbTests()
