# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Synapse-32 is a 32-bit RISC-V CPU core (RV32I with Zicsr and Zifencei extensions) implementing a classic 5-stage pipeline with instruction cache support. The project is written in Verilog and uses Cocotb (Python) for testing.

## Build and Test Commands

### Running Tests

```bash
# Navigate to tests directory
cd tests

# Create virtual environment (first time only)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run all tests
pytest

# Run specific test file
pytest system_tests/test_icache.py
pytest system_tests/test_full_integration.py -v

# Run specific test within a file
pytest system_tests/test_csr.py::runCocotbTests -v
```

**Important:** Test discovery is configured to only find `runCocotbTests` functions (see `pytest.ini`). Individual cocotb test cases are invisible to pytest and are discovered by cocotb itself.

### Running C Programs on the CPU

```bash
# Navigate to sim directory
cd sim

# Compile and run a C program
python run_c_code.py test_uart_hello.c

# This will:
# 1. Compile the C code using RISC-V toolchain
# 2. Generate instruction memory
# 3. Run Verilator simulation
# 4. Generate waveform for GTKWave
```

## Architecture

### 5-Stage Pipeline

The CPU implements: **IF → ID → EX → MEM → WB**

**Key Module Hierarchy:**
- `top.v` - Top-level integrating CPU, memories, I-cache, peripherals
- `riscv_cpu.v` - Main CPU pipeline coordinating all stages
  - Pipeline registers: `IF_ID`, `ID_EX`, `EX_MEM`, `MEM_WB`
  - Core modules: `decoder`, `registerfile`, `execution_unit`, `writeback`
  - Hazard handling: `load_use_detector`, `store_load_detector`, `forwarding_unit`
  - Interrupt support: `interrupt_controller`, `csr_file`
- `icache_nway_multiword.v` - 4-way set-associative I-cache (4KB, round-robin replacement)

### Pipeline Stall Sources

The CPU combines multiple stall signals:
```verilog
combined_stall = stall_pipeline || icache_stall;
```
- `stall_pipeline` - Load-use hazard detected by `load_use_detector`
- `icache_stall` - Cache miss in instruction cache

### Instruction Encoding

All instructions use 6-bit IDs defined in `rtl/include/instr_defines.vh`:
- Decoder converts 32-bit RISC-V instruction → 6-bit `instr_id`
- Modules use `instr_id` (e.g., `INSTR_ADD`, `INSTR_BEQ`) instead of opcode/funct3/funct7
- This simplifies control logic throughout pipeline

### Hazard Handling

**Data Forwarding:** `forwarding_unit.v` resolves RAW hazards by forwarding from:
- EX/MEM → EX (bypass ALU results)
- MEM/WB → EX (bypass memory data)
- WB → EX (bypass all writeback sources including load/store queues)

**Load-Use Stalls:** `load_use_detector.v` detects when ID stage needs data from load in EX stage, stalls pipeline 1 cycle.

**Store-to-Load Forwarding:**
- Old in-order path: `store_load_detector.v` and `store_load_forward.v` (deprecated, kept for compatibility)
- New queue-based path: `store_queue.v` CAM lookup in EX stage, single-cycle forwarding to WB

**Control Hazards:** Branches/jumps flush pipeline by inserting NOPs (`32'h13` = ADDI x0,x0,0) into IF/ID register when `branch_flush` asserted.

### Instruction Cache

**Configuration (parametrizable):**
- 4-way set-associative, 64 sets, 4 words/line = 4KB total
- Round-robin replacement policy
- 3-state FSM: IDLE → FETCH → ALLOCATE

**Critical Design:** The ALLOCATE state checks if `cpu_addr` changed during cache miss (branch executed during refill). If address changed, cache either serves new address from cache (if hit) or starts new refill (if miss). This prevents serving stale instructions after branches.

**FENCE.I Support:** CPU detects `INSTR_FENCE_I` and asserts `fence_i_signal` to invalidate entire cache.

## Testing Architecture

