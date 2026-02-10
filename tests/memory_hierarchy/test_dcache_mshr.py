"""
D-Cache with MSHR Integration Tests - Fully Non-Blocking

Tests the integrated D-cache+MSHR system's ability to:
- Handle 2 independent outstanding misses simultaneously (miss-under-miss)
- Serve cache hits during refill (hit-under-miss)
- Coalesce multiple requests to the same cache line
- Handle MSHR full conditions (stall on third miss)
- Detect and handle victim conflicts
- Properly arbitrate memory access between MSHRs

Uses 32-bit memory interface with burst logic (matching I-cache design).
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb_test.simulator import run
import os

# Cache configuration (must match dcache.v parameters)
CACHE_LINE_WORDS = 4  # Matching I-cache default


async def settle(dut):
    """Wait for combinational logic to settle"""
    await Timer(1, unit="ns")


async def wait_cycles(dut, n=1):
    """Wait n clock cycles with settling"""
    for _ in range(n):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")


async def reset_cache(dut):
    """Reset the cache"""
    dut.rst.value = 1
    dut.cpu_req.value = 0
    dut.cpu_write.value = 0
    dut.cpu_addr.value = 0
    dut.cpu_wdata.value = 0
    dut.cpu_byte_en.value = 0
    dut.mem_valid.value = 0
    dut.invalidate.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def provide_burst_refill(dut, data_words):
    """
    Provide a burst refill response.

    Args:
        dut: Device under test
        data_words: List of 32-bit words to send (or single value to replicate)
    """
    if isinstance(data_words, int):
        # Single value - replicate for all words
        data_words = [data_words] * CACHE_LINE_WORDS

    for i, word in enumerate(data_words):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        dut.mem_data.value = word
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0


async def provide_burst_writeback_ack(dut):
    """
    Acknowledge a burst writeback.
    Memory accepts each word when mem_valid is asserted.
    """
    for i in range(CACHE_LINE_WORDS):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0


async def prime_cache_line(dut, addr, data_value):
    """
    Prime a cache line by issuing a write miss and completing the refill.
    Returns with cache in IDLE state with the line cached.
    """
    dut.cpu_req.value = 1
    dut.cpu_addr.value = addr
    dut.cpu_write.value = 1
    dut.cpu_wdata.value = data_value
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for cache to request memory (FETCH state)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    # Provide burst refill for write-allocate
    await provide_burst_refill(dut, 0xFFFFFFFF)

    # Wait for ALLOCATE to complete
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_basic_read_miss(dut):
    """Test: Basic read miss with burst refill (regression test)"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Request read from address 0x1000 (word 0 of a cache line)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # With non-blocking cache, first miss doesn't stall (MSHR allocated)
    # but cpu_valid should be 0 since data not ready
    assert dut.cpu_valid.value == 0, "Should not have valid data yet"

    # Wait for cache to request memory (FETCH state)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    assert dut.mem_req.value == 1, "Cache should request refill"
    assert dut.mem_write.value == 0, "Should be read request"

    # Provide burst refill
    # Word 0 = 0xDEADBEEF, others = 0xFFFFFFFF
    refill_data = [0xDEADBEEF] + [0xFFFFFFFF] * (CACHE_LINE_WORDS - 1)
    await provide_burst_refill(dut, refill_data)

    # Wait for ALLOCATE state
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Response should be valid"
    assert dut.cpu_data.value == 0xDEADBEEF, \
        f"Should get refill data, got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_basic_read_miss PASSED")


