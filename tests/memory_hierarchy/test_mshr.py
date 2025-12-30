"""
MSHR (Miss Status Holding Register) Unit Tests

Tests the MSHR module's ability to:
- Allocate MSHRs for cache misses
- Match requests to existing MSHRs (coalescing)
- Track word masks for partial line requests
- Retire MSHRs when refill completes
- Handle MSHR full conditions
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_test.simulator import run
from cocotb.runner import get_runner
import os


def get_mshr_addr(dut, mshr_id):
    """Extract address for a specific MSHR from flattened array"""
    addr_width = 32
    start_bit = mshr_id * addr_width
    addr_flat = int(dut.mshr_addr_flat.value)
    addr = (addr_flat >> start_bit) & ((1 << addr_width) - 1)
    return addr


def get_mshr_word_mask(dut, mshr_id):
    """Extract word mask for a specific MSHR from flattened array"""
    words_per_line = 16
    start_bit = mshr_id * words_per_line
    mask_flat = int(dut.mshr_word_mask_flat.value)
    mask = (mask_flat >> start_bit) & ((1 << words_per_line) - 1)
    return mask


async def reset_mshr(dut):
    """Reset the MSHR"""
    dut.rst.value = 1
    dut.alloc_req.value = 0
    dut.match_req.value = 0
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_basic_allocation(dut):
    """Test: Allocate a single MSHR"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Initially should be ready (no MSHRs allocated)
    assert dut.alloc_ready.value == 1, "MSHR should be ready initially"
    assert dut.mshr_full.value == 0, "MSHR should not be full initially"

    # Allocate MSHR for address 0x1000, word 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0

    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)

    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR was allocated
    assert dut.mshr_valid.value & (1 << alloc_id), f"MSHR {alloc_id} should be valid"

    # Verify address stored correctly (line address, word offset removed)
    expected_line_addr = 0x1000 & ~0x3F  # Remove lower 6 bits (word offset + byte offset)
    stored_addr = get_mshr_addr(dut, alloc_id)
    assert stored_addr == expected_line_addr, f"MSHR addr mismatch: got {hex(stored_addr)}, expected {hex(expected_line_addr)}"

    # Verify word mask has bit 0 set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0001, f"Word mask should be 0x0001, got {hex(word_mask)}"

    cocotb.log.info("✓ Basic allocation test PASSED")


@cocotb.test()
async def test_multiple_allocations(dut):
    """Test: Allocate multiple MSHRs"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    allocated_ids = []

    # Allocate 4 MSHRs with different addresses
    addresses = [0x1000, 0x2000, 0x3000, 0x4000]

    for i, addr in enumerate(addresses):
        assert dut.alloc_ready.value == 1, f"MSHR should be ready for allocation {i}"

        dut.alloc_req.value = 1
        dut.alloc_addr.value = addr
        dut.alloc_word_offset.value = i % 16  # Different word offsets

        await RisingEdge(dut.clk)
        alloc_id = int(dut.alloc_id.value)
        allocated_ids.append(alloc_id)

        dut.alloc_req.value = 0
        await RisingEdge(dut.clk)

    # Verify all 4 MSHRs are valid
    valid_bits = int(dut.mshr_valid.value)
    for mshr_id in allocated_ids:
        assert valid_bits & (1 << mshr_id), f"MSHR {mshr_id} should be valid"

    # Verify we still have MSHRs available (8 total, used 4)
    assert dut.alloc_ready.value == 1, "Should still have MSHRs available"
    assert dut.mshr_full.value == 0, "Should not be full (only 4/8 used)"

    cocotb.log.info(f"✓ Allocated {len(allocated_ids)} MSHRs: {allocated_ids}")
    cocotb.log.info("✓ Multiple allocations test PASSED")


@cocotb.test()
async def test_mshr_full(dut):
    """Test: Fill all MSHRs and verify full condition"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate all 8 MSHRs
    for i in range(8):
        assert dut.alloc_ready.value == 1, f"Should be ready for MSHR {i}"

        dut.alloc_req.value = 1
        dut.alloc_addr.value = 0x1000 * (i + 1)  # Different addresses
        dut.alloc_word_offset.value = 0

        await RisingEdge(dut.clk)
        dut.alloc_req.value = 0
        await RisingEdge(dut.clk)

    # Verify all MSHRs are valid
    assert dut.mshr_valid.value == 0xFF, "All 8 MSHRs should be valid"
    assert dut.mshr_full.value == 1, "MSHR should be full"
    assert dut.alloc_ready.value == 0, "Should not be ready when full"

    cocotb.log.info("✓ MSHR full test PASSED")


