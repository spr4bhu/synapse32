#!/usr/bin/env python3
"""
Diagnostic test to check what instructions are actually being executed
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
from pathlib import Path

def create_simple_load_use_hex():
    """Create a simple, focused load-use test"""
    curr_dir = Path.cwd()
    build_dir = curr_dir / "build"
    build_dir.mkdir(exist_ok=True)
    
    hex_file = build_dir / "load_use_diagnostic.hex"
    
    # Simple, clear instructions
    instructions = [
        0x10000237,  # lui x4, 0x10000     # x4 = 0x10000000 (data base)
        0x00100093,  # addi x1, x0, 1      # x1 = 1
        0x00122023,  # sw x1, 0(x4)        # Store 1 to memory[0x10000000]
        0x00022283,  # lw x5, 0(x4)        # LOAD: x5 = memory[0x10000000] = 1
        0x00528313,  # addi x6, x5, 5      # DEPENDENT: x6 = x5 + 5 = 6 (HAZARD!)
        0x00000013,  # nop
        0x00000013,  # nop
        0x00000013,  # nop
    ]
    
    with open(hex_file, 'w') as f:
        f.write("@00000000\n")
        
        # Write as hex (4 instructions per line)
        for i in range(0, len(instructions), 4):
            line = " ".join(f"{instructions[j]:08x}" for j in range(i, min(i+4, len(instructions))))
            f.write(f"{line}\n")
        
        # Add padding
        padding_lines = 32
        for _ in range(padding_lines):
            f.write("00000013 00000013 00000013 00000013\n")
    
    return str(hex_file.absolute())

@cocotb.test()
async def test_load_use_diagnostic(dut):
    """Diagnostic test to see what's actually happening"""
    print("=== LOAD-USE DIAGNOSTIC TEST ===")
    
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
    
    print("=== INSTRUCTION TRACE ===")
    
    for cycle in range(50):
        await RisingEdge(dut.clk)
        
        try:
            pc = int(dut.pc_debug.value)
            instr = int(dut.instr_debug.value)
            
            # Decode instruction manually
            opcode = instr & 0x7F
            rd = (instr >> 7) & 0x1F
            rs1 = (instr >> 15) & 0x1F
            rs2 = (instr >> 20) & 0x1F
            
            # Get pipeline state
            try:
                cpu = dut.cpu_inst
                
                # ID stage
                id_rs1 = int(getattr(cpu, 'decoder_inst0_rs1_out', type('obj', (object,), {'value': 0})).value)
                id_rs2 = int(getattr(cpu, 'decoder_inst0_rs2_out', type('obj', (object,), {'value': 0})).value)
                id_rd = int(getattr(cpu, 'decoder_inst0_rd_out', type('obj', (object,), {'value': 0})).value)
                id_instr_id = int(getattr(cpu, 'decoder_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                
                # EX stage  
                ex_instr_id = int(getattr(cpu, 'id_ex_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                ex_rs1_addr = int(getattr(cpu, 'id_ex_inst0_rs1_addr_out', type('obj', (object,), {'value': 0})).value)
                ex_rs2_addr = int(getattr(cpu, 'id_ex_inst0_rs2_addr_out', type('obj', (object,), {'value': 0})).value)
                ex_rd_addr = int(getattr(cpu, 'id_ex_inst0_rd_addr_out', type('obj', (object,), {'value': 0})).value)
                
                # MEM stage
                mem_instr_id = int(getattr(cpu, 'ex_mem_inst0_instr_id_out', type('obj', (object,), {'value': 0})).value)
                mem_rd_addr = int(getattr(cpu, 'ex_mem_inst0_rd_addr_out', type('obj', (object,), {'value': 0})).value)
                
                # Load-use stall
                load_use_stall = int(getattr(cpu, 'load_use_stall', type('obj', (object,), {'value': 0})).value)
                
                # Forwarding
                forward_a = int(getattr(cpu, 'forward_a', type('obj', (object,), {'value': 0})).value)
                forward_b = int(getattr(cpu, 'forward_b', type('obj', (object,), {'value': 0})).value)
                
                # Register writes
                rf_wr_en = int(getattr(cpu, 'rf_inst0_wr_en', type('obj', (object,), {'value': 0})).value)
                rf_rd_addr = int(getattr(cpu, 'rf_inst0_rd_in', type('obj', (object,), {'value': 0})).value)
                rf_rd_value = int(getattr(cpu, 'rf_inst0_rd_value_in', type('obj', (object,), {'value': 0})).value)
                
                print(f"Cycle {cycle:2d}: PC=0x{pc:08x} instr=0x{instr:08x} op=0x{opcode:02x}")
                print(f"  ID: rs1={id_rs1} rs2={id_rs2} rd={id_rd} instr_id={id_instr_id}")
                print(f"  EX: rs1={ex_rs1_addr} rs2={ex_rs2_addr} rd={ex_rd_addr} instr_id={ex_instr_id}")
                print(f"  MEM: rd={mem_rd_addr} instr_id={mem_instr_id}")
                print(f"  Stall: load_use={load_use_stall} forward_a={forward_a} forward_b={forward_b}")
                
                if rf_wr_en and rf_rd_addr != 0:
                    print(f"  WRITE: x{rf_rd_addr} = {rf_rd_value}")
                print()
                
                # Stop when we see the expected sequence
                if pc == 0x0C:  # Should be the load instruction
                    print(f"LOAD instruction at PC=0x0C: instr_id={id_instr_id} (expected 22 for LW)")
                if pc == 0x10:  # Should be the dependent instruction
                    print(f"DEPENDENT instruction at PC=0x10: instr_id={id_instr_id} (expected 11 for ADDI)")
                    print(f"Load-use stall: {load_use_stall}")
                    
            except Exception as e:
                print(f"Cycle {cycle:2d}: PC=0x{pc:08x} instr=0x{instr:08x} (debug error: {e})")
                
        except Exception as e:
            print(f"Cycle {cycle:2d}: Error reading signals: {e}")
            
        # Stop after we see some execution
        if cycle > 40 and pc > 0x10:
            break
    
    print("=== DIAGNOSTIC COMPLETE ===")

def runCocotbTests():
    """Run diagnostic test"""
    from cocotb_test.simulator import run
    import shutil
    import os
    
    hex_file = create_simple_load_use_hex()
    print(f"Created diagnostic hex: {hex_file}")
    
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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "load_use_diagnostic")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)
    
    run(
        verilog_sources=sources,
        toplevel="top",
        module="load_use_diagnostic",
        testcase="test_load_use_diagnostic",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )

if __name__ == "__main__":
    runCocotbTests()