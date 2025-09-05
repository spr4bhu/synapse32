#!/usr/bin/env python3
"""
Enhanced memory debug to track data flow through pipeline
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
async def test_enhanced_memory_debug(dut):
    """Enhanced debug to track data through entire pipeline"""
    print("=== ENHANCED MEMORY DEBUG ===")
    
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
    
    print("=== TRACKING DATA THROUGH ENTIRE PIPELINE ===")
    
    for cycle in range(40):
        await RisingEdge(dut.clk)
        
        try:
            pc = int(dut.pc_debug.value)
            
            # Get top-level memory interface
            mem_read_data = int(getattr(dut, 'mem_read_data', type('obj', (object,), {'value': 0})).value)
            cpu_input_data = int(getattr(dut.cpu_inst, 'module_read_data_in', type('obj', (object,), {'value': 0})).value)
            
            # Get MEM_WB pipeline register data
            try:
                mem_wb_mem_data_in = int(dut.cpu_inst.mem_wb_inst.mem_data_in.value)
                mem_wb_mem_data_out = int(dut.cpu_inst.mem_wb_inst.mem_data_out.value)
                mem_wb_instr_id = int(dut.cpu_inst.mem_wb_inst.instr_id_out.value)
            except:
                mem_wb_mem_data_in = mem_wb_mem_data_out = mem_wb_instr_id = 0
            
            # Get writeback stage data
            try:
                wb_mem_data_in = int(dut.cpu_inst.writeback_inst.mem_data_in.value)
                wb_rd_value_in = int(dut.cpu_inst.writeback_inst.rd_value_in.value)
                wb_is_load = int(dut.cpu_inst.writeback_inst.is_load_instr.value)
                wb_rd_value_out = int(dut.cpu_inst.writeback_inst.rd_value_out.value)
                wb_instr_id = int(dut.cpu_inst.writeback_inst.instr_id_in.value)
            except:
                wb_mem_data_in = wb_rd_value_in = wb_is_load = wb_rd_value_out = wb_instr_id = 0
            
            # Get register writes
            try:
                rf_wr_en = int(dut.cpu_inst.rf_inst0_wr_en.value)
                rf_rd_addr = int(dut.cpu_inst.rf_inst0_rd_in.value)
                rf_rd_value = int(dut.cpu_inst.rf_inst0_rd_value_in.value)
            except:
                rf_wr_en = rf_rd_addr = rf_rd_value = 0
            
            # Show detailed trace when we have interesting data
            if (mem_read_data != 0 or cpu_input_data != 0 or 
                mem_wb_mem_data_out != 0 or wb_mem_data_in != 0 or
                (rf_wr_en and rf_rd_addr == 5)):
                
                print(f"\nCycle {cycle}: PC=0x{pc:08x}")
                print(f"  TOP LEVEL:")
                print(f"    mem_read_data = {mem_read_data}")
                print(f"    cpu_input_data = {cpu_input_data}")
                
                print(f"  MEM_WB STAGE:")
                print(f"    mem_data_in = {mem_wb_mem_data_in}")
                print(f"    mem_data_out = {mem_wb_mem_data_out}")
                print(f"    instr_id = {mem_wb_instr_id}")
                
                print(f"  WRITEBACK STAGE:")
                print(f"    mem_data_in = {wb_mem_data_in}")
                print(f"    rd_value_in (ALU) = {wb_rd_value_in}")
                print(f"    is_load_instr = {wb_is_load}")
                print(f"    rd_value_out = {wb_rd_value_out}")
                print(f"    instr_id = {wb_instr_id}")
                
                print(f"  REGISTER FILE:")
                print(f"    wr_en = {rf_wr_en}, addr = {rf_rd_addr}, value = {rf_rd_value}")
            
            # Highlight register writes to x5
            if rf_wr_en and rf_rd_addr == 5:
                print(f"\n*** CYCLE {cycle}: WRITING x5 = {rf_rd_value} ***")
                print(f"    Writeback selected: {'MEMORY' if wb_is_load else 'ALU'}")
                print(f"    Memory data available: {wb_mem_data_in}")
                print(f"    ALU result: {wb_rd_value_in}")
                
        except Exception as e:
            print(f"Debug error on cycle {cycle}: {e}")
        
        # Stop after key operations
        if cycle > 35 and pc > 0x20:
            break
    
    print("\n=== ENHANCED DEBUG COMPLETE ===")

def runCocotbTests():
    """Run enhanced memory debug test"""
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "enhanced_memory_debug")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="enhanced_memory_debug",
        testcase="test_enhanced_memory_debug",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()