@cocotb.test()
async def test_cam_matching(dut):
    """Test: CAM matching for coalescing"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for address 0x1000, word 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0

    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Match request to same cache line (different word offset)
    dut.match_req.value = 1
    dut.match_addr.value = 0x1004  # Same line, word 1
    dut.match_word_offset.value = 1

    await RisingEdge(dut.clk)

    # Verify match
    assert dut.match_hit.value == 1, "Should match existing MSHR"
    assert int(dut.match_id.value) == alloc_id, f"Match ID should be {alloc_id}"

    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # Try matching different cache line (should not match)
    dut.match_req.value = 1
    dut.match_addr.value = 0x2000  # Different line
    dut.match_word_offset.value = 0

    await RisingEdge(dut.clk)

    assert dut.match_hit.value == 0, "Should not match different cache line"

    cocotb.log.info("✓ CAM matching test PASSED")


@cocotb.test()
async def test_request_coalescing(dut):
    """Test: Multiple requests to same line coalesce into one MSHR"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for address 0x1000, word 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0

    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Initial word mask should be 0x0001 (word 0)
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0001, f"Initial word mask should be 0x0001, got {hex(word_mask)}"

    # Coalesce request for word 1
    dut.match_req.value = 1
    dut.match_addr.value = 0x1004  # Same line, word 1
    dut.match_word_offset.value = 1

    await RisingEdge(dut.clk)
    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # Word mask should now have bits 0 and 1 set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0003, f"Word mask should be 0x0003, got {hex(word_mask)}"

    # Coalesce request for word 5
    dut.match_req.value = 1
    dut.match_addr.value = 0x1014  # Same line, word 5
    dut.match_word_offset.value = 5

    await RisingEdge(dut.clk)
    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # Word mask should have bits 0, 1, and 5 set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0023, f"Word mask should be 0x0023, got {hex(word_mask)}"

    # Verify only ONE MSHR is allocated (coalescing worked)
    valid_count = bin(int(dut.mshr_valid.value)).count('1')
    assert valid_count == 1, f"Should have only 1 MSHR allocated, got {valid_count}"

    cocotb.log.info("✓ Request coalescing test PASSED")


@cocotb.test()
async def test_retirement(dut):
    """Test: Retire MSHR and verify it becomes free"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0

    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR is valid
    assert dut.mshr_valid.value & (1 << alloc_id), "MSHR should be valid"

    # Retire MSHR
    dut.retire_req.value = 1
    dut.retire_id.value = alloc_id

    await RisingEdge(dut.clk)
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR is no longer valid
    assert not (dut.mshr_valid.value & (1 << alloc_id)), "MSHR should be invalid after retirement"

    # Verify word mask is cleared
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0, f"Word mask should be 0 after retirement, got {hex(word_mask)}"

    cocotb.log.info("✓ Retirement test PASSED")


@cocotb.test()
async def test_allocation_after_retirement(dut):
    """Test: Allocate MSHR after retiring one"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate 3 MSHRs
    allocated_ids = []
    for i in range(3):
        dut.alloc_req.value = 1
        dut.alloc_addr.value = 0x1000 * (i + 1)
        dut.alloc_word_offset.value = 0

        await RisingEdge(dut.clk)
        allocated_ids.append(int(dut.alloc_id.value))
        dut.alloc_req.value = 0
        await RisingEdge(dut.clk)

    cocotb.log.info(f"Allocated MSHRs: {allocated_ids}")

    # Retire middle MSHR
    retire_id = allocated_ids[1]
    dut.retire_req.value = 1
    dut.retire_id.value = retire_id

    await RisingEdge(dut.clk)
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)

    # Allocate new MSHR - should reuse retired slot
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x5000
    dut.alloc_word_offset.value = 3

    await RisingEdge(dut.clk)
    new_alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    cocotb.log.info(f"New allocation reused MSHR {new_alloc_id}")

    # Verify we still have 3 MSHRs allocated
    valid_count = bin(int(dut.mshr_valid.value)).count('1')
    assert valid_count == 3, f"Should have 3 MSHRs allocated, got {valid_count}"

    # Verify new MSHR has correct address
    stored_addr = get_mshr_addr(dut, new_alloc_id)
    expected_addr = 0x5000 & ~0x3F
    assert stored_addr == expected_addr, f"Address mismatch: got {hex(stored_addr)}, expected {hex(expected_addr)}"

    # Verify word mask
    word_mask = get_mshr_word_mask(dut, new_alloc_id)
    assert word_mask == 0x0008, f"Word mask should be 0x0008 (bit 3), got {hex(word_mask)}"

    cocotb.log.info("✓ Allocation after retirement test PASSED")