### Cocotb Test Structure

Tests are Python files using cocotb decorators:
```python
@cocotb.test()
async def test_name(dut):
    # Test logic using async/await
    await RisingEdge(dut.clk)
```

Each test file has a `runCocotbTests()` function that configures and runs Verilator:
```python
def runCocotbTests():
    run(
        verilog_sources=[...],
        toplevel="module_name",
        module="test_file_name",
        simulator="verilator",
        ...
    )
```

### Test Categories

**System Tests** (`tests/system_tests/`):
- Full CPU integration tests (programs with multiple instructions)
- I-cache validation (hit/miss, refill, invalidation)
- CSR and interrupt handling
- Pipeline hazard scenarios

**Unit Tests** (`tests/unit_tests/`):
- Individual module verification (ALU, decoder, etc.)

### Writing Tests for Cache/Memory Modules

When testing modules with asynchronous memory interfaces:
1. Use `FallingEdge(dut.clk)` to set `mem_valid` based on previous cycle's `mem_req`
2. Memory latency can be variable - cache must handle multi-cycle responses
3. Test address changes during multi-cycle operations (critical for cache correctness)

## Code Style and Conventions

### Verilog Modules

**Standard Module Structure:**
```verilog
`default_nettype none
`include "instr_defines.vh"  // If needed

module module_name #(
    parameter PARAM1 = default_value,
    parameter PARAM2 = default_value
)(
    input wire clk,
    input wire rst,
    // ... other ports
);
    // localparam calculations
    // State machine states
    // Register/wire declarations
    // Combinational logic blocks
    // Sequential logic blocks
endmodule

`default_nettype wire  // Reset at end
```

**Parametrization:** All configurable values should be module parameters, not hardcoded. This allows different configurations for testing and future OoO support.

**Documentation:** Minimal inline comments explaining complex logic (e.g., forwarding decisions, state transitions). No elaborate headers - code should be self-documenting with clear naming.

### State Machines

Use localparam for states with explicit bit widths:
```verilog
localparam [1:0] STATE_IDLE = 2'd0;
localparam [1:0] STATE_ACTIVE = 2'd1;
```

Separate combinational output logic from sequential state transitions for clarity and to avoid latches.

## Memory Hierarchy Upgrade Plan

The project is currently on `feature/dcache-integration` branch implementing an 8-phase memory hierarchy upgrade.

### Phase Status

**✅ Phase 1 - Load Queue (COMPLETE)**
- 8-entry circular buffer with head/tail pointers
- Asynchronous load completion (decouples loads from pipeline)
- Allocates in EX stage, retires to WB when data ready
- Location: `rtl/pipeline_stages/load_queue.v`
- Tests: `tests/memory_hierarchy/test_load_queue.py` (8 unit tests)

**✅ Phase 2 - Store Queue (COMPLETE)**
- 8-entry circular buffer with CAM-based forwarding
- Store-to-load forwarding (newest match priority)
- Program-order retirement (FIFO from head)
- Single-cycle forwarding latency (matches load queue)
- Priority-based memory arbitration (industry standard)
- Location: `rtl/pipeline_stages/store_queue.v`
- Tests: `tests/memory_hierarchy/test_store_queue.py` (8 unit tests)
- Integration tests: `tests/system_tests/test_memory_forwarding.py` (8 tests)

**Remaining Phases:**
3. L1 D-cache with MSHRs (4-way 32KB, non-blocking)
4. I-cache MSHR upgrade (non-blocking with prefetch support)
5. Sequential prefetcher for I-cache
6. Stride prefetcher for D-cache
7. L2 unified cache (8-way 512KB, initially non-inclusive for simplicity)
8. Performance optimizations and tuning

**Design Philosophy:** Build memory hierarchy infrastructure now (queues, MSHRs) that can support future out-of-order execution. All components fully parametrizable to run with minimal configuration on current in-order pipeline, scaling up later.

### Memory Arbitration

The CPU uses **priority-based arbitration** (industry standard, matches ARM Cortex-A and RISC-V Rocket):

```verilog
// Priority levels:
// 1. Store queue >75% full → prioritize stores (prevent deadlock)
// 2. Load queue >75% full → prioritize loads (unblock pipeline)
// 3. Otherwise → loads get priority (critical path)

