#!/usr/bin/env python3
"""
Cache Stall Specific Test
Tests cache miss stall behavior and pipeline freezing
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path

def create_cache_stall_hex():
    """Create cache stall test program with distant jumps"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)
    
    hex_file = build_dir / "cache_stall.hex"
    
    instructions = []
    
    # Block 1: Initial instructions (0x00-0x20)
    instructions.extend([
        0x00100093,  # addi x1, x0, 1      # x1 = 1
        0x00200113,  # addi x2, x0, 2      # x2 = 2
        0x100000ef,  # jal x1, 0x100       # Jump to 0x100 (cache miss expected)
        0x00318193,  # addi x3, x3, 3      # Should return here
        0x200000ef,  # jal x1, 0x200       # Jump to 0x200 (another cache miss)
        0x00418213,  # addi x4, x4, 4      # Should return here
        0x00500293,  # addi x5, x0, 5      # x5 = 5
        0x00000013,  # nop
    ])
    
    # Pad to 0x100 (256 bytes = 64 instructions)
    while len(instructions) < 64:
        instructions.append(0x00000013)  # nop
    
    # Block 2: At 0x100 (should cause cache miss)
    instructions.extend([
        0x06400313,  # addi x6, x0, 100    # x6 = 100
        0x0c800393,  # addi x7, x0, 200    # x7 = 200
        0x00008067,  # jalr x0, x1, 0      # Return
        0x00000013,  # nop
    ])
    
    # Pad to 0x200 (512 bytes = 128 instructions)
    while len(instructions) < 128:
        instructions.append(0x00000013)  # nop
    
    # Block 3: At 0x200 (should cause another cache miss)
    instructions.extend([
        0x12c00413,  # addi x8, x0, 300    # x8 = 300
        0x19000493,  # addi x9, x0, 400    # x9 = 400
        0x00008067,  # jalr x0, x1, 0      # Return  
        0x00000013,  # nop
    ])
    
    # Continue execution after returns
    while len(instructions) < 140:
        instructions.append(0x00000013)  # nop
    
    # Final block: Store results to verify execution
    instructions.extend([
        0x10000537,  # lui x10, 0x10000    # x10 = data base
        0x00152023,  # sw x1, 0(x10)       # Store x1
        0x00252223,  # sw x2, 4(x10)       # Store x2  
        0x00652623,  # sw x6, 12(x10)      # Store x6 (should be 100)
        0x00852823,  # sw x8, 16(x10)      # Store x8 (should be 300)
        0x00000013,  # nop
    ])
    
    with open(hex_file, 'w') as f:
        f.write("@00000000\n")
        
        # Pad to ensure adequate size
        while len(instructions) < 256:
            instructions.append(0x00000013)
        
        # Write as hex
        for i in range(0, len(instructions), 4):
            line = " ".join(f"{instructions[j]:08x}" for j in range(i, min(i+4, len(instructions))))
            f.write(f"{line}\n")
    
    return str(hex_file.absolute())

