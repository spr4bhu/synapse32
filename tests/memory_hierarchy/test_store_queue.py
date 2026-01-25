"""
Store Queue Unit Tests

Tests the store queue module in isolation, verifying:
- Basic enqueue/dequeue operations
- Program-order retirement
- Store-to-load forwarding (CAM lookup)
- Full/empty status
- Circular buffer wraparound
- Byte masking for SB/SH stores
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
from cocotb.runner import get_runner
import sys
import os

# Add project root to path for accessing test utilities
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)


@cocotb.test()
async def test_basic_enqueue_dequeue(dut):
    """Test basic store enqueue and memory write"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Verify queue is empty
    assert dut.empty.value == 1, "Queue should be empty after reset"
    assert dut.full.value == 0, "Queue should not be full after reset"

    # Enqueue a store (SW to address 0x1000, data 0x12345678)
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x1000
    dut.enq_data.value = 0x12345678
    dut.enq_store_type.value = 0b010  # SW
    await RisingEdge(dut.clk)
    assert dut.enq_ready.value == 1, "Queue should be ready to accept store"
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Queue should no longer be empty
    assert dut.empty.value == 0, "Queue should not be empty after enqueue"

    # Memory write should become valid
    assert dut.mem_write_valid.value == 1, "Memory write should be valid"
    assert dut.mem_write_addr.value == 0x1000, f"Write address mismatch: got 0x{dut.mem_write_addr.value:x}"
    assert dut.mem_write_data.value == 0x12345678, f"Write data mismatch: got 0x{dut.mem_write_data.value:x}"
    assert dut.mem_write_byte_en.value == 0b1111, "Byte enable should be 0b1111 for SW"

    # Accept the write
    dut.mem_write_ready.value = 1
    await RisingEdge(dut.clk)
    dut.mem_write_ready.value = 0
    await RisingEdge(dut.clk)

    # Queue should be empty again
    assert dut.empty.value == 1, "Queue should be empty after dequeue"
    assert dut.mem_write_valid.value == 0, "Memory write should not be valid"


@cocotb.test()
async def test_program_order_retirement(dut):
    """Test that stores retire in program order (FIFO)"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Enqueue 3 stores with different addresses
    stores = [
        (0x1000, 0xAAAAAAAA, 0b010),  # SW
        (0x2000, 0xBBBBBBBB, 0b010),  # SW
        (0x3000, 0xCCCCCCCC, 0b010),  # SW
    ]

    for addr, data, store_type in stores:
        dut.enq_valid.value = 1
        dut.enq_addr.value = addr
        dut.enq_data.value = data
        dut.enq_store_type.value = store_type
        await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Retire stores in order
    for addr, data, _ in stores:
        assert dut.mem_write_valid.value == 1, "Memory write should be valid"
        assert dut.mem_write_addr.value == addr, f"Expected address 0x{addr:x}, got 0x{dut.mem_write_addr.value:x}"
        assert dut.mem_write_data.value == data, f"Expected data 0x{data:x}, got 0x{dut.mem_write_data.value:x}"

        # Accept the write
        dut.mem_write_ready.value = 1
        await RisingEdge(dut.clk)
        dut.mem_write_ready.value = 0
        await RisingEdge(dut.clk)

    # Queue should be empty
    assert dut.empty.value == 1, "Queue should be empty after all retirements"


@cocotb.test()
async def test_byte_masking(dut):
    """Test byte enable generation for SB, SH, SW"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Test SB (store byte)
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x1000
    dut.enq_data.value = 0x12345678
    dut.enq_store_type.value = 0b000  # SB
    await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    assert dut.mem_write_byte_en.value == 0b0001, "Byte enable should be 0b0001 for SB"
    assert dut.mem_write_data.value == 0x78, f"Data should be lower byte only, got 0x{dut.mem_write_data.value:x}"
    dut.mem_write_ready.value = 1
    await RisingEdge(dut.clk)
    dut.mem_write_ready.value = 0
    await RisingEdge(dut.clk)

    # Test SH (store halfword)
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x2000
    dut.enq_data.value = 0x12345678
    dut.enq_store_type.value = 0b001  # SH
    await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    assert dut.mem_write_byte_en.value == 0b0011, "Byte enable should be 0b0011 for SH"
    assert dut.mem_write_data.value == 0x5678, f"Data should be lower halfword only, got 0x{dut.mem_write_data.value:x}"
    dut.mem_write_ready.value = 1
    await RisingEdge(dut.clk)
    dut.mem_write_ready.value = 0
    await RisingEdge(dut.clk)

    # Test SW (store word)
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x3000
    dut.enq_data.value = 0x12345678
    dut.enq_store_type.value = 0b010  # SW
    await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    assert dut.mem_write_byte_en.value == 0b1111, "Byte enable should be 0b1111 for SW"
    assert dut.mem_write_data.value == 0x12345678, f"Data should be full word, got 0x{dut.mem_write_data.value:x}"
    dut.mem_write_ready.value = 1
    await RisingEdge(dut.clk)
    dut.mem_write_ready.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_store_to_load_forwarding(dut):
    """Test CAM lookup for store-to-load forwarding"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Enqueue a SW to address 0x1000
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x1000
    dut.enq_data.value = 0xDEADBEEF
    dut.enq_store_type.value = 0b010  # SW
    await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Lookup LW at same address - should forward
    dut.lookup_valid.value = 1
    dut.lookup_addr.value = 0x1000
    dut.lookup_load_type.value = 0b010  # LW
    await RisingEdge(dut.clk)
    assert dut.forward_match.value == 1, "Should match for LW at same address"
    assert dut.forward_data.value == 0xDEADBEEF, f"Forwarded data mismatch: got 0x{dut.forward_data.value:x}"

    # Lookup LW at different address - should not forward
    dut.lookup_addr.value = 0x2000
    await RisingEdge(dut.clk)
    assert dut.forward_match.value == 0, "Should not match for different address"

    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_forwarding_sign_extension(dut):
    """Test sign/zero extension for forwarded loads"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Enqueue SB with negative byte (0x80 = -128 signed)
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0x1000
    dut.enq_data.value = 0x00000080
    dut.enq_store_type.value = 0b000  # SB
    await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Lookup LB (sign-extend)
    dut.lookup_valid.value = 1
    dut.lookup_addr.value = 0x1000
    dut.lookup_load_type.value = 0b000  # LB
    await RisingEdge(dut.clk)
    assert dut.forward_match.value == 1, "Should match SB->LB"
    assert dut.forward_data.value == 0xFFFFFF80, f"Expected sign-extended 0xFFFFFF80, got 0x{dut.forward_data.value:x}"

    # Lookup LBU (zero-extend)
    dut.lookup_load_type.value = 0b100  # LBU
    await RisingEdge(dut.clk)
    assert dut.forward_match.value == 1, "Should match SB->LBU"
    assert dut.forward_data.value == 0x00000080, f"Expected zero-extended 0x00000080, got 0x{dut.forward_data.value:x}"

    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_full_empty_conditions(dut):
    """Test full/empty status signals"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Initially empty
    assert dut.empty.value == 1, "Queue should be empty"
    assert dut.full.value == 0, "Queue should not be full"

    # Fill the queue (8 entries)
    for i in range(8):
        dut.enq_valid.value = 1
        dut.enq_addr.value = 0x1000 + i*4
        dut.enq_data.value = 0xA0000000 + i
        dut.enq_store_type.value = 0b010  # SW
        await RisingEdge(dut.clk)

    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Should be full
    assert dut.full.value == 1, "Queue should be full"
    assert dut.empty.value == 0, "Queue should not be empty"
    assert dut.enq_ready.value == 0, "Queue should not be ready when full"

    # Drain the queue
    for i in range(8):
        assert dut.mem_write_valid.value == 1, f"Memory write should be valid for entry {i}"
        dut.mem_write_ready.value = 1
        await RisingEdge(dut.clk)
        dut.mem_write_ready.value = 0
        await RisingEdge(dut.clk)

    # Should be empty again
    assert dut.empty.value == 1, "Queue should be empty after draining"
    assert dut.full.value == 0, "Queue should not be full"


@cocotb.test()
async def test_wraparound(dut):
    """Test circular buffer wraparound behavior"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Fill and drain multiple times to exercise wraparound
    for cycle in range(3):
        # Fill queue
        for i in range(8):
            dut.enq_valid.value = 1
            dut.enq_addr.value = 0x1000 + cycle*0x100 + i*4
            dut.enq_data.value = 0xA0000000 + cycle*0x100 + i
            dut.enq_store_type.value = 0b010
            await RisingEdge(dut.clk)
        dut.enq_valid.value = 0
        await RisingEdge(dut.clk)

        # Drain queue
        for i in range(8):
            expected_addr = 0x1000 + cycle*0x100 + i*4
            assert dut.mem_write_addr.value == expected_addr, \
                f"Cycle {cycle}, entry {i}: expected 0x{expected_addr:x}, got 0x{dut.mem_write_addr.value:x}"
            dut.mem_write_ready.value = 1
            await RisingEdge(dut.clk)
            dut.mem_write_ready.value = 0
            await RisingEdge(dut.clk)

        assert dut.empty.value == 1, f"Queue should be empty after cycle {cycle}"


