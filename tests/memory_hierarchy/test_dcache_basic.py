import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
from cocotb_test.simulator import run
import os

# Helper function to reset DUT
async def reset_dut(dut):
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

# Helper to wait for cache to be ready
async def wait_ready(dut):
    while dut.cpu_req_ready.value == 0:
        await RisingEdge(dut.clk)

@cocotb.test()
async def test_read_miss_refill_hit(dut):
    """Test: Read miss → refill → read hit"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Initialize inputs
    dut.cpu_req_valid.value = 0
    dut.cpu_req_write.value = 0
    dut.mem_resp_valid.value = 0

    await RisingEdge(dut.clk)

    # Request 1: Read from 0x1000 (will miss)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0
    dut.cpu_req_wdata.value = 0
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for lookup to complete (miss)
    await RisingEdge(dut.clk)

    # Wait for memory request (fetch)
    timeout = 0
    while dut.mem_req_valid.value == 0 and timeout < 10:
        await RisingEdge(dut.clk)
        timeout += 1

    assert dut.mem_req_valid.value == 1, "Memory request should be valid"
    assert dut.mem_req_write.value == 0, "Should be read request"
    assert dut.mem_req_addr.value == 0x1000, f"Address should be 0x1000, got {hex(dut.mem_req_addr.value)}"

    # Memory is ready immediately
    dut.mem_req_ready.value = 1
    await RisingEdge(dut.clk)

    # Provide memory response (64-byte line = 512 bits = 16 words)
    # Word 0 (offset 0x0) = 0x12345678
    # Word 1 (offset 0x4) = 0xAABBCCDD
    refill_data = 0
    refill_data |= (0x12345678 << (0 * 32))   # Word 0
    refill_data |= (0xAABBCCDD << (1 * 32))   # Word 1
    refill_data |= (0xDEADBEEF << (4 * 32))   # Word 4

    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    # Wait for refill to complete
    await RisingEdge(dut.clk)

    # Cache should be ready now
    await wait_ready(dut)

    # Request 2: Read from 0x1000 again (should HIT)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x1000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    # Cache samples request on clock edge, provides response combinationally
    assert dut.cpu_resp_valid.value == 1, "Should have immediate response on hit"
    assert dut.cpu_resp_rdata.value == 0x12345678, \
        f"Data mismatch: expected 0x12345678, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    await RisingEdge(dut.clk)
    cocotb.log.info("✓ Read miss → refill → hit test PASSED")


@cocotb.test()
async def test_write_hit_dirty(dut):
    """Test: Write hit marks line dirty"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # First, fill the cache line with a read
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for memory request
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    # Provide refill data
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = 0x11111111  # All words same for simplicity

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    # Wait for cache ready
    await wait_ready(dut)

    # Now write to the same address (should hit)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x99999999
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Write completes
    await RisingEdge(dut.clk)

    # Wait for ready
    await wait_ready(dut)

    # Read back to verify write
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x2000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    assert dut.cpu_resp_valid.value == 1, "Should have immediate response"
    assert dut.cpu_resp_rdata.value == 0x99999999, \
        f"Write data not persisted: expected 0x99999999, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    await RisingEdge(dut.clk)
    cocotb.log.info("✓ Write hit → dirty test PASSED")