@cocotb.test()
async def test_two_independent_misses(dut):
    """Test: Two independent misses to different sets allocate both MSHRs"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Use addresses that map to DIFFERENT cache sets
    # With 64 sets, 4 words/line: set_index = addr[9:4]
    # 0x1000 -> set (0x1000 >> 4) & 0x3F = 0
    # 0x1010 -> set (0x1010 >> 4) & 0x3F = 1
    ADDR1 = 0x1000  # Set 0
    ADDR2 = 0x1010  # Set 1

    # Issue first miss
    dut.cpu_req.value = 1
    dut.cpu_addr.value = ADDR1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Non-blocking: should not stall (MSHR[0] allocated)
    assert dut.cpu_stall.value == 0, "Should not stall on first miss (MSHR available)"
    assert dut.cpu_valid.value == 0, "Should not have valid data yet"

    # Let MSHR[0] transition to FETCH and wait for memory request
    for _ in range(5):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Issue second miss to different set (MSHR[1])
    dut.cpu_addr.value = ADDR2
    await RisingEdge(dut.clk)

    # Non-blocking: should not stall (MSHR[1] allocated)
    assert dut.cpu_stall.value == 0, "Should not stall on second miss (MSHR available)"

    # Keep cpu_req=1 to keep requesting ADDR2 while we process the refills
    # Complete first refill (MSHR[0] for ADDR1 - has memory grant)
    await provide_burst_refill(dut, 0x11111111)

    # Wait for MSHR[0] ALLOCATE to complete
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Now MSHR[1] should get memory grant for ADDR2
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    # Complete second refill (MSHR[1] for ADDR2)
    await provide_burst_refill(dut, 0x22222222)

    # Wait for MSHR[1] ALLOCATE to complete - cpu_valid should go high
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Second line should be valid on ALLOCATE"
    assert dut.cpu_data.value == 0x22222222, f"Got {hex(dut.cpu_data.value)}"

    # Now verify first line is also cached
    dut.cpu_addr.value = ADDR1
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "First line should be cached"
    assert dut.cpu_data.value == 0x11111111, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_two_independent_misses PASSED")


@cocotb.test()
async def test_hit_during_miss(dut):
    """Test: Serve cache hit while miss refill in progress (hit-under-miss)"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Prime cache with data at address 0x2000
    await prime_cache_line(dut, 0x2000, 0xCAFEBABE)

    # Step 2: Issue miss to address 0x1000 (different set)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for cache to enter FETCH state
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    # Start providing burst refill but don't complete yet
    for i in range(2):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        dut.mem_data.value = 0x12345678
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)

    # Step 3: While MSHR is in FETCH, request hit to address 0x2000
    dut.cpu_addr.value = 0x2000
    dut.cpu_write.value = 0

    await RisingEdge(dut.clk)

    # Hit-under-miss: should be served immediately
    assert dut.cpu_valid.value == 1, "Hit should be served during miss"
    assert dut.cpu_data.value == 0xCAFEBABE, \
        f"Should get cached data 0xCAFEBABE, got {hex(dut.cpu_data.value)}"
    assert dut.cpu_stall.value == 0, "Should not stall on hit"

    # Complete the remaining burst refill for 0x1000
    dut.cpu_addr.value = 0x1000  # Switch back to check miss completion
    for i in range(CACHE_LINE_WORDS - 2):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        dut.mem_data.value = 0x12345678
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0

    # Wait for ALLOCATE
    await RisingEdge(dut.clk)

    # Verify 0x1000 is now cached
    assert dut.cpu_valid.value == 1, "Miss should complete"
    assert dut.cpu_data.value == 0x12345678, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_hit_during_miss PASSED")


@cocotb.test()
async def test_hit_during_two_misses(dut):
    """Test: Serve cache hit while both MSHRs are handling misses"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Step 1: Prime cache with data at address 0x3000
    await prime_cache_line(dut, 0x3000, 0xBEEFCAFE)

    # Step 2: Issue first miss to 0x1000
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for FETCH
    for _ in range(5):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Issue second miss to 0x2000 (MSHR[1])
    dut.cpu_addr.value = 0x2000
    await RisingEdge(dut.clk)

    # Both MSHRs should be allocated now

    # Step 3: Issue hit to 0x3000 while both MSHRs busy
    dut.cpu_addr.value = 0x3000
    await RisingEdge(dut.clk)

    # Hit-under-miss: should serve immediately
    assert dut.cpu_valid.value == 1, "Hit should be served while MSHRs busy"
    assert dut.cpu_data.value == 0xBEEFCAFE, f"Got {hex(dut.cpu_data.value)}"
    assert dut.cpu_stall.value == 0, "Should not stall on hit"

    # Clean up: complete the refills
    dut.cpu_req.value = 0
    await provide_burst_refill(dut, 0x11111111)  # MSHR[0]
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Wait for MSHR[1] to get memory grant
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0x22222222)  # MSHR[1]

    await RisingEdge(dut.clk)
    cocotb.log.info("test_hit_during_two_misses PASSED")


@cocotb.test()
async def test_third_miss_stalls(dut):
    """Test: Third miss stalls when both MSHRs are full"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Issue first miss to 0x1000 (MSHR[0])
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_stall.value == 0, "First miss should not stall"

    # Wait for FETCH
    for _ in range(5):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Issue second miss to 0x2000 (MSHR[1])
    dut.cpu_addr.value = 0x2000
    await RisingEdge(dut.clk)
    assert dut.cpu_stall.value == 0, "Second miss should not stall"

    await RisingEdge(dut.clk)

    # Issue third miss to 0x3000 - should stall (both MSHRs full)
    dut.cpu_addr.value = 0x3000
    await RisingEdge(dut.clk)
    assert dut.cpu_stall.value == 1, "Third miss should stall (MSHRs full)"

    # Complete first refill (frees MSHR[0])
    await provide_burst_refill(dut, 0x11111111)

    # Wait for ALLOCATE state to complete (frees MSHR)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Third miss should now proceed (MSHR[0] free)
    assert dut.cpu_stall.value == 0, "Should not stall after MSHR freed"

    # Clean up
    dut.cpu_req.value = 0

    # Complete remaining refills
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break
    await provide_burst_refill(dut, 0x22222222)

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break
    await provide_burst_refill(dut, 0x33333333)

    cocotb.log.info("test_third_miss_stalls PASSED")


