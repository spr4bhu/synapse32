"""
Standalone test for write_allocate to check isolation
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb_test.simulator import run
import os

async def reset_dut(dut):
    dut.rst.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await RisingEdge(dut.clk)

async def wait_ready(dut, max_cycles=100):
    timeout = 0
    while dut.cpu_req_ready.value == 0:
        await RisingEdge(dut.clk)
        timeout += 1
        if timeout > max_cycles:
            raise Exception(f"Timeout waiting for cpu_req_ready after {max_cycles} cycles")

@cocotb.test()
async def test_write_allocate_standalone(dut):
    """Test: Write miss triggers write-allocate - STANDALONE"""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    dut.cpu_req_valid.value = 0
    dut.mem_resp_valid.value = 0
    dut.mem_req_ready.value = 1

    await RisingEdge(dut.clk)

    # Write miss (should write-allocate)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x5000
    dut.cpu_req_write.value = 1
    dut.cpu_req_wdata.value = 0xABCDEF00
    dut.cpu_req_byte_en.value = 0xF

    await RisingEdge(dut.clk)
    dut.cpu_req_valid.value = 0

    # Should generate memory request (fetch for write-allocate)
    while dut.mem_req_valid.value == 0:
        await RisingEdge(dut.clk)

    assert dut.mem_req_write.value == 0, "Write-allocate should fetch first (read)"

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 1
    dut.mem_resp_rdata.value = (1 << 512) - 1  # All 1s

    await RisingEdge(dut.clk)
    dut.mem_resp_valid.value = 0

    await wait_ready(dut)
    
    # Wait one additional cycle to ensure arrays from UPDATE_CACHE are fully stable
    await RisingEdge(dut.clk)

    # Read back - should have written data merged with fetched data
    # Verify cache is ready and in IDLE state
    assert dut.cpu_req_ready.value == 1, "Cache should be ready"
    assert dut.state.value == 0, f"Cache should be in IDLE state, got {dut.state.value}"
    
    # Set request BEFORE clock edge so combinational logic sees it in that cycle
    await FallingEdge(dut.clk)
    dut.cpu_req_valid.value = 1
    dut.cpu_req_addr.value = 0x5000
    dut.cpu_req_write.value = 0
    
    cocotb.log.info(f"Set request: addr=0x5000, valid={dut.cpu_req_valid.value}, state={dut.state.value}")
    
    # Response should be available immediately (combinational output)
    # Check after clock edge when cache processes the request
    await RisingEdge(dut.clk)
    
    cocotb.log.info(f"After RisingEdge: addr={hex(dut.cpu_req_addr.value)}, valid={dut.cpu_req_valid.value}, resp_valid={dut.cpu_resp_valid.value}, state={dut.state.value}")
    
    # Let combinational logic settle
    await Timer(1, units="ns")
    
    cocotb.log.info(f"After Timer: resp_valid={dut.cpu_resp_valid.value}")
    
    # Check response while cpu_req_valid is still asserted (combinational output requires it)
    assert dut.cpu_resp_valid.value == 1, f"Read should hit - resp_valid={dut.cpu_resp_valid.value}, state={dut.state.value}, addr={hex(dut.cpu_req_addr.value)}"
    assert dut.cpu_resp_rdata.value == 0xABCDEF00, \
        f"Write-allocate failed: expected 0xABCDEF00, got {hex(dut.cpu_resp_rdata.value)}"
    
    dut.cpu_req_valid.value = 0

    cocotb.log.info("✓ Write-allocate test PASSED")

def runCocotbTests():
    """Run standalone write_allocate test"""
    rtl_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'rtl')
    verilog_sources = [os.path.join(rtl_dir, 'dcache.v')]
    
    run(
        verilog_sources=verilog_sources,
        toplevel="dcache",
        module="test_dcache_write_allocate_standalone",
        simulator="verilator",
        work_dir="sim_build_dcache_write_allocate_standalone",
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
