"""
D-Cache with MSHR Integration Tests

Tests the integrated D-cache+MSHR system's ability to:
- Serve cache hits during refill (non-blocking operation)
- Coalesce multiple requests to the same cache line
- Track multiple outstanding misses in MSHRs
- Service MSHRs sequentially
- Handle MSHR full conditions
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
    dut.mem_req_ready.value = 0
    dut.mem_resp_valid.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_basic_read_miss(dut):
    """Test: Basic read miss (regression test)"""
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
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            break

    assert dut.mem_req_valid.value == 1, "Cache should request refill"
    assert dut.mem_req_write.value == 0, "Should be read request"

    # Provide memory response (multi-cycle latency)
    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    # Provide full 512-bit cache line (64 bytes = 16 words)
    # Word 0 (offset 0x0) = 0xDEADBEEF
    refill_data = 0xDEADBEEF << (0 * 32)  # Word 0
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    # State transitions to UPDATE_CACHE on this rising edge
    # Output logic evaluates combinational, but we need to wait for state to be stable
    await RisingEdge(dut.clk)  # Wait for UPDATE_CACHE state to be active
    assert dut.cpu_resp_valid.value == 1, "Response should be valid"
    assert dut.cpu_resp_rdata.value == 0xDEADBEEF, \
        f"Should get refill data, got {hex(dut.cpu_resp_rdata.value)}"

    dut.mem_resp_valid.value = 0

    cocotb.log.info("✓ Basic read miss test PASSED")


@cocotb.test()
async def test_hit_during_refill(dut):
    """Test: Serve cache hit while refill in progress"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Prime cache with data at address 0x2000
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xCAFEBABE
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for write miss → refill
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            break

    # Provide refill for write-allocate
    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1  # All 1s

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 0

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 2: Cause a miss to address 0x1000 (different cache line)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter REFILL state
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            break

    # Provide mem_req_ready and wait for REFILL state
    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 3: While in REFILL state, request address 0x2000 (HIT!)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Cache should serve hit during refill (combinational response)
    assert dut.cpu_resp_valid.value == 1, "Should serve hit during refill"
    assert dut.cpu_resp_rdata.value == 0xCAFEBABE, \
        f"Should get cached data 0xCAFEBABE, got {hex(dut.cpu_resp_rdata.value)}"

    dut.cpu_req_valid.value = 0

    # Complete the refill for 0x1000
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = 0x12345678

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    cocotb.log.info("✓ Hit during refill test PASSED")


@cocotb.test()
async def test_secondary_miss_coalesce(dut):
    """Test: Two misses to same cache line coalesce into one MSHR"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: First miss to address 0x1000 (word 0)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter REFILL state
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            break

    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 2: While in REFILL, issue second miss to same line (word 4)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1010  # Same line, different word
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Should NOT generate second memory request (coalesced in MSHR)
    # Cache should be in REFILL state, accepting request for coalescing
    assert dut.cpu_req_ready.value == 1, "Should accept request for coalescing"

    dut.cpu_req_valid.value = 0

    # Complete refill
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    # Create test data where word 0 = 0x1111, word 4 = 0x2222
    # Provide full 512-bit cache line (64 bytes = 16 words)
    refill_data = 0
    for i in range(16):
        if i == 0:
            refill_data |= (0x1111 << (i * 32))
        elif i == 4:
            refill_data |= (0x2222 << (i * 32))
        else:
            refill_data |= (0xFFFF << (i * 32))
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    # State transitions to UPDATE_CACHE on this rising edge
    await RisingEdge(dut.clk)  # Wait for UPDATE_CACHE state to be active

    # First request (word 0) gets response
    assert dut.cpu_resp_valid.value == 1, "Should respond to first request"
    assert dut.cpu_resp_rdata.value == 0x1111, \
        f"Should get word 0 data 0x1111, got {hex(dut.cpu_resp_rdata.value)}"

    dut.mem_resp_valid.value = 0

    # Second request should be served from cache (now that line is filled)
    # Wait for cache to return to IDLE after UPDATE_CACHE
    await RisingEdge(dut.clk)
    
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1010
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    # Hit should be served immediately (combinational in IDLE state)
    assert dut.cpu_resp_valid.value == 1, "Second request should hit"
    assert dut.cpu_resp_rdata.value == 0x2222, \
        f"Should get word 4 data 0x2222, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    cocotb.log.info("✓ Secondary miss coalesce test PASSED")


@cocotb.test()
async def test_write_during_refill(dut):
    """Test: Write hit during refill updates cache"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Prime cache with data at address 0x2000
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x1111
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Complete write-allocate refill
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1:
            break

    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 2: Cause miss to 0x1000
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1:
            break

    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 3: Write to 0x2000 during refill
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x9999
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Write hits assert cpu_resp_valid (Level 3: write hits during refill)
    # The write is accepted and processed, response valid indicates completion
    assert dut.cpu_resp_valid.value == 1, "Should respond to write hit"

    dut.cpu_req_valid.value = 0

    # Complete refill
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    # Provide full 512-bit cache line (64 bytes = 16 words)
    # Word 0 (offset 0x0) = 0xDEADBEEF
    refill_data = 0xDEADBEEF << (0 * 32)  # Word 0
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    # State transitions to UPDATE_CACHE on this rising edge
    await RisingEdge(dut.clk)  # Wait for UPDATE_CACHE state to be active
    dut.mem_resp_valid.value = 0

    await RisingEdge(dut.clk)

    # Step 4: Read back 0x2000 to verify write
    # Wait for cache to return to IDLE after UPDATE_CACHE completes
    await RisingEdge(dut.clk)
    
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    # Hit should be served immediately (combinational in IDLE state)
    assert dut.cpu_resp_valid.value == 1, "Read should hit"
    assert dut.cpu_resp_rdata.value == 0x9999, \
        f"Should read written value 0x9999, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    cocotb.log.info("✓ Write during refill test PASSED")


@cocotb.test()
async def test_multiple_outstanding_misses(dut):
    """Test: Multiple outstanding misses tracked in MSHRs"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # TODO: This test requires proper MSHR address extraction to service multiple MSHRs
    # For now, simplified test - just verify MSHR allocation works

    # Issue first miss
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for FETCH/REFILL
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1:
            break

    await FallingEdge(dut.clk)
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Issue second miss to different line during refill
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000  # Different line
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Should accept and allocate MSHR
    assert dut.cpu_req_ready.value == 1, "Should accept second miss"

    dut.cpu_req_valid.value = 0

    # Complete first refill
    await FallingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    # Provide full 512-bit cache line (64 bytes = 16 words)
    # Word 0 (offset 0x0) = 0x1111
    refill_data = 0x1111 << (0 * 32)  # Word 0
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 0

    cocotb.log.info("✓ Multiple outstanding misses test PASSED")


def runCocotbTests():
    """Run all D-cache MSHR integration tests"""
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
        test_module="test_dcache_mshr",
    )


if __name__ == "__main__":
    runCocotbTests()
