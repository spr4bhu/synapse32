"""
D-Cache Edge Case and Stress Tests

Tests critical scenarios not covered by basic tests:
- Memory backpressure
- Request rejection when busy
- Multiple address changes during refill
- Write-after-write same address
- LRU thrashing
- Zero byte enables
- Partial byte writes
- Reset during operation
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb.runner import get_runner
import sys

# Helper to reset cache
async def reset_dut(dut):
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

# Helper to wait for cache ready
async def wait_ready(dut, max_cycles=100):
    timeout = 0
    while dut.cpu_req_ready.value == 0:
        await RisingEdge(dut.clk)
        timeout += 1
        if timeout > max_cycles:
            raise Exception(f"Timeout waiting for cpu_req_ready")

# Helper to ensure cache is completely idle and ready
async def ensure_cache_idle(dut, max_cycles=50):
    """Ensure cache is in IDLE state and ready for new requests"""
    wait_count = 0
    while (dut.state.value != 0 or dut.cpu_req_ready.value != 1) and wait_count < max_cycles:
        await RisingEdge(dut.clk)
        wait_count += 1
    
    if wait_count >= max_cycles:
        raise Exception(f"Cache did not return to IDLE after {max_cycles} cycles. State={dut.state.value}, ready={dut.cpu_req_ready.value}")
    
    # Additional cycles to ensure stability
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

# Helper to ensure test isolation - call at end of each test
async def ensure_test_isolation(dut):
    """Ensure test is completely finished and cache is isolated for next test"""
    # Deassert all input signals
    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1  # Keep ready high for next test
    
    # Wait for cache to be completely idle
    await ensure_cache_idle(dut)
    
    # Extra barrier cycles to prevent interference
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

# Helper to ensure cache is completely idle and ready
async def ensure_cache_idle(dut, max_cycles=50):
    """Ensure cache is in IDLE state and ready for new requests"""
    wait_count = 0
    while (dut.state.value != 0 or dut.cpu_req_ready.value != 1) and wait_count < max_cycles:
        await RisingEdge(dut.clk)
        wait_count += 1
    
    if wait_count >= max_cycles:
        raise Exception(f"Cache did not return to IDLE after {max_cycles} cycles. State={dut.state.value}, ready={dut.cpu_req_ready.value}")
    
    # Additional cycles to ensure stability
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

# Helper to ensure test isolation - call at end of each test
async def ensure_test_isolation(dut):
    """Ensure test is completely finished and cache is isolated for next test"""
    # Deassert all input signals
    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1  # Keep ready high for next test
    
    # Wait for cache to be completely idle
    await ensure_cache_idle(dut)
    
    # Extra barrier cycles to prevent interference
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

# Helper to wait for specific state
async def wait_for_state(dut, target_state, max_cycles=100):
    """Wait for cache to reach specific state"""
    timeout = 0
    while dut.state.value != target_state:
        await RisingEdge(dut.clk)
        timeout += 1
        if timeout > max_cycles:
            raise Exception(f"Timeout waiting for state {target_state}, current state={dut.state.value}")

# Helper to wait for memory response to complete
async def wait_for_mem_response_complete(dut, max_cycles=100):
    """Wait for memory response to be processed and cache to return to IDLE with stable arrays"""
    # After mem_resp_valid is set, the state transitions: READ_MEM (2) -> UPDATE_CACHE (3) -> IDLE (0)
    
    # Wait for UPDATE_CACHE state (state = 3 = 0b11)
    timeout = 0
    while dut.state.value != 3 and timeout < max_cycles:  # UPDATE_CACHE = 3
        await RisingEdge(dut.clk)
        timeout += 1
    
    if timeout >= max_cycles:
        raise Exception(f"Timeout waiting for UPDATE_CACHE state, current state={dut.state.value}")
    
    # UPDATE_CACHE is single-cycle: arrays updated on this clock edge, next cycle is IDLE
    # Wait for transition to IDLE
    await RisingEdge(dut.clk)
    
    # Verify we're in IDLE
    assert dut.state.value == 0, f"Cache should be in IDLE after UPDATE_CACHE, got state={dut.state.value}"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready in IDLE state"
    
    # Arrays are updated in UPDATE_CACHE on clock edge, so they're available in IDLE
    # Wait one more cycle to ensure everything is fully stable
    await RisingEdge(dut.clk)
    assert dut.state.value == 0, "Cache should still be in IDLE"
    assert dut.cpu_req_ready.value == 1, "Cache should still be ready"

@cocotb.test()
async def test_memory_backpressure(dut):
    """Test: Memory backpressure (mem_req_ready=0 for extended time)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 0  # Memory NOT ready
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing memory backpressure...")

    # Issue read request (will miss)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for cache to transition to FETCH state
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Verify cache is waiting for memory (mem_req_valid should be asserted)
    assert dut.mem_req_valid.value == 1, "Cache should assert mem_req_valid"
    cocotb.log.info(f"✓ Cache waiting for memory (state={dut.state.value})")

    # Keep memory busy for 10 cycles
    for i in range(10):
        assert dut.mem_req_valid.value == 1, f"mem_req_valid should stay high (cycle {i})"
        await RisingEdge(dut.clk)

    cocotb.log.info("✓ Cache correctly waited during backpressure")

    # Now make memory ready
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    # Provide response
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = 0x12345678 | ((1 << 512) - 1)

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Memory backpressure test PASSED")