@cocotb.test()
async def test_cache_stall_behavior(dut):
    """Test cache stall behavior with distant jumps"""
    print("=== CACHE STALL BEHAVIOR TEST ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Reset
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    
    stall_metrics = {
        "cache_misses": [],
        "stall_periods": [],
        "pc_during_stalls": [],
        "max_stall_duration": 0,
        "total_stall_cycles": 0,
        "pipeline_freeze_verified": False
    }
    
    current_stall_start = None
    last_pc = 0
    pc_frozen_cycles = 0
    
    print("Monitoring cache stalls and pipeline behavior...")
    
    for cycle in range(300):
        await RisingEdge(dut.clk)
        
        try:
            pc = int(dut.pc_debug.value)
            cache_stall = int(getattr(dut, 'cache_stall_debug', type('obj', (object,), {'value': 0})).value)
            cache_miss = int(getattr(dut, 'cache_miss_debug', type('obj', (object,), {'value': 0})).value)
            
            # Track cache misses
            if cache_miss:
                miss_info = {"cycle": cycle, "pc": pc}
                stall_metrics["cache_misses"].append(miss_info)
                print(f"Cycle {cycle}: CACHE MISS at PC=0x{pc:08x}")
            
            # Track stall periods
            if cache_stall:
                if current_stall_start is None:
                    current_stall_start = cycle
                    print(f"Cycle {cycle}: CACHE STALL START at PC=0x{pc:08x}")
                
                stall_metrics["total_stall_cycles"] += 1
                stall_metrics["pc_during_stalls"].append(pc)
                
                # Check if PC is frozen during stall
                if pc == last_pc:
                    pc_frozen_cycles += 1
                
            else:
                if current_stall_start is not None:
                    stall_duration = cycle - current_stall_start
                    stall_metrics["stall_periods"].append({
                        "start": current_stall_start,
                        "duration": stall_duration,
                        "pc": pc
                    })
                    stall_metrics["max_stall_duration"] = max(stall_metrics["max_stall_duration"], stall_duration)
                    print(f"Cycle {cycle}: CACHE STALL END (duration: {stall_duration} cycles)")
                    current_stall_start = None
                    pc_frozen_cycles = 0
            
            last_pc = pc
            
            # Log important PC transitions
            if pc in [0x100, 0x200] and cycle < 200:
                print(f"Cycle {cycle}: Reached distant PC=0x{pc:08x}")
                
        except Exception as e:
            pass
        
        # Early exit if we've seen enough stalls
        if len(stall_metrics["stall_periods"]) >= 3:
            break
    
    # Final stall period if still stalling
    if current_stall_start is not None:
        stall_duration = cycle - current_stall_start
        stall_metrics["stall_periods"].append({
            "start": current_stall_start,
            "duration": stall_duration,
            "pc": last_pc
        })
        stall_metrics["max_stall_duration"] = max(stall_metrics["max_stall_duration"], stall_duration)
    
    # Verify pipeline freezing
    if pc_frozen_cycles > 0:
        stall_metrics["pipeline_freeze_verified"] = True
    
    # Analysis
    print(f"\n=== CACHE STALL TEST RESULTS ===")
    print(f"Total Cache Misses: {len(stall_metrics['cache_misses'])}")
    print(f"Total Stall Periods: {len(stall_metrics['stall_periods'])}")
    print(f"Max Stall Duration: {stall_metrics['max_stall_duration']} cycles")
    print(f"Total Stall Cycles: {stall_metrics['total_stall_cycles']}")
    print(f"Pipeline Freeze Verified: {stall_metrics['pipeline_freeze_verified']}")
    
    # Show stall periods
    for i, period in enumerate(stall_metrics['stall_periods'][:5]):  # First 5
        print(f"  Stall {i+1}: {period['duration']} cycles starting at cycle {period['start']}")
    
    # Show cache misses
    for i, miss in enumerate(stall_metrics['cache_misses'][:5]):  # First 5
        print(f"  Miss {i+1}: Cycle {miss['cycle']} at PC=0x{miss['pc']:08x}")
    
    # Validation
    assert len(stall_metrics['cache_misses']) >= 2, "Should have at least 2 cache misses from distant jumps"
    assert len(stall_metrics['stall_periods']) >= 2, "Should have stall periods corresponding to misses"
    assert stall_metrics['max_stall_duration'] > 1, "Cache stalls should last multiple cycles"
    assert stall_metrics['max_stall_duration'] < 50, "Cache stalls shouldn't be excessive"
    
    # Verify distant addresses were reached
    distant_pcs = [miss['pc'] for miss in stall_metrics['cache_misses']]
    assert any(pc >= 0x100 for pc in distant_pcs), "Should have cache miss at distant address 0x100+"
    
    print("✅ Cache stall behavior test PASSED")
    return stall_metrics

def runCocotbTests():
    """Run cache stall test"""
    from cocotb_test.simulator import run
    import shutil
    import os
    
    hex_file = create_cache_stall_hex()
    print(f"Created cache stall test hex: {hex_file}")
    
    # Setup build (same as basic test)
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "cache_stall")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="cache_stall_test",
        testcase="test_cache_stall_behavior",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()