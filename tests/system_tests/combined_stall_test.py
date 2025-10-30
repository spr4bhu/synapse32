#!/usr/bin/env python3
"""
Combined Cache and Load-Use Stall Test
Tests interaction between cache stalls and load-use hazards
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path

def create_combined_stall_hex():
    """Create test program with both cache misses and load-use hazards"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)
    
    hex_file = build_dir / "combined_stall.hex"
    
    instructions = []
    
    # Block 1: Setup and initial load-use test (0x00-0x30)
    instructions.extend([
        0x10000237,  # lui x4, 0x10000     # x4 = data memory base
        0x00100093,  # addi x1, x0, 1      # x1 = 1
        0x00122023,  # sw x1, 0(x4)        # Store 1 to memory[0]
        0x00222223,  # sw x2, 4(x4)        # Store 0 to memory[4]
        
        # Load-use hazard with cache hit (sequential code)
        0x00022283,  # lw x5, 0(x4)        # x5 = memory[0] = 1 (load)
        0x00528313,  # addi x6, x5, 5      # x6 = x5 + 5 = 6 (LOAD-USE HAZARD)
        
        # Jump to distant address
        0x0c000067,  # jalr x0, x0, 192    # Jump to 0xC0 (distant cache miss)
        0x00000013,  # nop (should be skipped)
    ])
    
    # Pad to 0xC0 (192 bytes = 48 instructions)
    while len(instructions) < 48:
        instructions.append(0x00000013)  # nop
    
    # Block 2: Distant block with load-use hazard (0xC0+)
    instructions.extend([
        # This block should cause cache miss
        0x10000237,  # lui x4, 0x10000     # x4 = data memory base (reload)
        0x02a00313,  # addi x6, x0, 42     # x6 = 42 (OVERWRITES previous value!)
        0x00622623,  # sw x6, 12(x4)       # Store 42 to memory[12]
        
        # Load-use hazard in distant block
        0x00c22383,  # lw x7, 12(x4)       # x7 = memory[12] = 42 (load)
        0x06438413,  # addi x8, x7, 100    # x8 = x7 + 100 = 142 (LOAD-USE HAZARD)
        
        # Another load-use sequence
        0x00822823,  # sw x8, 16(x4)       # Store 142 to memory[16]
        0x01022483,  # lw x9, 16(x4)       # x9 = memory[16] = 142 (load)
        0x00148513,  # addi x10, x9, 1     # x10 = x9 + 1 = 143 (LOAD-USE HAZARD)

        # Jump to another distant block
        0x09c0006f,  # jal x0, 156         # Jump to 0x180 (PC-relative: 0xE4 + 0x9C = 0x180)
        0x00000013,  # nop
    ])
    
    # Pad to 0x180 (384 bytes = 96 instructions)
    while len(instructions) < 96:
        instructions.append(0x00000013)  # nop
    
    # Block 3: Another distant block (0x180+)
    instructions.extend([
        # Third cache miss with complex hazards
        0x10000237,  # lui x4, 0x10000     # x4 = data memory base
        0x15e00593,  # addi x11, x0, 350   # x11 = 350
        0x00b22a23,  # sw x11, 20(x4)      # Store 350 to memory[20]
        
        # Multiple dependent loads
        0x01422603,  # lw x12, 20(x4)      # x12 = 350 (load)
        0x00c60633,  # add x12, x12, x12   # x12 = 350 + 350 = 700 (LOAD-USE)
        0x00c22c23,  # sw x12, 24(x4)      # Store 700 to memory[24]
        0x01822683,  # lw x13, 24(x4)      # x13 = 700 (another load)
        0x00168693,  # addi x13, x13, 1    # x13 = 700 + 1 = 701 (LOAD-USE)
        
        # Final results storage
        0x00d22e23,  # sw x13, 28(x4)      # Store final result
        0x1ff00713,  # addi x14, x0, 511   # x14 = 511 (completion marker)
        
        # End
        0x00000013,  # nop
        0x00000013,  # nop
    ])
    
    with open(hex_file, 'w') as f:
        f.write("@00000000\n")
        
        # Ensure adequate padding
        while len(instructions) < 150:
            instructions.append(0x00000013)
        
        # Write as hex
        for i in range(0, len(instructions), 4):
            line = " ".join(f"{instructions[j]:08x}" for j in range(i, min(i+4, len(instructions))))
            f.write(f"{line}\n")
    
    return str(hex_file.absolute())

