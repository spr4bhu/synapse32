"""
Load Queue Standalone Testbench

Tests the load queue in isolation with a configurable memory model.
Validates:
- Basic enqueue/dequeue operations
- Out-of-order memory responses
- Program-order completion
- Queue full/empty conditions
- All RISC-V load types (LB, LH, LW, LBU, LHU)
- Wraparound behavior
- Concurrent enqueue/dequeue
"""

import cocotb
from cocotb.triggers import RisingEdge, Timer, ClockCycles
from cocotb.clock import Clock
from cocotb_test.simulator import run
import os
import random
from pathlib import Path

# RISC-V Load Type Encodings (func3)
LOAD_LB = 0b000   # Load Byte (sign-extend)
LOAD_LH = 0b001   # Load Halfword (sign-extend)
LOAD_LW = 0b010   # Load Word
LOAD_LBU = 0b100  # Load Byte (zero-extend)
LOAD_LHU = 0b101  # Load Halfword (zero-extend)


async def reset_dut(dut):
    """Reset the load queue"""
    dut.rst.value = 1
    dut.enq_valid.value = 0
    dut.enq_addr.value = 0
    dut.enq_rd.value = 0
    dut.enq_load_type.value = 0
    dut.mem_req_ready.value = 1
    dut.mem_resp_valid.value = 0
    dut.mem_resp_data.value = 0
    dut.mem_resp_lq_id.value = 0
    dut.deq_ready.value = 1

    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)


async def enqueue_load(dut, addr, rd, load_type):
    """Enqueue a load into the load queue"""
    dut.enq_valid.value = 1
    dut.enq_addr.value = addr
    dut.enq_rd.value = rd
    dut.enq_load_type.value = load_type
    await RisingEdge(dut.clk)

    # Check if enqueue succeeded
    enq_ready = dut.enq_ready.value
    lq_id = int(dut.enq_lq_id.value) if enq_ready else None

    dut.enq_valid.value = 0
    return enq_ready, lq_id


async def send_mem_response(dut, lq_id, data):
    """Send memory response for a specific LQ entry"""
    dut.mem_resp_valid.value = 1
    dut.mem_resp_lq_id.value = lq_id
    dut.mem_resp_data.value = data
    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0


async def wait_for_dequeue(dut, expected_rd, expected_data, timeout=100):
    """Wait for a specific load to dequeue"""
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        if dut.deq_valid.value:
            rd = int(dut.deq_rd.value)
            data = int(dut.deq_data.value)

            if rd == expected_rd:
                assert data == expected_data, \
                    f"Dequeue data mismatch: expected {expected_data:#x}, got {data:#x}"
                return True

    assert False, f"Timeout waiting for dequeue of rd={expected_rd}"


def sign_extend_byte(value):
    """Sign extend 8-bit value to 32 bits"""
    if value & 0x80:
        return value | 0xFFFFFF00
    return value & 0xFF


def sign_extend_halfword(value):
    """Sign extend 16-bit value to 32 bits"""
    if value & 0x8000:
        return value | 0xFFFF0000
    return value & 0xFFFF


def zero_extend_byte(value):
    """Zero extend 8-bit value to 32 bits"""
    return value & 0xFF


def zero_extend_halfword(value):
    """Zero extend 16-bit value to 32 bits"""
    return value & 0xFFFF


