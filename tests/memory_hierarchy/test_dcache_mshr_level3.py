"""
D-Cache with MSHR Integration Tests - Level 3 (Hit-During-Refill)

Tests Level 3 functionality:
- Serve cache hits while refill is in progress (non-blocking)
- Accept new requests in READ_MEM/UPDATE_CACHE states
- Generate responses for hits during refill
- Handle write hits during refill
- Route responses correctly (refill vs hit-during-refill)
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
async def test_hit_during_refill(dut):
    """Test: Serve cache hit while refill is in progress"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Fill cache with a line (so we can hit it later)
    # First, do a read miss to populate the cache line, then write to it
    # Read from 0x3000 (will miss and refill)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept read miss"
    dut.cpu_req_valid.value = 0

    # Wait for memory request and provide response
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            dut.mem_req_ready.value = 1
            await FallingEdge(dut.clk)
            dut.mem_resp_valid.value = 1
            dut.mem_resp_rdata.value = 0x00000000  # Initial data
            await RisingEdge(dut.clk)
            dut.mem_req_ready.value = 0
            dut.mem_resp_valid.value = 0
            break

    # Wait for cache update
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Now write to the populated line (write hit)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xDEADBEEF
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept write hit"
    dut.cpu_req_valid.value = 0

    # Wait for write to complete (cache update with non-blocking assignments)
    await RisingEdge(dut.clk)  # Write happens here
    await RisingEdge(dut.clk)  # Arrays update here (non-blocking)
    await RisingEdge(dut.clk)  # Arrays are now visible

    # Step 2: Trigger a miss to start refill
    # Read from address 0x1000 (will miss and start refill)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept miss request"
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter READ_MEM state
    await RisingEdge(dut.clk)

    # Step 3: Issue a hit request while refill is in progress
    # Read from address 0x3000 (should hit - same line we wrote earlier)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    # Level 3: Cache should accept hit during refill
    assert dut.cpu_req_ready.value == 1, "Should accept hit request during refill (Level 3 non-blocking)"
    # Response is generated combinationally, should be available on same cycle
    # But may need to wait for non-blocking assignments
    await RisingEdge(dut.clk)  # Wait for response to be visible
    assert dut.cpu_resp_valid.value == 1, "Should provide hit response"
    assert dut.cpu_resp_rdata.value == 0xDEADBEEF, f"Should return correct data, got {hex(dut.cpu_resp_rdata.value)}"
    dut.cpu_req_valid.value = 0

    cocotb.log.info("✓ Hit-during-refill test PASSED")