@cocotb.test()
async def test_youngest_match_priority(dut):
    """Test that CAM returns youngest matching store"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.mem_write_ready.value = 0
    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

    # Enqueue 3 SW to same address with different data
    stores = [0x11111111, 0x22222222, 0x33333333]
    for data in stores:
        dut.enq_valid.value = 1
        dut.enq_addr.value = 0x1000
        dut.enq_data.value = data
        dut.enq_store_type.value = 0b010  # SW
        await RisingEdge(dut.clk)
    dut.enq_valid.value = 0
    await RisingEdge(dut.clk)

    # Lookup should return youngest (most recent) store
    dut.lookup_valid.value = 1
    dut.lookup_addr.value = 0x1000
    dut.lookup_load_type.value = 0b010  # LW
    await RisingEdge(dut.clk)

    assert dut.forward_match.value == 1, "Should find matching store"
    assert dut.forward_data.value == 0x33333333, \
        f"Should forward youngest store (0x33333333), got 0x{dut.forward_data.value:x}"

    dut.lookup_valid.value = 0
    await RisingEdge(dut.clk)


def runCocotbTests():
    """Run cocotb tests for store queue"""

    # Get project root directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    rtl_dir = os.path.join(project_root, "rtl")
    include_dir = os.path.join(rtl_dir, "include")

    sim = os.getenv("SIM", "verilator")

    verilog_sources = [
        os.path.join(rtl_dir, "pipeline_stages", "store_queue.v"),
    ]

    runner = get_runner(sim)
    runner.build(
        verilog_sources=verilog_sources,
        hdl_toplevel="store_queue",
        includes=[include_dir],
        always=True,
        build_dir=os.path.join(project_root, "tests", "sim_build", "store_queue"),
        build_args=["--Wno-WIDTH", "--Wno-CASEINCOMPLETE", "--trace", "--trace-fst"]
    )

    runner.test(
        hdl_toplevel="store_queue",
        test_module="test_store_queue",
        test_args=["--trace", "--trace-fst"]
    )


if __name__ == "__main__":
    runCocotbTests()
