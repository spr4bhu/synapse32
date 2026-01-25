"""
Comprehensive I-Cache Tests (mirroring D-cache failing tests)

Tests I-cache functionality that mirrors the failing D-cache tests:
- Immediate hit responses after miss (like write-allocate)
- Word offsets in same line (like byte-level writes)
- LRU replacement
- Multiple accesses to same line
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb_test.simulator import run
import os

# Helper functions from test_icache.py
async def fill_cache_line(dut, addr):
    """Fill a cache line by accessing addr and completing the refill"""
    dut.cpu_addr.value = addr
    dut.cpu_req.value = 1
    
    for cycle in range(40):
        # Set mem_valid on falling edge based on previous mem_req
        await FallingEdge(dut.clk)
        
        mem_req = int(dut.mem_req.value)
        if mem_req == 1:
            mem_addr = int(dut.mem_addr.value)
            dut.mem_data.value = 0xDEAD0000 | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        
        await RisingEdge(dut.clk)
        
        if int(dut.cpu_stall.value) == 0:
            break
    
    # Deassert request
    dut.cpu_req.value = 0
    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)


async def check_cache_hit(dut, addr):
    """Check if accessing addr results in a cache hit"""
    dut.cpu_addr.value = addr
    dut.cpu_req.value = 1
    await Timer(1, units="ns")  # Let combinational logic settle
    
    stall = int(dut.cpu_stall.value)
    valid = int(dut.cpu_valid.value)
    
    dut.cpu_req.value = 0
    return stall == 0 and valid == 1

# Helper function to reset DUT
async def reset_dut(dut):
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

# Helper to wait for cache to be ready
async def wait_ready(dut, max_cycles=100):
    timeout = 0
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)
        timeout += 1
        if timeout > max_cycles:
            raise Exception(f"Timeout waiting for cpu_stall=0 after {max_cycles} cycles")

@cocotb.test()
async def test_immediate_read_hit(dut):
    """Test: Read hit provides immediate response after miss (like write-allocate)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req.value = 0
    dut.mem_valid.value = 0

    await RisingEdge(dut.clk)

    # Step 1: Miss - fill cache line
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x5000

    # Wait for memory request
    while dut.mem_req.value == 0:
        await RisingEdge(dut.clk)

    # Provide refill data (I-cache has 4 words per line)
    for word in range(4):
        await FallingEdge(dut.clk)
        if dut.mem_req.value == 1:
            mem_addr = int(dut.mem_addr.value)
            # Match I-cache test pattern: data based on address
            dut.mem_data.value = 0x12345678 | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        await RisingEdge(dut.clk)
        if dut.cpu_stall.value == 0:
            break

    dut.mem_valid.value = 0
    dut.cpu_req.value = 0
    # Wait for cache to be ready
    await RisingEdge(dut.clk)
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)

    # Step 2: Read hit - should be immediate (combinational)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x5000

    await RisingEdge(dut.clk)
    
    # In IDLE state with hit, response should be valid immediately
    assert dut.cpu_stall.value == 0, "Read hit should not stall"
    assert dut.cpu_valid.value == 1, "Read hit should provide immediate response"
    
    dut.cpu_req.value = 0

    cocotb.log.info("✓ Immediate read hit test PASSED")