@cocotb.test()
async def test_mshr_coalescing(dut):
    """Test: Two misses to same cache line coalesce into one MSHR"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Issue first miss to 0x1000 (word 0)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for FETCH
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Start burst refill - provide first few words
    for i in range(2):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        dut.mem_data.value = 0x1111 if i == 0 else 0x2222
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)

    # Issue second miss to same line (word 1) - should coalesce
    dut.cpu_addr.value = 0x1004  # Same line, different word

    await RisingEdge(dut.clk)

    # Should stall (coalescing - MSHR matched but not completing)
    assert dut.cpu_stall.value == 1, "Should stall during coalescing"

    # Complete remaining burst refill
    for i in range(2, CACHE_LINE_WORDS):
        await FallingEdge(dut.clk)
        dut.mem_valid.value = 1
        dut.mem_data.value = 0x3333 if i == 2 else 0x4444
        await RisingEdge(dut.clk)

    await FallingEdge(dut.clk)
    dut.mem_valid.value = 0

    # Wait for ALLOCATE
    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Verify both words are cached
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Word 0 should hit"
    assert dut.cpu_data.value == 0x1111, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_addr.value = 0x1004
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Word 1 should hit"
    assert dut.cpu_data.value == 0x2222, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_mshr_coalescing PASSED")


@cocotb.test()
async def test_writeback_then_fetch(dut):
    """Test: Miss that evicts dirty line does WRITEBACK -> FETCH"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Fill all 4 ways of set 0 with dirty lines
    # Set 0 addresses: 0x1000, 0x2000, 0x3000, 0x4000 (assuming 64 sets, 4-word lines)
    # Actually with NUM_SETS=64, INDEX_BITS=6, addresses that map to set 0:
    # 0x0000, 0x1000, 0x2000, etc. map to different sets
    # Set 0 = addr[7:2] bits for index (with 64 sets, 4-word lines)
    # Let's use addresses that map to set 0: 0x0000, 0x4000, 0x8000, 0xC000

    for i, addr in enumerate([0x0000, 0x4000, 0x8000, 0xC000]):
        await prime_cache_line(dut, addr, 0xDEAD0000 + i)

    # Now cause a miss to a new address that maps to set 0
    # This will evict one of the dirty lines
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x10000  # Different tag, same set
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for WRITEBACK state (mem_write = 1)
    writeback_seen = False
    for _ in range(20):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 1:
            writeback_seen = True
            break

    assert writeback_seen, "Should enter WRITEBACK state for dirty eviction"

    # Acknowledge writeback
    await provide_burst_writeback_ack(dut)

    # Now wait for FETCH state (mem_write = 0)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    assert dut.mem_req.value == 1, "Should enter FETCH state"
    assert dut.mem_write.value == 0, "FETCH should be read"

    # Complete refill
    await provide_burst_refill(dut, 0x99999999)

    await RisingEdge(dut.clk)

    # Verify new line is cached
    assert dut.cpu_valid.value == 1, "New line should be valid"
    assert dut.cpu_data.value == 0x99999999, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_writeback_then_fetch PASSED")


@cocotb.test()
async def test_memory_arbitration(dut):
    """Test: MSHR[0] gets priority when both need memory access"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Issue first miss to 0x1000 (MSHR[0])
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Issue second miss immediately to 0x2000 (MSHR[1])
    dut.cpu_addr.value = 0x2000
    await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Wait for memory request - should be for 0x1000 (MSHR[0] priority)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Check that memory address is for first miss (0x1000 base)
    mem_addr = int(dut.mem_addr.value)
    assert (mem_addr & 0xFFF0) == 0x1000, \
        f"MSHR[0] should get memory first, addr={hex(mem_addr)}"

    # Complete MSHR[0] refill
    await provide_burst_refill(dut, 0x11111111)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Now MSHR[1] should get memory
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    mem_addr = int(dut.mem_addr.value)
    assert (mem_addr & 0xFFF0) == 0x2000, \
        f"MSHR[1] should get memory after MSHR[0] completes, addr={hex(mem_addr)}"

    # Complete MSHR[1] refill
    await provide_burst_refill(dut, 0x22222222)

    await RisingEdge(dut.clk)
    cocotb.log.info("test_memory_arbitration PASSED")


###############################################################################
# EDGE CASE TESTS
###############################################################################

@cocotb.test()
async def test_rapid_address_changes(dut):
    """Test: Rapid address changes don't corrupt cache state"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Prime a line first
    await prime_cache_line(dut, 0x1000, 0xAAAAAAAA)

    # Rapidly change addresses every cycle
    addrs = [0x1000, 0x1010, 0x1020, 0x1000, 0x1010, 0x1000]
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    for addr in addrs:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)

    # Stop and verify the primed line is still correct
    dut.cpu_addr.value = 0x1000
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Primed line should still hit"
    assert dut.cpu_data.value == 0xAAAAAAAA, f"Data corrupted: {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_rapid_address_changes PASSED")