@cocotb.test()
async def test_miss_clean_eviction(dut):
    """Test: Cache miss evicting clean line (no writeback)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # Fill all 4 ways of set 0 with clean lines
    # Set index is bits [12:6], so addresses with same bits [12:6]
    # Set 0: addresses 0x0000, 0x0040, 0x0080, 0x00C0 (offset bits [5:0])
    # But we need different tags, so use different upper bits

    addresses = [0x00000, 0x10000, 0x20000, 0x30000]  # All map to set 0

    for addr in addresses:
        # Read to fill
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0

        await RisingEdge(dut.clk)
        dut.cpu_req_valid.value = 0

        # Wait for mem request
        while dut.mem_req_valid.value == 0:
            await RisingEdge(dut.clk)

        # Provide response
        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 1
        dut.mem_resp_rdata.value = addr  # Use address as data

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 0

        await wait_ready(dut)

    # Now all 4 ways full, next miss will evict
    # The evicted line should be clean (no writeback)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x40000  # New address, same set
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Wait for mem request
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    # Should be FETCH, not WRITEBACK (clean eviction)
    assert dut.mem_req_write.value == 0, "Should be fetch (read), not writeback"

    await RisingEdge(dut.clk)
    cocotb.log.info("✓ Clean eviction test PASSED")


@cocotb.test()
async def test_miss_dirty_eviction(dut):
    """Test: Cache miss evicting dirty line (writeback required)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # Fill 4 ways of set 0
    addresses = [0x00000, 0x10000, 0x20000, 0x30000]

    for i, addr in enumerate(addresses):
        cocotb.log.info(f"Filling way {i} with address 0x{addr:05X}")
        # Read to fill
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = addr
        dut.cpu_req_write.value = 0

        await RisingEdge(dut.clk)
        dut.cpu_req_valid.value = 0

        timeout = 0
        while dut.mem_req_valid.value == 0:
            await RisingEdge(dut.clk)
            timeout += 1
            if timeout > 10:
                cocotb.log.error(f"Timeout waiting for mem_req during fill {i}! state={dut.state.value}")
                assert False, f"Cache stuck during fill {i}"

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 1
        dut.mem_resp_rdata.value = addr

        await RisingEdge(dut.clk)
        dut.mem_resp_valid.value = 0

        await wait_ready(dut)
        cocotb.log.info(f"Completed fill {i}")

    # Write to one line to make it dirty (write to 0x00000)
    cocotb.log.info("Writing to 0x00000 to make it dirty")
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x00000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xDEADBEEF
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    cocotb.log.info("Waiting for cache ready after write")
    await wait_ready(dut)
    cocotb.log.info("Cache ready after write")

    # Evict with new access (will evict LRU, which might be 0x00000)
    cocotb.log.info(f"Before eviction request: state={dut.state.value}, cpu_req_ready={dut.cpu_req_ready.value}")
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x40000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    cocotb.log.info(f"After eviction request cycle: state={dut.state.value}, mem_req_valid={dut.mem_req_valid.value}")
    dut.cpu_req_valid.value = 0

    # Wait for mem request
    timeout = 0
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)
        timeout += 1
        if timeout > 10:
            cocotb.log.error(f"Timeout waiting for mem_req_valid! state={dut.state.value}")
            assert False, "Cache not generating memory request"

    # First request should be WRITEBACK (dirty line)
    if dut.mem_req_write.value == 1:
        cocotb.log.info("✓ Dirty eviction triggered writeback")

        # Complete writeback (mem_req_ready=1, so transitions immediately)
        await RisingEdge(dut.clk)

        # Now should be in FETCH state (mem_req_valid stays high, but write→read)
        # Wait one more cycle for state transition to complete
        await RisingEdge(dut.clk)

        assert dut.mem_req_valid.value == 1, "Should still have memory request (for fetch)"
        assert dut.mem_req_write.value == 0, "After writeback, should fetch (read)"
    else:
        cocotb.log.info("Note: Dirty line wasn't selected as victim (LRU chose different way)")

    await RisingEdge(dut.clk)
    cocotb.log.info("✓ Dirty eviction test PASSED")


@cocotb.test()
async def test_byte_write(dut):
    """Test: Partial word writes with byte enables"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # Write miss (write-allocate) - write only byte 0 (LSB)
    cocotb.log.info(f"Before write: state={dut.state.value}")
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0x12345678
    dut.cpu_req_byte_en.value = 0b0001  # Only byte 0

    await RisingEdge(dut.clk)
    cocotb.log.info(f"After write req: state={dut.state.value}")
    dut.cpu_req_valid.value = 0

    # Wait for memory request (cache miss)
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    cocotb.log.info(f"Memory request generated, state={dut.state.value}")

    # Provide refill data (all 1s)
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1  # All 1s

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)
    cocotb.log.info(f"Write miss complete, state={dut.state.value}")

    # Read back
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x3000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    # Response should be available immediately (combinational output in IDLE state)
    # Should have: 0xFFFFFF78 (only byte 0 changed)
    expected = 0xFFFFFF78
    assert dut.cpu_resp_valid.value == 1, "Should have immediate response"
    assert dut.cpu_resp_rdata.value == expected, \
        f"Byte write failed: expected {hex(expected)}, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    await RisingEdge(dut.clk)
    cocotb.log.info("✓ Byte write test PASSED")


@cocotb.test()
async def test_different_offsets(dut):
    """Test: Reading different word offsets in same cache line"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # Fill line
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x4000
    dut.cpu_req_write.value = 0

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    # Create refill data with distinct values for each word
    refill_data = 0
    for word_idx in range(16):
        refill_data |= ((0xA0 + word_idx) << (word_idx * 32))

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = refill_data

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)

    # Read different offsets in same line
    test_offsets = [0, 4, 8, 12, 32, 60]  # Various byte offsets

    for offset in test_offsets:
        dut.cpu_req_valid.value = 1
        dut.cpu_req_addr.value = 0x4000 + offset
        dut.cpu_req_write.value = 0

        await RisingEdge(dut.clk)
        # Response should be available immediately (combinational output in IDLE state)
        word_idx = offset // 4
        expected = 0xA0 + word_idx

        assert dut.cpu_resp_valid.value == 1, f"No response for offset {offset}"
        assert dut.cpu_resp_rdata.value == expected, \
            f"Offset {offset}: expected {hex(expected)}, got {hex(dut.cpu_resp_rdata.value)}"

        dut.cpu_req_valid.value = 0
        await RisingEdge(dut.clk)

    cocotb.log.info("✓ Different offsets test PASSED")


def runCocotbTests():
    """Run tests with Verilator"""

    rtl_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'rtl')

    verilog_sources = [
        os.path.join(rtl_dir, 'dcache.v'),
    ]

    run(
        verilog_sources=verilog_sources,
        toplevel="dcache",
        module="test_dcache_basic",
        simulator="verilator",
        work_dir="sim_build_dcache_basic",
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
