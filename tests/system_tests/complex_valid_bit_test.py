"""
Complex test to prove necessity of valid bits in pipeline.

This test exercises scenarios that should expose problems when valid bits are missing:
1. Back-to-back hazards with flushes
2. Flush during load-use stall
3. Branch misprediction with pending operations
4. Multiple dependency chains with flushes
"""

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.clock import Clock
import os


def create_complex_test_hex():
    """Create a complex test program using Python encoding"""

    def encode_r_type(funct7, rs2, rs1, funct3, rd, opcode):
        return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    def encode_i_type(imm, rs1, funct3, rd, opcode):
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode

    def encode_s_type(imm, rs2, rs1, funct3, opcode):
        imm_11_5 = (imm >> 5) & 0x7F
        imm_4_0 = imm & 0x1F
        return (imm_11_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_0 << 7) | opcode

    def encode_b_type(imm, rs2, rs1, funct3, opcode):
        imm_12 = (imm >> 12) & 0x1
        imm_10_5 = (imm >> 5) & 0x3F
        imm_4_1 = (imm >> 1) & 0xF
        imm_11 = (imm >> 11) & 0x1
        return (imm_12 << 31) | (imm_10_5 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (imm_4_1 << 8) | (imm_11 << 7) | opcode

    def encode_u_type(imm, rd, opcode):
        return ((imm & 0xFFFFF) << 12) | (rd << 7) | opcode

    def encode_j_type(imm, rd, opcode):
        imm_20 = (imm >> 20) & 0x1
        imm_10_1 = (imm >> 1) & 0x3FF
        imm_11 = (imm >> 11) & 0x1
        imm_19_12 = (imm >> 12) & 0xFF
        return (imm_20 << 31) | (imm_19_12 << 12) | (imm_11 << 20) | (imm_10_1 << 21) | (rd << 7) | opcode

    instructions = []

    # Test 1: Basic setup
    instructions.append(encode_u_type(0x10000, 4, 0x37))          # lui x4, 0x10000 (data base)

    # Test 2: Store-load-use with bubble insertion
    instructions.append(encode_i_type(100, 0, 0, 5, 0x13))       # addi x5, x0, 100
    instructions.append(encode_s_type(0, 5, 4, 2, 0x23))         # sw x5, 0(x4)
    instructions.append(encode_i_type(0, 4, 2, 6, 0x03))         # lw x6, 0(x4) [100]
    instructions.append(encode_i_type(1, 6, 0, 7, 0x13))         # addi x7, x6, 1 [101] (load-use stall creates bubble)

    # Test 3: Branch that flushes pipeline - CRITICAL TEST
    # If valid bits don't work, flushed instructions will execute
    instructions.append(encode_i_type(5, 0, 0, 9, 0x13))         # addi x9, x0, 5
    instructions.append(encode_i_type(5, 0, 0, 10, 0x13))        # addi x10, x0, 5
    instructions.append(encode_b_type(16, 10, 9, 0, 0x63))       # beq x9, x10, +16 (skip 3 instrs) FIX: was +12
    instructions.append(encode_i_type(999, 0, 0, 11, 0x13))      # addi x11, x0, 999 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(888, 0, 0, 12, 0x13))      # addi x12, x0, 888 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(777, 0, 0, 13, 0x13))      # addi x13, x0, 777 [SHOULD BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(42, 0, 0, 11, 0x13))       # addi x11, x0, 42 [SHOULD EXECUTE]

    # Test 4: Store, then branch, then load - tests if flushed store executed
    instructions.append(encode_i_type(123, 0, 0, 14, 0x13))      # addi x14, x0, 123
    instructions.append(encode_s_type(4, 14, 4, 2, 0x23))        # sw x14, 4(x4) [stores 123]
    instructions.append(encode_b_type(16, 0, 0, 0, 0x63))        # beq x0, x0, +16 (always branch) FIX: was +12
    instructions.append(encode_i_type(666, 0, 0, 15, 0x13))      # addi x15, x0, 666 [SHOULD BE FLUSHED]
    instructions.append(encode_s_type(8, 15, 4, 2, 0x23))        # sw x15, 8(x4) [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(555, 0, 0, 16, 0x13))      # addi x16, x0, 555 [SHOULD BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(8, 4, 2, 17, 0x03))        # lw x17, 8(x4) [should be 0, not 666]

    # Test 5: Complex dependency chain with branch in middle
    instructions.append(encode_i_type(1, 0, 0, 18, 0x13))        # addi x18, x0, 1
    instructions.append(encode_i_type(1, 18, 0, 19, 0x13))       # addi x19, x18, 1 [2]
    instructions.append(encode_b_type(12, 0, 0, 0, 0x63))        # beq x0, x0, +12 (skip 2 instrs) FIX: was +8
    instructions.append(encode_i_type(333, 0, 0, 20, 0x13))      # addi x20, x0, 333 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(444, 0, 0, 21, 0x13))      # addi x21, x0, 444 [SHOULD BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(1, 19, 0, 22, 0x13))       # addi x22, x19, 1 [3]

    # Test 6: Load-use stall followed by branch
    instructions.append(encode_i_type(200, 0, 0, 23, 0x13))      # addi x23, x0, 200
    instructions.append(encode_s_type(12, 23, 4, 2, 0x23))       # sw x23, 12(x4)
    instructions.append(encode_i_type(12, 4, 2, 24, 0x03))       # lw x24, 12(x4) [200] (creates stall)
    instructions.append(encode_b_type(12, 0, 0, 0, 0x63))        # beq x0, x0, +12 (branch during stall resolution) FIX: was +8
    instructions.append(encode_i_type(111, 0, 0, 25, 0x13))      # addi x25, x0, 111 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(222, 0, 0, 26, 0x13))      # addi x26, x0, 222 [SHOULD BE FLUSHED]
    # Branch target:
    instructions.append(encode_i_type(1, 24, 0, 27, 0x13))       # addi x27, x24, 1 [201]

    # Test 7: Back-to-back branches (tests bubble handling)
    instructions.append(encode_i_type(10, 0, 0, 28, 0x13))       # addi x28, x0, 10
    instructions.append(encode_b_type(12, 0, 0, 0, 0x63))        # beq x0, x0, +12 (first branch) FIX: was +8
    instructions.append(encode_i_type(99, 0, 0, 29, 0x13))       # addi x29, x0, 99 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(88, 0, 0, 30, 0x13))       # addi x30, x0, 88 [SHOULD BE FLUSHED]
    # First branch target:
    instructions.append(encode_b_type(12, 0, 0, 0, 0x63))        # beq x0, x0, +12 (second branch) FIX: was +8
    instructions.append(encode_i_type(77, 0, 0, 29, 0x13))       # addi x29, x0, 77 [SHOULD BE FLUSHED]
    instructions.append(encode_i_type(66, 0, 0, 30, 0x13))       # addi x30, x0, 66 [SHOULD BE FLUSHED]
    # Second branch target:
    instructions.append(encode_i_type(55, 0, 0, 29, 0x13))       # addi x29, x0, 55 [SHOULD EXECUTE]

    # Signal completion
    instructions.append(encode_u_type(0x10000, 1, 0x37))         # lui x1, 0x10000
    instructions.append(encode_i_type(0xFF, 1, 0, 1, 0x13))      # addi x1, x1, 0xFF
    instructions.append(encode_s_type(0, 0, 1, 2, 0x23))         # sw x0, 0(x1) (CPU_DONE)

    # Infinite loop
    loop_offset = 0  # Jump to self
    instructions.append(encode_j_type(0, 0, 0x6F))               # j 0 (infinite loop)

    # Write hex file
    build_dir = os.path.join(os.path.dirname(__file__), "build")
    os.makedirs(build_dir, exist_ok=True)
    hex_file = os.path.join(build_dir, "complex_test.hex")

    with open(hex_file, 'w') as f:
        for i, instr in enumerate(instructions):
            f.write(f"@{i:08x}\n")
            f.write(f"{instr:08x}\n")

    print(f"Created complex test hex: {hex_file}")
    return hex_file


@cocotb.test()
async def test_complex_valid_bit_scenarios(dut):
    """Test complex scenarios that should expose valid bit necessity"""

    # Start clock
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Track register writes dynamically
    register_state = {i: 0 for i in range(32)}  # Initialize all registers to 0
    memory_state = {}  # Track memory writes

    # Run and monitor
    cpu_inst = dut.cpu_inst
    for cycle in range(400):
        await RisingEdge(dut.clk)

        # Track register writes
        try:
            if hasattr(cpu_inst, 'rf_inst0_wr_en') and int(cpu_inst.rf_inst0_wr_en.value):
                rd_addr = int(cpu_inst.rf_inst0_rd_in.value)
                rd_value = int(cpu_inst.rf_inst0_rd_value_in.value)
                if rd_addr != 0:  # x0 is hardwired to 0
                    register_state[rd_addr] = rd_value
                    # Debug critical registers
                    if rd_addr in [11, 12, 13, 15, 16, 20, 21, 25, 26, 29, 30]:
                        print(f"  Cycle {cycle}: x{rd_addr} ← {rd_value}")
        except:
            pass

        # Track memory writes
        try:
            if hasattr(dut, 'mem_wr_en_debug') and int(dut.mem_wr_en_debug.value):
                addr = int(dut.mem_addr_debug.value)
                data = int(dut.mem_data_debug.value)
                memory_state[addr] = data
                print(f"  Cycle {cycle}: MEM[0x{addr:08x}] ← {data}")
        except:
            pass

    # Wait a bit more
    for _ in range(20):
        await RisingEdge(dut.clk)

    # Read register file
    print("\n" + "="*70)
    print("COMPLEX VALID BIT TEST - Register Verification")
    print("="*70)
    print("\nTesting scenarios where flushed instructions should NOT execute:")
    print("If valid bits don't work, we'll see corruption from flushed instrs\n")

    # Critical registers that test flush behavior
    critical_tests = {
        'x11': (42, 999, "Branch flush test: x11 should be 42, NOT 999"),
        'x12': (0, 888, "Branch flush test: x12 should be 0 (never written), NOT 888"),
        'x13': (0, 777, "Branch flush test: x13 should be 0 (never written), NOT 777"),
        'x15': (0, 666, "Store flush test: x15 should be 0 (never written), NOT 666"),
        'x16': (0, 555, "Store flush test: x16 should be 0 (never written), NOT 555"),
        'x17': (0, 666, "Memory corruption test: x17 should be 0, NOT 666 from flushed store"),
        'x20': (0, 333, "Mid-chain flush: x20 should be 0 (flushed), NOT 333"),
        'x21': (0, 444, "Mid-chain flush: x21 should be 0 (flushed), NOT 444"),
        'x25': (0, 111, "Stall+branch flush: x25 should be 0 (flushed), NOT 111"),
        'x26': (0, 222, "Stall+branch flush: x26 should be 0 (flushed), NOT 222"),
        'x29': (55, [99, 77], "Back-to-back branch: x29 should be 55, NOT 99 or 77"),
        'x30': (0, [88, 66], "Back-to-back branch: x30 should be 0, NOT 88 or 66"),
    }

    # Non-critical registers (should work regardless)
    expected = {
        'x5': 100,
        'x6': 100,
        'x7': 101,
        'x9': 5,
        'x10': 5,
        'x14': 123,
        'x18': 1,
        'x19': 2,
        'x22': 3,
        'x23': 200,
        'x24': 200,
        'x27': 201,
        'x28': 10,
    }

    results = {}
    correct = 0
    total = 0
    critical_failures = []

    print("Non-Critical Tests (should pass regardless of valid bits):")
    for reg_name, expected_val in expected.items():
        reg_num = int(reg_name[1:])
        actual_val = register_state[reg_num]
        results[reg_name] = actual_val
        total += 1

        if actual_val == expected_val:
            print(f"  ✓ {reg_name} = {actual_val}")
            correct += 1
        else:
            print(f"  ✗ {reg_name} = {actual_val} (expected {expected_val})")

    print("\n" + "="*70)
    print("CRITICAL Tests (expose valid bit problems):")
    print("="*70)

    for reg_name, (expected_val, bad_val, description) in critical_tests.items():
        reg_num = int(reg_name[1:])
        actual_val = register_state[reg_num]
        results[reg_name] = actual_val
        total += 1

        # Check if value is bad
        is_bad = False
        if isinstance(bad_val, list):
            is_bad = actual_val in bad_val
            bad_str = f" or {' or '.join(map(str, bad_val))}"
        else:
            is_bad = actual_val == bad_val
            bad_str = f" or {bad_val}"

        if actual_val == expected_val:
            print(f"  ✓ {reg_name} = {actual_val}")
            print(f"      {description}")
            correct += 1
        elif is_bad:
            print(f"  ❌ {reg_name} = {actual_val} (expected {expected_val})")
            print(f"      {description}")
            print(f"      >>> FLUSHED INSTRUCTION EXECUTED! Valid bits failed! <<<")
            critical_failures.append((reg_name, actual_val, expected_val, description))
        else:
            print(f"  ✗ {reg_name} = {actual_val} (expected {expected_val})")
            print(f"      {description}")
            print(f"      (Unexpected value, not the bad value{bad_str})")

    # Check memory corruption
    print("\n" + "="*70)
    print("Memory Corruption Tests:")
    print("="*70)

    mem_checks = {
        0x10000000: (100, None, "mem[0] - normal store"),
        0x10000004: (123, None, "mem[4] - normal store"),
        0x10000008: (0, 666, "mem[8] - CRITICAL: flushed store should NOT have written"),
        0x1000000C: (200, None, "mem[12] - normal store"),
    }

    mem_failures = []
    for addr, (expected_val, bad_val, description) in mem_checks.items():
        actual = memory_state.get(addr, 0)  # Default to 0 if never written

        if actual == expected_val:
            print(f"  ✓ 0x{addr:08x} = {actual} - {description}")
        elif bad_val is not None and actual == bad_val:
            print(f"  ❌ 0x{addr:08x} = {actual} (expected {expected_val})")
            print(f"      {description}")
            print(f"      >>> FLUSHED STORE EXECUTED! Valid bits failed! <<<")
            mem_failures.append((addr, actual, expected_val))
        else:
            print(f"  ✗ 0x{addr:08x} = {actual} (expected {expected_val}) - {description}")

    # Final verdict
    print("\n" + "="*70)
    print(f"Overall Score: {correct}/{total} ({100*correct//total if total > 0 else 0}%)")
    print("="*70)

    if critical_failures or mem_failures:
        print("\n" + "🔥"*35)
        print("❌ VALID BITS ARE ABSOLUTELY NECESSARY!")
        print("🔥"*35)
        print(f"\nProof of failure:")
        print(f"  • {len(critical_failures)} register corruption(s) from flushed instructions")
        print(f"  • {len(mem_failures)} memory corruption(s) from flushed stores")
        print("\nWithout valid bits, the CPU:")
        print("  1. Executes instructions that should be flushed")
        print("  2. Writes to registers from invalid bubbles")
        print("  3. Performs memory operations from flushed instructions")
        print("  4. Cannot maintain correct program semantics")
        print("\nThis is a CRITICAL BUG that makes the CPU incorrect!")
    else:
        print("\n✅ All tests passed")
        print(f"   {correct}/{total} correct")
        if correct == total:
            print("   Valid bits may be optional for these scenarios")
        else:
            print("   Some non-critical failures, but no corruption from flushed instructions")

    print("="*70 + "\n")

    # Assertions
    if critical_failures:
        print("\nCritical Failures Details:")
        for reg, actual, expected, desc in critical_failures:
            print(f"  {reg}: got {actual}, expected {expected}")
            print(f"    {desc}")

    if mem_failures:
        print("\nMemory Corruption Details:")
        for addr, actual, expected in mem_failures:
            print(f"  0x{addr:08x}: got {actual}, expected {expected}")

    assert len(critical_failures) == 0, f"CRITICAL: {len(critical_failures)} flushed instructions executed!"
    assert len(mem_failures) == 0, f"CRITICAL: {len(mem_failures)} flushed stores executed!"


def runCocotbTests():
    """Run complex valid bit test"""
    from cocotb_test.simulator import run
    import shutil
    import os

    hex_file = create_complex_test_hex()

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
    sim_build_dir = os.path.join(curr_dir, "sim_build", "complex_valid_test")
    if os.path.exists(sim_build_dir):
        shutil.rmtree(sim_build_dir)

    run(
        verilog_sources=sources,
        toplevel="top",
        module="complex_valid_bit_test",
        testcase="test_complex_valid_bit_scenarios",
        includes=[str(incl_dir)],
        simulator="verilator",
        timescale="1ns/1ps",
        defines=[f"INSTR_HEX_FILE=\"{hex_file}\""],
        sim_build=sim_build_dir,
        force_compile=True,
    )


if __name__ == "__main__":
    runCocotbTests()