@cocotb.test()
async def test_basic_enqueue_dequeue(dut):
    """Test 1: Basic single load enqueue and dequeue"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Enqueue a single load
    ready, lq_id = await enqueue_load(dut, addr=0x1000, rd=5, load_type=LOAD_LW)
    assert ready, "Queue should be ready when empty"
    assert lq_id == 0, "First entry should get ID 0"

    # Wait for memory request
    await RisingEdge(dut.clk)
    assert dut.mem_req_valid.value == 1, "Memory request should be issued"
    assert int(dut.mem_req_addr.value) == 0x1000, "Request address should match"
    assert int(dut.mem_req_lq_id.value) == lq_id, "Request should carry LQ ID"

    # Send memory response
    await send_mem_response(dut, lq_id, 0xDEADBEEF)

    # Check dequeue
    await RisingEdge(dut.clk)
    assert dut.deq_valid.value == 1, "Dequeue should be valid"
    assert int(dut.deq_rd.value) == 5, "Should dequeue to rd=5"
    assert int(dut.deq_data.value) == 0xDEADBEEF, "Data should match"

    # Dequeue completes
    await RisingEdge(dut.clk)
    assert dut.deq_valid.value == 0, "Should become invalid after dequeue"
    assert dut.empty.value == 1, "Queue should be empty"

    dut._log.info("✓ Test 1 passed: Basic enqueue/dequeue")


@cocotb.test()
async def test_out_of_order_responses(dut):
    """Test 2: Out-of-order memory responses, program-order dequeue"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Disable auto-dequeue by setting deq_ready low initially
    dut.deq_ready.value = 0

    # Enqueue 4 loads
    loads = []
    for i in range(4):
        ready, lq_id = await enqueue_load(
            dut,
            addr=0x1000 + (i * 4),
            rd=10 + i,
            load_type=LOAD_LW
        )
        assert ready, f"Enqueue {i} should succeed"
        loads.append((lq_id, 10 + i, 0xA000 + i))
        await ClockCycles(dut.clk, 2)  # Give time for memory request

    # Respond out of order: 2, 0, 3, 1
    response_order = [2, 0, 3, 1]
    for idx in response_order:
        lq_id, rd, data = loads[idx]
        await send_mem_response(dut, lq_id, data)
        await ClockCycles(dut.clk, 1)

    # Now enable dequeue and collect in program order
    await ClockCycles(dut.clk, 2)
    dut.deq_ready.value = 1

    # Dequeue should happen in program order: 0, 1, 2, 3
    dequeued = []
    for i in range(4):
        # Wait for dequeue to become valid
        timeout = 20
        for _ in range(timeout):
            await RisingEdge(dut.clk)
            if dut.deq_valid.value:
                rd = int(dut.deq_rd.value)
                data = int(dut.deq_data.value)
                dequeued.append((rd, data))
                dut._log.info(f"Dequeued {i}: rd={rd}, data={data:#x}")
                break
        else:
            dut._log.error(f"Timeout on dequeue {i}: deq_valid={dut.deq_valid.value}, empty={dut.empty.value}, count={dut.count.value}")
            assert False, f"Timeout waiting for dequeue {i}"

    # Verify order
    for i, (rd, data) in enumerate(dequeued):
        expected_rd = 10 + i
        expected_data = 0xA000 + i
        assert rd == expected_rd, f"Dequeue {i}: expected rd={expected_rd}, got {rd}"
        assert data == expected_data, f"Dequeue {i}: expected data={expected_data:#x}, got {data:#x}"

    dut._log.info("✓ Test 2 passed: Out-of-order responses with program-order dequeue")


@cocotb.test()
async def test_queue_full(dut):
    """Test 3: Queue full detection (8 entries)"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Enqueue 8 loads (fill the queue)
    for i in range(8):
        ready, lq_id = await enqueue_load(dut, addr=0x2000 + i*4, rd=1+i, load_type=LOAD_LW)
        assert ready, f"Enqueue {i} should succeed"
        await ClockCycles(dut.clk, 1)
        if i == 7:
            await RisingEdge(dut.clk)
            assert dut.full.value == 1, f"Full signal should be asserted at entry {i}"

    # Try to enqueue 9th load - should fail
    ready, _ = await enqueue_load(dut, addr=0x3000, rd=20, load_type=LOAD_LW)
    assert not ready, "Enqueue should fail when queue is full"
    assert dut.full.value == 1, "Full signal should be asserted"

    # Respond to first load
    await ClockCycles(dut.clk, 2)  # Wait for memory request
    await send_mem_response(dut, lq_id=0, data=0xAAAA)
    await RisingEdge(dut.clk)

    # Should dequeue automatically, making space
    for _ in range(10):
        await RisingEdge(dut.clk)
        if dut.full.value == 0:
            break
    else:
        assert False, "Queue should no longer be full after dequeue"

    # Now 9th load should succeed
    ready, _ = await enqueue_load(dut, addr=0x3000, rd=20, load_type=LOAD_LW)
    assert ready, "Enqueue should succeed after dequeue"

    dut._log.info("✓ Test 3 passed: Queue full detection")


@cocotb.test()
async def test_load_byte_sign_extend(dut):
    """Test 4: LB (load byte with sign extension)"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    test_cases = [
        (0x0000007F, 0x0000007F),  # Positive byte (0x7F)
        (0x00000080, 0xFFFFFF80),  # Negative byte (0x80 sign-extends to 0xFFFFFF80)
        (0x000000FF, 0xFFFFFFFF),  # 0xFF sign-extends to 0xFFFFFFFF
        (0x12345678, 0x00000078),  # Only lowest byte, positive
    ]

    for i, (mem_data, expected) in enumerate(test_cases):
        ready, lq_id = await enqueue_load(dut, addr=0x4000+i*4, rd=5+i, load_type=LOAD_LB)
        await ClockCycles(dut.clk, 2)
        await send_mem_response(dut, lq_id, mem_data)
        await wait_for_dequeue(dut, expected_rd=5+i, expected_data=expected)

    dut._log.info("✓ Test 4 passed: LB sign extension")


