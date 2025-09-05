#!/usr/bin/env python3
"""
Diagnostic to check memory address calculations and data flow
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path

def create_memory_debug_hex():
    """Create test program to debug memory operations"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)
    
    hex_file = build_dir / "memory_debug.hex"
    
    # Very simple test program
    instructions = [
        0x10000237,  # lui x4, 0x10000     # x4 = 0x10000000 (data base)
        0x00100093,  # addi x1, x0, 1      # x1 = 1
        0x00000113,  # addi x2, x0, 0      # x2 = 0 (for debugging)
        0x00122023,  # sw x1, 0(x4)        # Store 1 to memory[0x10000000]
        0x00022283,  # lw x5, 0(x4)        # Load from memory[0x10000000] -> x5
        0x00528313,  # addi x6, x5, 5      # x6 = x5 + 5 (should be 6)
        0x00000013,  # nop
        0x00000013,  # nop
    ]
    
    with open(hex_file, 'w') as f:
        f.write("@00000000\n")
        
        # Write as hex
        for i in range(0, len(instructions), 4):
            line = " ".join(f"{instructions[j]:08x}" for j in range(i, min(i+4, len(instructions))))
            f.write(f"{line}\n")
        
        # Add padding
        for _ in range(32):
            f.write("00000013 00000013 00000013 00000013\n")
    
    return str(hex_file.absolute())