@cocotb.test()
async def test_write_hit_during_refill(dut):
    """Test: Handle write hit while refill is in progress"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Fill cache with a line
    # First read to populate, then write
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x4000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept read miss"
    dut.cpu_req_valid.value = 0

    # Wait for memory request and provide response
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
            dut.mem_req_ready.value = 1
            await FallingEdge(dut.clk)
            dut.mem_resp_valid.value = 1
            dut.mem_resp_rdata.value = 0x00000000
            await RisingEdge(dut.clk)
            dut.mem_req_ready.value = 0
            dut.mem_resp_valid.value = 0
            break

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Now write to populated line
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x4000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xCAFEBABE
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept write hit"
    dut.cpu_req_valid.value = 0

    # Wait for write to complete
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Step 2: Trigger a miss to start refill
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept miss request"
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter READ_MEM state
    await RisingEdge(dut.clk)

    # Step 3: Issue a write hit while refill is in progress
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x4000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x12345678
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    # Level 3: Cache should accept write hit during refill
    assert dut.cpu_req_ready.value == 1, "Should accept write hit during refill (Level 3 non-blocking)"
    dut.cpu_req_valid.value = 0

    # Wait for write to complete (non-blocking assignments)
    await RisingEdge(dut.clk)  # Write happens
    await RisingEdge(dut.clk)  # Arrays update
    await RisingEdge(dut.clk)  # Arrays visible

    # Step 4: Verify write was applied by reading back
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x4000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept read request"
    await RisingEdge(dut.clk)  # Wait for response
    assert dut.cpu_resp_valid.value == 1, "Should provide response"
    assert dut.cpu_resp_rdata.value == 0x12345678, f"Should return updated data, got {hex(dut.cpu_resp_rdata.value)}"
    dut.cpu_req_valid.value = 0

    cocotb.log.info("✓ Write hit-during-refill test PASSED")


@cocotb.test()
async def test_multiple_hits_during_refill(dut):
    """Test: Serve multiple hits while refill is in progress"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Fill multiple cache lines
    # For each address: read miss to populate, then write hit to set data
    for addr, data in [(0x5000, 0x11111111), (0x6000, 0x22222222), (0x7000, 0x33333333)]:
        # Read miss to populate
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0
        dut.cpu_req_byte_en.value = 0xF

        await RisingEdge(dut.clk)
        assert dut.cpu_req_ready.value == 1, f"Should accept read miss to {hex(addr)}"
        dut.cpu_req_valid.value = 0

        # Provide memory response
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req_valid.value == 1 and dut.mem_req_write.value == 0:
                dut.mem_req_ready.value = 1
                await FallingEdge(dut.clk)
                dut.mem_resp_valid.value = 1
                dut.mem_resp_rdata.value = 0x00000000
                await RisingEdge(dut.clk)
                dut.mem_req_ready.value = 0
                dut.mem_resp_valid.value = 0
                break

        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        # Write hit to set data
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 1
        dut.cpu_req_wdata.value = data
        dut.cpu_req_byte_en.value = 0xF

        await RisingEdge(dut.clk)
        assert dut.cpu_req_ready.value == 1, f"Should accept write hit to {hex(addr)}"
        dut.cpu_req_valid.value = 0
        await RisingEdge(dut.clk)  # Write happens
        await RisingEdge(dut.clk)  # Arrays update
        await RisingEdge(dut.clk)  # Arrays visible

    # Step 2: Trigger a miss to start refill
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept miss request"
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter READ_MEM state
    await RisingEdge(dut.clk)

    # Step 3: Issue multiple hit requests while refill is in progress
    for addr, expected_data in [(0x5000, 0x11111111), (0x6000, 0x22222222), (0x7000, 0x33333333)]:
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0
        dut.cpu_req_byte_en.value = 0xF

        await RisingEdge(dut.clk)
        # Level 3: Cache should accept hits during refill
        assert dut.cpu_req_ready.value == 1, f"Should accept hit request to {hex(addr)} during refill"
        await RisingEdge(dut.clk)  # Wait for response
        assert dut.cpu_resp_valid.value == 1, f"Should provide response for {hex(addr)}"
        assert dut.cpu_resp_rdata.value == expected_data, f"Should return correct data for {hex(addr)}, got {hex(dut.cpu_resp_rdata.value)}"
        dut.cpu_req_valid.value = 0
        await RisingEdge(dut.clk)  # Wait a cycle between requests

    cocotb.log.info("✓ Multiple hits-during-refill test PASSED")


@cocotb.test()
async def test_miss_during_refill(dut):
    """Test: Accept miss requests during refill (non-blocking)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Trigger first miss to start refill
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_req_ready.value == 1, "Should accept first miss request"
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter READ_MEM state
    await RisingEdge(dut.clk)

    # Step 2: Issue second miss request while first refill is in progress
    # Level 3: Cache should accept miss during refill if MSHR available
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000  # Different address, no coalescing
    dut.cpu_req_write.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    # Level 3: Cache accepts misses during refill (non-blocking)
    assert dut.cpu_req_ready.value == 1, "Should accept miss request during refill (Level 3 non-blocking)"
    dut.cpu_req_valid.value = 0

    # Verify second MSHR was allocated
    await RisingEdge(dut.clk)
    mshr_valid = int(dut.mshr_valid.value)
    mshr_count = bin(mshr_valid).count('1')
    assert mshr_count == 2, f"Should have 2 MSHRs allocated (non-blocking), got {mshr_count}"

    cocotb.log.info("✓ Miss-during-refill test PASSED")


def runCocotbTests():
    """Run all D-cache MSHR Level 3 tests"""
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
        test_module="test_dcache_mshr_level3",
    )


if __name__ == "__main__":
    runCocotbTests()