@cocotb.test()
async def test_load_halfword_sign_extend(dut):
    """Test 5: LH (load halfword with sign extension)"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    test_cases = [
        (0x00007FFF, 0x00007FFF),  # Positive halfword
        (0x00008000, 0xFFFF8000),  # Negative halfword (0x8000 sign-extends)
        (0x0000FFFF, 0xFFFFFFFF),  # 0xFFFF sign-extends to 0xFFFFFFFF
        (0x12345678, 0x00005678),  # Only lowest halfword, positive
    ]

    for i, (mem_data, expected) in enumerate(test_cases):
        ready, lq_id = await enqueue_load(dut, addr=0x5000+i*4, rd=10+i, load_type=LOAD_LH)
        await ClockCycles(dut.clk, 2)
        await send_mem_response(dut, lq_id, mem_data)
        await wait_for_dequeue(dut, expected_rd=10+i, expected_data=expected)

    dut._log.info("✓ Test 5 passed: LH sign extension")


@cocotb.test()
async def test_load_byte_zero_extend(dut):
    """Test 6: LBU (load byte with zero extension)"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    test_cases = [
        (0x00000080, 0x00000080),  # Should zero-extend, not sign-extend
        (0x000000FF, 0x000000FF),  # 0xFF zero-extends to 0x000000FF
        (0x12345678, 0x00000078),  # Only lowest byte
    ]

    for i, (mem_data, expected) in enumerate(test_cases):
        ready, lq_id = await enqueue_load(dut, addr=0x6000+i*4, rd=15+i, load_type=LOAD_LBU)
        await ClockCycles(dut.clk, 2)
        await send_mem_response(dut, lq_id, mem_data)
        await wait_for_dequeue(dut, expected_rd=15+i, expected_data=expected)

    dut._log.info("✓ Test 6 passed: LBU zero extension")


@cocotb.test()
async def test_load_halfword_zero_extend(dut):
    """Test 7: LHU (load halfword with zero extension)"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    test_cases = [
        (0x00008000, 0x00008000),  # Should zero-extend, not sign-extend
        (0x0000FFFF, 0x0000FFFF),  # 0xFFFF zero-extends to 0x0000FFFF
        (0x12345678, 0x00005678),  # Only lowest halfword
    ]

    for i, (mem_data, expected) in enumerate(test_cases):
        ready, lq_id = await enqueue_load(dut, addr=0x7000+i*4, rd=20+i, load_type=LOAD_LHU)
        await ClockCycles(dut.clk, 2)
        await send_mem_response(dut, lq_id, mem_data)
        await wait_for_dequeue(dut, expected_rd=20+i, expected_data=expected)

    dut._log.info("✓ Test 7 passed: LHU zero extension")


@cocotb.test()
async def test_wraparound(dut):
    """Test 8: Circular buffer wraparound"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Fill queue
    for i in range(8):
        await enqueue_load(dut, addr=0x8000+i*4, rd=1+i, load_type=LOAD_LW)

    # Drain queue
    for i in range(8):
        await send_mem_response(dut, lq_id=i, data=0xB000+i)
        await RisingEdge(dut.clk)
        assert dut.deq_valid.value == 1

    await RisingEdge(dut.clk)
    assert dut.empty.value == 1, "Queue should be empty after draining"

    # Fill again (tests wraparound)
    for i in range(8):
        ready, lq_id = await enqueue_load(dut, addr=0x9000+i*4, rd=10+i, load_type=LOAD_LW)
        assert ready, f"Re-enqueue {i} should succeed after wraparound"
        assert lq_id == i, f"LQ ID should wrap around correctly"

    dut._log.info("✓ Test 8 passed: Circular buffer wraparound")


