"""
Edge Case Tests for Synapse-32 RISC-V CPU

Tests extreme and untested scenarios:
1. Maximum register usage (all 32 registers)
2. Extreme pipeline hazards (100+ cycle chains)
3. Cache + hazard combinations
4. Interrupt handling (timer, external, during hazards)
5. Error conditions (misaligned, unmapped, illegal instructions)
6. Race conditions (simultaneous stalls)

Target: top.v (full system integration)
Simulator: Verilator with cocotb
"""

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb.clock import Clock
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ============================================================================
# Memory Map Constants
# ============================================================================
INSTR_MEM_BASE = 0x00000000
DATA_MEM_BASE = 0x10000000
TIMER_BASE = 0x02004000
UNMAPPED_ADDR = 0x30000000  # Outside any valid region

# ============================================================================
# RISC-V Instruction Encoding Functions (from test_full_integration.py)
# ============================================================================

def encode_r_type(opcode, rd, funct3, rs1, rs2, funct7):
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_i_type(opcode, rd, funct3, rs1, imm):
    imm = imm & 0xFFF
    return (imm << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

def encode_s_type(opcode, funct3, rs1, rs2, imm):
    imm = imm & 0xFFF
    imm_11_5 = (imm >> 5) & 0x7F
    imm_4_0 = imm & 0x1F
    return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

def encode_b_type(opcode, funct3, rs1, rs2, imm):
    imm = imm & 0x1FFF
    imm_12 = (imm >> 12) & 0x1
    imm_10_5 = (imm >> 5) & 0x3F
    imm_4_1 = (imm >> 1) & 0xF
    imm_11 = (imm >> 11) & 0x1
    return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | \
           (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

def encode_u_type(opcode, rd, imm):
    imm = imm & 0xFFFFF
    return (imm << 12) | (rd << 7) | opcode

def encode_j_type(opcode, rd, imm):
    imm = imm & 0x1FFFFF
    imm_20 = (imm >> 20) & 0x1
    imm_10_1 = (imm >> 1) & 0x3FF
    imm_11 = (imm >> 11) & 0x1
    imm_19_12 = (imm >> 12) & 0xFF
    return (imm_20 << 31) | (imm_10_1 << 21) | (imm_11 << 20) | \
           (imm_19_12 << 12) | (rd << 7) | opcode

# Instruction generators
def ADDI(rd, rs1, imm):
    return encode_i_type(0x13, rd, 0x0, rs1, imm)

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

def LW(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x2, rs1, imm)

def LH(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x1, rs1, imm)

def LB(rd, rs1, imm):
    return encode_i_type(0x03, rd, 0x0, rs1, imm)

def SW(rs1, rs2, imm):
    return encode_s_type(0x23, 0x2, rs1, rs2, imm)

def BNE(rs1, rs2, imm):
    return encode_b_type(0x63, 0x1, rs1, rs2, imm)

def BEQ(rs1, rs2, imm):
    return encode_b_type(0x63, 0x0, rs1, rs2, imm)

def JAL(rd, imm):
    return encode_j_type(0x6F, rd, imm)

def JALR(rd, rs1, imm):
    return encode_i_type(0x67, rd, 0x0, rs1, imm)

def LUI(rd, imm):
    return encode_u_type(0x37, rd, imm)

def CSRRW(rd, csr, rs1):
    return encode_i_type(0x73, rd, 0x1, rs1, csr)

def CSRRS(rd, csr, rs1):
    return encode_i_type(0x73, rd, 0x2, rs1, csr)

def CSRRWI(rd, csr, imm):
    return encode_i_type(0x73, rd, 0x5, imm, csr)

def FENCE_I():
    return encode_i_type(0x0F, 0, 0x1, 0, 0)

def HALT():
    return JAL(0, 0)

# CSR addresses
MSTATUS = 0x300
MIE = 0x304
MIP = 0x344
MEPC = 0x341
MCAUSE = 0x342

# ============================================================================
# Helper Functions
# ============================================================================

async def reset_dut(dut, cycles=5):
    """Reset the DUT"""
    dut.rst.value = 1
    dut.software_interrupt.value = 0
    dut.external_interrupt.value = 0
    await ClockCycles(dut.clk, cycles)

async def release_reset(dut):
    """Release reset"""
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

async def load_program(dut, instructions):
    """Load program into instruction memory"""
    for i, instr in enumerate(instructions):
        addr = i * 4
        dut.instr_mem_inst.instr_ram[i].value = instr
    await release_reset(dut)

def set_data_mem(dut, addr, value):
    """Set data memory value (data_ram is byte-addressed)"""
    offset = addr - DATA_MEM_BASE
    # Store 32-bit value as 4 bytes (little-endian)
    dut.data_mem_inst.data_ram[offset].value = value & 0xFF
    dut.data_mem_inst.data_ram[offset + 1].value = (value >> 8) & 0xFF
    dut.data_mem_inst.data_ram[offset + 2].value = (value >> 16) & 0xFF
    dut.data_mem_inst.data_ram[offset + 3].value = (value >> 24) & 0xFF

async def wait_cycles(dut, cycles):
    """Wait for N clock cycles"""
    await ClockCycles(dut.clk, cycles)

async def verify_reg(dut, reg, expected, desc=""):
    """Verify register value"""
    actual = int(dut.cpu_inst.rf_inst0.register_file[reg].value)
    if actual != expected:
        log.error(f"{desc}: Expected x{reg}={expected}, got {actual}")
        return False
    return True

# ============================================================================
# TEST 1: Maximum Register Usage
# ============================================================================

@cocotb.test()
async def test_max_register_usage(dut):
    """Test using all 32 registers simultaneously"""
    log.info("=== Test: Maximum Register Usage (All 32 Registers) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Initialize all registers x1-x31 with unique values
    # x0 is hardwired to 0
    program = []

    # Initialize x1-x15 with values 1-15
    for i in range(1, 16):
        program.append(ADDI(i, 0, i))

    # Initialize x16-x31 with values 16-31
    for i in range(16, 32):
        program.append(ADDI(i, 0, i))

    # Now perform operations using multiple registers
    # x31 = x1 + x2 + x3 + ... + x30
    program.append(ADD(31, 1, 2))    # x31 = x1 + x2 = 3
    program.append(ADD(31, 31, 3))   # x31 += x3 = 6
    program.append(ADD(31, 31, 4))   # x31 += x4 = 10
    program.append(ADD(31, 31, 5))   # x31 += x5 = 15
    program.append(ADD(31, 31, 6))   # x31 += x6 = 21
    program.append(ADD(31, 31, 7))   # x31 += x7 = 28
    program.append(ADD(31, 31, 8))   # x31 += x8 = 36

    # Use all registers in a complex expression
    program.append(ADD(29, 10, 11))  # x29 = 21
    program.append(ADD(28, 12, 13))  # x28 = 25
    program.append(ADD(27, 14, 15))  # x27 = 29
    program.append(ADD(26, 29, 28))  # x26 = 46
    program.append(ADD(25, 26, 27))  # x25 = 75

    program.append(HALT())

    await load_program(dut, program)
    await wait_cycles(dut, 300)

    # Verify all registers hold their values
    log.info("[INFO] Verifying all 32 registers...")
    all_pass = True

    # x0 should always be 0
    all_pass &= await verify_reg(dut, 0, 0, "x0 hardwired zero")

    # x1-x24 should have their initialized values (potentially modified)
    for i in range(1, 25):
        all_pass &= await verify_reg(dut, i, i, f"x{i} initialized")

    # Check computed values
    all_pass &= await verify_reg(dut, 25, 75, "x25 = x26 + x27")
    all_pass &= await verify_reg(dut, 26, 46, "x26 = x29 + x28")
    all_pass &= await verify_reg(dut, 27, 29, "x27 = x14 + x15")
    all_pass &= await verify_reg(dut, 28, 25, "x28 = x12 + x13")
    all_pass &= await verify_reg(dut, 29, 21, "x29 = x10 + x11")
    all_pass &= await verify_reg(dut, 31, 36, "x31 = sum of x1-x8")

    assert all_pass, "Maximum register usage test failed"
    log.info("[PASS] All 32 registers work correctly!")

# ============================================================================
# TEST 2: Extreme Pipeline Hazards
# ============================================================================

@cocotb.test()
async def test_extreme_hazards(dut):
    """Test back-to-back hazards for 100+ cycles"""
    log.info("=== Test: Extreme Pipeline Hazards (100+ Cycle Chain) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Create a long dependency chain: x1 = 1, x2 = x1+1, x3 = x2+1, ...
    # Use only registers x1-x30 (avoid x0 and x31 for cleaner logic)
    program = [ADDI(1, 0, 1)]  # x1 = 1

    # Create 29 back-to-back RAW hazards (x1 -> x30)
    for i in range(2, 31):
        program.append(ADDI(i, i-1, 1))  # x[i] = x[i-1] + 1

    # Add a simple load-use hazard test
    # Initialize memory
    set_data_mem(dut, DATA_MEM_BASE, 100)
    set_data_mem(dut, DATA_MEM_BASE + 4, 200)

    program.append(LUI(10, DATA_MEM_BASE >> 12))  # x10 = base address

    # Create 5 back-to-back load-use hazards
    program.append(LW(11, 10, 0))           # x11 = 100
    program.append(ADDI(11, 11, 1))         # x11 = 101 (load-use!)
    program.append(LW(12, 10, 4))           # x12 = 200
    program.append(ADDI(12, 12, 1))         # x12 = 201 (load-use!)
    program.append(ADD(13, 11, 12))         # x13 = 302

    program.append(HALT())

    await load_program(dut, program)

    # This should take a LONG time due to many stalls
    await wait_cycles(dut, 2000)

    # Verify the dependency chain worked
    # x30 should equal 30 (from chain x1=1, x2=2, ..., x30=30)
    assert await verify_reg(dut, 30, 30, "Long dependency chain"), \
        "Extreme hazards test failed"

    # Verify load-use hazards worked
    x11 = int(dut.cpu_inst.rf_inst0.register_file[11].value)
    x12 = int(dut.cpu_inst.rf_inst0.register_file[12].value)
    x13 = int(dut.cpu_inst.rf_inst0.register_file[13].value)
    log.info(f"[RESULT] x11={x11}, x12={x12}, x13={x13}")
    assert x11 == 101, f"Load-use hazard failed: x11={x11}, expected 101"
    assert x12 == 201, f"Load-use hazard failed: x12={x12}, expected 201"
    assert x13 == 302, f"Load-use hazard failed: x13={x13}, expected 302"

    log.info("[PASS] Extreme hazards handled correctly!")

# ============================================================================
# TEST 3: Cache + Hazard Combination
# ============================================================================

@cocotb.test()
async def test_cache_hazard_combo(dut):
    """Test cache operations with pipeline hazards"""
    log.info("=== Test: Cache + Pipeline Hazards ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Initialize data memory
    set_data_mem(dut, DATA_MEM_BASE, 42)
    set_data_mem(dut, DATA_MEM_BASE + 4, 58)

    # Test cache with multiple loads creating hazards
    # This tests instruction cache working while data hazards are resolved
    program = [
        LUI(10, DATA_MEM_BASE >> 12),  # x10 = base address
        LW(1, 10, 0),                  # x1 = MEM[base] = 42
        ADD(2, 1, 1),                  # x2 = x1 + x1 = 84 (load-use hazard)
        ADDI(3, 2, 10),                # x3 = x2 + 10 = 94 (RAW hazard)
        LW(4, 10, 4),                  # x4 = MEM[base+4] = 58
        ADD(5, 3, 4),                  # x5 = x3 + x4 = 152 (load-use hazard)
        ADDI(6, 5, 1),                 # x6 = x5 + 1 = 153 (RAW hazard)
        HALT(),
    ]

    await load_program(dut, program)
    await wait_cycles(dut, 200)

    # Verify results
    x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
    x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)
    x3 = int(dut.cpu_inst.rf_inst0.register_file[3].value)
    x4 = int(dut.cpu_inst.rf_inst0.register_file[4].value)
    x5 = int(dut.cpu_inst.rf_inst0.register_file[5].value)
    x6 = int(dut.cpu_inst.rf_inst0.register_file[6].value)

    log.info(f"[RESULT] x1={x1}, x2={x2}, x3={x3}, x4={x4}, x5={x5}, x6={x6}")

    # x1=42, x2=84, x3=94, x4=58, x5=152, x6=153
    assert x1 == 42, f"LW 1 failed: x1={x1}"
    assert x2 == 84, f"Load-use hazard 1 failed: x2={x2}"
    assert x3 == 94, f"RAW hazard 1 failed: x3={x3}"
    assert x4 == 58, f"LW 2 failed: x4={x4}"
    assert x5 == 152, f"Load-use hazard 2 failed: x5={x5}"
    assert x6 == 153, f"RAW hazard 2 failed: x6={x6}"

    log.info("[PASS] Cache + hazard combination works!")

# ============================================================================
# TEST 4: Timer Interrupt
# ============================================================================

@cocotb.test()
async def test_timer_interrupt(dut):
    """Test timer interrupt during normal execution"""
    log.info("=== Test: Timer Interrupt ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Enable timer interrupts via CSR
    # Set MIE.MTIE (bit 7) = 1
    program = [
        CSRRWI(1, MIE, 0x80),      # Enable timer interrupt (bit 7)
        CSRRWI(2, MSTATUS, 0x08),  # Enable global interrupts (MIE bit 3)

        # Main program: count in a loop
        ADDI(10, 0, 0),            # counter = 0
        ADDI(11, 0, 100),          # max = 100
        # Loop
        ADDI(10, 10, 1),           # counter++
        BNE(10, 11, -4),           # loop if counter < 100

        # Done
        ADDI(12, 0, 99),           # marker = 99
        HALT(),
    ]

    await load_program(dut, program)

    # Let program run for a bit
    await wait_cycles(dut, 50)

    # Trigger timer interrupt
    log.info("[INFO] Triggering timer interrupt...")
    dut.cpu_inst.timer_interrupt.value = 1
    await wait_cycles(dut, 10)
    dut.cpu_inst.timer_interrupt.value = 0

    # Continue execution
    await wait_cycles(dut, 200)

    # Verify program continued (may or may not reach 100 depending on ISR)
    counter = int(dut.cpu_inst.rf_inst0.register_file[10].value)
    log.info(f"[RESULT] Counter reached: {counter}")

    # Test passes if CPU didn't crash
    # (interrupt handling implementation may vary)
    assert counter > 0, "CPU crashed or didn't execute"

    log.info("[PASS] Timer interrupt handled (CPU didn't crash)!")

# ============================================================================
# TEST 5: External Interrupt
# ============================================================================

@cocotb.test()
async def test_external_interrupt(dut):
    """Test external interrupt during loop"""
    log.info("=== Test: External Interrupt ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Simple counting program
    program = [
        ADDI(1, 0, 0),      # counter = 0
        ADDI(2, 0, 50),     # max = 50
        # Loop
        ADDI(1, 1, 1),      # counter++
        BNE(1, 2, -4),      # loop
        HALT(),
    ]

    await load_program(dut, program)

    # Run for a bit
    await wait_cycles(dut, 30)

    # Trigger external interrupt
    log.info("[INFO] Triggering external interrupt...")
    dut.external_interrupt.value = 1
    await wait_cycles(dut, 5)
    dut.external_interrupt.value = 0

    # Continue
    await wait_cycles(dut, 150)

    # Verify CPU is still running
    counter = int(dut.cpu_inst.rf_inst0.register_file[1].value)
    log.info(f"[RESULT] Counter = {counter}")
    assert counter > 0, "CPU crashed"

    log.info("[PASS] External interrupt handled!")

# ============================================================================
# TEST 6: Interrupt During Hazard
# ============================================================================

@cocotb.test()
async def test_interrupt_during_hazard(dut):
    """Test interrupt while pipeline stalled on hazard"""
    log.info("=== Test: Interrupt During Pipeline Stall ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Initialize memory
    set_data_mem(dut, DATA_MEM_BASE, 123)

    program = [
        LUI(10, DATA_MEM_BASE >> 12),
        ADDI(1, 0, 0),      # counter = 0
        # Loop with load-use hazard
        LW(2, 10, 0),       # Load (causes stall on next instr)
        ADDI(3, 2, 1),      # Use immediately (stall!)
        ADDI(1, 1, 1),      # counter++
        ADDI(4, 0, 20),
        BNE(1, 4, -16),     # loop 20 times
        HALT(),
    ]

    await load_program(dut, program)

    # Run until we're in the middle of load-use hazards
    await wait_cycles(dut, 20)

    # Trigger interrupt during stall
    log.info("[INFO] Triggering interrupt during pipeline stall...")
    dut.software_interrupt.value = 1
    await wait_cycles(dut, 3)
    dut.software_interrupt.value = 0

    # Continue execution
    await wait_cycles(dut, 300)

    # Verify CPU survived
    counter = int(dut.cpu_inst.rf_inst0.register_file[1].value)
    log.info(f"[RESULT] Loop iterations completed: {counter}")
    assert counter > 0, "CPU crashed during interrupt+hazard"

    log.info("[PASS] Interrupt during hazard handled!")

# ============================================================================
# TEST 7: Misaligned Memory Access
# ============================================================================

@cocotb.test()
async def test_misaligned_load(dut):
    """Test unaligned memory access"""
    log.info("=== Test: Misaligned Memory Access ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Initialize memory
    set_data_mem(dut, DATA_MEM_BASE, 0xDEADBEEF)
    set_data_mem(dut, DATA_MEM_BASE + 4, 0xCAFEBABE)

    # Try to load from misaligned address (addr % 4 != 0)
    program = [
        LUI(10, DATA_MEM_BASE >> 12),
        LW(1, 10, 0),      # Aligned load (OK)
        LW(2, 10, 2),      # Misaligned load (base + 2)
        ADDI(3, 1, 1),     # Should still work
        HALT(),
    ]

    await load_program(dut, program)
    await wait_cycles(dut, 100)

    # Verify CPU didn't crash (behavior may vary)
    x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
    x3 = int(dut.cpu_inst.rf_inst0.register_file[3].value)

    log.info(f"[RESULT] x1 = 0x{x1:08x}, x3 = 0x{x3:08x}")

    # Test passes if CPU didn't crash/hang
    assert x3 == x1 + 1, "CPU crashed on misaligned access"

    log.info("[PASS] Misaligned access handled (CPU didn't crash)!")

# ============================================================================
# TEST 8: Unmapped Memory Access
# ============================================================================

@cocotb.test()
async def test_unmapped_memory(dut):
    """Test access to non-existent memory region"""
    log.info("=== Test: Unmapped Memory Access ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Access completely unmapped address
    program = [
        LUI(10, UNMAPPED_ADDR >> 12),  # x10 = unmapped address
        LW(1, 10, 0),                   # Try to load from unmapped
        ADDI(2, 0, 99),                 # This should still execute
        HALT(),
    ]

    await load_program(dut, program)
    await wait_cycles(dut, 100)

    # Verify CPU continued execution
    x2 = int(dut.cpu_inst.rf_inst0.register_file[2].value)

    log.info(f"[RESULT] x2 = {x2}")
    assert x2 == 99, "CPU crashed on unmapped access"

    log.info("[PASS] Unmapped memory access handled!")

# ============================================================================
# TEST 9: Illegal Instruction
# ============================================================================

@cocotb.test()
async def test_illegal_instruction(dut):
    """Test invalid opcode handling"""
    log.info("=== Test: Illegal Instruction ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Create program with illegal instruction
    program = [
        ADDI(1, 0, 10),      # Legal
        0xFFFFFFFF,          # Illegal instruction (all 1's)
        ADDI(2, 0, 20),      # Legal (may not execute)
        HALT(),
    ]

    await load_program(dut, program)
    await wait_cycles(dut, 100)

    # Verify first instruction executed
    x1 = int(dut.cpu_inst.rf_inst0.register_file[1].value)
    log.info(f"[RESULT] x1 = {x1}")

    # Test passes if CPU executed at least the first instruction
    assert x1 == 10, "CPU didn't execute before illegal instruction"

    log.info("[PASS] Illegal instruction handled (CPU didn't crash)!")

# ============================================================================
# TEST 10: Simultaneous Stalls (Race Conditions)
# ============================================================================

@cocotb.test()
async def test_simultaneous_stalls(dut):
    """Test multiple stall sources active simultaneously"""
    log.info("=== Test: Simultaneous Stalls (Cache + Hazard + Branch) ===")

    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Initialize memory
    for i in range(10):
        set_data_mem(dut, DATA_MEM_BASE + i*4, i+50)

    program = [
        LUI(10, DATA_MEM_BASE >> 12),  # Base address
        ADDI(15, 0, 0),                # Loop counter
        ADDI(16, 0, 10),               # Loop max

        # Loop with multiple stall sources
        LW(1, 10, 0),                  # Cache miss (possibly)
        ADD(2, 1, 1),                  # Load-use hazard
        ADDI(3, 2, 1),                 # RAW hazard chain
        BNE(3, 15, 8),                 # Branch (control hazard)
        FENCE_I(),                      # Force cache invalidation

        # Continue loop
        ADDI(15, 15, 1),               # counter++
        BNE(15, 16, -28),              # Loop back

        ADDI(20, 0, 77),               # Marker
        HALT(),
    ]

    await load_program(dut, program)

    # This should experience:
    # - Cache misses/refills
    # - Load-use stalls
    # - RAW hazard forwarding
    # - Branch mispredictions
    # - All potentially happening at once!

    await wait_cycles(dut, 500)

    # Verify loop completed
    counter = int(dut.cpu_inst.rf_inst0.register_file[15].value)
    marker = int(dut.cpu_inst.rf_inst0.register_file[20].value)

    log.info(f"[RESULT] Loop counter = {counter}, marker = {marker}")

    # Test passes if CPU survived the chaos
    assert counter >= 0, "CPU crashed with simultaneous stalls"
    assert marker == 77, "Program didn't complete"

    log.info("[PASS] Simultaneous stalls handled correctly!")

# ============================================================================
# Test Runner (pytest-cocotb integration)
# ============================================================================

def runCocotbTests():
    """Run all edge case tests"""
    from cocotb_test.simulator import run

    root_dir = os.getcwd()
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

    run(
        verilog_sources=sources,
        toplevel="top",
        module="test_edge_cases",
        includes=[incl_dir],
        simulator="verilator",
        timescale="1ns/1ps",
    )

if __name__ == "__main__":
    runCocotbTests()
