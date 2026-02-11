import cocotb
from cocotb.triggers import RisingEdge, Timer, FallingEdge
from cocotb.clock import Clock
from cocotb_test.simulator import run
import os


async def do_reset(dut):
    """Reset the DUT"""
    dut.rst.value = 1
    dut.cpu_req.value = 0
    dut.cpu_addr.value = 0
    dut.mem_data.value = 0
    dut.mem_valid.value = 0
    dut.invalidate.value = 0
    
    await Timer(50, units="ns")
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)


async def fill_cache_line(dut, addr):
    """Fill a cache line by accessing addr and completing the refill"""
    dut.cpu_addr.value = addr
    dut.cpu_req.value = 1
    
    for cycle in range(40):
        # Set mem_valid on falling edge based on previous mem_req
        await FallingEdge(dut.clk)
        
        mem_req = int(dut.mem_req.value)
        if mem_req == 1:
            mem_addr = int(dut.mem_addr.value)
            dut.mem_data.value = 0xDEAD0000 | (mem_addr & 0xFFFF)
            dut.mem_valid.value = 1
        else:
            dut.mem_valid.value = 0
        
        await RisingEdge(dut.clk)
        
        if int(dut.cpu_stall.value) == 0:
            break
    
    # Deassert request
    dut.cpu_req.value = 0
    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)


async def check_cache_hit(dut, addr):
    """Check if accessing addr results in a cache hit"""
    dut.cpu_addr.value = addr
    dut.cpu_req.value = 1
    await Timer(1, units="ns")  # Let combinational logic settle
    
    stall = int(dut.cpu_stall.value)
    valid = int(dut.cpu_valid.value)
    
    dut.cpu_req.value = 0
    return stall == 0 and valid == 1


@cocotb.test()
async def test_icache_basic_hit(dut):
    """Test basic cache hit functionality - repeated fetches should hit"""
    print("Starting basic cache hit test...")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await do_reset(dut)
    
    # First access - fill the cache line
    test_addr = 0x100
    await fill_cache_line(dut, test_addr)
    print("Cache line filled")
    
    await RisingEdge(dut.clk)
    
    # Second access - should hit
    hit = await check_cache_hit(dut, test_addr)
    assert hit, "Second access should hit"
    
    print(f"Second access hit! Data: {int(dut.cpu_data.value):#010x}")
    print("Basic cache hit test passed!")


@cocotb.test()
async def test_icache_cache_line_fetch(dut):
    """Test that entire cache line is fetched on miss"""
    print("Starting cache line fetch test...")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await do_reset(dut)
    
    # Fill a cache line
    base_addr = 0x200
    await fill_cache_line(dut, base_addr)
    
    await RisingEdge(dut.clk)
    
    # Now access other words in same cache line - should all hit
    for offset in range(0, 16, 4):  # 4 words * 4 bytes each
        test_addr = base_addr + offset
        hit = await check_cache_hit(dut, test_addr)
        assert hit, f"Access to addr {hex(test_addr)} should hit"
        print(f"Word at offset {offset}: {int(dut.cpu_data.value):#010x} - HIT")
        await RisingEdge(dut.clk)
    
    print("Cache line fetch test passed!")


@cocotb.test()
async def test_icache_invalidation(dut):
    """Test FENCE.I cache invalidation"""
    print("Starting cache invalidation test...")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await do_reset(dut)
    
    # Fill cache with first access
    test_addr = 0x300
    await fill_cache_line(dut, test_addr)
    
    await RisingEdge(dut.clk)
    
    # Verify it's in cache (hit)
    hit = await check_cache_hit(dut, test_addr)
    assert hit, "Should hit before invalidation"
    print("Cache entry confirmed before invalidation")
    
    await RisingEdge(dut.clk)
    
    # Invalidate cache
    dut.invalidate.value = 1
    await RisingEdge(dut.clk)
    dut.invalidate.value = 0
    await RisingEdge(dut.clk)
    
    # Access same address - should miss now
    dut.cpu_addr.value = test_addr
    dut.cpu_req.value = 1
    await Timer(1, units="ns")
    
    stall = int(dut.cpu_stall.value)
    assert stall == 1, f"Should miss after invalidation (stall={stall})"
    print("Cache miss after invalidation confirmed")
    
    # Complete the refill for clean exit
    dut.cpu_req.value = 0
    await fill_cache_line(dut, test_addr)
    
    print("Cache invalidation test passed!")