@cocotb.test()
async def test_word_mask_all_words(dut):
    """Test: Word mask with all 16 words requested"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for word 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0

    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Coalesce requests for all other words (1-15)
    for word_idx in range(1, 16):
        dut.match_req.value = 1
        dut.match_addr.value = 0x1000 + (word_idx * 4)
        dut.match_word_offset.value = word_idx

        await RisingEdge(dut.clk)
        dut.match_req.value = 0
        await RisingEdge(dut.clk)

    # Word mask should have all 16 bits set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0xFFFF, f"Word mask should be 0xFFFF, got {hex(word_mask)}"

    cocotb.log.info("✓ Word mask all words test PASSED")


@cocotb.test()
async def test_priority_encoder_first_match(dut):
    """Test: Priority encoder returns FIRST match, not last"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHRs at different addresses
    # We'll allocate MSHR 2 and MSHR 5 to the SAME cache line
    # (This shouldn't happen in practice, but tests priority encoder determinism)

    # Allocate MSHR 0 for address 0x1000
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    mshr_0_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Allocate MSHR 1 for address 0x2000
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x2000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    mshr_1_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Now allocate MSHR 2 and MSHR 5 to SAME line (0x1000)
    # This creates multiple matches for priority encoder test
    # First, allocate MSHR 2
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1004  # Same line as MSHR 0 (0x1000)
    dut.alloc_word_offset.value = 1
    await RisingEdge(dut.clk)
    mshr_2_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Wait a cycle, then check match
    # Match request for same line should match MSHR 0 (first allocated, lowest ID)
    dut.match_req.value = 1
    dut.match_addr.value = 0x1008  # Same line
    dut.match_word_offset.value = 2
    await RisingEdge(dut.clk)

    # Should match MSHR 0 (first match, lowest ID)
    assert dut.match_hit.value == 1, "Should match existing MSHR"
    match_id = int(dut.match_id.value)
    assert match_id == mshr_0_id, f"Should match MSHR {mshr_0_id} (first), got {match_id}"

    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    cocotb.log.info(f"✓ Priority encoder returned first match (MSHR {match_id})")
    cocotb.log.info("✓ Priority encoder first match test PASSED")


@cocotb.test()
async def test_simultaneous_retire_match(dut):
    """Test: Simultaneous retire + match on same MSHR"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for address 0x1000
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Verify initial word mask
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0001, f"Initial word mask should be 0x0001, got {hex(word_mask)}"

    # Simultaneously retire and match same MSHR
    # This tests the race condition fix
    dut.retire_req.value = 1
    dut.retire_id.value = alloc_id
    dut.match_req.value = 1
    dut.match_addr.value = 0x1004  # Same line, word 1
    dut.match_word_offset.value = 1

    await RisingEdge(dut.clk)

    dut.retire_req.value = 0
    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # After retirement, MSHR should be invalid
    assert not (dut.mshr_valid.value & (1 << alloc_id)), "MSHR should be invalid after retirement"

    # Word mask should be cleared (retire wins)
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0, f"Word mask should be 0 after retire (retire wins), got {hex(word_mask)}"

    cocotb.log.info("✓ Simultaneous retire + match test PASSED")


@cocotb.test()
async def test_retire_immediate_reuse(dut):
    """Test: Retire and allocate same MSHR in same cycle (immediate reuse)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id_0 = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Retire MSHR 0 and allocate new MSHR (should reuse same slot)
    dut.retire_req.value = 1
    dut.retire_id.value = alloc_id_0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x2000  # New address
    dut.alloc_word_offset.value = 2
    await RisingEdge(dut.clk)

    new_alloc_id = int(dut.alloc_id.value)
    dut.retire_req.value = 0
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # MSHR should be valid (alloc wins)
    assert dut.mshr_valid.value & (1 << new_alloc_id), "MSHR should be valid after alloc"

    # Should have new address
    stored_addr = get_mshr_addr(dut, new_alloc_id)
    expected_addr = 0x2000 & ~0x3F
    assert stored_addr == expected_addr, f"Address should be {hex(expected_addr)}, got {hex(stored_addr)}"

    # Should have new word mask
    word_mask = get_mshr_word_mask(dut, new_alloc_id)
    assert word_mask == 0x0004, f"Word mask should be 0x0004 (bit 2), got {hex(word_mask)}"

    cocotb.log.info("✓ Retire immediate reuse test PASSED")