@cocotb.test()
async def test_word_offsets_same_line(dut):
    """Test: Different word offsets in same cache line (like byte-level writes)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req.value = 0
    dut.mem_valid.value = 0

    await RisingEdge(dut.clk)

    # Fill cache line at base address
    base_addr = 0x3000
    dut.cpu_req.value = 1
    dut.cpu_addr.value = base_addr

    # Wait for memory request
    while dut.mem_req.value == 0:
        await RisingEdge(dut.clk)

    # Provide refill data (I-cache has 4 words per line)
    # Use same pattern as test_icache.py
    for cycle in range(40):
        await FallingEdge(dut.clk)
        if dut.mem_req.value == 1:
            mem_addr = int(dut.mem_addr.value)
            dut.mem_data.value = 0xDEAD0000 | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        await RisingEdge(dut.clk)
        if dut.cpu_stall.value == 0:
            break

    dut.mem_valid.value = 0
    dut.cpu_req.value = 0
    # Wait for cache to be ready (stall should be 0)
    await RisingEdge(dut.clk)
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)

    # Access different word offsets in same line - all should hit
    # I-cache line is 4 words (16 bytes), so offsets are 0, 4, 8, 12
    # Use same pattern as test_icache.py - check after clock edge
    for offset in [0, 4, 8, 12]:
        addr = base_addr + offset
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        
        await RisingEdge(dut.clk)
        dut.cpu_req.value = 0
        
        # Check hit after clock edge (combinational output should be ready)
        assert dut.cpu_stall.value == 0, f"Address 0x{addr:05X} should hit (no stall)"
        assert dut.cpu_valid.value == 1, f"Address 0x{addr:05X} should hit (valid)"
        
        await RisingEdge(dut.clk)

    cocotb.log.info("✓ Word offsets same line test PASSED")


@cocotb.test()
async def test_fetch_after_miss(dut):
    """Test: Fetch after miss should hit (like write-allocate)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req.value = 0
    dut.mem_valid.value = 0

    await RisingEdge(dut.clk)

    # Miss - should trigger fetch
    test_addr = 0x5000
    dut.cpu_req.value = 1
    dut.cpu_addr.value = test_addr

    # Wait for memory request
    while dut.mem_req.value == 0:
        await RisingEdge(dut.clk)

    assert dut.mem_req.value == 1, "Should generate memory request"

    # Provide refill data (I-cache has 4 words per line)
    # Use same pattern as test_icache.py
    for cycle in range(40):
        await FallingEdge(dut.clk)
        if dut.mem_req.value == 1:
            mem_addr = int(dut.mem_addr.value)
            # Use test pattern for word 0, address-based for others
            if (mem_addr & 0x3) == 0:
                dut.mem_data.value = 0xABCDEF00
            else:
                dut.mem_data.value = 0xABCDEF00 | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        await RisingEdge(dut.clk)
        if dut.cpu_stall.value == 0:
            break

    dut.mem_valid.value = 0
    dut.cpu_req.value = 0
    # Wait for cache to be ready
    await RisingEdge(dut.clk)
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)

    # Read back - should hit
    dut.cpu_req.value = 1
    dut.cpu_addr.value = test_addr

    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0

    assert dut.cpu_stall.value == 0, "Read should hit"
    assert dut.cpu_valid.value == 1, "Read should hit"
    # Data should match what we provided for word 0
    assert (dut.cpu_data.value & 0xFFFFFFFF) == 0xABCDEF00, \
        f"Fetch after miss failed: expected 0xABCDEF00, got {hex(dut.cpu_data.value)}"

    cocotb.log.info("✓ Fetch after miss test PASSED")