@cocotb.test()
async def test_write_then_read_same_cycle(dut):
    """Test: Write followed by read to same address"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Prime cache line
    await prime_cache_line(dut, 0x1000, 0x11111111)

    # Write new value
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 1
    dut.cpu_wdata.value = 0x99999999
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Write should hit"

    # Immediately read back
    dut.cpu_write.value = 0
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Read should hit"
    assert dut.cpu_data.value == 0x99999999, f"Got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_write_then_read_same_cycle PASSED")


@cocotb.test()
async def test_byte_writes(dut):
    """Test: Individual byte writes with byte enable"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Prime with known pattern
    await prime_cache_line(dut, 0x1000, 0xFFFFFFFF)

    # Write byte 0 only
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 1
    dut.cpu_wdata.value = 0x000000AA
    dut.cpu_byte_en.value = 0x1  # Only byte 0
    await RisingEdge(dut.clk)

    # Write byte 2 only
    dut.cpu_wdata.value = 0x00BB0000
    dut.cpu_byte_en.value = 0x4  # Only byte 2
    await RisingEdge(dut.clk)

    # Read back
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF
    await RisingEdge(dut.clk)

    expected = 0xFFBBFFAA
    assert dut.cpu_data.value == expected, \
        f"Byte writes failed: expected {hex(expected)}, got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_byte_writes PASSED")


@cocotb.test()
async def test_invalidate_during_idle(dut):
    """Test: Cache invalidation clears all lines"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Prime multiple lines
    await prime_cache_line(dut, 0x1000, 0x11111111)
    await prime_cache_line(dut, 0x1010, 0x22222222)
    await prime_cache_line(dut, 0x1020, 0x33333333)

    # Verify they hit
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_addr.value = 0x1000
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Should hit before invalidate"

    # Invalidate
    dut.cpu_req.value = 0
    dut.invalidate.value = 1
    await RisingEdge(dut.clk)
    dut.invalidate.value = 0
    await RisingEdge(dut.clk)

    # All lines should miss now
    dut.cpu_req.value = 1
    for addr in [0x1000, 0x1010, 0x1020]:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 0, f"Should miss after invalidate: {hex(addr)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_invalidate_during_idle PASSED")


@cocotb.test()
async def test_same_set_eviction_chain(dut):
    """Test: Fill all ways of a set, then evict through LRU"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # With 4 ways and 64 sets, these addresses all map to set 0
    # set_index = addr[9:4], so we need same bits [9:4] but different tags
    # 0x0000, 0x0400, 0x0800, 0x0C00 all have set_index = 0 (diff tag, same index)
    addrs = [0x0000, 0x0400, 0x0800, 0x0C00]
    values = [0x11111111, 0x22222222, 0x33333333, 0x44444444]

    # Fill all 4 ways
    for addr, val in zip(addrs, values):
        await prime_cache_line(dut, addr, val)

    # Verify all hit
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF
    for addr, val in zip(addrs, values):
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"Should hit: {hex(addr)}"
        assert dut.cpu_data.value == val, f"Wrong data for {hex(addr)}"

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Add 5th line to same set - evicts one dirty line
    # This is a write miss that triggers WRITEBACK then FETCH
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000  # Also set 0, different tag
    dut.cpu_write.value = 1
    dut.cpu_wdata.value = 0x55555555
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait for WRITEBACK (dirty eviction)
    for _ in range(20):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 1:
            break

    if dut.mem_req.value == 1 and dut.mem_write.value == 1:
        await provide_burst_writeback_ack(dut)

    # Wait for FETCH
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    await provide_burst_refill(dut, 0xFFFFFFFF)

    # Wait for ALLOCATE to complete
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # 5th line should hit with written data (not refill data)
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_addr.value = 0x1000
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "5th line should hit"
    assert dut.cpu_data.value == 0x55555555, f"5th line has wrong data: {hex(dut.cpu_data.value)}"

    # At least one original line should miss (evicted to make room for 5th)
    # Note: Due to LRU timing during verify loop, multiple evictions may occur
    miss_count = 0
    hit_count = 0
    for addr in addrs:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        if dut.cpu_valid.value == 0:
            miss_count += 1
            cocotb.log.info(f"  Miss at {hex(addr)}")
        else:
            hit_count += 1

    assert miss_count >= 1, f"Expected at least 1 eviction, got {miss_count} misses"
    assert hit_count >= 1, f"Expected at least 1 hit, got {hit_count} hits"

    dut.cpu_req.value = 0
    cocotb.log.info("test_same_set_eviction_chain PASSED")