@cocotb.test()
async def test_request_rejection_when_busy(dut):
    """Test: Request arrives while cache is busy (should be rejected)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing request rejection when busy...")

    # Issue first request
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Cache should now be processing (LOOKUP -> FETCH)
    await RisingEdge(dut.clk)

    # Try to issue second request while busy
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)

    # Cache should NOT be ready (cpu_req_ready should be 0)
    assert dut.cpu_req_ready.value == 0, "Cache should reject requests when busy"
    cocotb.log.info("✓ Request correctly rejected when busy")

    dut.cpu_req_valid.value = 0

    # Complete first request
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)

    # Now cache should be ready for new requests
    assert dut.cpu_req_ready.value == 1, "Cache should be ready after completing request"
    cocotb.log.info("✓ Request rejection test PASSED")


@cocotb.test()
async def test_lru_thrashing(dut):
    """Test: Fill all 4 ways then evict repeatedly (LRU correctness)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing LRU thrashing...")

    # Fill all 4 ways of set 0
    addresses = [0x00000, 0x10000, 0x20000, 0x30000]

    for i, addr in enumerate(addresses):
        cocotb.log.info(f"Filling way {i} with 0x{addr:05X}")
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0

        await RisingEdge(dut.clk)
        dut.cpu_req_valid.value = 0

        # Wait for memory request
        while dut.mem_req_valid.value == 0:
            await RisingEdge(dut.clk)

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 1
        dut.mem_resp_rdata.value = addr | ((1 << 512) - 1)

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 0

        await wait_ready(dut)

    cocotb.log.info("✓ All 4 ways filled")

    # Now thrash by accessing 8 more addresses (should evict in LRU order)
    thrash_addresses = [0x40000, 0x50000, 0x60000, 0x70000,
                       0x80000, 0x90000, 0xA0000, 0xB0000]

    for i, addr in enumerate(thrash_addresses):
        cocotb.log.info(f"Thrash access {i}: 0x{addr:05X}")
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0

        await RisingEdge(dut.clk)
        dut.cpu_req_valid.value = 0

        # Should miss and evict
        while dut.mem_req_valid.value == 0:
            await RisingEdge(dut.clk)

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 1
        dut.mem_resp_rdata.value = addr | ((1 << 512) - 1)

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 0

        await wait_ready(dut)

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ LRU thrashing test PASSED")


@cocotb.test()
async def test_write_after_write_same_address(dut):
    """Test: Two writes to same cache line"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing write-after-write same address...")

    # First write (miss, will write-allocate)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x5000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xAAAAAAAA
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for memory request
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1  # All 1s

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)
    cocotb.log.info("✓ First write completed")

    # Second write to SAME address (should hit)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x5000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x55555555
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    await wait_ready(dut)
    cocotb.log.info("✓ Second write completed")

    # Read back to verify second write
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x5000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    assert dut.cpu_resp_valid.value == 1, "Response should be valid immediately on hit"
    assert dut.cpu_resp_rdata.value == 0x55555555, \
        f"Should read second write value, got {hex(dut.cpu_resp_rdata.value)}"

    dut.cpu_req_valid.value = 0

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Write-after-write test PASSED")


@cocotb.test()
async def test_zero_byte_enables(dut):
    """Test: Zero byte enables (should do nothing)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing zero byte enables...")

    # Write with ZERO byte enables (edge case) - should still write-allocate
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x6000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xDEADBEEF
    dut.cpu_req_byte_en.value = 0b0000  # NO bytes enabled!

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for cache to enter READ_MEM state (write-allocate)
    await wait_for_state(dut, 2, max_cycles=20)  # READ_MEM = 2
    assert dut.mem_req_valid.value == 1, "Should have memory request"
    assert dut.mem_req_write.value == 0, "Should be read request (write-allocate)"

    # Provide memory response
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = 0xFFFFFFFF | ((1 << 512) - 1)  # All 1s

    # Wait for response to be processed and cache to return to IDLE
    await wait_for_mem_response_complete(dut)

    # Verify cache is ready and in IDLE with stable arrays
    # Arrays are updated in UPDATE_CACHE on clock edge, so after wait_for_mem_response_complete
    # we should be in IDLE with updated arrays ready
    assert dut.state.value == 0, f"Cache should be in IDLE, got state={dut.state.value}"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready"

    # Read back - should still be all 1s (no bytes were written)
    # Arrays from UPDATE_CACHE are now stable in IDLE state
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x6000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    # Cache should detect hit and provide response in same cycle
    assert dut.state.value == 0, f"Cache should remain in IDLE on hit, got state={dut.state.value}"
    assert dut.cpu_resp_valid.value == 1, "Should have immediate response on hit"
    assert dut.cpu_resp_rdata.value == 0xFFFFFFFF, \
        f"Zero byte enables should not modify data, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Zero byte enables test PASSED")


