# Synapse-32

Synapse-32 is a 32-bit RISC-V CPU core written in Verilog, supporting RV32I instructions, along with Zicsr and Zifencei extensions.

## Processor Architecture

### 5-Stage Pipeline
This processor implements a classic 5-stage RISC pipeline:

1. **IF (Instruction Fetch)**: 
   - Fetches the next instruction from instruction memory
   - Updates the Program Counter (PC)

2. **ID (Instruction Decode)**:
   - Decodes the instruction
   - Reads values from register file
   - Generates immediate values and control signals

3. **EX (Execute)**:
   - Performs ALU operations
   - Calculates branch/jump addresses
   - Makes branch decisions

4. **MEM (Memory Access)**:
   - Issues loads and stores to the memory subsystem through the load and store queues
   - Memory accesses complete asynchronously and retire in program order

5. **WB (Write Back)**:
   - Writes results back to the register file
   - Selects appropriate data source (ALU or memory)

### Pipeline Hazard Handling

The CPU implements several techniques to handle pipeline hazards:

1. **Data Forwarding**:
   - Resolves Read-After-Write (RAW) hazards
   - Forwards data from EX/MEM and MEM/WB stages to the EX stage
   - Avoids pipeline stalls in most cases

2. **Load-Use Hazard Detection**:
   - Detects when an instruction immediately needs data from a preceding load
   - Inserts pipeline stalls when necessary

3. **Store-Load Forwarding**:
   - The store queue forwards a pending store's data to a later load from the same address, before the store drains to memory
   - Avoids a round-trip to memory while preserving memory consistency

4. **Control Hazard Management**:
   - Handles branch and jump instructions
   - Flushes the pipeline when branches are taken
   - Supports efficient control flow

### Instruction Cache

The CPU includes an N-way set-associative instruction cache:

- **Configuration**: 4-way set-associative, 64 sets, 4 words per line (4KB total)
- **Replacement Policy**: Round-robin
- **Cache Invalidation**: FENCE.I instruction support

### Memory Subsystem

A single unified memory backs both instructions and data, accessed through a pair of queues:

- **Unified Memory**: One module replacing the earlier separate instruction and data memories
- **Store Queue**: Buffers stores and forwards their data to later loads from the same address
- **Load Queue**: Tracks in-flight loads and retires them in program order with sign/zero extension

## Running Code on the CPU

To compile the CPU and view the simulation, you need to have the following tools installed:

- [Icarus Verilog](https://steveicarus.github.io/iverilog/usage/installation.html)
- [Verilator](https://verilator.org/guide/latest/install.html)
- [Gtkwave](https://gtkwave.sourceforge.net/)
- [Cocotb](https://cocotb.readthedocs.io/en/stable/)

You can write any C program to test the CPU, we provide a linker and startup file to help you with that. You can find the linker script and startup file in the `sim` folder of this repository. An example hello world program is provided in the `sim` folder as well.

### Compiling the CPU and Running Simulation of the Example Program

To compile the CPU and run the simulation of the example hello world program, follow these steps:

1. Navigate to the `sim` folder in your cloned repository:
   ```bash
   cd sim
   ```
2. Create a virtual environment and install the required dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use .venv\Scripts\activate
   pip install -r ../tests/requirements.txt # install cocotb and other dependencies
   ```

3. Compile the CPU using python script:
   ```bash
   python run_c_code.py test_uart_hello.c
   ```

The helper script `run_c_code.py` will compile the C code, generate the necessary files, and run the simulation using verilator. It will also generate a waveform file for viewing in GTKWave.

## CPU Regression Tests

The CPU comes with a set of regression tests to ensure its functionality. These tests cover various aspects of the CPU, including instruction execution, pipeline behavior, and hazard handling.

These tests are written in Python using the Cocotb framework, which allows for writing testbenches in Python and simulating them with Verilog.

To run the regression tests, follow these steps:

1. Navigate to the `tests` folder in your cloned repository:
   ```bash
   cd tests
   ```
2. Create a virtual environment and install the required dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use .venv\Scripts\
   pip install -r requirements.txt
   ```
3. Run the regression tests using pytest:
   ```bash
   pytest
   ```

### Available Tests

The regression tests include:
- **Basic Arithmetic Operations**: Tests for addition, subtraction, and other arithmetic instructions.
- **Decoder Tests**: Verifies the instruction decoding logic.
- **Hazard Handling Tests**: Ensures that data forwarding and hazard detection work correctly.
- **Control Flow Tests**: Validates branch and jump instructions.
- **Memory Access Tests**: Checks load and store operations.
- **Memory Hazard Tests**: Validates store-to-load forwarding and load/store queue behavior.
- **Instruction Cache Tests**: Validates cache hit/miss, line fetching, invalidation, and replacement policy.
- **CSR Tests**: Validates the control and status register operations.
- **UART Tests**: Validates the UART communication functionality.

## Contributors

- [Saish Karole](https://github.com/saishock1504)
- [Atharva Kashalkar](https://github.com/RapidRoger18)
- [Zain Siddavatam](https://github.com/SuperChamp234)
- [Chanchal Bahrani](https://github.com/Chanchal1010)
- [Shri Vishakh Devanand](https://github.com/5iri)

### Acknowledgements and Resources

- [SRA VJTI Eklavya 2023](https://sravjti.in/)
- https://www.chipverify.com/verilog/verilog-tutorial
- https://www.edx.org/course/building-a-risc-v-cpu-core