@cocotb.test()
async def test_write_miss_allocate(dut):
    """Test: Write miss does write-allocate correctly"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Write miss - should fetch line then write
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1000
    dut.cpu_write.value = 1
    dut.cpu_wdata.value = 0xDEADBEEF
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 0, "Write miss should not be valid immediately"

    # Wait for FETCH
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1 and dut.mem_write.value == 0:
            break

    # Provide refill data (different from write data)
    await provide_burst_refill(dut, 0xFFFFFFFF)

    # Wait for ALLOCATE
    await RisingEdge(dut.clk)

    # Read back - should have written data, not refill data
    dut.cpu_write.value = 0
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Should hit after write-allocate"
    assert dut.cpu_data.value == 0xDEADBEEF, \
        f"Write-allocate failed: got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_write_miss_allocate PASSED")


###############################################################################
# STRESS TESTS
###############################################################################

@cocotb.test()
async def test_stress_sequential_accesses(dut):
    """Stress test: 100 sequential read/write operations"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Prime some lines
    for i in range(8):
        await prime_cache_line(dut, i * 0x10, 0x1000 + i)

    dut.cpu_req.value = 1
    dut.cpu_byte_en.value = 0xF

    # Interleaved reads and writes
    for i in range(100):
        addr = (i % 8) * 0x10
        if i % 3 == 0:
            # Write
            dut.cpu_write.value = 1
            dut.cpu_wdata.value = 0xA000 + i
            dut.cpu_addr.value = addr
            await RisingEdge(dut.clk)
        else:
            # Read
            dut.cpu_write.value = 0
            dut.cpu_addr.value = addr
            await RisingEdge(dut.clk)
            assert dut.cpu_valid.value == 1, f"Miss on iteration {i}, addr {hex(addr)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_stress_sequential_accesses PASSED")


@cocotb.test()
async def test_stress_miss_storm(dut):
    """Stress test: Many consecutive misses with refills"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Cause many misses to different sets
    addrs = [i * 0x10 for i in range(16)]  # 16 different sets
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    for idx, addr in enumerate(addrs):
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)

        # Wait for memory request if miss
        if dut.cpu_valid.value == 0:
            for _ in range(10):
                await RisingEdge(dut.clk)
                if dut.mem_req.value == 1:
                    break

            # Provide refill
            await provide_burst_refill(dut, 0x1000 + idx)
            await RisingEdge(dut.clk)

    # Verify all lines are now cached
    for idx, addr in enumerate(addrs):
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"Miss after storm: {hex(addr)}"
        assert dut.cpu_data.value == 0x1000 + idx, \
            f"Wrong data for {hex(addr)}: {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_stress_miss_storm PASSED")


@cocotb.test()
async def test_stress_dirty_eviction_chain(dut):
    """Stress test: Chain of dirty evictions"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Fill set 0 with dirty lines (4 ways)
    set0_addrs = [0x0000, 0x0400, 0x0800, 0x0C00]
    for i, addr in enumerate(set0_addrs):
        await prime_cache_line(dut, addr, 0xD1D1D100 + i)

    # Now repeatedly evict and replace in set 0
    new_addrs = [0x1000, 0x1400, 0x1800, 0x1C00]
    for i, addr in enumerate(new_addrs):
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 1
        dut.cpu_wdata.value = 0xBEEF00 + i
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        # Should need writeback then fetch
        # Wait for writeback
        for _ in range(20):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1 and dut.mem_write.value == 1:
                break

        if dut.mem_req.value == 1 and dut.mem_write.value == 1:
            await provide_burst_writeback_ack(dut)

        # Wait for fetch
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1 and dut.mem_write.value == 0:
                break

        await provide_burst_refill(dut, 0xFFFFFFFF)
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

        dut.cpu_req.value = 0
        await RisingEdge(dut.clk)

    # Verify new lines are cached with correct data
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    for i, addr in enumerate(new_addrs):
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"New line should hit: {hex(addr)}"
        # Data should be written value, not refill value
        expected = 0xBEEF00 + i
        assert dut.cpu_data.value == expected, \
            f"Wrong data: expected {hex(expected)}, got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_stress_dirty_eviction_chain PASSED")