@cocotb.test()
async def test_icache_different_sets(dut):
    """Test accesses to different cache sets don't conflict"""
    print("Starting different sets test...")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await do_reset(dut)
    
    # Different sets: addresses differ in index bits [9:4]
    test_addresses = [
        0x000,   # Set 0
        0x010,   # Set 1  (differs in bit 4)
        0x020,   # Set 2  (differs in bit 5)
        0x100,   # Set 16 (differs in bit 8)
    ]
    
    # Fill cache with entries from different sets
    for addr in test_addresses:
        print(f"Filling cache line at {hex(addr)}")
        await fill_cache_line(dut, addr)
        await RisingEdge(dut.clk)
    
    # Now verify all entries are still in cache
    hits = 0
    for addr in test_addresses:
        hit = await check_cache_hit(dut, addr)
        if hit:
            hits += 1
            print(f"Address {hex(addr)}: HIT")
        else:
            print(f"Address {hex(addr)}: MISS (unexpected)")
        await RisingEdge(dut.clk)
    
    assert hits == len(test_addresses), f"All addresses should hit, got {hits}/{len(test_addresses)}"
    print("Different sets test passed!")


@cocotb.test()
async def test_icache_round_robin_replacement(dut):
    """Test round-robin replacement policy when set is full"""
    print("Starting round-robin replacement test...")
    
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    
    await do_reset(dut)

    # 5 addresses to same set (different tags) to trigger eviction
    set_0_addresses = [
        0x00000000,
        0x00000400,
        0x00000800,
        0x00000C00,
        0x00001000,
    ]

    for i, addr in enumerate(set_0_addresses[:4]):
        print(f"Filling way {i} with address {hex(addr)}")
        await fill_cache_line(dut, addr)
        await RisingEdge(dut.clk)

    print(f"Filling 5th address {hex(set_0_addresses[4])} - should evict way 0")
    await fill_cache_line(dut, set_0_addresses[4])
    await RisingEdge(dut.clk)

    dut.cpu_addr.value = set_0_addresses[0]
    dut.cpu_req.value = 1
    await Timer(1, units="ns")

    first_misses = int(dut.cpu_stall.value) == 1
    print(f"First address after 5th fill: {'MISS (evicted)' if first_misses else 'HIT'}")

    dut.cpu_req.value = 0
    await RisingEdge(dut.clk)

    for addr in set_0_addresses[1:5]:
        hit = await check_cache_hit(dut, addr)
        status = "HIT" if hit else "MISS"
        print(f"Address {hex(addr)}: {status}")
        await RisingEdge(dut.clk)
    
    assert first_misses, "Way 0 entry should have been evicted by round-robin"
    print("Round-robin replacement test passed!")


def runCocotbTests():
    """Run all icache tests"""
    root_dir = os.getcwd()
    while not os.path.exists(os.path.join(root_dir, "rtl")):
        if os.path.dirname(root_dir) == root_dir:
            raise FileNotFoundError("rtl directory not found")
        root_dir = os.path.dirname(root_dir)
    
    rtl_dir = os.path.join(root_dir, "rtl")
    
    # Only need the cache module for these tests
    sources = [os.path.join(rtl_dir, "icache_nway_multiword.v")]
    incl_dir = os.path.join(rtl_dir, "include")
    
    tests = [
        "test_icache_basic_hit",
        "test_icache_cache_line_fetch",
        "test_icache_invalidation",
        "test_icache_different_sets",
        "test_icache_round_robin_replacement",
    ]
    
    # Create waveforms directory
    waveform_dir = os.path.join(os.getcwd(), "waveforms")
    if not os.path.exists(waveform_dir):
        os.makedirs(waveform_dir)
    
    for test_name in tests:
        print(f"\n=== Running {test_name} ===")
        waveform_path = os.path.join(waveform_dir, f"{test_name}.vcd")
        
        run(
            verilog_sources=sources,
            toplevel="icache",
            module="test_icache",
            testcase=test_name,
            includes=[str(incl_dir)],
            simulator="verilator",
            timescale="1ns/1ps",
            extra_args=["--trace", "--trace-structs"]
        )


if __name__ == "__main__":
    runCocotbTests()