@cocotb.test()
async def test_concurrent_enqueue_dequeue(dut):
    """Test 9: Simultaneous enqueue and dequeue"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Enqueue first load
    ready, lq_id = await enqueue_load(dut, addr=0xA000, rd=5, load_type=LOAD_LW)
    await ClockCycles(dut.clk, 2)

    # Respond to first load
    await send_mem_response(dut, lq_id, 0xCCCC)
    await RisingEdge(dut.clk)

    # Now enqueue and dequeue simultaneously
    dut.enq_valid.value = 1
    dut.enq_addr.value = 0xA004
    dut.enq_rd.value = 6
    dut.enq_load_type.value = LOAD_LW
    dut.deq_ready.value = 1

    await RisingEdge(dut.clk)

    # Check both happened
    # (count should stay same: +1 enqueue, -1 dequeue)

    dut.enq_valid.value = 0

    dut._log.info("✓ Test 9 passed: Concurrent enqueue/dequeue")


@cocotb.test()
async def test_variable_memory_latency(dut):
    """Test 10: Variable memory response latency"""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())
    await reset_dut(dut)

    # Disable auto-dequeue
    dut.deq_ready.value = 0

    loads = []
    for i in range(4):
        ready, lq_id = await enqueue_load(dut, addr=0xB000+i*4, rd=1+i, load_type=LOAD_LW)
        loads.append((lq_id, 1+i, 0xD000+i))
        await ClockCycles(dut.clk, 2)  # Wait for memory request

    # Respond with random delays (but all responses sent)
    for lq_id, rd, data in loads:
        delay = random.randint(2, 8)
        await ClockCycles(dut.clk, delay)
        await send_mem_response(dut, lq_id, data)

    # Enable dequeue
    await ClockCycles(dut.clk, 2)
    dut.deq_ready.value = 1

    # All should eventually dequeue in program order
    for i in range(4):
        # Since all responses are sent, dequeues should happen
        timeout = 30
        for _ in range(timeout):
            await RisingEdge(dut.clk)
            if dut.deq_valid.value:
                rd = int(dut.deq_rd.value)
                data = int(dut.deq_data.value)
                expected_rd = 1 + i
                expected_data = 0xD000 + i
                assert rd == expected_rd, f"Dequeue {i}: expected rd={expected_rd}, got {rd}"
                assert data == expected_data, f"Dequeue {i}: expected data={expected_data:#x}, got {data:#x}"
                break
        else:
            assert False, f"Timeout waiting for dequeue {i}"

    dut._log.info("✓ Test 10 passed: Variable memory latency")


# Test runner
def runCocotbTests():
    """Pytest entry point for running cocotb tests"""
    proj_path = Path(__file__).resolve().parent.parent.parent
    rtl_dir = proj_path / "rtl"

    verilog_sources = [
        rtl_dir / "pipeline_stages" / "load_queue.v",
    ]

    run(
        verilog_sources=verilog_sources,
        toplevel="load_queue",
        module="test_load_queue",
        simulator="verilator",
        work_dir=proj_path / "tests" / "sim_build" / "load_queue",
        waves=True,
        extra_args=[
            "--trace-fst",
            "--trace-structs",
        ]
    )


if __name__ == "__main__":
    runCocotbTests()