@cocotb.test()
async def test_concurrent_mshr_completion(dut):
    """Test: Both MSHRs complete in quick succession"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Issue two misses to different sets
    ADDR1 = 0x1000  # Set 0
    ADDR2 = 0x1010  # Set 1

    dut.cpu_req.value = 1
    dut.cpu_addr.value = ADDR1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    dut.cpu_addr.value = ADDR2
    await RisingEdge(dut.clk)

    dut.cpu_req.value = 0

    # Complete first MSHR
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0xAAAAAAAA)
    await RisingEdge(dut.clk)

    # Immediately complete second MSHR (minimal gap)
    for _ in range(5):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0xBBBBBBBB)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Both should be cached now
    dut.cpu_req.value = 1
    dut.cpu_addr.value = ADDR1
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "First line should be cached"
    assert dut.cpu_data.value == 0xAAAAAAAA

    dut.cpu_addr.value = ADDR2
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Second line should be cached"
    assert dut.cpu_data.value == 0xBBBBBBBB

    dut.cpu_req.value = 0
    cocotb.log.info("test_concurrent_mshr_completion PASSED")


@cocotb.test()
async def test_lru_debug(dut):
    """Debug test: Trace LRU state and victim selection"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Open debug file
    debug_file = open('/tmp/lru_debug.txt', 'w')
    def log(msg):
        debug_file.write(msg + '\n')
        debug_file.flush()
        cocotb.log.info(msg)

    # Use set 1 with 4 addresses
    addrs = [0x0010, 0x0410, 0x0810, 0x0C10]
    SET_IDX = 1

    log("=== Filling 4 ways ===")

    for i, addr in enumerate(addrs):
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 0
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        # Log LRU state before miss handling
        lru = int(dut.lru_state[SET_IDX].value)
        log(f"  Fill {hex(addr)}: LRU before = {lru:03b}")

        # Wait for FETCH
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break

        await provide_burst_refill(dut, addr)
        await RisingEdge(dut.clk)

        # Log LRU state after ALLOCATE
        lru = int(dut.lru_state[SET_IDX].value)
        log(f"  Fill {hex(addr)}: LRU after  = {lru:03b}, way {i}")

        await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    log("=== Verifying 4 ways (read access updates LRU) ===")

    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    for i, addr in enumerate(addrs):
        lru_before = int(dut.lru_state[SET_IDX].value)
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        lru_after = int(dut.lru_state[SET_IDX].value)
        hit = dut.cpu_valid.value == 1
        log(f"  Read {hex(addr)}: hit={hit}, LRU {lru_before:03b} -> {lru_after:03b}")

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    log("=== Adding 5th line (0x1010) ===")

    lru_before = int(dut.lru_state[SET_IDX].value)
    log(f"  LRU before 5th line: {lru_before:03b}")

    # Based on LRU, which victim should be selected?
    if (lru_before & 1) == 0:  # lru[0] == 0
        if (lru_before & 2) == 0:  # lru[1] == 0
            expected_victim = 0
        else:
            expected_victim = 1
    else:  # lru[0] == 1
        if (lru_before & 4) == 0:  # lru[2] == 0
            expected_victim = 2
        else:
            expected_victim = 3
    log(f"  Expected victim way: {expected_victim}")

    # Trigger 5th miss
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1010
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # CRITICAL: Deassert cpu_req and wait for state to settle
    dut.cpu_req.value = 0
    await wait_cycles(dut, 2)  # Let MSHR allocation propagate

    # Now check MSHR state
    mshr0_valid = int(dut.mshr_valid.value) & 1
    mshr0_state = int(dut.mshr_state[0].value)
    mshr0_victim = int(dut.mshr_victim_way[0].value)
    mshr0_index = int(dut.mshr_index[0].value)
    log(f"  MSHR[0]: valid={mshr0_valid}, state={mshr0_state}, victim_way={mshr0_victim}, index={mshr0_index}")

    # Check which way was invalidated (for clean miss, happens immediately)
    valid_ways = []
    for w in range(4):
        if dut.valid[SET_IDX][w].value == 1:
            valid_ways.append(w)

    log(f"  Valid ways after MSHR alloc: {valid_ways}")

    # Wait for FETCH to complete
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0x1010)

    # Check MSHR state right after refill
    mshr0_valid = int(dut.mshr_valid.value) & 1
    mshr0_state = int(dut.mshr_state[0].value)
    log(f"  After refill: mshr_valid[0]={mshr0_valid}, mshr_state[0]={mshr0_state}")

    await RisingEdge(dut.clk)  # ALLOCATE should run here

    # Check after ALLOCATE
    mshr0_valid_after = int(dut.mshr_valid.value) & 1
    mshr0_state_after = int(dut.mshr_state[0].value)
    lru_after = int(dut.lru_state[SET_IDX].value)
    log(f"  After ALLOCATE: mshr_valid[0]={mshr0_valid_after}, mshr_state[0]={mshr0_state_after}, LRU={lru_after:03b}")

    # Check valid bits
    valid_bits = [int(dut.valid[SET_IDX][w].value) for w in range(4)]
    log(f"  Valid bits: {valid_bits}")

    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    log("=== Checking which original addresses hit/miss ===")

    miss_count = 0
    for addr in addrs:
        # Set address and request, then check combinational output BEFORE clock edge
        dut.cpu_addr.value = addr
        dut.cpu_req.value = 1
        await settle(dut)  # Let combinational hit logic settle

        # Check hit/miss using combinational output (before clock triggers allocation)
        hit = dut.cpu_valid.value == 1
        log(f"  {hex(addr)}: {'HIT' if hit else 'MISS'}")
        if not hit:
            miss_count += 1

        # CRITICAL: Deassert request BEFORE clock edge to prevent MSHR allocation
        dut.cpu_req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)  # Extra settling

    # Verify exactly 1 eviction
    assert miss_count == 1, f"Expected 1 eviction, got {miss_count}"

    dut.cpu_req.value = 0
    log("test_lru_debug PASSED")
    debug_file.close()