@cocotb.test()
async def test_retire_invalid_mshr(dut):
    """Test: Retire invalid MSHR (should be idempotent)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Try to retire MSHR 0 (which is invalid)
    dut.retire_req.value = 1
    dut.retire_id.value = 0
    await RisingEdge(dut.clk)
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)

    # MSHR 0 should still be invalid (idempotent)
    assert not (dut.mshr_valid.value & (1 << 0)), "MSHR 0 should remain invalid"

    # Word mask should be 0
    word_mask = get_mshr_word_mask(dut, 0)
    assert word_mask == 0, f"Word mask should be 0, got {hex(word_mask)}"

    # Now allocate MSHR 0
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Should work normally
    assert dut.mshr_valid.value & (1 << alloc_id), "MSHR should be valid after allocation"

    cocotb.log.info("✓ Retire invalid MSHR test PASSED")


@cocotb.test()
async def test_allocate_when_full(dut):
    """Test: Attempt to allocate when MSHR is full (should be ignored)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Fill all 8 MSHRs and track which address goes to which MSHR
    mshr_addresses = {}  # Map MSHR ID -> address
    for i in range(8):
        dut.alloc_req.value = 1
        dut.alloc_addr.value = 0x1000 * (i + 1)
        dut.alloc_word_offset.value = 0
        await RisingEdge(dut.clk)
        alloc_id = int(dut.alloc_id.value)
        mshr_addresses[alloc_id] = 0x1000 * (i + 1)
        dut.alloc_req.value = 0
        await RisingEdge(dut.clk)

    # Verify full
    assert dut.mshr_full.value == 1, "MSHR should be full"
    assert dut.alloc_ready.value == 0, "Should not be ready when full"
    assert dut.mshr_valid.value == 0xFF, "All 8 MSHRs should be valid"

    # Try to allocate when full (ignoring alloc_ready)
    # This simulates a buggy caller
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x9000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Should still be full (allocation ignored due to alloc_ready=0)
    assert dut.mshr_full.value == 1, "MSHR should still be full"
    assert dut.mshr_valid.value == 0xFF, "All 8 MSHRs should still be valid"

    # Verify no MSHR was corrupted (all addresses should remain unchanged)
    for mshr_id, expected_addr in mshr_addresses.items():
        stored_addr = get_mshr_addr(dut, mshr_id)
        expected_line_addr = expected_addr & ~0x3F
        assert stored_addr == expected_line_addr, \
            f"MSHR {mshr_id} should still have address {hex(expected_line_addr)}, got {hex(stored_addr)}"

    cocotb.log.info("✓ Allocate when full test PASSED")


@cocotb.test()
async def test_reset_during_operation(dut):
    """Test: Reset while MSHRs are active (should clear all state)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate 3 MSHRs with different addresses
    allocated_ids = []
    for i in range(3):
        dut.alloc_req.value = 1
        dut.alloc_addr.value = 0x1000 * (i + 1)
        dut.alloc_word_offset.value = i
        await RisingEdge(dut.clk)
        allocated_ids.append(int(dut.alloc_id.value))
        dut.alloc_req.value = 0
        await RisingEdge(dut.clk)

    # Verify MSHRs are valid
    valid_bits = int(dut.mshr_valid.value)
    assert valid_bits != 0, "Should have MSHRs allocated"
    for mshr_id in allocated_ids:
        assert valid_bits & (1 << mshr_id), f"MSHR {mshr_id} should be valid"

    # Reset during operation
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Verify all MSHRs are cleared
    assert dut.mshr_valid.value == 0, "All MSHRs should be invalid after reset"
    assert dut.mshr_full.value == 0, "MSHR should not be full after reset"
    assert dut.alloc_ready.value == 1, "MSHR should be ready after reset"

    # Verify word masks are cleared
    for mshr_id in allocated_ids:
        word_mask = get_mshr_word_mask(dut, mshr_id)
        assert word_mask == 0, f"MSHR {mshr_id} word mask should be 0 after reset"

    cocotb.log.info("✓ Reset during operation test PASSED")


@cocotb.test()
async def test_concurrent_alloc_match(dut):
    """Test: Concurrent alloc + match in same cycle (different addresses)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for address 0x1000
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id_0 = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Simultaneously allocate new MSHR and match existing one
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x2000  # New address
    dut.alloc_word_offset.value = 1
    dut.match_req.value = 1
    dut.match_addr.value = 0x1004  # Match existing MSHR (same line, word 1)
    dut.match_word_offset.value = 1
    await RisingEdge(dut.clk)

    new_alloc_id = int(dut.alloc_id.value)
    match_hit = dut.match_hit.value
    match_id = int(dut.match_id.value) if match_hit else None

    dut.alloc_req.value = 0
    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # Verify both operations succeeded
    assert dut.mshr_valid.value & (1 << new_alloc_id), "New MSHR should be allocated"
    assert match_hit == 1, "Match should succeed"
    assert match_id == alloc_id_0, f"Match should return MSHR {alloc_id_0}"

    # Verify word mask for matched MSHR was updated
    word_mask = get_mshr_word_mask(dut, alloc_id_0)
    assert word_mask == 0x0003, f"Word mask should be 0x0003 (bits 0 and 1), got {hex(word_mask)}"

    # Verify new MSHR has correct address
    stored_addr = get_mshr_addr(dut, new_alloc_id)
    expected_addr = 0x2000 & ~0x3F
    assert stored_addr == expected_addr, f"New MSHR address mismatch: got {hex(stored_addr)}, expected {hex(expected_addr)}"

    cocotb.log.info("✓ Concurrent alloc + match test PASSED")


