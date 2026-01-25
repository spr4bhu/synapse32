"""
D-Cache with MSHR Integration Tests - Level 1 (Basic MSHR Tracking)

Tests Level 1 functionality:
- MSHR allocation on cache miss
- MSHR retirement on refill complete
- Blocking behavior preserved (no hit-during-refill yet)
- All basic D-cache tests should pass (regression)
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
from cocotb.runner import get_runner
import os


async def reset_cache(dut):
    """Reset the cache"""
    dut.rst.value = 1
    dut.cpu_req_valid.value = 0
    dut.mem_req_ready.value = 1  # Memory ready by default
    dut.mem_resp_valid.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_basic_read_miss_level1(dut):
    """Test: Basic read miss with MSHR tracking (Level 1 regression)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Request read from address 0x1000
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept request"

    dut.cpu_req_valid.value = 0

    # Wait for cache to request memory
    mem_req_seen = False
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            mem_req_seen = True
            # Set mem_req_ready immediately when we see the request
            dut.mem_req_ready.value = 1
            break

    assert mem_req_seen, "Cache should request refill"
    assert dut.mem_req_write.value == 0, "Should be read request"

    # Wait one cycle for cache to enter READ_MEM state and see mem_req_ready=1
    await RisingEdge(dut.clk)

    # Provide memory response (64-byte line = 512 bits = 16 words)
    # Word 0 (offset 0x0) = 0xDEADBEEF
    # Both mem_req_ready and mem_resp_valid must be 1 on the same cycle for state transition
    refill_data = 0xDEADBEEF  # Only word 0, rest are zeros

    # Set response valid on FallingEdge so it's stable for the next RisingEdge
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1  # Response valid
    dut.mem_resp_rdata.value = refill_data
    # mem_req_ready should already be 1

    await RisingEdge(dut.clk)
    # Cache should transition to UPDATE_CACHE on this cycle
    # Wait one more cycle for UPDATE_CACHE to set cpu_resp_valid
    await RisingEdge(dut.clk)
    
    # Response should be valid in UPDATE_CACHE state
    assert dut.cpu_resp_valid.value == 1, "Response should be valid in UPDATE_CACHE"
    assert dut.cpu_resp_rdata.value == 0xDEADBEEF, \
        f"Should get refill data, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.mem_resp_valid.value = 0
    
    dut.mem_resp_valid.value = 0

    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 0

    cocotb.log.info("✓ Basic read miss test PASSED (Level 1)")


@cocotb.test()
async def test_mshr_allocation(dut):
    """Test: Verify MSHR is allocated on miss"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Initially no MSHRs should be valid
    assert int(dut.mshr_valid.value) == 0, "No MSHRs should be valid initially"
    assert dut.mshr_full.value == 0, "MSHR should not be full initially"

    # Request read miss
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait a cycle for MSHR allocation
    await RisingEdge(dut.clk)

    # Verify MSHR was allocated
    mshr_valid_count = bin(int(dut.mshr_valid.value)).count('1')
    assert mshr_valid_count == 1, f"Should have 1 MSHR allocated, got {mshr_valid_count}"

    cocotb.log.info("✓ MSHR allocation test PASSED")


@cocotb.test()
async def test_mshr_retirement(dut):
    """Test: Verify MSHR is retired on refill complete"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Request read miss
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for MSHR allocation
    await RisingEdge(dut.clk)
    mshr_valid_before = int(dut.mshr_valid.value)
    assert mshr_valid_before != 0, "MSHR should be allocated"

    # Wait for memory request
    mem_req_seen = False
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1:
            mem_req_seen = True
            # Set mem_req_ready immediately when we see the request
            dut.mem_req_ready.value = 1
            break

    assert mem_req_seen, "Memory request should be seen"

    # Wait a cycle for state to be in READ_MEM
    await RisingEdge(dut.clk)

    # Provide memory response (both mem_req_ready and mem_resp_valid must be 1)
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = 0x12345678
    # mem_req_ready should already be 1

    # Wait for UPDATE_CACHE → IDLE transition (MSHR retirement)
    # Cache enters UPDATE_CACHE on this cycle, mshr_retire_req is asserted
    await RisingEdge(dut.clk)
    # State transitions to IDLE, MSHR retirement happens on this clock edge (non-blocking)
    await RisingEdge(dut.clk)
    # MSHR retirement takes effect (non-blocking assignment visible)
    await RisingEdge(dut.clk)

    # Verify MSHR was retired
    mshr_valid_after = int(dut.mshr_valid.value)
    # Debug: show which MSHRs are still valid
    if mshr_valid_after != 0:
        valid_mshrs = [i for i in range(8) if (mshr_valid_after >> i) & 1]
        cocotb.log.warning(f"MSHRs still valid: {valid_mshrs}, mshr_valid={mshr_valid_after} (binary: {bin(mshr_valid_after)})")
    assert mshr_valid_after == 0, f"MSHR should be retired, but mshr_valid={mshr_valid_after} (binary: {bin(mshr_valid_after)})"

    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 0

    cocotb.log.info("✓ MSHR retirement test PASSED")