@cocotb.test()
async def test_memory_debug(dut):
    """Debug memory address calculation and data flow"""
    print("=== MEMORY DEBUG TEST ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Reset
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    
    # Let cache warm up
    await ClockCycles(dut.clk, 25)
    
    print("=== MEMORY OPERATION TRACE ===")
    
    for cycle in range(40):
        await RisingEdge(dut.clk)
        
        try:
            pc = int(dut.pc_debug.value)
            instr = int(dut.instr_debug.value)
            
            # Get memory interface signals
            mem_write_en = int(getattr(dut, 'cpu_mem_write_en', type('obj', (object,), {'value': 0})).value)
            mem_read_en = int(getattr(dut, 'cpu_mem_read_en', type('obj', (object,), {'value': 0})).value)
            mem_write_addr = int(getattr(dut, 'cpu_mem_write_addr', type('obj', (object,), {'value': 0})).value)
            mem_read_addr = int(getattr(dut, 'cpu_mem_read_addr', type('obj', (object,), {'value': 0})).value)
            mem_write_data = int(getattr(dut, 'cpu_mem_write_data', type('obj', (object,), {'value': 0})).value)
            mem_read_data = int(getattr(dut, 'mem_read_data', type('obj', (object,), {'value': 0})).value)
            
            try:
                cpu = dut.cpu_inst
                
                # Get register file state
                try:
                    rf_x1 = int(cpu.rf_inst0.register_file[1])
                    rf_x4 = int(cpu.rf_inst0.register_file[4]) 
                    rf_x5 = int(cpu.rf_inst0.register_file[5])
                    rf_x6 = int(cpu.rf_inst0.register_file[6])
                except:
                    rf_x1 = rf_x4 = rf_x5 = rf_x6 = 0
                
                # Get pipeline stages
                id_instr_id = int(getattr(cpu, 'decoder_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                ex_instr_id = int(getattr(cpu, 'id_ex_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                mem_instr_id = int(getattr(cpu, 'ex_mem_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                
                # Get memory unit signals
                try:
                    mem_unit_wr_en = int(getattr(cpu, 'mem_unit_inst0_wr_enable_out', type('obj', (object,), {'value': 0})).value)
                    mem_unit_rd_en = int(getattr(cpu, 'mem_unit_inst0_read_enable_out', type('obj', (object,), {'value': 0})).value)
                    mem_unit_wr_addr = int(getattr(cpu, 'mem_unit_inst0_wr_addr_out', type('obj', (object,), {'value': 0})).value)
                    mem_unit_rd_addr = int(getattr(cpu, 'mem_unit_inst0_read_addr_out', type('obj', (object,), {'value': 0})).value)
                    mem_unit_wr_data = int(getattr(cpu, 'mem_unit_inst0_wr_data_out', type('obj', (object,), {'value': 0})).value)
                except:
                    mem_unit_wr_en = mem_unit_rd_en = 0
                    mem_unit_wr_addr = mem_unit_rd_addr = mem_unit_wr_data = 0
                
                # Register writes
                rf_wr_en = int(getattr(cpu, 'rf_inst0_wr_en', type('obj', (object,), {'value': 0})).value)
                rf_rd_addr = int(getattr(cpu, 'rf_inst0_rd_in', type('obj', (object,), {'value': 0})).value)
                rf_rd_value = int(getattr(cpu, 'rf_inst0_rd_value_in', type('obj', (object,), {'value': 0})).value)
                
                print(f"Cycle {cycle:2d}: PC=0x{pc:08x} instr=0x{instr:08x}")
                print(f"  Registers: x1={rf_x1} x4=0x{rf_x4:08x} x5={rf_x5} x6={rf_x6}")
                print(f"  Pipeline: ID={id_instr_id} EX={ex_instr_id} MEM={mem_instr_id}")
                
                # Memory operations
                if mem_write_en or mem_read_en or mem_unit_wr_en or mem_unit_rd_en:
                    print(f"  MEMORY:")
                    if mem_write_en:
                        print(f"    TOP WRITE: addr=0x{mem_write_addr:08x} data=0x{mem_write_data:08x}")
                    if mem_read_en:
                        print(f"    TOP READ:  addr=0x{mem_read_addr:08x} data=0x{mem_read_data:08x}")
                    if mem_unit_wr_en:
                        print(f"    UNIT WRITE: addr=0x{mem_unit_wr_addr:08x} data=0x{mem_unit_wr_data:08x}")
                    if mem_unit_rd_en:
                        print(f"    UNIT READ:  addr=0x{mem_unit_rd_addr:08x}")
                
                # Register writes
                if rf_wr_en and rf_rd_addr != 0:
                    print(f"  REG WRITE: x{rf_rd_addr} = {rf_rd_value}")
                
                print()
                
                # Stop when we see the key operations
                if pc == 0x0C:  # Store instruction
                    print(f"*** STORE INSTRUCTION at PC=0x0C ***")
                if pc == 0x10:  # Load instruction  
                    print(f"*** LOAD INSTRUCTION at PC=0x10 ***")
                if pc == 0x14:  # Dependent instruction
                    print(f"*** DEPENDENT INSTRUCTION at PC=0x14 ***")
                    
            except Exception as e:
                print(f"Cycle {cycle:2d}: PC=0x{pc:08x} (pipeline debug error: {e})")
                
        except Exception as e:
            print(f"Cycle {cycle:2d}: Error reading signals: {e}")
            
        # Stop after key operations
        if cycle > 35 and pc > 0x14:
            break
    
    print("=== FINAL REGISTER STATE ===")
    try:
        cpu = dut.cpu_inst
        rf_x1 = int(cpu.rf_inst0.register_file[1])
        rf_x4 = int(cpu.rf_inst0.register_file[4])
        rf_x5 = int(cpu.rf_inst0.register_file[5]) 
        rf_x6 = int(cpu.rf_inst0.register_file[6])
        print(f"x1 = {rf_x1} (should be 1)")
        print(f"x4 = 0x{rf_x4:08x} (should be 0x10000000)")
        print(f"x5 = {rf_x5} (should be 1)")
        print(f"x6 = {rf_x6} (should be 6)")
    except:
        print("Could not read final register state")
    
    print("=== MEMORY DEBUG COMPLETE ===")

def runCocotbTests():
    """Run memory debug test"""
    from cocotb_test.simulator import run
    import shutil
    import os
    
    hex_file = create_memory_debug_hex()
    print(f"Created memory debug hex: {hex_file}")
    
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "memory_debug")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="memory_address_diagnostic",
        testcase="test_memory_debug",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()