@cocotb.test()
async def test_round_robin_replacement(dut):
    """Test: Round-robin replacement policy correctness"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req.value = 0
    dut.mem_valid.value = 0

    await RisingEdge(dut.clk)

    # Fill all 4 ways of set 0 (round-robin will use ways 0, 1, 2, 3 in order)
    addresses = [0x00000, 0x10000, 0x20000, 0x30000]

    for addr in addresses:
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr

        # Wait for memory request
        while dut.mem_req.value == 0:
            await RisingEdge(dut.clk)

        # Provide refill data (I-cache has 4 words per line)
        # Use same pattern as test_icache.py
        for cycle in range(40):
            await FallingEdge(dut.clk)
            if dut.mem_req.value == 1:
                mem_addr = int(dut.mem_addr.value)
                dut.mem_data.value = addr | (mem_addr & 0xFFFF)
                dut.mem_valid.value = 1
            else:
                dut.mem_valid.value = 0
            await RisingEdge(dut.clk)
            if dut.cpu_stall.value == 0:
                break

        dut.mem_valid.value = 0
        dut.cpu_req.value = 0
        # Wait for cache to be ready
        await RisingEdge(dut.clk)
        while dut.cpu_stall.value == 1:
            await RisingEdge(dut.clk)

    # Verify all addresses hit
    for addr in addresses:
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        
        await RisingEdge(dut.clk)
        dut.cpu_req.value = 0

        assert dut.cpu_stall.value == 0, f"Address 0x{addr:05X} should hit"
        assert dut.cpu_valid.value == 1, f"Address 0x{addr:05X} should hit"

        await RisingEdge(dut.clk)

    # Now add new address - should evict round-robin (way 0, since we've filled 0,1,2,3)
    new_addr = 0x40000
    dut.cpu_req.value = 1
    dut.cpu_addr.value = new_addr

    # Should generate memory request (eviction)
    while dut.mem_req.value == 0:
        await RisingEdge(dut.clk)

    # Provide refill data (I-cache has 4 words per line)
    # Use same pattern as test_icache.py
    for cycle in range(40):
        await FallingEdge(dut.clk)
        if dut.mem_req.value == 1:
            mem_addr = int(dut.mem_addr.value)
            dut.mem_data.value = new_addr | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        await RisingEdge(dut.clk)
        if dut.cpu_stall.value == 0:
            break

    dut.mem_valid.value = 0
    dut.cpu_req.value = 0
    # Wait for cache to be ready
    await RisingEdge(dut.clk)
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)

    # Verify new address hits
    dut.cpu_req.value = 1
    dut.cpu_addr.value = new_addr
    await Timer(1, units="ns")
    assert dut.cpu_stall.value == 0, "New address should hit"
    assert dut.cpu_valid.value == 1, "New address should hit"
    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # First address (0x00000) should now miss (evicted by round-robin)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x00000
    await RisingEdge(dut.clk)
    # Should generate memory request (miss)
    assert dut.mem_req.value == 1, "First address should miss (evicted by round-robin)"
    dut.cpu_req.value = 0

    cocotb.log.info("✓ Round-robin replacement test PASSED")


@cocotb.test()
async def test_multiple_hits_same_line(dut):
    """Test: Multiple hits to same line (like write hits)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req.value = 0
    dut.mem_valid.value = 0

    await RisingEdge(dut.clk)

    # Fill cache line
    test_addr = 0x2000
    dut.cpu_req.value = 1
    dut.cpu_addr.value = test_addr

    while dut.mem_req.value == 0:
        await RisingEdge(dut.clk)

    # Use same pattern as test_icache.py
    for cycle in range(40):
        await FallingEdge(dut.clk)
        if dut.mem_req.value == 1:
            mem_addr = int(dut.mem_addr.value)
            dut.mem_data.value = 0xFFFFFFFF | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        await RisingEdge(dut.clk)
        if dut.cpu_stall.value == 0:
            break

    dut.mem_valid.value = 0
    dut.cpu_req.value = 0
    # Wait for cache to be ready
    await RisingEdge(dut.clk)
    while dut.cpu_stall.value == 1:
        await RisingEdge(dut.clk)

    # Multiple hits - all should be immediate
    for i in range(5):
        dut.cpu_req.value = 1
        dut.cpu_addr.value = test_addr

        await RisingEdge(dut.clk)
        dut.cpu_req.value = 0

        assert dut.cpu_stall.value == 0, f"Hit {i+1} should not stall"
        assert dut.cpu_valid.value == 1, f"Hit {i+1} should be valid"

        await RisingEdge(dut.clk)

    cocotb.log.info("✓ Multiple hits same line test PASSED")


def runCocotbTests():
    """Run all comprehensive I-cache tests"""

    rtl_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'rtl')

    verilog_sources = [
        os.path.join(rtl_dir, 'icache_nway_multiword.v'),
    ]

    run(
        verilog_sources=verilog_sources,
        toplevel="icache",
        module="test_icache_comprehensive",
        simulator="verilator",
        work_dir="sim_build_icache_comprehensive",
        extra_args=[
            "--trace",
            "--trace-structs",
            "-Wno-fatal",
            "-Wno-WIDTH",
            "-Wno-CASEINCOMPLETE"
        ]
    )

if __name__ == "__main__":
    runCocotbTests()
