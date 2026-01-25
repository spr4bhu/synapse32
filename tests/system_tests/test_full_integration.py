"""
Comprehensive Integration Tests for Synapse-32 RISC-V CPU with Instruction Cache

This test suite covers all CPU features and their interaction with the cache:
- Cache operations (hit/miss/refill)
- All RISC-V instruction types (R, I, S, B, U, J)
- Pipeline hazards (RAW, load-use, control)
- FENCE.I cache invalidation
- CSR operations
- Complex scenarios (loops, function calls)

Target: top.v (full system integration)
Simulator: Verilator with cocotb
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer, ClockCycles, FallingEdge
from cocotb.clock import Clock
import os
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)

# ============================================================================
# Memory Map Constants (from memory_map.vh)
# ============================================================================
INSTR_MEM_BASE = 0x00000000
INSTR_MEM_SIZE = 0x00080000  # 512KB
DATA_MEM_BASE = 0x10000000  # Hardware translates to unified memory
DATA_MEM_SIZE = 0x00100000   # 1MB
TIMER_BASE = 0x02004000
UART_BASE = 0x20000000

# ============================================================================
# RISC-V Instruction Encoding Functions
# ============================================================================

def encode_r_type(opcode, rd, funct3, rs1, rs2, funct7):
    """Encode R-type instruction: add, sub, and, or, xor, sll, srl, sra, slt, sltu"""
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_i_type(opcode, rd, funct3, rs1, imm):
    """Encode I-type instruction: addi, andi, ori, xori, slti, sltiu, loads, jalr"""
    imm = imm & 0xFFF  # 12-bit immediate
    return (imm << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_s_type(opcode, funct3, rs1, rs2, imm):
    """Encode S-type instruction: sb, sh, sw"""
    imm = imm & 0xFFF  # 12-bit immediate
    imm_11_5 = (imm >> 5) & 0x7F
    imm_4_0 = imm & 0x1F
    return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

def encode_b_type(opcode, funct3, rs1, rs2, imm):
    """Encode B-type instruction: beq, bne, blt, bge, bltu, bgeu"""
    imm = imm & 0x1FFF  # 13-bit immediate
    imm_12 = (imm >> 12) & 0x1
    imm_10_5 = (imm >> 5) & 0x3F
    imm_4_1 = (imm >> 1) & 0xF
    imm_11 = (imm >> 11) & 0x1
    return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

def encode_u_type(opcode, rd, imm):
    """Encode U-type instruction: lui, auipc"""
    imm = imm & 0xFFFFF  # 20-bit immediate (upper bits)
    return (imm << 12) | (rd << 7) | opcode

def encode_j_type(opcode, rd, imm):
    """Encode J-type instruction: jal"""
    imm = imm & 0x1FFFFF  # 21-bit immediate
    imm_20 = (imm >> 20) & 0x1
    imm_10_1 = (imm >> 1) & 0x3FF
    imm_11 = (imm >> 11) & 0x1
    imm_19_12 = (imm >> 12) & 0xFF
    return (imm_20 << 31) | (imm_10_1 << 21) | (imm_11 << 20) | \
           (imm_19_12 << 12) | (rd << 7) | opcode

# ============================================================================
# Instruction Generators (using RISC-V standard opcodes)
# ============================================================================

# R-type instructions (opcode = 0b0110011 = 0x33)
def ADD(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x0, rs1, rs2, 0x00)

def SUB(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x0, rs1, rs2, 0x20)

def AND(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x7, rs1, rs2, 0x00)

def OR(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x6, rs1, rs2, 0x00)

def XOR(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x4, rs1, rs2, 0x00)

def SLL(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x1, rs1, rs2, 0x00)

def SRL(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x5, rs1, rs2, 0x00)

def SRA(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x5, rs1, rs2, 0x20)

def SLT(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x2, rs1, rs2, 0x00)

def SLTU(rd, rs1, rs2):
    return encode_r_type(0x33, rd, 0x3, rs1, rs2, 0x00)

# I-type arithmetic instructions (opcode = 0b0010011 = 0x13)
def ADDI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x0, rs1, imm)

def ANDI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x7, rs1, imm)

def ORI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x6, rs1, imm)

def XORI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x4, rs1, imm)

def SLTI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x2, rs1, imm)

def SLTIU(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x3, rs1, imm)

def SLLI(rd, rs1, shamt):
    return encode_i_type(0x13, rd, 0x1, rs1, shamt & 0x1F)

def SRLI(rd, rs1, shamt):
    return encode_i_type(0x13, rd, 0x5, rs1, shamt & 0x1F)

def SRAI(rd, rs1, shamt):
    return encode_i_type(0x13, rd, 0x5, rs1, (0x400 | (shamt & 0x1F)))

# Load instructions (opcode = 0b0000011 = 0x03)
def LW(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x2, rs1, imm)

def LH(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x1, rs1, imm)

def LB(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x0, rs1, imm)

def LHU(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x5, rs1, imm)

def LBU(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x4, rs1, imm)

# Store instructions (opcode = 0b0100011 = 0x23)
def SW(rs1, rs2, imm):
    return encode_s_type(0x23, 0x2, rs1, rs2, imm)

def SH(rs1, rs2, imm):
    return encode_s_type(0x23, 0x1, rs1, rs2, imm)

def SB(rs1, rs2, imm):
    return encode_s_type(0x23, 0x0, rs1, rs2, imm)

# Branch instructions (opcode = 0b1100011 = 0x63)
def BEQ(rs1, rs2, imm):
    return encode_b_type(0x63, 0x0, rs1, rs2, imm)

def BNE(rs1, rs2, imm):
    return encode_b_type(0x63, 0x1, rs1, rs2, imm)

def BLT(rs1, rs2, imm):
    return encode_b_type(0x63, 0x4, rs1, rs2, imm)

def BGE(rs1, rs2, imm):
    return encode_b_type(0x63, 0x5, rs1, rs2, imm)

def BLTU(rs1, rs2, imm):
    return encode_b_type(0x63, 0x6, rs1, rs2, imm)

def BGEU(rs1, rs2, imm):
    return encode_b_type(0x63, 0x7, rs1, rs2, imm)

# U-type instructions
def LUI(rd, imm):
    return encode_u_type(0x37, rd, imm)

def AUIPC(rd, imm):
    return encode_u_type(0x17, rd, imm)

# J-type instructions
def JAL(rd, imm):
    return encode_j_type(0x6F, rd, imm)

def JALR(rd, rs1, imm):
    return encode_i_type(0x67, rd, 0x0, rs1, imm)

# System instructions
def NOP():
    return ADDI(0, 0, 0)

def FENCE_I():
    """FENCE.I instruction for instruction cache invalidation"""
    return 0x0000100F

def HALT():
    """Infinite loop to stop execution (JAL x0, 0 - jumps to itself)"""
    return JAL(0, 0)

# CSR instructions (opcode = 0b1110011 = 0x73)
def CSRRW(rd, rs1, csr):
    return (csr << 20) | (rs1 << 15) | (0x1 << 12) | (rd << 7) | 0x73

def CSRRS(rd, rs1, csr):
    return (csr << 20) | (rs1 << 15) | (0x2 << 12) | (rd << 7) | 0x73

def CSRRC(rd, rs1, csr):
    return (csr << 20) | (rs1 << 15) | (0x3 << 12) | (rd << 7) | 0x73

def CSRRWI(rd, uimm, csr):
    return (csr << 20) | (uimm << 15) | (0x5 << 12) | (rd << 7) | 0x73

def CSRRSI(rd, uimm, csr):
    return (csr << 20) | (uimm << 15) | (0x6 << 12) | (rd << 7) | 0x73

def CSRRCI(rd, uimm, csr):
    return (csr << 20) | (uimm << 15) | (0x7 << 12) | (rd << 7) | 0x73

# CSR addresses
CSR_MSTATUS = 0x300
CSR_MTVEC = 0x305
CSR_MEPC = 0x341
CSR_MCAUSE = 0x342
CSR_CYCLE = 0xC00
CSR_CYCLEH = 0xC80

# ============================================================================
# Helper Functions
# ============================================================================

async def reset_dut(dut, cycles=5):
    """Reset the DUT properly using hardware reset signal.
    
    The reset signal clears:
    - All pipeline registers
    - Register file (all 32 registers set to 0)
    - Instruction cache (all valid bits cleared)
    - PC (reset to 0)
    """
    print(f"[DEBUG] Asserting hardware reset...")
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, cycles)
    print("[DEBUG] Reset held for {} cycles, ready for program load".format(cycles))

async def release_reset(dut):
    """Release reset after program is loaded"""
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    print("[DEBUG] Reset released, CPU executing from PC=0")

async def wait_for_cache_ready(dut, max_cycles=100):
    """Wait for instruction cache to be ready (no stall)"""
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        try:
            if not int(dut.icache_stall.value):
                return True
        except:
            return True
    return False

async def load_program(dut, instructions, start_addr=0):
    """Load program into instruction memory and release reset
    
    Instructions should be a list of 32-bit instruction values.
    They will be loaded starting at start_addr.
    Call this AFTER reset_dut (which keeps reset held).
    """
    print(f"[DEBUG] Loading {len(instructions)} instructions at 0x{start_addr:08x}")
    # Access unified memory (byte-addressed RAM array)
    mem = dut.unified_memory_inst.ram

    for i, instr in enumerate(instructions):
        byte_addr = start_addr + (i * 4)
        try:
            # Write instruction as 4 bytes (little-endian)
            mem[byte_addr + 0].value = (instr >> 0) & 0xFF
            mem[byte_addr + 1].value = (instr >> 8) & 0xFF
            mem[byte_addr + 2].value = (instr >> 16) & 0xFF
            mem[byte_addr + 3].value = (instr >> 24) & 0xFF
            # Only print first few and last few for brevity
            if i < 3 or i >= len(instructions) - 2:
                print(f"[DEBUG]   [0x{byte_addr:08x}]: 0x{instr:08x}")
            elif i == 3:
                print(f"[DEBUG]   ... ({len(instructions) - 4} more instructions)")
        except Exception as e:
            print(f"[ERROR] Failed to load instruction at byte_addr 0x{byte_addr:08x}: {e}")
            break
    
    # Now release reset
    await release_reset(dut)
    print(f"[DEBUG] Program loaded and CPU started")

async def run_cycles(dut, cycles, check_completion=True, verbose=False):
    """Run for specified cycles, monitoring execution"""
    print(f"[DEBUG] Running for {cycles} cycles...")
    for cycle in range(cycles):
        await RisingEdge(dut.clk)
        
        # Log current state periodically
        if verbose or cycle % 20 == 0:
            try:
                pc = int(dut.cpu_pc_out.value)
                stall = int(dut.icache_stall.value) if hasattr(dut, 'icache_stall') else 0
                instr = int(dut.instr_debug.value) if hasattr(dut, 'instr_debug') else 0
                print(f"[DEBUG] Cycle {cycle:4d}: PC=0x{pc:08x}, instr=0x{instr:08x}, stall={stall}")
            except Exception as e:
                if verbose:
                    print(f"[DEBUG] Cycle {cycle:4d}: Error reading state: {e}")
    print(f"[DEBUG] Completed {cycles} cycles")

def get_reg(dut, reg_num):
    """Get register value from register file"""
    if reg_num == 0:
        return 0
    try:
        return int(dut.cpu_inst.rf_inst0.register_file[reg_num].value)
    except Exception as e:
        print(f"[WARN] Could not read register x{reg_num}: {e}")
        return None

def set_reg(dut, reg_num, value):
    """Set register value in register file (for test setup)"""
    if reg_num == 0:
        return  # x0 is always 0
    try:
        dut.cpu_inst.rf_inst0.register_file[reg_num].value = value
        print(f"[DEBUG] Set x{reg_num} = 0x{value:08x}")
    except Exception as e:
        print(f"[WARN] Could not write register x{reg_num}: {e}")

async def verify_reg(dut, reg_num, expected, name=""):
    """Verify register has expected value"""
    actual = get_reg(dut, reg_num)
    if actual is None:
        print(f"[FAIL] {name} x{reg_num}: Could not read register")
        return False
    
    # Handle signed values
    if expected < 0:
        expected = expected & 0xFFFFFFFF
    
    if actual != expected:
        print(f"[FAIL] {name} x{reg_num}: expected 0x{expected:08x}, got 0x{actual:08x}")
        return False
    else:
        print(f"[PASS] {name} x{reg_num} = 0x{actual:08x} ✓")
        return True

def get_data_mem(dut, addr):
    """Get data from unified memory (byte-addressable)"""
    try:
        # Map DATA_MEM_BASE addresses to unified memory (hardware does same translation)
        # DATA_MEM at 0x10000000 maps to offset 0x00080000 in unified memory
        actual_addr = (addr - DATA_MEM_BASE) + INSTR_MEM_SIZE
        mem = dut.unified_memory_inst.ram
        # Read 4 bytes and combine (little-endian)
        b0 = int(mem[actual_addr].value)
        b1 = int(mem[actual_addr + 1].value)
        b2 = int(mem[actual_addr + 2].value)
        b3 = int(mem[actual_addr + 3].value)
        val = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0
        print(f"[DEBUG] Read MEM[0x{addr:08x}] (actual 0x{actual_addr:08x}) = 0x{val:08x}")
        return val
    except Exception as e:
        print(f"[WARN] Could not read data memory at 0x{addr:08x}: {e}")
        return None

def set_data_mem(dut, addr, value):
    """Set data in unified memory (word, byte-addressable storage)"""
    try:
        # Map DATA_MEM_BASE addresses to unified memory (hardware does same translation)
        # DATA_MEM at 0x10000000 maps to offset 0x00080000 in unified memory
        actual_addr = (addr - DATA_MEM_BASE) + INSTR_MEM_SIZE
        mem = dut.unified_memory_inst.ram
        # Write 4 bytes (little-endian)
        mem[actual_addr].value = value & 0xFF
        mem[actual_addr + 1].value = (value >> 8) & 0xFF
        mem[actual_addr + 2].value = (value >> 16) & 0xFF
        mem[actual_addr + 3].value = (value >> 24) & 0xFF
        print(f"[DEBUG] Set MEM[0x{addr:08x}] (actual 0x{actual_addr:08x}) = 0x{value:08x}")
    except Exception as e:
        print(f"[WARN] Could not write data memory at 0x{addr:08x}: {e}")

def dump_registers(dut, regs=None):
    """Dump register values for debugging"""
    if regs is None:
        regs = range(1, 32)  # x1-x31
    print("[DEBUG] Register dump:")
    for reg in regs:
        val = get_reg(dut, reg)
        if val is not None and val != 0:
            print(f"[DEBUG]   x{reg:2d} = 0x{val:08x} ({val})")

def print_program(instructions, start_addr=0):
    """Print program listing"""
    print("[DEBUG] Program listing:")
    for i, instr in enumerate(instructions):
        addr = start_addr + i * 4
        print(f"[DEBUG]   0x{addr:08x}: 0x{instr:08x}")

# ============================================================================
# Category 1: Cache + Basic Execution Tests
# ============================================================================

@cocotb.test()
async def test_cache_cold_start(dut):
    """Test cache behavior on cold start with empty cache"""
    print("=== Test: Cache Cold Start ===")
    
    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    # Reset
    await reset_dut(dut)
    
    # Load simple program
    program = [
        ADDI(1, 0, 100),    # x1 = 100
        ADDI(2, 0, 200),    # x2 = 200
        ADD(3, 1, 2),       # x3 = x1 + x2 = 300
        HALT(),             # Stop here
    ]
    await load_program(dut, program)
    
    # Run and track cache stalls
    stall_count = 0
    for cycle in range(80):
        await RisingEdge(dut.clk)
        try:
            if int(dut.icache_stall.value):
                stall_count += 1
            if cycle % 10 == 0:
                pc = int(dut.cpu_pc_out.value)
                print(f"[DEBUG] Cycle {cycle}: PC=0x{pc:08x}, stalls={stall_count}")
        except:
            pass
    
    print(f"[DEBUG] Total stall cycles: {stall_count}")
    
    assert await verify_reg(dut, 1, 100, "Cold start")
    assert await verify_reg(dut, 2, 200, "Cold start")
    assert await verify_reg(dut, 3, 300, "Cold start")
    
    print("Cache cold start test PASSED")

@cocotb.test()
async def test_cache_hit_after_refill(dut):
    """Test cache hit behavior after initial refill"""
    log.info("=== Test: Cache Hit After Refill ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Program that loops back to cached instructions
    # Loop 3 times incrementing x1
    program = [
        ADDI(1, 0, 0),      # 0x00: x1 = 0
        ADDI(2, 0, 3),      # 0x04: x2 = 3 (loop count)
        ADDI(1, 1, 1),      # 0x08: loop: x1 += 1
        ADDI(2, 2, -1),     # 0x0C: x2 -= 1
        BNE(2, 0, -8),      # 0x10: if x2 != 0, goto loop (PC-8)
        HALT(),             # 0x14: stop
    ]
    await load_program(dut, program)
    
    # Run enough cycles for loop completion
    await run_cycles(dut, 100)
    
    # x1 should be 3 (looped 3 times)
    assert await verify_reg(dut, 1, 3, "Cache hit")
    assert await verify_reg(dut, 2, 0, "Cache hit")
    
    log.info("Cache hit after refill test PASSED")

@cocotb.test()
async def test_cache_line_boundary(dut):
    """Test instruction fetch across cache line boundaries"""
    log.info("=== Test: Cache Line Boundary ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Cache line = 4 words = 16 bytes
    # Create program that spans multiple cache lines
    program = [
        # Cache line 0 (0x00-0x0F)
        ADDI(1, 0, 1),      # 0x00
        ADDI(2, 0, 2),      # 0x04
        ADDI(3, 0, 3),      # 0x08
        ADDI(4, 0, 4),      # 0x0C
        # Cache line 1 (0x10-0x1F)
        ADDI(5, 0, 5),      # 0x10
        ADDI(6, 0, 6),      # 0x14
        ADDI(7, 0, 7),      # 0x18
        ADDI(8, 0, 8),      # 0x1C
        # Cache line 2 (0x20-0x2F)
        ADD(9, 1, 2),       # 0x20: x9 = 1+2 = 3
        ADD(10, 3, 4),      # 0x24: x10 = 3+4 = 7
        ADD(11, 5, 6),      # 0x28: x11 = 5+6 = 11
        ADD(12, 7, 8),      # 0x2C: x12 = 7+8 = 15
        HALT(),             # Stop here
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    # Verify all values
    assert await verify_reg(dut, 1, 1, "Line boundary")
    assert await verify_reg(dut, 5, 5, "Line boundary")
    assert await verify_reg(dut, 9, 3, "Line boundary")
    assert await verify_reg(dut, 10, 7, "Line boundary")
    assert await verify_reg(dut, 11, 11, "Line boundary")
    assert await verify_reg(dut, 12, 15, "Line boundary")
    
    log.info("Cache line boundary test PASSED")

@cocotb.test()
async def test_sequential_execution(dut):
    """Test sequential instruction execution with cache"""
    log.info("=== Test: Sequential Execution ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Long sequence of dependent instructions
    program = [
        ADDI(1, 0, 1),      # x1 = 1
        ADDI(1, 1, 1),      # x1 = 2
        ADDI(1, 1, 1),      # x1 = 3
        ADDI(1, 1, 1),      # x1 = 4
        ADDI(1, 1, 1),      # x1 = 5
        ADDI(1, 1, 1),      # x1 = 6
        ADDI(1, 1, 1),      # x1 = 7
        ADDI(1, 1, 1),      # x1 = 8
        ADDI(1, 1, 1),      # x1 = 9
        ADDI(1, 1, 1),      # x1 = 10
        HALT(),             # Stop here
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 80)
    
    assert await verify_reg(dut, 1, 10, "Sequential")
    
    log.info("Sequential execution test PASSED")

@cocotb.test()
async def test_cache_stall_handling(dut):
    """Test CPU properly stalls during cache misses"""
    print("=== Test: Cache Stall Handling ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 42),     # x1 = 42
        ADDI(2, 1, 1),      # x2 = 43
        ADD(3, 1, 2),       # x3 = 85
        HALT(),             # Stop here
    ]
    await load_program(dut, program)
    
    # Run and monitor stalls
    stall_cycles = 0
    for cycle in range(60):
        await RisingEdge(dut.clk)
        try:
            stall = int(dut.icache_stall.value)
            if stall:
                stall_cycles += 1
            if cycle % 10 == 0:
                pc = int(dut.cpu_pc_out.value)
                print(f"[DEBUG] Cycle {cycle}: PC=0x{pc:08x}, stalls={stall_cycles}")
        except:
            pass
    
    print(f"[DEBUG] Total stall cycles: {stall_cycles}")
    
    # Verify correct execution despite stalls
    assert await verify_reg(dut, 1, 42, "Stall handling")
    assert await verify_reg(dut, 2, 43, "Stall handling")
    assert await verify_reg(dut, 3, 85, "Stall handling")
    
    print("Cache stall handling test PASSED")

# ============================================================================
# Category 2: R-Type Instructions
# ============================================================================

@cocotb.test()
async def test_r_type_arithmetic(dut):
    """Test R-type arithmetic: ADD, SUB"""
    log.info("=== Test: R-Type Arithmetic ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 100),    # x1 = 100
        ADDI(2, 0, 50),     # x2 = 50
        ADD(3, 1, 2),       # x3 = 100 + 50 = 150
        SUB(4, 1, 2),       # x4 = 100 - 50 = 50
        ADD(5, 3, 4),       # x5 = 150 + 50 = 200
        SUB(6, 3, 4),       # x6 = 150 - 50 = 100
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 60)
    
    assert await verify_reg(dut, 3, 150, "ADD")
    assert await verify_reg(dut, 4, 50, "SUB")
    assert await verify_reg(dut, 5, 200, "ADD chain")
    assert await verify_reg(dut, 6, 100, "SUB chain")
    
    log.info("R-type arithmetic test PASSED")

@cocotb.test()
async def test_r_type_logical(dut):
    """Test R-type logical: AND, OR, XOR"""
    log.info("=== Test: R-Type Logical ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 0xFF),   # x1 = 0xFF
        ADDI(2, 0, 0x0F),   # x2 = 0x0F
        AND(3, 1, 2),       # x3 = 0xFF & 0x0F = 0x0F
        OR(4, 1, 2),        # x4 = 0xFF | 0x0F = 0xFF
        XOR(5, 1, 2),       # x5 = 0xFF ^ 0x0F = 0xF0
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 60)
    
    assert await verify_reg(dut, 3, 0x0F, "AND")
    assert await verify_reg(dut, 4, 0xFF, "OR")
    assert await verify_reg(dut, 5, 0xF0, "XOR")
    
    log.info("R-type logical test PASSED")

@cocotb.test()
async def test_r_type_shift(dut):
    """Test R-type shifts: SLL, SRL, SRA"""
    log.info("=== Test: R-Type Shift ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 8),      # x1 = 8
        ADDI(2, 0, 2),      # x2 = 2 (shift amount)
        SLL(3, 1, 2),       # x3 = 8 << 2 = 32
        SRL(4, 1, 2),       # x4 = 8 >> 2 = 2
        LUI(5, 0x80000),    # x5 = 0x80000000 (negative)
        SRL(6, 5, 2),       # x6 = logical right shift
        SRA(7, 5, 2),       # x7 = arithmetic right shift (sign extend)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 70)
    
    assert await verify_reg(dut, 3, 32, "SLL")
    assert await verify_reg(dut, 4, 2, "SRL")
    # For SRL: 0x80000000 >> 2 = 0x20000000
    assert await verify_reg(dut, 6, 0x20000000, "SRL negative")
    # For SRA: 0x80000000 >> 2 = 0xE0000000 (sign extended)
    assert await verify_reg(dut, 7, 0xE0000000, "SRA")
    
    log.info("R-type shift test PASSED")

@cocotb.test()
async def test_r_type_compare(dut):
    """Test R-type comparisons: SLT, SLTU"""
    log.info("=== Test: R-Type Compare ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 10),     # x1 = 10
        ADDI(2, 0, 20),     # x2 = 20
        ADDI(3, 0, -1),     # x3 = -1 (0xFFFFFFFF)
        SLT(4, 1, 2),       # x4 = (10 < 20) = 1
        SLT(5, 2, 1),       # x5 = (20 < 10) = 0
        SLTU(6, 1, 3),      # x6 = (10 <u 0xFFFFFFFF) = 1
        SLT(7, 1, 3),       # x7 = (10 <s -1) = 0 (signed)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 70)
    
    assert await verify_reg(dut, 4, 1, "SLT true")
    assert await verify_reg(dut, 5, 0, "SLT false")
    assert await verify_reg(dut, 6, 1, "SLTU")
    assert await verify_reg(dut, 7, 0, "SLT signed")
    
    log.info("R-type compare test PASSED")

# ============================================================================
# Category 3: I-Type Instructions
# ============================================================================

@cocotb.test()
async def test_i_type_arithmetic(dut):
    """Test I-type arithmetic: ADDI, SLTI, SLTIU"""
    log.info("=== Test: I-Type Arithmetic ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 100),    # x1 = 100
        ADDI(2, 1, 50),     # x2 = 150
        ADDI(3, 2, -30),    # x3 = 120 (negative immediate)
        SLTI(4, 1, 200),    # x4 = (100 < 200) = 1
        SLTI(5, 1, 50),     # x5 = (100 < 50) = 0
        SLTIU(6, 1, 200),   # x6 = (100 <u 200) = 1
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 60)
    
    assert await verify_reg(dut, 1, 100, "ADDI")
    assert await verify_reg(dut, 2, 150, "ADDI chain")
    assert await verify_reg(dut, 3, 120, "ADDI negative")
    assert await verify_reg(dut, 4, 1, "SLTI true")
    assert await verify_reg(dut, 5, 0, "SLTI false")
    assert await verify_reg(dut, 6, 1, "SLTIU")
    
    log.info("I-type arithmetic test PASSED")

@cocotb.test()
async def test_i_type_logical(dut):
    """Test I-type logical: ANDI, ORI, XORI"""
    log.info("=== Test: I-Type Logical ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 0xFF),   # x1 = 0xFF
        ANDI(2, 1, 0x0F),   # x2 = 0xFF & 0x0F = 0x0F
        ORI(3, 1, 0x100),   # x3 = 0xFF | 0x100 = 0x1FF
        XORI(4, 1, 0xFF),   # x4 = 0xFF ^ 0xFF = 0x00
        XORI(5, 1, 0xF0),   # x5 = 0xFF ^ 0xF0 = 0x0F
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 60)
    
    assert await verify_reg(dut, 2, 0x0F, "ANDI")
    assert await verify_reg(dut, 3, 0x1FF, "ORI")
    assert await verify_reg(dut, 4, 0x00, "XORI")
    assert await verify_reg(dut, 5, 0x0F, "XORI")
    
    log.info("I-type logical test PASSED")

@cocotb.test()
async def test_i_type_shift(dut):
    """Test I-type shifts: SLLI, SRLI, SRAI"""
    log.info("=== Test: I-Type Shift ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 1),      # x1 = 1
        SLLI(2, 1, 4),      # x2 = 1 << 4 = 16
        SLLI(3, 2, 4),      # x3 = 16 << 4 = 256
        SRLI(4, 3, 2),      # x4 = 256 >> 2 = 64
        LUI(5, 0x80000),    # x5 = 0x80000000
        SRLI(6, 5, 4),      # x6 = 0x08000000 (logical)
        SRAI(7, 5, 4),      # x7 = 0xF8000000 (arithmetic)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 70)
    
    assert await verify_reg(dut, 2, 16, "SLLI")
    assert await verify_reg(dut, 3, 256, "SLLI chain")
    assert await verify_reg(dut, 4, 64, "SRLI")
    assert await verify_reg(dut, 6, 0x08000000, "SRLI negative")
    assert await verify_reg(dut, 7, 0xF8000000, "SRAI")
    
    log.info("I-type shift test PASSED")

# ============================================================================
# Category 4: Load/Store Instructions
# ============================================================================

@cocotb.test()
async def test_load_store_word(dut):
    """Test LW and SW instructions"""
    log.info("=== Test: Load/Store Word ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Initialize base address register
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = DATA_MEM_BASE (base addr)
        ADDI(1, 0, 0x123),              # x1 = test value (12-bit fits)
        SW(10, 1, 0),                    # MEM[base+0] = x1
        ADDI(2, 0, 0x456),              # x2 = another test value (12-bit fits)
        SW(10, 2, 4),                    # MEM[base+4] = x2
        LW(3, 10, 0),                    # x3 = MEM[base+0]
        LW(4, 10, 4),                    # x4 = MEM[base+4]
        ADD(5, 3, 4),                    # x5 = x3 + x4
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 3, 0x123, "LW 1")
    assert await verify_reg(dut, 4, 0x456, "LW 2")
    assert await verify_reg(dut, 5, 0x123 + 0x456, "LW sum")
    
    log.info("Load/Store word test PASSED")

@cocotb.test()
async def test_load_store_byte(dut):
    """Test LB, LBU, SB instructions"""
    log.info("=== Test: Load/Store Byte ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = DATA_MEM_BASE
        ADDI(1, 0, 0x7F),               # x1 = 0x7F (positive byte)
        SB(10, 1, 0),                   # MEM[base+0] = 0x7F
        ADDI(2, 0, 0x80),               # x2 = 0x80 (negative when signed)
        SB(10, 2, 1),                   # MEM[base+1] = 0x80
        LB(3, 10, 0),                   # x3 = sign-extended 0x7F = 0x7F
        LB(4, 10, 1),                   # x4 = sign-extended 0x80 = 0xFFFFFF80
        LBU(5, 10, 0),                  # x5 = zero-extended 0x7F = 0x7F
        LBU(6, 10, 1),                  # x6 = zero-extended 0x80 = 0x80
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 3, 0x7F, "LB positive")
    assert await verify_reg(dut, 4, 0xFFFFFF80, "LB negative (sign ext)")
    assert await verify_reg(dut, 5, 0x7F, "LBU positive")
    assert await verify_reg(dut, 6, 0x80, "LBU zero ext")
    
    log.info("Load/Store byte test PASSED")

@cocotb.test()
async def test_load_store_halfword(dut):
    """Test LH, LHU, SH instructions"""
    log.info("=== Test: Load/Store Halfword ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = DATA_MEM_BASE
        ADDI(1, 0, 0x7FF),              # x1 = 0x7FF (positive halfword)
        SH(10, 1, 0),                   # MEM[base+0] = 0x7FF
        LUI(2, 0x00008),                # x2 = 0x8000 (negative halfword)
        SH(10, 2, 2),                   # MEM[base+2] = 0x8000
        LH(3, 10, 0),                   # x3 = sign-extended 0x7FF
        LH(4, 10, 2),                   # x4 = sign-extended 0x8000
        LHU(5, 10, 0),                  # x5 = zero-extended 0x7FF
        LHU(6, 10, 2),                  # x6 = zero-extended 0x8000
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 3, 0x7FF, "LH positive")
    assert await verify_reg(dut, 4, 0xFFFF8000, "LH negative (sign ext)")
    assert await verify_reg(dut, 5, 0x7FF, "LHU positive")
    assert await verify_reg(dut, 6, 0x8000, "LHU zero ext")
    
    log.info("Load/Store halfword test PASSED")

# ============================================================================
# Category 5: Branch Instructions
# ============================================================================

@cocotb.test()
async def test_branch_equal(dut):
    """Test BEQ and BNE instructions"""
    log.info("=== Test: Branch Equal/Not Equal ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # RISC-V has no delay slots - instruction after taken branch should NOT execute
    program = [
        ADDI(1, 0, 10),     # 0x00: x1 = 10
        ADDI(2, 0, 10),     # 0x04: x2 = 10
        ADDI(3, 0, 20),     # 0x08: x3 = 20
        BEQ(1, 2, 8),       # 0x0C: if x1==x2, branch to 0x14 (should skip 0x10)
        ADDI(4, 0, 1),      # 0x10: x4 = 1 (MUST be skipped when branch taken)
        ADDI(5, 0, 2),      # 0x14: x5 = 2 (executed - branch target)
        BNE(1, 3, 8),       # 0x18: if x1!=x3, branch to 0x20 (should skip 0x1C)
        ADDI(6, 0, 3),      # 0x1C: x6 = 3 (MUST be skipped when branch taken)
        ADDI(7, 0, 4),      # 0x20: x7 = 4 (executed - branch target)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 80)
    
    # x4 should be 0 (skipped due to BEQ taken) - RISC-V requires no delay slots
    assert await verify_reg(dut, 4, 0, "BEQ skip (no delay slot)")
    assert await verify_reg(dut, 5, 2, "After BEQ")
    # x6 should be 0 (skipped due to BNE taken) - RISC-V requires no delay slots
    assert await verify_reg(dut, 6, 0, "BNE skip (no delay slot)")
    assert await verify_reg(dut, 7, 4, "After BNE")
    
    log.info("Branch equal test PASSED")

@cocotb.test()
async def test_branch_less_than(dut):
    """Test BLT, BGE, BLTU, BGEU instructions"""
    log.info("=== Test: Branch Less/Greater ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 5),      # 0x00: x1 = 5
        ADDI(2, 0, 10),     # 0x04: x2 = 10
        ADDI(3, 0, -1),     # 0x08: x3 = -1 (0xFFFFFFFF)
        # Test BLT (signed less than)
        BLT(1, 2, 8),       # 0x0C: if 5 < 10 (signed), skip
        ADDI(4, 0, 1),      # 0x10: x4 = 1 (skipped)
        ADDI(5, 0, 2),      # 0x14: x5 = 2 (executed)
        # Test BGE (signed greater or equal)
        BGE(2, 1, 8),       # 0x18: if 10 >= 5 (signed), skip
        ADDI(6, 0, 3),      # 0x1C: x6 = 3 (skipped)
        ADDI(7, 0, 4),      # 0x20: x7 = 4 (executed)
        # Test signed vs unsigned
        BLT(3, 1, 8),       # 0x24: if -1 < 5 (signed), skip
        ADDI(8, 0, 5),      # 0x28: x8 = 5 (skipped - -1 < 5 signed)
        BLTU(1, 3, 8),      # 0x2C: if 5 <u 0xFFFFFFFF, skip
        ADDI(9, 0, 6),      # 0x30: x9 = 6 (skipped)
        ADDI(10, 0, 7),     # 0x34: x10 = 7 (executed)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 4, 0, "BLT skip")
    assert await verify_reg(dut, 5, 2, "After BLT")
    assert await verify_reg(dut, 6, 0, "BGE skip")
    assert await verify_reg(dut, 7, 4, "After BGE")
    assert await verify_reg(dut, 8, 0, "BLT signed skip")
    assert await verify_reg(dut, 9, 0, "BLTU skip")
    assert await verify_reg(dut, 10, 7, "After BLTU")
    
    log.info("Branch less than test PASSED")

# ============================================================================
# Category 6: Jump Instructions
# ============================================================================

@cocotb.test()
async def test_jal(dut):
    """Test JAL instruction"""
    log.info("=== Test: JAL ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 1),      # 0x00: x1 = 1
        JAL(2, 12),         # 0x04: x2 = PC+4 = 0x08, jump to 0x10
        ADDI(3, 0, 2),      # 0x08: x3 = 2 (skipped)
        ADDI(4, 0, 3),      # 0x0C: x4 = 3 (skipped)
        ADDI(5, 0, 4),      # 0x10: x5 = 4 (executed after jump)
        ADDI(6, 0, 5),      # 0x14: x6 = 5
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 80)
    
    assert await verify_reg(dut, 1, 1, "Before JAL")
    assert await verify_reg(dut, 2, 0x08, "JAL return addr")  # PC+4 at time of JAL
    assert await verify_reg(dut, 3, 0, "Skipped by JAL")
    assert await verify_reg(dut, 4, 0, "Skipped by JAL")
    assert await verify_reg(dut, 5, 4, "After JAL")
    assert await verify_reg(dut, 6, 5, "After JAL")
    
    log.info("JAL test PASSED")

@cocotb.test()
async def test_jalr(dut):
    """Test JALR instruction"""
    log.info("=== Test: JALR ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 0x14),   # 0x00: x1 = 0x14 (target address)
        ADDI(2, 0, 1),      # 0x04: x2 = 1
        JALR(3, 1, 0),      # 0x08: x3 = PC+4 = 0x0C, jump to x1+0 = 0x14
        ADDI(4, 0, 2),      # 0x0C: x4 = 2 (skipped)
        ADDI(5, 0, 3),      # 0x10: x5 = 3 (skipped)
        ADDI(6, 0, 4),      # 0x14: x6 = 4 (jump target)
        ADDI(7, 0, 5),      # 0x18: x7 = 5
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 80)
    
    assert await verify_reg(dut, 3, 0x0C, "JALR return addr")
    assert await verify_reg(dut, 4, 0, "Skipped by JALR")
    assert await verify_reg(dut, 5, 0, "Skipped by JALR")
    assert await verify_reg(dut, 6, 4, "JALR target")
    assert await verify_reg(dut, 7, 5, "After JALR")
    
    log.info("JALR test PASSED")

# ============================================================================
# Category 7: U-Type Instructions
# ============================================================================

@cocotb.test()
async def test_lui_auipc(dut):
    """Test LUI and AUIPC instructions"""
    log.info("=== Test: LUI/AUIPC ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        LUI(1, 0x12345),    # 0x00: x1 = 0x12345000
        LUI(2, 0x80000),    # 0x04: x2 = 0x80000000
        AUIPC(3, 0),        # 0x08: x3 = PC + 0 = 0x08
        AUIPC(4, 1),        # 0x0C: x4 = PC + 0x1000 = 0x100C
        LUI(5, 0xFFFFF),    # 0x10: x5 = 0xFFFFF000
        ADDI(6, 1, 0x678),  # 0x14: x6 = 0x12345000 + 0x678 = 0x12345678
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 70)
    
    assert await verify_reg(dut, 1, 0x12345000, "LUI")
    assert await verify_reg(dut, 2, 0x80000000, "LUI high bit")
    assert await verify_reg(dut, 3, 0x08, "AUIPC")
    assert await verify_reg(dut, 4, 0x100C, "AUIPC offset")
    assert await verify_reg(dut, 5, 0xFFFFF000, "LUI all ones")
    assert await verify_reg(dut, 6, 0x12345678, "LUI+ADDI combo")
    
    log.info("LUI/AUIPC test PASSED")

# ============================================================================
# Category 8: Hazard Detection and Resolution
# ============================================================================

@cocotb.test()
async def test_raw_hazard(dut):
    """Test RAW (Read After Write) hazard detection and forwarding"""
    log.info("=== Test: RAW Hazard ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Back-to-back dependencies requiring forwarding
    program = [
        ADDI(1, 0, 10),     # x1 = 10
        ADDI(2, 1, 5),      # x2 = x1 + 5 = 15 (RAW on x1)
        ADDI(3, 2, 5),      # x3 = x2 + 5 = 20 (RAW on x2)
        ADDI(4, 3, 5),      # x4 = x3 + 5 = 25 (RAW on x3)
        ADD(5, 1, 2),       # x5 = x1 + x2 = 25 (RAW on both)
        ADD(6, 3, 4),       # x6 = x3 + x4 = 45 (RAW on both)
        ADD(7, 5, 6),       # x7 = x5 + x6 = 70 (RAW on both)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 80)
    
    assert await verify_reg(dut, 1, 10, "RAW base")
    assert await verify_reg(dut, 2, 15, "RAW chain 1")
    assert await verify_reg(dut, 3, 20, "RAW chain 2")
    assert await verify_reg(dut, 4, 25, "RAW chain 3")
    assert await verify_reg(dut, 5, 25, "RAW dual source 1")
    assert await verify_reg(dut, 6, 45, "RAW dual source 2")
    assert await verify_reg(dut, 7, 70, "RAW final")
    
    log.info("RAW hazard test PASSED")

@cocotb.test()
async def test_load_use_hazard(dut):
    """Test load-use hazard with load queue"""
    log.info("=== Test: Load-Use Hazard (with load queue) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Initialize data memory
    set_data_mem(dut, DATA_MEM_BASE, 42)
    set_data_mem(dut, DATA_MEM_BASE + 4, 58)

    # With load queue, loads complete asynchronously, so we need NOPs
    # between load and use to allow queue to complete
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = base address
        LW(1, 10, 0),                   # x1 = MEM[base] = 42 (enqueued to LQ)
        NOP(),                          # Wait for load queue
        NOP(),                          # Wait for load queue
        ADD(2, 1, 1),                   # x2 = x1 + x1 = 84
        LW(3, 10, 4),                   # x3 = MEM[base+4] = 58 (enqueued to LQ)
        NOP(),                          # Wait for load queue
        NOP(),                          # Wait for load queue
        ADDI(4, 3, 10),                 # x4 = x3 + 10 = 68
        ADD(5, 1, 3),                   # x5 = x1 + x3 = 100
        HALT(),
    ]
    await load_program(dut, program)

    await run_cycles(dut, 150)  # More cycles for load queue processing

    assert await verify_reg(dut, 1, 42, "LW 1")
    assert await verify_reg(dut, 2, 84, "Load-use ADD")
    assert await verify_reg(dut, 3, 58, "LW 2")
    assert await verify_reg(dut, 4, 68, "Load-use ADDI")
    assert await verify_reg(dut, 5, 100, "ADD after loads")

    log.info("Load-use hazard test PASSED")

@cocotb.test()
async def test_control_hazard(dut):
    """Test control hazard from branches and jumps"""
    log.info("=== Test: Control Hazard ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        ADDI(1, 0, 0),      # 0x00: x1 = 0
        ADDI(2, 0, 3),      # 0x04: x2 = 3 (loop count)
        # Loop start
        ADDI(1, 1, 1),      # 0x08: x1 += 1
        ADDI(2, 2, -1),     # 0x0C: x2 -= 1
        BNE(2, 0, -8),      # 0x10: if x2 != 0, goto 0x08
        # Should NOT execute the instruction after branch until branch resolved
        ADDI(3, 0, 100),    # 0x14: x3 = 100 (only once after loop)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 1, 3, "Loop counter")
    assert await verify_reg(dut, 2, 0, "Loop exit condition")
    assert await verify_reg(dut, 3, 100, "After loop")
    
    log.info("Control hazard test PASSED")

# ============================================================================
# Category 9: FENCE.I Tests
# ============================================================================

@cocotb.test()
async def test_fence_i_cache_invalidation(dut):
    """Test FENCE.I instruction invalidates instruction cache"""
    log.info("=== Test: FENCE.I Cache Invalidation ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Program with FENCE.I
    program = [
        ADDI(1, 0, 1),      # x1 = 1
        ADDI(2, 0, 2),      # x2 = 2
        FENCE_I(),          # Invalidate icache
        ADDI(3, 0, 3),      # x3 = 3 (should refetch from memory)
        ADDI(4, 0, 4),      # x4 = 4
        ADD(5, 1, 2),       # x5 = 3
        ADD(6, 3, 4),       # x6 = 7
        HALT(),
    ]
    await load_program(dut, program)
    
    # Monitor fence_i signal
    fence_i_seen = False
    
    for cycle in range(100):
        await RisingEdge(dut.clk)
        try:
            if int(dut.fence_i_signal.value):
                fence_i_seen = True
                log.info(f"FENCE.I signal asserted at cycle {cycle}")
        except:
            pass
    
    assert fence_i_seen, "FENCE.I signal was never asserted"
    
    assert await verify_reg(dut, 1, 1, "Before FENCE.I")
    assert await verify_reg(dut, 2, 2, "Before FENCE.I")
    assert await verify_reg(dut, 3, 3, "After FENCE.I")
    assert await verify_reg(dut, 4, 4, "After FENCE.I")
    assert await verify_reg(dut, 5, 3, "Sum before FENCE.I")
    assert await verify_reg(dut, 6, 7, "Sum after FENCE.I")
    
    log.info("FENCE.I cache invalidation test PASSED")

# ============================================================================
# Category 10: CSR Instructions
# ============================================================================

@cocotb.test()
async def test_csr_read_write(dut):
    """Test CSR read/write instructions"""
    log.info("=== Test: CSR Read/Write ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Test CSR operations using mstatus (0x300)
    program = [
        ADDI(1, 0, 0x8),    # x1 = 0x8 (MIE bit)
        CSRRW(2, 1, CSR_MSTATUS),  # x2 = mstatus, mstatus = x1
        CSRRS(3, 0, CSR_MSTATUS),  # x3 = mstatus (read only)
        ADDI(4, 0, 0x80),   # x4 = 0x80 (MPIE bit)
        CSRRS(5, 4, CSR_MSTATUS),  # x5 = mstatus, mstatus |= x4
        CSRRS(6, 0, CSR_MSTATUS),  # x6 = mstatus (read current)
        CSRRC(7, 4, CSR_MSTATUS),  # x7 = mstatus, mstatus &= ~x4
        CSRRS(8, 0, CSR_MSTATUS),  # x8 = mstatus (read after clear)
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    # Verify CSR operations worked
    assert await verify_reg(dut, 3, 0x8, "CSRRS read mstatus")
    assert await verify_reg(dut, 6, 0x88, "CSRRS set bits")
    assert await verify_reg(dut, 8, 0x8, "CSRRC clear bits")
    
    log.info("CSR read/write test PASSED")

@cocotb.test()
async def test_csr_immediate(dut):
    """Test CSR immediate instructions"""
    log.info("=== Test: CSR Immediate ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    program = [
        CSRRWI(1, 0x1F, CSR_MSTATUS),  # mstatus = 0x1F (5-bit immediate)
        CSRRS(2, 0, CSR_MSTATUS),      # x2 = mstatus
        CSRRSI(3, 0x10, CSR_MSTATUS),  # x3 = mstatus, mstatus |= 0x10
        CSRRS(4, 0, CSR_MSTATUS),      # x4 = mstatus
        CSRRCI(5, 0x0F, CSR_MSTATUS),  # x5 = mstatus, mstatus &= ~0x0F
        CSRRS(6, 0, CSR_MSTATUS),      # x6 = mstatus
        HALT(),
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 2, 0x1F, "CSRRWI")
    assert await verify_reg(dut, 4, 0x1F, "CSRRSI")
    assert await verify_reg(dut, 6, 0x10, "CSRRCI")
    
    log.info("CSR immediate test PASSED")

# ============================================================================
# Category 11: Complex Scenarios
# ============================================================================

@cocotb.test()
async def test_nested_loop(dut):
    """Test nested loop execution"""
    log.info("=== Test: Nested Loop ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Nested loop: sum = 0; for i=0 to 2: for j=0 to 2: sum++
    # Result: sum = 3 * 3 = 9
    program = [
        ADDI(5, 0, 0),      # 0x00: sum (x5) = 0
        ADDI(1, 0, 0),      # 0x04: i (x1) = 0
        ADDI(3, 0, 3),      # 0x08: outer limit = 3
        # Outer loop start (0x0C)
        ADDI(2, 0, 0),      # 0x0C: j (x2) = 0
        # Inner loop start (0x10)
        ADDI(5, 5, 1),      # 0x10: sum++
        ADDI(2, 2, 1),      # 0x14: j++
        BNE(2, 3, -8),      # 0x18: if j != 3, goto inner loop (0x10)
        # Inner loop end
        ADDI(1, 1, 1),      # 0x1C: i++
        BNE(1, 3, -20),     # 0x20: if i != 3, goto outer loop (0x0C)
        # End
        HALT(),             # 0x24: stop
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 300)
    
    assert await verify_reg(dut, 5, 9, "Nested loop sum")
    assert await verify_reg(dut, 1, 3, "Outer loop counter")
    assert await verify_reg(dut, 2, 3, "Inner loop counter")
    
    log.info("Nested loop test PASSED")

@cocotb.test()
async def test_function_call(dut):
    """Test function call and return pattern"""
    log.info("=== Test: Function Call ===")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await reset_dut(dut)
    
    # Simple function call pattern:
    # main: call add_five(10), result in x10
    # add_five: returns x10 + 5
    program = [
        # Main (0x00)
        ADDI(10, 0, 10),    # 0x00: x10 = 10 (argument)
        JAL(1, 12),         # 0x04: call add_five at 0x10, ra = 0x08
        ADDI(2, 10, 0),     # 0x08: x2 = x10 (save result after return)
        JAL(0, 12),         # 0x0C: jump to end at 0x18 (skip function body)
        
        # Function add_five (0x10)
        ADDI(10, 10, 5),    # 0x10: x10 = x10 + 5
        JALR(0, 1, 0),      # 0x14: return (jump to ra=0x08)
        
        # End (0x18)
        ADDI(3, 0, 99),     # 0x18: x3 = 99 (end marker)
        HALT(),             # 0x1C: halt
    ]
    await load_program(dut, program)
    
    await run_cycles(dut, 100)
    
    assert await verify_reg(dut, 10, 15, "Function result")
    assert await verify_reg(dut, 2, 15, "Saved result")
    assert await verify_reg(dut, 3, 99, "End marker")
    
    log.info("Function call test PASSED")

@cocotb.test()
async def test_memory_intensive(dut):
    """Test memory-intensive operations with load queue"""
    log.info("=== Test: Memory Intensive (with load queue) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Store array, then read back and sum
    # With load queue, need NOPs between load and use
    program = [
        LUI(10, DATA_MEM_BASE >> 12),   # x10 = base address
        # Store values 1-4
        ADDI(1, 0, 1),
        SW(10, 1, 0),       # MEM[0] = 1
        ADDI(1, 0, 2),
        SW(10, 1, 4),       # MEM[4] = 2
        ADDI(1, 0, 3),
        SW(10, 1, 8),       # MEM[8] = 3
        ADDI(1, 0, 4),
        SW(10, 1, 12),      # MEM[12] = 4
        # Load and sum
        ADDI(5, 0, 0),      # x5 = sum = 0
        LW(1, 10, 0),       # Load from LQ
        NOP(),              # Wait for load queue
        NOP(),
        ADD(5, 5, 1),       # sum += MEM[0]
        LW(1, 10, 4),       # Load from LQ
        NOP(),              # Wait for load queue
        NOP(),
        ADD(5, 5, 1),       # sum += MEM[4]
        LW(1, 10, 8),       # Load from LQ
        NOP(),              # Wait for load queue
        NOP(),
        ADD(5, 5, 1),       # sum += MEM[8]
        LW(1, 10, 12),      # Load from LQ
        NOP(),              # Wait for load queue
        NOP(),
        ADD(5, 5, 1),       # sum += MEM[12]
        HALT(),
    ]
    await load_program(dut, program)

    await run_cycles(dut, 200)  # More cycles for load queue processing

    assert await verify_reg(dut, 5, 10, "Memory sum (1+2+3+4)")

    log.info("Memory intensive test PASSED")

# ============================================================================
# Test Runner Configuration
# ============================================================================

def runCocotbTests():
    """Run the cocotb tests via cocotb-test"""
    from cocotb_test.simulator import run
    import os
    
    # Get repository root directory
    curr_dir = os.getcwd()
    root_dir = curr_dir
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
    
    # Run the test with Verilator (no waveforms, using debug prints)
    run(
        verilog_sources=sources,
        toplevel="top",
        module="test_full_integration",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
        extra_args=["-Wno-fatal"]
    )

if __name__ == "__main__":
    runCocotbTests()
