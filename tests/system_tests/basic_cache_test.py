#!/usr/bin/env python3
"""
Basic Cache Functionality Test
Tests cache hits, misses, and basic stall behavior
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path

def create_basic_cache_hex():
    """Create basic cache test program"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)
    
    hex_file = build_dir / "basic_cache.hex"
    
    # Simple sequential program to test cache behavior
    instructions = [
        # Test 1: Sequential execution (should cause initial cache miss, then hits)
        0x00100093,  # addi x1, x0, 1      # PC = 0x00
        0x00200113,  # addi x2, x0, 2      # PC = 0x04  
        0x00300193,  # addi x3, x0, 3      # PC = 0x08
        0x00400213,  # addi x4, x0, 4      # PC = 0x0C
        0x00500293,  # addi x5, x0, 5      # PC = 0x10
        0x00600313,  # addi x6, x0, 6      # PC = 0x14
        0x00700393,  # addi x7, x0, 7      # PC = 0x18
        0x00800413,  # addi x8, x0, 8      # PC = 0x1C
        
        # Test 2: Simple data memory operations
        0x10000537,  # lui x10, 0x10000    # x10 = data memory base
        0x00152023,  # sw x1, 0(x10)       # Store x1 to memory
        0x00252223,  # sw x2, 4(x10)       # Store x2 to memory
        0x00352423,  # sw x3, 8(x10)       # Store x3 to memory
        
        # Test 3: Jump to distant address (should cause cache miss)
        0x0640006f,  # jal x0, 0x64        # Jump to 0x64 (100 bytes away)
        
        # Padding to reach 0x64
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
        
        # Target at 0x64: Different cache block
        0x00900493,  # addi x9, x0, 9      # x9 = 9 (cache miss expected)
        0x00a00513,  # addi x10, x0, 10    # x10 = 10 (cache hit expected)
        0x00b00593,  # addi x11, x0, 11    # x11 = 11 (cache hit expected)
        
        # End
        0x00000013,  # nop
    ]
    
    with open(hex_file, 'w') as f:
        f.write("@00000000\n")
        
        # Pad instructions to fill memory properly
        padded_instructions = list(instructions)
        while len(padded_instructions) < 64:
            padded_instructions.append(0x00000013)  # NOP
        
        # Write as hex words
        for i in range(0, len(padded_instructions), 4):
            line = " ".join(f"{padded_instructions[j]:08x}" for j in range(i, min(i+4, len(padded_instructions))))
            f.write(f"{line}\n")
    
    return str(hex_file.absolute())

@cocotb.test()
async def test_basic_cache_functionality(dut):
    """Test basic cache hit/miss behavior"""
    print("=== BASIC CACHE FUNCTIONALITY TEST ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Reset
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    
    cache_metrics = {
        "first_miss_cycle": None,
        "first_hit_cycle": None,
        "jump_miss_cycle": None,
        "total_hits": 0,
        "total_misses": 0,
        "total_stalls": 0,
        "pc_at_first_miss": None,
        "pc_at_jump_miss": None
    }
    
    print("Monitoring cache behavior for basic operations...")
    
    for cycle in range(150):
        await RisingEdge(dut.clk)
        
        try:
            # Get signals (adapt to your actual signal names)
            pc = int(dut.pc_debug.value)
            cache_hit = getattr(dut, 'cache_hit_debug', None)
            cache_miss = getattr(dut, 'cache_miss_debug', None)
            cache_stall = getattr(dut, 'cache_stall_debug', None)
            
            if cache_hit is not None:
                hit = int(cache_hit.value)
                miss = int(cache_miss.value)
                stall = int(cache_stall.value)
                
                cache_metrics["total_hits"] += hit
                cache_metrics["total_misses"] += miss
                cache_metrics["total_stalls"] += stall
                
                # Record first cache miss
                if miss and cache_metrics["first_miss_cycle"] is None:
                    cache_metrics["first_miss_cycle"] = cycle
                    cache_metrics["pc_at_first_miss"] = pc
                    print(f"Cycle {cycle}: FIRST CACHE MISS at PC=0x{pc:08x}")
                
                # Record first cache hit
                if hit and cache_metrics["first_hit_cycle"] is None:
                    cache_metrics["first_hit_cycle"] = cycle
                    print(f"Cycle {cycle}: FIRST CACHE HIT at PC=0x{pc:08x}")
                
                # Record jump miss (PC around 0x64)
                if miss and pc >= 0x60 and cache_metrics["jump_miss_cycle"] is None:
                    cache_metrics["jump_miss_cycle"] = cycle
                    cache_metrics["pc_at_jump_miss"] = pc
                    print(f"Cycle {cycle}: JUMP TARGET CACHE MISS at PC=0x{pc:08x}")
                
                # Log cache events
                if hit and cycle < 100:
                    print(f"Cycle {cycle}: Cache HIT at PC=0x{pc:08x}")
                if miss:
                    print(f"Cycle {cycle}: Cache MISS at PC=0x{pc:08x}")
                    
        except Exception as e:
            # Handle missing signals gracefully
            pass
        
        # Early exit if we've seen enough activity
        if cache_metrics["total_misses"] >= 2 and cache_metrics["total_hits"] >= 5:
            break
    
    # Analysis
    print(f"\n=== BASIC CACHE TEST RESULTS ===")
    print(f"Total Cache Hits: {cache_metrics['total_hits']}")
    print(f"Total Cache Misses: {cache_metrics['total_misses']}")
    print(f"Total Cache Stalls: {cache_metrics['total_stalls']}")
    print(f"First Miss: Cycle {cache_metrics['first_miss_cycle']} at PC=0x{cache_metrics['pc_at_first_miss']:08x}" if cache_metrics['first_miss_cycle'] else "None")
    print(f"First Hit: Cycle {cache_metrics['first_hit_cycle']}" if cache_metrics['first_hit_cycle'] else "None")
    print(f"Jump Miss: Cycle {cache_metrics['jump_miss_cycle']} at PC=0x{cache_metrics['pc_at_jump_miss']:08x}" if cache_metrics['jump_miss_cycle'] else "None")
    
    # Validation
    assert cache_metrics["total_misses"] > 0, "Cache must experience misses"
    assert cache_metrics["total_hits"] >= cache_metrics["total_misses"], "Should have more hits than misses for sequential code"
    
    if cache_metrics["first_miss_cycle"] is not None and cache_metrics["first_hit_cycle"] is not None:
        assert cache_metrics["first_hit_cycle"] > cache_metrics["first_miss_cycle"], "First hit should come after first miss"
    
    print("✅ Basic cache functionality test PASSED")
    return cache_metrics

def runCocotbTests():
    """Run basic cache test"""
    from cocotb_test.simulator import run
    import shutil
    import os
    
    hex_file = create_basic_cache_hex()
    print(f"Created basic cache test hex: {hex_file}")
    
    # Setup build
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "basic_cache")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="basic_cache_test",
        testcase="test_basic_cache_functionality",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()