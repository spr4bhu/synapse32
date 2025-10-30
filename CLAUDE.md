# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Synapse-32 is a 32-bit RISC-V CPU core written in Verilog, implementing the RV32I instruction set with Zicsr and Zifencei extensions. The design features a classic 5-stage pipeline (IF/ID/EX/MEM/WB) with data forwarding, hazard detection, and an N-way set-associative instruction cache.

## Build and Test Commands

### Running the Test Suite

Navigate to the `tests` directory and use pytest:

```bash
cd tests
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest  # Runs all tests
```

The project uses Cocotb (Python testbenches for Verilog) with pytest as the test runner. The `pytest.ini` configures pytest to only discover the Cocotb test runner functions.

### Running C Code on the CPU

Navigate to the `sim` directory to compile and simulate C programs:

```bash
cd sim
python -m venv .venv
source .venv/bin/activate
pip install -r ../tests/requirements.txt
python run_c_code.py <your_c_file.c>  # Example: python run_c_code.py test_uart_hello.c
```

The `run_c_code.py` script compiles C code using RISC-V GCC, generates hex files, and runs Verilator simulation. Example programs include `test_uart_hello.c` and `fibonacci.c`.

### Required Tools

- Icarus Verilog (iverilog)
- Verilator
- GTKWave (for viewing waveforms)
- Cocotb (Python testbench framework)
- RISC-V GCC toolchain (for compiling C programs)

## Architecture

### Module Hierarchy

- **`top.v`**: Top-level integration module connecting CPU, memories, and peripherals
  - Instantiates the CPU core, instruction cache, data memory, timer, and UART
  - Uses memory-mapped I/O with address decoding defined in `rtl/include/memory_map.vh`
  - Connects I-cache to burst controller for efficient memory fetching

- **`riscv_cpu.v`**: The main CPU pipeline orchestration
  - Instantiates and connects all 5 pipeline stages
  - Manages pipeline control signals (stalls, flushes, valid bits)
  - Implements hazard detection and forwarding logic coordination
  - Handles cache stall propagation through the pipeline

### Pipeline Stages (rtl/pipeline_stages/)

The pipeline follows a classic RISC design with inter-stage registers:

1. **IF (Instruction Fetch)**: PC module fetches instructions from I-cache
2. **IF_ID**: Pipeline register with flush capability
3. **ID (Instruction Decode)**: Decoder and register file read
4. **ID_EX**: Pipeline register storing decoded instruction info, includes valid bit tracking
5. **EX (Execute)**: `execution_unit.v` performs ALU ops, branch/jump decisions, CSR operations
6. **EX_MEM**: Pipeline register forwarding execution results
7. **MEM (Memory Access)**: `memory_unit.v` handles loads/stores
8. **MEM_WB**: Pipeline register with memory data
9. **WB (Write Back)**: `writeback.v` selects data source and writes to register file

### Core Modules (rtl/core_modules/)

- **`decoder.v`**: Decodes instructions, generates control signals and immediates
- **`registerfile.v`**: 32-entry register file with dual read ports and single write port
- **`alu.v`**: Arithmetic and logic operations
- **`pc.v`**: Program counter with jump/branch support
- **`csr_file.v`**: Control and Status Registers (CSRs) for system control
- **`csr_exec.v`**: CSR instruction execution logic
- **`interrupt_controller.v`**: Handles timer, software, and external interrupts
- **`timer.v`**: Memory-mapped timer peripheral
- **`uart.v`**: UART transmitter for serial output

### Hazard Handling (rtl/pipeline_stages/)

- **`forwarding_unit.v`**: Implements data forwarding from EX/MEM and MEM/WB stages to EX stage
  - Generates `forward_a` and `forward_b` signals (2-bit selectors)
  - Resolves Read-After-Write (RAW) hazards without stalling when possible

- **`load_use_detector.v`**: Detects when a load instruction is immediately followed by a dependent instruction
  - Generates stall signal to insert bubble in pipeline

- **`store_load_detector.v`** and **`store_load_forward.v`**: Handle store-to-load forwarding scenarios

### Cache System

- **`icache_nway_multiword.v`**: N-way set-associative instruction cache
  - Configurable associativity and block size
  - Generates `cache_stall` signal when cache miss occurs
  - Interfaces with burst controller for cache line fills

- **`burst_controller.v`**: Manages burst reads from instruction memory to fill cache lines

### Memory Map (rtl/include/memory_map.vh)

Memory regions are defined with macros:
- Instruction Memory: `IS_INSTR_MEM(addr)`
- Data Memory: `IS_DATA_MEM(addr)` (base: 0x10000000)
- Timer: `IS_TIMER_MEM(addr)`
- UART: `IS_UART_MEM(addr)`

### Valid Bit Tracking

The pipeline uses valid bits to track whether each pipeline stage contains a valid instruction. This is critical for handling stalls and flushes correctly:
- When a stall occurs, invalid instructions (bubbles) propagate through the pipeline
- Valid bits prevent invalid instructions from affecting architectural state
- Used in conjunction with cache stalls and load-use hazard detection

## Test Organization

### Unit Tests (tests/unit_tests/)

Test individual modules in isolation:
- `test_alu.py`: ALU operations
- `test_decoder_gcc.py`: Instruction decoding

### System Tests (tests/system_tests/)

Full CPU integration tests:
- `test_riscv_cpu_basic.py`: Basic instruction execution and hazard handling
- `test_fibonacci.py`: Fibonacci program execution
- `test_uart_cpu.py`: UART communication functionality
- `test_csr.py`: CSR instruction tests
- `test_interrupts.py`: Interrupt handling
- `*_cache_test.py`: Cache behavior tests
- `*_stall_test.py`: Pipeline stall scenarios

Tests use Cocotb to instantiate the DUT (Device Under Test) and drive/monitor signals.

## Key Development Patterns

### Pipeline Modifications

When modifying pipeline behavior:
1. Update the relevant stage module in `rtl/pipeline_stages/` or `rtl/core_modules/`
2. Ensure valid bits propagate correctly through modified logic
3. Consider impact on forwarding and hazard detection units
4. Update inter-stage pipeline registers if new signals are added
5. Test with both unit tests and system integration tests

### Memory-Mapped Peripherals

To add a new peripheral:
1. Define address range in `rtl/include/memory_map.vh`
2. Add peripheral module to `rtl/`
3. Instantiate in `top.v` with appropriate address decoding
4. Connect to the memory data multiplexer in `top.v`

### C Program Development

C programs for the CPU must:
- Use the linker script `sim/link.ld` which defines memory layout
- Include startup code `sim/start.S` for initialization
- Use memory-mapped I/O addresses defined in memory_map.vh for peripherals
- Signal completion by writing to CPU_DONE_ADDR (0x100000FF)

## Git Workflow

Current branch: `pipeline_fix`
Main branch: `main`

Recent work has focused on pipeline hazard handling, valid bit propagation, and execution unit improvements.
