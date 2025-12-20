# Instruction Cache Integration and Bug Fixes

This document describes all changes made to integrate an N-way set-associative instruction cache into the Synapse-32 RISC-V CPU, along with bug fixes discovered during comprehensive testing.

## Table of Contents

1. [Overview](#overview)
2. [New Files](#new-files)
3. [Modified Files](#modified-files)
4. [Bug Fixes](#bug-fixes)
5. [Test Suite](#test-suite)
6. [Architecture Changes](#architecture-changes)

---

## Overview

The Synapse-32 CPU has been enhanced with:
- **Instruction Cache**: 4-way set-associative, 64 sets, 4 words/line (4KB total)
- **FENCE.I Support**: Cache invalidation instruction
- **Proper Reset Handling**: Register file and cache clear on reset
- **Pipeline Fix**: Correct branch flush behavior during cache stalls

All changes follow industry-standard practices and comply with the RISC-V specification.

---

## New Files

### 1. `rtl/icache_nway_multiword.v`

N-way set-associative instruction cache module with:
- Configurable associativity (NUM_WAYS parameter)
- Configurable number of sets (NUM_SETS parameter)
- Configurable cache line size (CACHE_LINE_WORDS parameter)
- Round-robin replacement policy
- FENCE.I cache invalidation support
- Proper reset handling (clears all valid bits)

**Interface:**
```verilog
module icache #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter NUM_WAYS = 4,
    parameter NUM_SETS = 64,
    parameter CACHE_LINE_WORDS = 4
)(
    input wire clk,
    input wire rst,
    
    // CPU Interface
    input wire [ADDR_WIDTH-1:0] cpu_addr,
    input wire cpu_req,
    output reg [DATA_WIDTH-1:0] cpu_data,
    output reg cpu_valid,
    output reg cpu_stall,
    
    // Memory Interface
    output reg [ADDR_WIDTH-1:0] mem_addr,
    output reg mem_req,
    input wire [DATA_WIDTH-1:0] mem_data,
    input wire mem_valid,
    
    // Control
    input wire invalidate
);
```

### 2. `tests/system_tests/test_full_integration.py`

Comprehensive integration test suite with 29 tests covering:
- Cache operations (cold start, hit/miss, line boundaries, stalls)
- R-type instructions (ADD, SUB, AND, OR, XOR, SLL, SRL, SRA, SLT, SLTU)
- I-type instructions (ADDI, ANDI, ORI, XORI, SLTI, SLTIU, SLLI, SRLI, SRAI)
- Load/Store instructions (LW, SW, LB, LBU, LH, LHU, SB, SH)
- Branch instructions (BEQ, BNE, BLT, BGE, BLTU, BGEU)
- Jump instructions (JAL, JALR)
- U-type instructions (LUI, AUIPC)
- Pipeline hazards (RAW, Load-Use, Control)
- FENCE.I cache invalidation
- CSR operations (CSRRW, CSRRS, CSRRC, CSRRWI, CSRRSI, CSRRCI)
- Complex scenarios (nested loops, function calls, memory-intensive operations)

### 3. `tests/system_tests/test_icache.py`

Unit tests for the instruction cache module in isolation.

---

## Modified Files

### 1. `rtl/top.v`

**Changes:**
- Added instruction cache instantiation between CPU and instruction memory
- Added cache interface wires
- Connected FENCE.I signal from CPU to cache invalidate input
- Modified instruction memory to connect through cache

**Added Wires:**
```verilog
wire [31:0] cache_mem_addr;
wire cache_mem_req;
wire [31:0] cache_mem_data;
wire cache_mem_valid;
wire icache_stall;
wire fence_i_signal;
```

**Cache Instantiation:**
```verilog
icache #(
    .ADDR_WIDTH(32),
    .DATA_WIDTH(32),
    .NUM_WAYS(4),
    .NUM_SETS(64),
    .CACHE_LINE_WORDS(4)
) icache_inst (
    .clk(clk),
    .rst(rst),
    .cpu_addr(cpu_pc_out),
    .cpu_req(1'b1),
    .cpu_data(instr_to_cpu),
    .cpu_stall(icache_stall),
    .mem_addr(cache_mem_addr),
    .mem_req(cache_mem_req),
    .mem_data(cache_mem_data),
    .mem_valid(cache_mem_valid),
    .invalidate(fence_i_signal)
);
```

### 2. `rtl/riscv_cpu.v`

**Changes:**
- Added instruction cache stall input (`icache_stall`)
- Added FENCE.I output signal (`fence_i_signal`)
- Combined stall sources: `combined_stall = stall_pipeline || icache_stall`
- **Critical fix**: Branch flush now overrides cache stall for IF_ID stage

**New Ports:**
```verilog
input wire icache_stall,        // Instruction cache miss stall
output wire fence_i_signal      // FENCE.I invalidation signal
```

**Critical Pipeline Fix:**
```verilog
// IF_ID stall logic: 
// - On branch flush, we MUST latch the NOP (override cache stall)
// - Only stall if not flushing
wire if_id_stall;
assign if_id_stall = combined_stall && !branch_flush;
```

**FENCE.I Detection:**
```verilog
assign fence_i_signal = (id_ex_inst0_instr_id_out == INSTR_FENCE_I);
```

### 3. `rtl/core_modules/registerfile.v`

**Changes:**
- Added `rst` input signal
- Changed from `initial` block initialization to proper synchronous reset
- All 32 registers clear to 0 on reset
- Added `default_nettype none` for better error checking
- Improved write-through forwarding check (excludes x0)

**Before:**
```verilog
module registerfile (
    input clk,
    ...
);
    initial begin
        register_file[0]  = 0;
        register_file[1]  = 0;
        // ... 30 more lines
    end
```

**After:**
```verilog
module registerfile (
    input wire clk,
    input wire rst,
    ...
);
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            for (i = 0; i < 32; i = i + 1) begin
                register_file[i] <= 32'b0;
            end
        end else begin
            register_file[0] <= 32'b0;
            if (wr_en && rd != 5'b0) begin
                register_file[rd] <= rd_value;
            end
        end
    end
```

### 4. `rtl/core_modules/alu.v`

**Bug Fix:** SLT/SLTU/SLTI/SLTIU instructions returned incorrect values.

**Before (Incorrect):**
```verilog
INSTR_SLT:   ALUoutput = {32{$signed(rs1) < $signed(rs2)}};  // Returns 0xFFFFFFFF when true
INSTR_SLTU:  ALUoutput = {32{rs1 < rs2}};                    // Returns 0xFFFFFFFF when true
INSTR_SLTI:  ALUoutput = {32{$signed(rs1) < $signed(imm)}};  // Returns 0xFFFFFFFF when true
INSTR_SLTIU: ALUoutput = {32{rs1 < imm}};                    // Returns 0xFFFFFFFF when true
```

**After (Correct per RISC-V Spec):**
```verilog
INSTR_SLT:   ALUoutput = {31'b0, $signed(rs1) < $signed(rs2)};  // Returns 0 or 1
INSTR_SLTU:  ALUoutput = {31'b0, rs1 < rs2};                    // Returns 0 or 1
INSTR_SLTI:  ALUoutput = {31'b0, $signed(rs1) < $signed(imm)};  // Returns 0 or 1
INSTR_SLTIU: ALUoutput = {31'b0, rs1 < imm};                    // Returns 0 or 1
```

---

## Bug Fixes

### Bug 1: SLT/SLTU Return Value (alu.v)

**Symptom:** Comparison instructions returned 0xFFFFFFFF (-1) instead of 1 when true.

**Root Cause:** Using `{32{comparison}}` replicates the 1-bit result 32 times.

**Fix:** Use `{31'b0, comparison}` to zero-extend the 1-bit result.

**RISC-V Spec:** "SLT and SLTU write 1 to rd if rs1 < rs2, 0 otherwise."

---

### Bug 2: Register File Reset (registerfile.v)

**Symptom:** Register values persisted across test runs, causing test failures.

**Root Cause:** Register file used `initial` blocks which only work in simulation and don't respond to reset.

**Fix:** Added proper `rst` input and synchronous reset logic that clears all registers.

---

### Bug 3: Pipeline Flush During Cache Stall (riscv_cpu.v)

**Symptom:** Instructions after taken branches executed (appeared as delay slot).

**Root Cause:** When branch was taken AND cache was stalled:
- IF_ID received NOP as input (correct)
- But IF_ID stall was high due to cache miss
- IF_ID held its OLD value instead of latching the NOP
- The old instruction (after the branch) eventually executed

**Fix:** Branch flush must override cache stall:
```verilog
wire if_id_stall;
assign if_id_stall = combined_stall && !branch_flush;
```

**RISC-V Spec:** "RISC-V does not have delay slots."

---

## Test Suite

### Test Categories and Count

| Category | Tests | Description |
|----------|-------|-------------|
| Cache Operations | 5 | Cold start, hit/miss, line boundaries, stalls |
| R-Type Instructions | 4 | Arithmetic, logical, shift, compare |
| I-Type Instructions | 3 | Arithmetic, logical, shift |
| Load/Store | 3 | Word, byte, halfword |
| Branches | 2 | BEQ/BNE, BLT/BGE/BLTU/BGEU |
| Jumps | 2 | JAL, JALR |
| U-Type | 1 | LUI, AUIPC |
| Hazards | 3 | RAW, Load-Use, Control |
| FENCE.I | 1 | Cache invalidation |
| CSR | 2 | Read/Write, Immediate |
| Complex | 3 | Nested loops, function calls, memory ops |
| **Total** | **29** | |

### Running Tests

```bash
cd tests/system_tests
python3 test_full_integration.py
```

Expected output: `TESTS=29 PASS=29 FAIL=0 SKIP=0`

---

## Architecture Changes

### Memory Hierarchy (Before)

```
CPU → Instruction Memory
```

### Memory Hierarchy (After)

```
CPU → Instruction Cache → Instruction Memory
        ↑
        └── FENCE.I invalidation
```

### Cache Configuration

| Parameter | Value |
|-----------|-------|
| Associativity | 4-way |
| Number of Sets | 64 |
| Words per Line | 4 |
| Line Size | 16 bytes |
| Total Size | 4 KB |
| Replacement Policy | Round-robin |

### Pipeline Stall Sources

1. **Load-Use Hazard**: Detected by `load_use_detector`, causes 1-cycle stall
2. **Cache Miss**: Indicated by `icache_stall`, stalls until refill complete
3. **Combined**: `combined_stall = stall_pipeline || icache_stall`

### Branch Handling

1. Branch decision made in EX stage
2. `branch_flush` signal asserts
3. IF_ID flushes (latches NOP, overriding any stall)
4. ID_EX inserts bubble
5. PC updates to branch target

---

## Verification

All 29 tests pass, verifying:
- ✅ Cache correctly handles cold start misses
- ✅ Cache hits after refill
- ✅ Multi-line programs work correctly
- ✅ All RV32I instructions execute correctly
- ✅ Pipeline hazards resolved correctly
- ✅ Branches have no delay slots
- ✅ FENCE.I invalidates cache
- ✅ CSR instructions work correctly
- ✅ Complex programs (loops, function calls) work correctly