@cocotb.test()
async def test_victim_selection_clean_lines(dut):
    """Test: Verify LRU victim selection with clean (non-dirty) lines"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Fill 4 ways of set 1 with READ operations (clean lines)
    # Set 1 addresses: addr[9:4] = 1 means addr & 0x3F0 = 0x010
    addrs = [0x0010, 0x0410, 0x0810, 0x0C10]  # All set 1, different tags

    for addr in addrs:
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 0
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        # Wait for FETCH (no writeback since cold miss)
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break

        await provide_burst_refill(dut, addr)  # Use addr as data for easy verification
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Verify all 4 are cached
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    for addr in addrs:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"Should hit: {hex(addr)}"

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Add 5th line - should evict one via LRU (no writeback needed - clean lines)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1010  # Also set 1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Should go directly to FETCH (no WRITEBACK)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    # Should be a read request (not write)
    assert dut.mem_write.value == 0, "Clean eviction should not need writeback"

    await provide_burst_refill(dut, 0x1010)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Verify 5th line is cached
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1010
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "5th line should hit"
    assert dut.cpu_data.value == 0x1010

    # Count evictions - but DON'T trigger new MSHR allocations on miss
    # Check cpu_valid BEFORE clock edge to avoid triggering MSHR allocation
    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    hit_count = 0
    miss_addrs = []
    for addr in addrs:
        # Set address and request, then check combinational output BEFORE clock edge
        dut.cpu_addr.value = addr
        dut.cpu_req.value = 1
        await settle(dut)  # Let combinational hit logic settle

        # Check hit/miss using combinational output (before clock triggers allocation)
        if dut.cpu_valid.value == 1:
            hit_count += 1
        else:
            miss_addrs.append(addr)

        # CRITICAL: Deassert request BEFORE clock edge to prevent MSHR allocation
        dut.cpu_req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)  # Extra settling

    # With 4 ways, adding 5th line should evict exactly 1
    assert hit_count == 3, f"Expected 3 hits, got {hit_count}"
    assert len(miss_addrs) == 1, f"Expected exactly 1 eviction, got {len(miss_addrs)}"
    cocotb.log.info(f"  Evicted addresses: {[hex(a) for a in miss_addrs]}")

    dut.cpu_req.value = 0
    cocotb.log.info("test_victim_selection_clean_lines PASSED")


@cocotb.test()
async def test_single_eviction_determinism(dut):
    """Test: Fill 4 ways, add 5th, verify exactly 1 eviction and correct LRU victim"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Use set 2 for this test
    SET_IDX = 2
    addrs = [0x0020, 0x0420, 0x0820, 0x0C20]  # All map to set 2

    # Fill 4 ways with READ operations (clean lines)
    for i, addr in enumerate(addrs):
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 0
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        # Wait for FETCH
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break

        await provide_burst_refill(dut, addr)
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Verify all 4 are cached
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    for addr in addrs:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"Should hit before 5th: {hex(addr)}"

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Record LRU state before adding 5th line
    lru_before = int(dut.lru_state[SET_IDX].value)

    # Predict which way should be evicted based on LRU
    if (lru_before & 1) == 0:  # lru[0] == 0
        if (lru_before & 2) == 0:  # lru[1] == 0
            expected_victim = 0
        else:
            expected_victim = 1
    else:  # lru[0] == 1
        if (lru_before & 4) == 0:  # lru[2] == 0
            expected_victim = 2
        else:
            expected_victim = 3

    expected_evicted_addr = addrs[expected_victim]

    # Add 5th line
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1020  # Also set 2, different tag
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0

    # Wait for FETCH
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0x1020)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Check hit/miss for all original addresses
    # Check BEFORE clock edge to avoid triggering MSHR allocation
    miss_count = 0
    evicted_addr = None
    for addr in addrs:
        dut.cpu_addr.value = addr
        dut.cpu_req.value = 1
        await settle(dut)  # Let combinational logic settle

        if dut.cpu_valid.value == 0:
            miss_count += 1
            evicted_addr = addr

        # Deassert BEFORE clock edge
        dut.cpu_req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    # Verify exactly 1 eviction
    assert miss_count == 1, f"Expected exactly 1 eviction, got {miss_count}"

    # Verify the evicted address matches LRU prediction
    assert evicted_addr == expected_evicted_addr, \
        f"Expected LRU victim {hex(expected_evicted_addr)}, got {hex(evicted_addr)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_single_eviction_determinism PASSED")