@cocotb.test()
async def test_combined_stall_interaction(dut):
    """Test interaction between cache stalls and load-use hazards"""
    print("=== COMBINED CACHE + LOAD-USE STALL TEST ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Reset
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    
    combined_metrics = {
        "cache_stalls": 0,
        "load_use_stalls": 0,
        "simultaneous_stalls": 0,
        "cache_miss_events": [],
        "load_use_events": [],
        "stall_interactions": [],
        "register_values": {},
        "hazard_resolutions": 0
    }
    
    current_cache_stall = False
    current_load_use_stall = False
    interaction_start = None
    
    print("Monitoring combined stall behavior...")
    
    for cycle in range(400):
        await RisingEdge(dut.clk)
        
        try:
            pc = int(dut.pc_debug.value)
            
            cache_stall = int(getattr(dut, 'cache_stall_debug', type('obj', (object,), {'value': 0})).value)
            cache_miss = int(getattr(dut, 'cache_miss_debug', type('obj', (object,), {'value': 0})).value)
            
            load_use_stall = 0
            try:
                cpu_inst = dut.cpu_inst
                load_use_stall = int(getattr(cpu_inst, 'load_use_stall', type('obj', (object,), {'value': 0})).value)
            except:
                pass
            
            combined_metrics["cache_stalls"] += cache_stall
            combined_metrics["load_use_stalls"] += load_use_stall
            
            if cache_stall and load_use_stall:
                combined_metrics["simultaneous_stalls"] += 1
                if not (current_cache_stall and current_load_use_stall):
                    print(f"Cycle {cycle}: SIMULTANEOUS STALLS at PC=0x{pc:08x}")
            
            if cache_miss:
                miss_event = {"cycle": cycle, "pc": pc}
                combined_metrics["cache_miss_events"].append(miss_event)
                print(f"Cycle {cycle}: CACHE MISS at PC=0x{pc:08x}")
            
            if load_use_stall and not current_load_use_stall:
                load_use_event = {"cycle": cycle, "pc": pc, "during_cache_stall": cache_stall}
                combined_metrics["load_use_events"].append(load_use_event)
                if cache_stall:
                    print(f"Cycle {cycle}: LOAD-USE STALL during CACHE STALL at PC=0x{pc:08x}")
                else:
                    print(f"Cycle {cycle}: LOAD-USE STALL (independent) at PC=0x{pc:08x}")
            
            if (cache_stall or load_use_stall) and interaction_start is None:
                interaction_start = cycle
            elif not (cache_stall or load_use_stall) and interaction_start is not None:
                interaction_duration = cycle - interaction_start
                interaction = {
                    "start": interaction_start,
                    "duration": interaction_duration,
                    "end_pc": pc
                }
                combined_metrics["stall_interactions"].append(interaction)
                combined_metrics["hazard_resolutions"] += 1
                print(f"Cycle {cycle}: STALL INTERACTION RESOLVED (duration: {interaction_duration} cycles)")
                interaction_start = None
            
            try:
                cpu_inst = dut.cpu_inst
                if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
                    rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
                    rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
                    if rd_addr != 0:
                        combined_metrics["register_values"][rd_addr] = rd_value
                        if rd_addr in [6, 8, 10, 13, 14]:
                            print(f"Cycle {cycle}: Register x{rd_addr} = {rd_value}")
            except:
                pass
            
            current_cache_stall = cache_stall
            current_load_use_stall = load_use_stall
            
        except Exception as e:
            pass

        # REMOVED: Early exit condition was preventing full program execution
        # if len(combined_metrics["cache_miss_events"]) >= 3 and len(combined_metrics["load_use_events"]) >= 5:
        #     break
    
    if interaction_start is not None:
        interaction_duration = cycle - interaction_start
        combined_metrics["stall_interactions"].append({
            "start": interaction_start,
            "duration": interaction_duration,
            "end_pc": pc
        })
    
    # Analysis
    print(f"\n=== COMBINED STALL TEST RESULTS ===")
    print(f"Cache Stall Cycles: {combined_metrics['cache_stalls']}")
    print(f"Load-Use Stall Cycles: {combined_metrics['load_use_stalls']}")
    print(f"Simultaneous Stall Cycles: {combined_metrics['simultaneous_stalls']}")
    print(f"Cache Miss Events: {len(combined_metrics['cache_miss_events'])}")
    print(f"Load-Use Events: {len(combined_metrics['load_use_events'])}")
    print(f"Stall Interactions: {len(combined_metrics['stall_interactions'])}")
    print(f"Hazard Resolutions: {combined_metrics['hazard_resolutions']}")
    
    for i, interaction in enumerate(combined_metrics['stall_interactions'][:5]):
        print(f"  Interaction {i+1}: {interaction['duration']} cycles")
    
    load_use_during_cache = [event for event in combined_metrics['load_use_events'] if event['during_cache_stall']]
    print(f"Load-Use Stalls during Cache Stalls: {len(load_use_during_cache)}")
    
    # CORRECTED EXPECTED VALUES
    expected_values = {
        6: 42,   # Block 2 overwrites Block 1 value
        8: 142,  # 42 + 100
        10: 143, # 142 + 1
        13: 701, # 700 + 1
        14: 511  # Completion marker
    }
    
    correct_values = 0
    print(f"\nRegister Verification:")
    for reg, expected in expected_values.items():
        if reg in combined_metrics["register_values"]:
            actual = combined_metrics["register_values"][reg]
            if actual == expected:
                print(f"  ✓ x{reg} = {actual}")
                correct_values += 1
            else:
                print(f"  ✗ x{reg} = {actual} (expected {expected})")
        else:
            print(f"  ✗ x{reg} = not written")
    
    # Validation
    assert len(combined_metrics['cache_miss_events']) >= 2, "Should have multiple cache misses"
    assert len(combined_metrics['load_use_events']) >= 3, "Should have multiple load-use hazards"
    assert correct_values >= 3, f"Should have at least 3 correct register values, got {correct_values}"
    
    print("✅ Combined stall interaction test PASSED")
    return combined_metrics

def runCocotbTests():
    """Run combined stall test"""
    from cocotb_test.simulator import run
    import shutil
    import os
    
    hex_file = create_combined_stall_hex()
    print(f"Created combined stall test hex: {hex_file}")
    
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "combined_stall")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="combined_stall_test",
        testcase="test_combined_stall_interaction",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()