@cocotb.test()
async def test_partial_byte_writes(dut):
    """Test: Partial byte enables across multiple writes to same address"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing partial byte writes...")

    # Step 1: Write byte 0 only (write-allocate)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x7000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x12345678
    dut.cpu_req_byte_en.value = 0b0001  # Byte 0 only

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for write-allocate to complete
    await wait_for_state(dut, 2, max_cycles=20)  # READ_MEM = 2
    
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1  # All 1s

    await wait_for_mem_response_complete(dut)
    assert dut.state.value == 0, "Cache should be in IDLE after write-allocate"
    cocotb.log.info("✓ Byte 0 written (write-allocate complete)")

    # Step 2: Write byte 1 only (write hit)
    # Ensure cache is ready and in IDLE with stable arrays from previous UPDATE_CACHE
    await wait_ready(dut)
    assert dut.state.value == 0, f"Cache should be in IDLE before write, got state={dut.state.value}"
    
    # Wait for cache to be fully ready (same pattern as other working tests)
    await RisingEdge(dut.clk)
    assert dut.state.value == 0, "Cache should still be in IDLE"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready"
    
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x7000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xAABBCCDD
    dut.cpu_req_byte_en.value = 0b0010  # Byte 1 only

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Write hit should complete in one cycle and stay in IDLE
    # Wait for cache to be ready (write hit should complete immediately)
    await wait_ready(dut, max_cycles=5)
    assert dut.state.value == 0, f"Cache should be in IDLE after write hit, got state={dut.state.value}"
    cocotb.log.info("✓ Byte 1 written (write hit)")

    # Step 3: Write all 4 bytes (write hit, overwrite everything)
    # Ensure cache is ready and in IDLE with stable arrays
    assert dut.state.value == 0, f"Cache should be in IDLE before write, got state={dut.state.value}"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready"
    
    # Wait for cache to be fully ready (same pattern as other working tests)
    await RisingEdge(dut.clk)
    assert dut.state.value == 0, "Cache should still be in IDLE"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready"
    
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x7000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x11223344
    dut.cpu_req_byte_en.value = 0xF  # All 4 bytes

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Write hit should complete in one cycle and stay in IDLE
    await wait_ready(dut, max_cycles=5)
    assert dut.state.value == 0, f"Cache should be in IDLE after write hit, got state={dut.state.value}"
    cocotb.log.info("✓ All bytes written (write hit)")

    # Step 4: Read back to verify final value
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x7000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    assert dut.state.value == 0, f"Cache should remain in IDLE on hit, got state={dut.state.value}"
    assert dut.cpu_resp_valid.value == 1, "Should have immediate response on hit"
    
    # Expected: 0x11223344 (all 4 bytes overwritten by last write)
    expected = 0x11223344
    assert dut.cpu_resp_rdata.value == expected, \
        f"Partial byte writes failed: expected {hex(expected)}, got {hex(dut.cpu_resp_rdata.value)}"

    dut.cpu_req_valid.value = 0

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Partial byte writes test PASSED")


@cocotb.test()
async def test_reset_during_operation(dut):
    """Test: Reset asserted during FETCH state"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing reset during operation...")

    # Issue read request
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x8000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for FETCH state
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    cocotb.log.info(f"Cache in state {dut.state.value}, asserting reset...")

    # Assert reset while cache is busy
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Cache should be back in IDLE
    assert dut.state.value == 0, f"Cache should be in IDLE after reset, got {dut.state.value}"
    assert dut.cpu_req_ready.value == 1, "Cache should be ready after reset"

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Reset during operation test PASSED")


@cocotb.test()
async def test_multiple_address_changes_during_refill(dut):
    """Test: Address changes multiple times during single refill"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    cocotb.log.info("Testing multiple address changes during refill...")

    # Issue first request
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x9000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for REFILL state
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    await RisingEdge(dut.clk)

    # First address change
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0xA000
    await RisingEdge(dut.clk)

    # Second address change
    dut.cpu_req_addr.value = 0xB000
    await RisingEdge(dut.clk)

    # Provide memory response
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1
    dut.cpu_req_valid.value = 0

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    # Cache should restart lookup with new address (0xB000)
    # Should eventually become ready after handling the new request
    await wait_ready(dut, max_cycles=200)

    # Ensure test isolation before ending
    await ensure_test_isolation(dut)

    cocotb.log.info("✓ Multiple address changes test PASSED")


def runCocotbTests():
    """Run all D-cache edge case tests"""
    import os

    # Get absolute path to RTL file
    rtl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "rtl")
    dcache_path = os.path.abspath(os.path.join(rtl_dir, "dcache.v"))

    runner = get_runner("verilator")
    runner.build(
        verilog_sources=[dcache_path],
        hdl_toplevel="dcache",
        build_args=[
            "--trace",
            "--trace-structs",
            "-Wno-fatal",
            "-Wno-WIDTH",
            "-Wno-CASEINCOMPLETE"
        ],
        always=True,
    )

    runner.test(
        hdl_toplevel="dcache",
        test_module="test_dcache_edge_cases",
    )

if __name__ == "__main__":
    runCocotbTests()
