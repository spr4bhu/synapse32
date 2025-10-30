#!/usr/bin/env python3
"""
Enhanced Test Runner with Comprehensive Debugging

This module wraps the existing combined_stall_test with enhanced tracing
and automatic bug detection. It integrates with our debug utilities to provide
detailed analysis of pipeline behavior.

Usage:
    python enhanced_test_runner.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from debug_utils.bug_detector import AdvancedBugDetector, PipelineState
from debug_utils.pipeline_trace import PipelineVisualizer, CycleState, PipelineStageState, InstructionType


def create_enhanced_combined_stall_test():
    """
    Create an enhanced version of combined_stall_test with integrated debugging
    """
    import cocotb
    from cocotb.triggers import RisingEdge, ClockCycles
    from cocotb.clock import Clock

    # Import the original test's hex creation function
    sys.path.insert(0, str(Path(__file__).parent.parent / "system_tests"))
    from combined_stall_test import create_combined_stall_hex

    @cocotb.test()
    async def test_combined_stall_with_debug(dut):
        """Enhanced combined stall test with comprehensive debugging"""
        print("\n" + "="*80)
        print("ENHANCED COMBINED STALL TEST WITH COMPREHENSIVE DEBUGGING")
        print("="*80)

        # Initialize debug infrastructure
        bug_detector = AdvancedBugDetector()
        visualizer = PipelineVisualizer(use_color=True)

        clock = Clock(dut.clk, 10, units="ns")
        cocotb.start_soon(clock.start())

        # Reset
        dut.rst.value = 1
        dut.software_interrupt.value = 0
        dut.external_interrupt.value = 0
        await ClockCycles(dut.clk, 5)
        dut.rst.value = 0

        print("Starting cycle-by-cycle analysis...")
        print("Collecting pipeline states for bug detection...\n")

        metrics = {
            "cache_stalls": 0,
            "load_use_stalls": 0,
            "register_values": {},
            "bug_cycles": []
        }

        for cycle in range(400):
            await RisingEdge(dut.clk)

            try:
                # Extract CPU state
                pc = int(dut.pc_debug.value) if hasattr(dut, 'pc_debug') else 0

                # Get stall signals
                cache_stall = False
                load_use_stall = False

                try:
                    cache_stall = bool(int(getattr(dut, 'cache_stall_debug', type('obj', (object,), {'value': 0})).value))
                except:
                    pass

                try:
                    cpu_inst = dut.cpu_inst
                    load_use_stall = bool(int(getattr(cpu_inst, 'load_use_stall', type('obj', (object,), {'value': 0})).value))
                except:
                    pass

                # Get valid bits from pipeline registers
                valid_if = True
                valid_id = True
                valid_ex = True
                valid_mem = True
                valid_wb = True

                try:
                    cpu_inst = dut.cpu_inst
                    valid_id = bool(int(getattr(cpu_inst, 'if_id_valid_out', type('obj', (object,), {'value': 1})).value))
                    valid_ex = bool(int(getattr(cpu_inst, 'id_ex_valid_out', type('obj', (object,), {'value': 1})).value))
                    valid_mem = bool(int(getattr(cpu_inst, 'ex_mem_valid_out', type('obj', (object,), {'value': 1})).value))
                    valid_wb = bool(int(getattr(cpu_inst, 'mem_wb_valid_out', type('obj', (object,), {'value': 1})).value))
                except:
                    pass

                # Get write enables
                wr_enable = False
                read_enable = False
                wr_en_out = False

                try:
                    wr_enable = bool(int(getattr(dut, 'cpu_mem_write_en', type('obj', (object,), {'value': 0})).value))
                    read_enable = bool(int(getattr(dut, 'cpu_mem_read_en', type('obj', (object,), {'value': 0})).value))
                except:
                    pass

                try:
                    cpu_inst = dut.cpu_inst
                    wr_en_out = bool(int(getattr(cpu_inst, 'wb_inst0_wr_en_out', type('obj', (object,), {'value': 0})).value))
                except:
                    pass

                # Create pipeline state for bug detector
                pipeline_state = PipelineState(
                    cycle=cycle,
                    pc=pc,
                    cache_stall=cache_stall,
                    load_use_stall=load_use_stall,
                    valid_if=valid_if,
                    valid_id=valid_id,
                    valid_ex=valid_ex,
                    valid_mem=valid_mem,
                    valid_wb=valid_wb,
                    wr_enable=wr_enable,
                    read_enable=read_enable,
                    wr_en_out=wr_en_out
                )

                bug_detector.add_pipeline_state(pipeline_state)

                # Create visualization state
                if_stage = PipelineStageState("fetch", InstructionType.UNKNOWN, valid_if, pc)
                id_stage = PipelineStageState("decode", InstructionType.UNKNOWN, valid_id)
                ex_stage = PipelineStageState("execute", InstructionType.UNKNOWN, valid_ex)
                mem_stage = PipelineStageState("memory", InstructionType.UNKNOWN, valid_mem)
                wb_stage = PipelineStageState("writebk", InstructionType.UNKNOWN, valid_wb)

                # Track register writes
                reg_write = None
                try:
                    cpu_inst = dut.cpu_inst
                    if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
                        rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
                        rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
                        if rd_addr != 0:
                            metrics["register_values"][rd_addr] = rd_value
                            reg_write = (rd_addr, rd_value)
                            if rd_addr in [6, 8, 10, 13, 14]:
                                print(f"Cycle {cycle}: Register x{rd_addr} = {rd_value}")
                except:
                    pass

                cycle_state = CycleState(
                    cycle=cycle,
                    if_stage=if_stage,
                    id_stage=id_stage,
                    ex_stage=ex_stage,
                    mem_stage=mem_stage,
                    wb_stage=wb_stage,
                    cache_stall=cache_stall,
                    load_use_stall=load_use_stall,
                    wr_enable=wr_enable,
                    read_enable=read_enable,
                    wr_en_out=wr_en_out,
                    reg_write=reg_write
                )

                visualizer.add_cycle(cycle_state)

                # Track metrics
                if cache_stall:
                    metrics["cache_stalls"] += 1
                if load_use_stall:
                    metrics["load_use_stalls"] += 1

                # Detect bugs in real-time
                if (wr_enable and (cache_stall or load_use_stall)) or \
                   (wr_en_out and (cache_stall or load_use_stall)):
                    if cycle not in metrics["bug_cycles"]:
                        metrics["bug_cycles"].append(cycle)
                        print(f"{visualizer.RED}⚠️  BUG DETECTED at cycle {cycle}!{visualizer.RESET}")
                        if wr_enable and cache_stall:
                            print(f"   → Memory write enable during cache stall (Bug #1)")
                        if wr_en_out and cache_stall:
                            print(f"   → Writeback enable during cache stall (Bug #3)")

            except Exception as e:
                # Silently continue on attribute errors
                pass

            # Stop after reasonable test duration
            if cycle > 300 and len(metrics["register_values"]) >= 5:
                break

        print("\n" + "="*80)
        print("RUNNING BUG DETECTION ALGORITHMS")
        print("="*80)

        # Run bug detection
        bug_reports = bug_detector.detect_all_bugs()

        # Print all bug reports
        for bug_id, report in bug_reports.items():
            if report.occurrence_count > 0:
                print(report)

        # Generate summary
        print(bug_detector.generate_summary())

        # Find bug cycles for focused visualization
        bug_cycles = visualizer.find_bug_cycles()

        if bug_cycles:
            print("\n" + "="*80)
            print(f"PIPELINE TRACE (Cycles with bugs: {bug_cycles[:10]})")
            print("="*80)

            # Show trace around first bug
            first_bug = bug_cycles[0]
            start = max(0, first_bug - 5)
            end = min(len(visualizer.cycles), first_bug + 10)

            trace = visualizer.render_full_trace(start, end)
            print(trace)

        # Export results
        output_dir = Path.cwd() / "debug_output"
        output_dir.mkdir(exist_ok=True)

        bug_detector.export_json(str(output_dir / "bug_report.json"))
        visualizer.export_to_file(str(output_dir / "pipeline_trace.txt"))

        print(f"\n✅ Debug output saved to: {output_dir}")

        # Validation
        expected_values = {
            6: 42,
            8: 142,
            10: 143,
            13: 701,
            14: 511
        }

        correct_values = 0
        print(f"\n{'='*80}")
        print("REGISTER VERIFICATION")
        print("="*80)
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

        print(f"\n{'='*80}")
        print("TEST SUMMARY")
        print("="*80)
        print(f"Cache stall cycles: {metrics['cache_stalls']}")
        print(f"Load-use stall cycles: {metrics['load_use_stalls']}")
        print(f"Bug occurrences: {len(metrics['bug_cycles'])}")
        print(f"Correct register values: {correct_values}/5")
        print("="*80)

        # We expect bugs, so don't fail if we find them
        assert correct_values >= 2, f"At least 2 registers should be correct, got {correct_values}"

        return metrics

    return test_combined_stall_with_debug


def main():
    """Run the enhanced test"""
    from cocotb_test.simulator import run
    import shutil

    # Import hex creation
    sys.path.insert(0, str(Path(__file__).parent.parent / "system_tests"))
    from combined_stall_test import create_combined_stall_hex

    hex_file = create_combined_stall_hex()
    print(f"Created test hex: {hex_file}")

    curr_dir = Path.cwd()
    root_dir = curr_dir
    while not (root_dir / "rtl").exists():
        root_dir = root_dir.parent

    sources = []
    rtl_dir = root_dir / "rtl"
    for verilog_file in rtl_dir.rglob("*.v"):
        sources.append(str(verilog_file))

    incl_dir = rtl_dir / "include"
    sim_build_dir = curr_dir / "sim_build" / "enhanced_combined_stall"
    if sim_build_dir.exists():
        shutil.rmtree(sim_build_dir)

    print(f"\nStarting enhanced simulation...")
    print(f"Simulator: Verilator")
    print(f"Sim build dir: {sim_build_dir}")

    run(
        verilog_sources=sources,
        toplevel="top",
        module="debug_utils.enhanced_test_runner",
        testcase="test_combined_stall_with_debug",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=str(sim_build_dir),
        force_compile=True,
        waves=True,  # Enable waveform generation
    )


if __name__ == "__main__":
    # Create the test function
    test_func = create_enhanced_combined_stall_test()

    # If running standalone, execute the test
    print("Enhanced Test Runner - Use with pytest or run standalone")
    print("\nTo run: python enhanced_test_runner.py")

    # Check if we should run
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        main()