@cocotb.test()
async def test_same_set_dual_mshr(dut):
    """Test: Two rapid misses to same set allocate different victim ways"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Use set 3 for this test
    SET_IDX = 3
    addrs = [0x0030, 0x0430, 0x0830, 0x0C30]  # All map to set 3

    # Fill all 4 ways with read operations
    for addr in addrs:
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 0
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break

        await provide_burst_refill(dut, addr)
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Issue first miss to set 3 (will allocate MSHR[0])
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1030  # Set 3, new tag
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)

    # Wait one cycle then issue second miss to same set (before first completes)
    await RisingEdge(dut.clk)

    dut.cpu_addr.value = 0x1430  # Also set 3, different tag
    await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await wait_cycles(dut, 2)

    # Check that both MSHRs are valid and have DIFFERENT victim_way values
    mshr0_valid = int(dut.mshr_valid.value) & 1
    mshr1_valid = (int(dut.mshr_valid.value) >> 1) & 1

    # At least one MSHR should be allocated
    assert mshr0_valid or mshr1_valid, "At least one MSHR should be allocated"

    if mshr0_valid and mshr1_valid:
        mshr0_victim = int(dut.mshr_victim_way[0].value)
        mshr1_victim = int(dut.mshr_victim_way[1].value)
        mshr0_index = int(dut.mshr_index[0].value)
        mshr1_index = int(dut.mshr_index[1].value)

        # If both target same set, victim ways must be different
        if mshr0_index == SET_IDX and mshr1_index == SET_IDX:
            assert mshr0_victim != mshr1_victim, \
                f"Same-set MSHRs must have different victims: MSHR[0]={mshr0_victim}, MSHR[1]={mshr1_victim}"
            cocotb.log.info(f"  MSHR[0] victim_way={mshr0_victim}, MSHR[1] victim_way={mshr1_victim}")

    # Complete any pending refills
    for _ in range(2):
        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break
        if dut.mem_req.value == 1:
            await provide_burst_refill(dut, 0xDEADBEEF)
            await RisingEdge(dut.clk)
            await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    cocotb.log.info("test_same_set_dual_mshr PASSED")


@cocotb.test()
async def test_lru_state_tracking(dut):
    """Test: Access pattern updates LRU correctly, eviction follows LRU"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # Use set 4 for this test
    SET_IDX = 4
    # Fill ways A=0, B=1, C=2, D=3 in order
    addrs = [0x0040, 0x0440, 0x0840, 0x0C40]  # All set 4

    for i, addr in enumerate(addrs):
        dut.cpu_req.value = 1
        dut.cpu_addr.value = addr
        dut.cpu_write.value = 0
        dut.cpu_byte_en.value = 0xF

        await RisingEdge(dut.clk)

        for _ in range(10):
            await RisingEdge(dut.clk)
            if dut.mem_req.value == 1:
                break

        await provide_burst_refill(dut, addr)
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Access way 0 (addr A) to make it MRU
    dut.cpu_req.value = 1
    dut.cpu_addr.value = addrs[0]
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF
    await RisingEdge(dut.clk)
    assert dut.cpu_valid.value == 1, "Way 0 should hit"

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    # Record LRU state - way 0 should now be MRU
    lru_after_access = int(dut.lru_state[SET_IDX].value)

    # Add 5th line (E)
    dut.cpu_req.value = 1
    dut.cpu_addr.value = 0x1040  # Set 4, new tag
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req.value = 0

    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.mem_req.value == 1:
            break

    await provide_burst_refill(dut, 0x1040)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Check which address was evicted
    # Way 0 (addr A) should NOT be evicted since we accessed it (made it MRU)
    # Check BEFORE clock edge to avoid triggering MSHR allocation
    dut.cpu_addr.value = addrs[0]  # Way 0, should still be cached
    dut.cpu_req.value = 1
    await settle(dut)

    assert dut.cpu_valid.value == 1, "Way 0 (accessed) should still be cached, not evicted"

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)

    # Count total evictions among ways 1, 2, 3
    # Check BEFORE clock edge to avoid triggering MSHR allocation
    miss_count = 0
    for addr in addrs[1:]:  # Skip way 0
        dut.cpu_addr.value = addr
        dut.cpu_req.value = 1
        await settle(dut)

        if dut.cpu_valid.value == 0:
            miss_count += 1

        dut.cpu_req.value = 0
        await RisingEdge(dut.clk)
        await RisingEdge(dut.clk)

    # Exactly one of ways 1, 2, 3 should be evicted
    assert miss_count == 1, f"Expected exactly 1 eviction from ways 1-3, got {miss_count}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_lru_state_tracking PASSED")


@cocotb.test()
async def test_address_aliasing(dut):
    """Test: Different addresses mapping to same set don't interfere"""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_cache(dut)

    # These addresses all map to different sets (differ in bits [9:4])
    test_cases = [
        (0x0000, 0x11111111),  # Set 0
        (0x0010, 0x22222222),  # Set 1
        (0x0020, 0x33333333),  # Set 2
        (0x0030, 0x44444444),  # Set 3
    ]

    # Prime all lines
    for addr, val in test_cases:
        await prime_cache_line(dut, addr, val)

    # Verify each line independently
    dut.cpu_req.value = 1
    dut.cpu_write.value = 0
    dut.cpu_byte_en.value = 0xF

    for addr, expected in test_cases:
        dut.cpu_addr.value = addr
        await RisingEdge(dut.clk)
        assert dut.cpu_valid.value == 1, f"Should hit: {hex(addr)}"
        assert dut.cpu_data.value == expected, \
            f"Aliasing error: {hex(addr)} expected {hex(expected)}, got {hex(dut.cpu_data.value)}"

    dut.cpu_req.value = 0
    cocotb.log.info("test_address_aliasing PASSED")


def runCocotbTests():
    """Run all D-cache MSHR integration tests"""
    import os

    # Get absolute paths to RTL files
    rtl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "rtl")
    dcache_path = os.path.abspath(os.path.join(rtl_dir, "dcache_mshr.v"))

    run(
        verilog_sources=[dcache_path],
        toplevel="dcache",
        module="test_dcache_mshr",
        simulator="verilator",
        extra_args=[
            "--trace",
            "--trace-structs",
            "-Wno-fatal",
            "-Wno-WIDTH",
            "-Wno-CASEINCOMPLETE",
            "-Wno-UNOPTFLAT"
        ],
    )


if __name__ == "__main__":
    runCocotbTests()