@cocotb.test()
async def test_word_offset_boundaries(dut):
    """Test: Word offset boundary cases (word 0, word 15)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR for word 0 (first word in line)
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000  # Word 0
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Verify word mask has bit 0 set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x0001, f"Word mask should be 0x0001 (bit 0), got {hex(word_mask)}"

    # Coalesce request for word 15 (last word in line)
    dut.match_req.value = 1
    dut.match_addr.value = 0x103C  # Word 15 (0x1000 + 15*4 = 0x103C)
    dut.match_word_offset.value = 15
    await RisingEdge(dut.clk)
    dut.match_req.value = 0
    await RisingEdge(dut.clk)

    # Word mask should have bits 0 and 15 set
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0x8001, f"Word mask should be 0x8001 (bits 0 and 15), got {hex(word_mask)}"

    # Verify address extraction works correctly for boundary words
    stored_addr = get_mshr_addr(dut, alloc_id)
    expected_addr = 0x1000 & ~0x3F  # Line address (remove word/byte offset)
    assert stored_addr == expected_addr, f"Address mismatch: got {hex(stored_addr)}, expected {hex(expected_addr)}"

    cocotb.log.info("✓ Word offset boundaries test PASSED")


@cocotb.test()
async def test_retire_twice_idempotent(dut):
    """Test: Retiring same MSHR twice (should be idempotent)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_mshr(dut)

    # Allocate MSHR
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x1000
    dut.alloc_word_offset.value = 0
    await RisingEdge(dut.clk)
    alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR is valid
    assert dut.mshr_valid.value & (1 << alloc_id), "MSHR should be valid"

    # Retire MSHR first time
    dut.retire_req.value = 1
    dut.retire_id.value = alloc_id
    await RisingEdge(dut.clk)
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR is invalid
    assert not (dut.mshr_valid.value & (1 << alloc_id)), "MSHR should be invalid after first retire"

    # Retire same MSHR again (should be idempotent)
    dut.retire_req.value = 1
    dut.retire_id.value = alloc_id
    await RisingEdge(dut.clk)
    dut.retire_req.value = 0
    await RisingEdge(dut.clk)

    # Verify MSHR is still invalid (idempotent)
    assert not (dut.mshr_valid.value & (1 << alloc_id)), "MSHR should remain invalid after second retire"

    # Word mask should still be 0
    word_mask = get_mshr_word_mask(dut, alloc_id)
    assert word_mask == 0, f"Word mask should be 0, got {hex(word_mask)}"

    # Should be able to allocate this MSHR again
    dut.alloc_req.value = 1
    dut.alloc_addr.value = 0x2000
    dut.alloc_word_offset.value = 2
    await RisingEdge(dut.clk)
    new_alloc_id = int(dut.alloc_id.value)
    dut.alloc_req.value = 0
    await RisingEdge(dut.clk)

    # Should be able to reuse (may or may not be same ID, but should work)
    assert dut.mshr_valid.value & (1 << new_alloc_id), "Should be able to allocate after double retire"

    cocotb.log.info("✓ Retire twice idempotent test PASSED")


def runCocotbTests():
    """Run all MSHR tests"""
    import os

    # Get absolute path to RTL file
    rtl_dir = os.path.join(os.path.dirname(__file__), "..", "..", "rtl")
    mshr_path = os.path.abspath(os.path.join(rtl_dir, "mshr.v"))

    runner = get_runner("verilator")
    runner.build(
        verilog_sources=[mshr_path],
        hdl_toplevel="mshr",
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
        hdl_toplevel="mshr",
        test_module="test_mshr",
    )


if __name__ == "__main__":
    runCocotbTests()