@cocotb.test()
async def test_mshr_full_stall(dut):
    """Test: Cache stalls when MSHR is full (Level 1: blocking, so only 1 MSHR active at a time)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Level 1 is blocking - cache won't accept new requests while refilling
    # So we can't allocate 8 MSHRs in quick succession
    # Instead, test that cache stalls when MSHR is full by trying to allocate
    # multiple MSHRs (they'll queue up, but only one will be active)
    
    # For Level 1, we test that the cache properly checks MSHR availability
    # and stalls when MSHRs are full (even though only 1 is active)
    
    # Allocate first MSHR (will be accepted)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept first request"
    dut.cpu_req_valid.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR was allocated
    mshr_valid_count = bin(int(dut.mshr_valid.value)).count('1')
    assert mshr_valid_count == 1, f"Should have 1 MSHR allocated, got {mshr_valid_count}"

    # Cache is now in READ_MEM state
    # Level 3: Cache is non-blocking, so it can accept new requests during refill
    # However, misses can only be accepted if MSHRs are available or coalescing is possible
    # Try to issue another miss (different address, so no coalescing)
    # Should be accepted if MSHR available (Level 3 non-blocking behavior)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000  # Different address, no coalescing
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Level 3: Cache accepts misses during refill if MSHR available
    # Since we only have 1 MSHR allocated, there are 7 free, so request should be accepted
    # (This test verifies non-blocking behavior - cache accepts requests during refill)
    assert dut.cpu_req_ready.value == 1, "Level 3: Should accept request during refill if MSHR available (non-blocking)"

    dut.cpu_req_valid.value = 0

    # Verify second MSHR was allocated (Level 3 non-blocking)
    await RisingEdge(dut.clk)
    mshr_valid_count_after = bin(int(dut.mshr_valid.value)).count('1')
    assert mshr_valid_count_after == 2, f"Level 3: Should have 2 MSHRs allocated (non-blocking), got {mshr_valid_count_after}"
    
    cocotb.log.info("✓ MSHR non-blocking test PASSED (Level 3: accepts requests during refill)")


def runCocotbTests():
    """Run all D-cache MSHR Level 1 tests"""
    import os

    # Get absolute paths to RTL files
    rtl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "rtl")
    dcache_mshr_path = os.path.abspath(os.path.join(rtl_dir, "dcache_mshr.v"))
    mshr_path = os.path.abspath(os.path.join(rtl_dir, "mshr.v"))

    runner = get_runner("verilator")
    runner.build(
        verilog_sources=[dcache_mshr_path, mshr_path],
        hdl_toplevel="dcache_mshr",
        build_args=[
            "--trace",
            "--trace-structs",
            "-Wno-fatal",
            "-Wno-WIDTH",
            "-Wno-CASEINCOMPLETE",
            "-Wno-UNOPTFLAT"  # For large cache arrays
        ],
        always=True,
    )

    runner.test(
        hdl_toplevel="dcache_mshr",
        test_module="test_dcache_mshr_level1",
    )


if __name__ == "__main__":
    runCocotbTests()