assign grant_store = sq_mem_write_valid && (
    !lq_mem_req_valid ||           // No competing load
    sq_almost_full ||               // SQ almost full - prioritize draining
    (!lq_almost_full)               // Neither full, stores get chance
);
assign grant_load = lq_mem_req_valid && !grant_store;
```

### Load/Store Queue Integration

**Load Queue Flow:**
1. EX stage detects load instruction
2. Allocate entry in load queue
3. Issue memory request when arbitration grants
4. When memory responds, mark data ready
5. Retire from head to WB stage (write register file)

**Store Queue Flow:**
1. EX stage detects store instruction
2. Allocate entry in store queue
3. Check CAM for store-to-load forwarding (if load in EX matches store in queue)
4. Retire from head (FIFO) to memory when arbitration grants

**Store-to-Load Forwarding:**
- CAM searches from tail-1 (newest) to head (oldest)
- Returns youngest matching store
- Handles size matching (SB→LB/LBU, SH→LH/LHU, SW→LW)
- Sign/zero extends forwarded data based on load type
- Single-cycle latency (registers forwarded data once, writes at WB)

## Important Notes

### Include Path
All Verilog includes use simple `include "filename"` syntax. The include path is configured in test runners to point to `rtl/include/`.

### Pipeline Flush Logic
When modifying pipeline stages, ensure NOPs (`32'h13`) are inserted correctly during flushes, not zeros. Zero is an illegal instruction and will cause decoder issues.

### Cache Bug Patterns to Avoid
- Missing address-change checks during multi-cycle operations (loads, cache refills)
- Not handling memory responses arriving out-of-order
- Serving stale data after control flow changes
- Incorrect state transitions when operations overlap

### Regression Testing Protocol

**CRITICAL: All tests must pass before proceeding to next phase.**

When implementing memory hierarchy upgrades, the following test suites MUST pass at 100% before moving to the next phase:

1. **Core Test Suites (44 tests total):**
   - `tests/system_tests/test_full_integration.py` - 29 tests (instruction execution, hazards, cache, CSR, interrupts)
   - `tests/system_tests/test_stress_fixed.py` - 5 tests (long-running programs, memory-intensive workloads, cache thrashing)
   - `tests/system_tests/test_edge_cases.py` - 10 tests (extreme hazards, interrupts, error conditions, race conditions)

2. **Memory Hierarchy Tests:**
   - Each new component (load queue, store queue, caches) gets standalone unit tests
   - These tests must pass before integration
   - After integration, all 44 core tests + new component tests must pass

**Running the Full Test Suite:**
```bash
cd tests
pytest system_tests/test_full_integration.py system_tests/test_stress_fixed.py system_tests/test_edge_cases.py -v
```

**Test Writing Best Practices:**
- **NEVER guess branch offsets manually** - Calculate programmatically using: `(target_index - (branch_index + 1)) * 4`
- **Account for load queue latency** - Insert 4 NOPs after LW instructions before using loaded data
- **Use instruction indices** - Comment each instruction with its index (e.g., `LW(1, 10, 0)  # 5: load from memory`)
- **Build programs incrementally** - Use placeholders for branches, calculate offsets after all instructions defined
- **Example:**
  ```python
  instructions = [
      ADDI(1, 0, 0),    # 0: counter = 0
      ADDI(2, 0, 10),   # 1: max = 10
      ADDI(1, 1, 1),    # 2: counter++ (loop start)
      NOP(),            # 3: Placeholder for branch
  ]
  loop_offset = (2 - (3 + 1)) * 4  # Target index 2, branch at index 3
  instructions[3] = BNE(1, 2, loop_offset)
  ```
