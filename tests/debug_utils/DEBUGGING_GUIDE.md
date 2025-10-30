# 🔍 Comprehensive Debugging Guide for RISC-V Pipeline Stall Bugs

## 📋 Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Bug Descriptions](#bug-descriptions)
4. [Debugging Workflow](#debugging-workflow)
5. [Tool Reference](#tool-reference)
6. [GTKWave Analysis](#gtkwave-analysis)
7. [Fix Implementation](#fix-implementation)
8. [Validation](#validation)

---

## Overview

This guide provides a systematic approach to debugging the 5 known pipeline stall bugs in the Synapse-32 RISC-V CPU. These bugs occur during cache integration when multi-cycle stalls interact with pipeline control signals.

### The Problem

The CPU has a 5-stage pipeline (IF → ID → EX → MEM → WB) with an instruction cache that can stall for 19 cycles on a cache miss. During these stalls, pipeline bubbles propagate through the stages. However, **write enables aren't properly gated**, causing:

1. Invalid memory writes during stalls
2. Register corruption from bubble instructions
3. Loads returning garbage data
4. Address decoding races

### The Solution

Gate all architectural state changes with stall signals:
```verilog
assign write_enable = instruction_valid && !cache_stall && !hazard_stall;
```

---

## Quick Start

### Step 1: Run Enhanced Diagnostic Test

```bash
cd /home/shashvat/synapse32/tests
source .venv/bin/activate

# Run enhanced test with full debugging
python debug_utils/enhanced_test_runner.py run
```

This will:
- Execute the combined stall test
- Detect bugs in real-time
- Generate comprehensive reports
- Create GTKWave save files

### Step 2: Review Output

Check `tests/debug_output/`:
- `bug_report.json` - Detailed bug analysis
- `pipeline_trace.txt` - ASCII pipeline visualization
- Console logs with cycle-by-cycle analysis

### Step 3: Visualize in GTKWave

```bash
# Find the generated VCD file
ls -lh sim_build/enhanced_combined_stall/*.vcd

# Open in GTKWave with pre-configured view
gtkwave sim_build/enhanced_combined_stall/dump.vcd gtkwave_views/overview.gtkw
```

---

## Bug Descriptions

### Bug #1: Memory Write Enable Not Gated ⚠️ CRITICAL

**Location:** `rtl/memory_unit.v:27`

**Problem:**
```verilog
assign wr_enable = is_store && valid_in;  // ❌ Missing stall check!
```

**Symptom:**
- Memory writes occur during cache stalls
- Wrong addresses get written (often 0x00000000)
- Corrupts program data

**Detection Pattern:**
```
wr_enable=1 && (cache_stall=1 || load_use_stall=1)
```

**Fix:**
```verilog
module memory_unit (
    input wire cache_stall,      // ADD
    input wire hazard_stall,     // ADD
    // ... other inputs
);

assign wr_enable = is_store && valid_in && !cache_stall && !hazard_stall;  // ✅
```

---

### Bug #2: Memory Read Enable Not Gated ⚠️ CRITICAL

**Location:** `rtl/memory_unit.v:28`

**Problem:**
```verilog
assign read_enable = is_load && valid_in;  // ❌ Missing stall check!
```

**Symptom:**
- Spurious memory reads during stalls
- Can trigger unintended side effects in peripherals

**Fix:**
```verilog
assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;  // ✅
```

---

### Bug #3: Writeback Enable Not Gated ⚠️ CRITICAL

**Location:** `rtl/writeback.v:20`

**Problem:**
```verilog
assign wr_en_out = valid_in && rd_valid_in;  // ❌ Missing stall check!
```

**Symptom:**
- Register file writes occur during stalls
- Bubble instructions write garbage to registers
- Subsequent instructions use corrupted values

**Detection Pattern:**
```
wr_en_out=1 && (cache_stall=1 || load_use_stall=1)
```

**Fix:**
```verilog
module writeback (
    input wire cache_stall,      // ADD
    input wire hazard_stall,     // ADD
    // ... other inputs
);

assign wr_en_out = valid_in && rd_valid_in && !cache_stall && !hazard_stall;  // ✅
```

---

### Bug #5: Memory Data Register Samples During Stalls ⚠️ CRITICAL

**Location:** `rtl/top.v:112`

**Problem:**
```verilog
always @(posedge clk) begin
    if (cpu_mem_read_en) begin
        mem_data_reg <= mem_read_data;  // ❌ Samples during stalls!
    end
end
```

**Symptom:**
- Loads return 0 or garbage values
- Memory data captured before it's ready
- Timing violation - samples combinational logic

**Scenario:**
```
Cycle 1:  Cache miss detected, mem_data_reg samples undefined value
Cycles 2-19: Stalled, but mem_data_reg already corrupted
Cycle 20: Stall ends, CPU gets garbage data
```

**Fix:**
```verilog
always @(posedge clk) begin
    if (cpu_mem_read_en && !cache_stall) begin  // ✅ Only sample when ready
        mem_data_reg <= mem_read_data;
    end
end
```

---

### Bug #6: Address Decoding Race Condition ⚠️ HIGH

**Location:** `rtl/top.v:54-57`

**Problem:**
```verilog
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;

// ❌ Uses data_mem_addr before it's stable!
assign data_mem_access = `IS_DATA_MEM(data_mem_addr) || ...
```

**Symptom:**
- Loads return instruction data (e.g., 0x10000237)
- Instruction memory accessed instead of data memory
- Intermittent - depends on synthesis timing

**Fix:**
```verilog
// ✅ Check addresses directly, not through mux
assign data_mem_access = (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                        (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

// Mux can be after checks
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
```

---

## Debugging Workflow

### Phase 1: Data Collection

1. **Run enhanced test to collect traces:**
   ```bash
   python debug_utils/enhanced_test_runner.py run
   ```

2. **Check test output for failures:**
   - Which registers have wrong values?
   - How many bug occurrences detected?
   - What cycles do bugs occur?

3. **Review bug report:**
   ```bash
   cat debug_output/bug_report.json
   ```

### Phase 2: Visual Analysis

1. **Open pipeline trace:**
   ```bash
   less debug_output/pipeline_trace.txt
   ```
   Look for cycles marked with "BUG#X"

2. **Open GTKWave:**
   ```bash
   gtkwave sim_build/enhanced_combined_stall/dump.vcd gtkwave_views/overview.gtkw
   ```

3. **Navigate to bug cycles:**
   - Use bug report's "first_occurrence" cycle
   - Set GTKWave time marker to that cycle
   - Observe signal interactions

### Phase 3: Root Cause Confirmation

For each bug type:

**Bug #1/2 (Memory Unit):**
1. Find cycle where `cache_stall=1`
2. Check if `wr_enable=1` or `read_enable=1`
3. Verify `valid_in=1` (stale instruction)
4. **Root cause:** No stall check in memory_unit.v

**Bug #3 (Writeback):**
1. Find cycle where `cache_stall=1`
2. Check if `wr_en_out=1`
3. Check if `rf_inst0_wr_en=1` (actual write happening)
4. **Root cause:** No stall check in writeback.v

**Bug #5 (Memory Data Reg):**
1. Find cache miss event
2. Observe `cache_stall=1` for 19 cycles
3. Watch `mem_data_reg` value
4. If it changes during stall, that's the bug
5. **Root cause:** Always samples when `cpu_mem_read_en=1`

**Bug #6 (Address Decode):**
1. Find data memory load (addr=0x1000xxxx)
2. Check `data_mem_access` and `instr_mem_access`
3. If both =1 simultaneously, that's the race
4. Check `mem_read_data` - might be instruction
5. **Root cause:** Combinational race in address mux

### Phase 4: Fix Implementation

See [Fix Implementation](#fix-implementation) section below.

---

## Tool Reference

### enhanced_test_runner.py

**Purpose:** Run tests with integrated debugging

**Usage:**
```bash
python debug_utils/enhanced_test_runner.py run
```

**Output:**
- Real-time bug detection during simulation
- Console logs with cycle-by-cycle analysis
- JSON bug reports
- Pipeline trace files

### signal_tracer.py

**Purpose:** Parse VCD files and extract signals

**Usage:**
```bash
python debug_utils/signal_tracer.py <vcd_file>
```

**Output:**
- Bug occurrence list with cycles
- Signal correlation analysis
- Can be used on any VCD file

### bug_detector.py

**Purpose:** Automated bug pattern recognition

**Usage:**
```python
from debug_utils import AdvancedBugDetector, PipelineState

detector = AdvancedBugDetector()
# Add states...
reports = detector.detect_all_bugs()
print(detector.generate_summary())
```

**Output:**
- Structured bug reports
- Root cause analysis
- Fix recommendations

### pipeline_trace.py

**Purpose:** ASCII visualization of pipeline

**Usage:**
```python
from debug_utils import PipelineVisualizer

viz = PipelineVisualizer()
# Add cycle states...
print(viz.render_full_trace())
```

**Output:**
- Color-coded pipeline display
- Stall and write enable visualization
- Bug markers

### gtkwave_generator.py

**Purpose:** Generate GTKWave save files

**Usage:**
```bash
python debug_utils/gtkwave_generator.py <vcd_file> [output_dir]
```

**Output:**
- Pre-configured signal views for each bug
- Overview with all critical signals
- Ready to open in GTKWave

---

## GTKWave Analysis

### Opening GTKWave

```bash
# With overview
gtkwave dump.vcd gtkwave_views/overview.gtkw

# With specific bug view
gtkwave dump.vcd gtkwave_views/bug1_memory_write_stall.gtkw
```

### Key Signal Groups

**Stall Signals (Yellow/Cyan):**
- `cache_stall_debug` - Cache miss stall
- `load_use_stall` - Load-use hazard stall

**Write Enables (Red - should be 0 during stalls):**
- `cpu_mem_write_en` - Memory write enable
- `wb_inst0_wr_en_out` - Writeback write enable
- `rf_inst0_wr_en` - Register file write enable

**Valid Bits:**
- `if_id_valid_out` - IF/ID stage valid
- `id_ex_valid_out` - ID/EX stage valid
- `ex_mem_valid_out` - EX/MEM stage valid
- `mem_wb_valid_out` - MEM/WB stage valid

**Memory Interface:**
- `mem_data_reg` - Registered memory data
- `mem_read_data` - Combinational memory data
- `data_mem_access` - Data memory selected
- `instr_mem_access` - Instruction memory selected

### Finding Bugs in GTKWave

1. **Zoom to bug cycle** (from bug report)
2. **Check stall signals** - should be 1
3. **Check write enables** - should be 0 but aren't
4. **Check valid bits** - may show stale instruction
5. **Observe corruption** - wrong data written

---

## Fix Implementation

### Priority Order

1. **Bug #5** (mem_data_reg sampling) - EASIEST FIX
2. **Bug #1** (memory write enable) - REQUIRES MODULE CHANGES
3. **Bug #3** (writeback enable) - REQUIRES MODULE CHANGES
4. **Bug #6** (address decode race) - LOGIC REORDERING
5. **Bug #2** (memory read enable) - SAME AS BUG #1

### Implementation Steps

#### Step 1: Fix Bug #5 (Quickest Win)

**File:** `rtl/top.v`

**Change:**
```verilog
// Line ~112
always @(posedge clk) begin
    if (rst) begin
        mem_data_reg <= 32'b0;
    end else if (cpu_mem_read_en && !cache_stall) begin  // ADD: && !cache_stall
        mem_data_reg <= mem_read_data;
    end
end
```

**Test:**
```bash
pytest system_tests/combined_stall_test.py -v
```

**Expected:** Some improvement, but not complete fix.

---

#### Step 2: Fix Bug #1 & #2 (Memory Unit)

**File:** `rtl/memory_unit.v`

**Changes:**

1. Add stall inputs to module:
```verilog
module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire cache_stall,        // ADD THIS
    input wire hazard_stall,       // ADD THIS
    // ... rest of inputs
);
```

2. Gate write and read enables:
```verilog
// Around line 27-28
assign wr_enable = is_store && valid_in && !cache_stall && !hazard_stall;
assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;
```

3. Update instantiation in `rtl/riscv_cpu.v`:
```verilog
memory_unit mem_unit_inst0 (
    .clk(clk),
    .rst(rst),
    .valid_in(ex_mem_valid_out),
    .cache_stall(cache_stall),      // ADD THIS
    .hazard_stall(load_use_stall),  // ADD THIS
    // ... rest of connections
);
```

---

#### Step 3: Fix Bug #3 (Writeback)

**File:** `rtl/writeback.v`

**Changes:**

1. Add stall inputs:
```verilog
module writeback (
    input wire valid_in,
    input wire rd_valid_in,
    input wire cache_stall,        // ADD THIS
    input wire hazard_stall,       // ADD THIS
    // ... rest of inputs
);
```

2. Gate write enable:
```verilog
// Around line 20
assign wr_en_out = valid_in && rd_valid_in && !cache_stall && !hazard_stall;
```

3. Update instantiation in `rtl/riscv_cpu.v`:
```verilog
writeback wb_inst0 (
    .valid_in(mem_wb_valid_out),
    .rd_valid_in(mem_wb_inst0_rd_valid_out),
    .cache_stall(cache_stall),      // ADD THIS
    .hazard_stall(load_use_stall),  // ADD THIS
    // ... rest of connections
);
```

---

#### Step 4: Fix Bug #6 (Address Decode)

**File:** `rtl/top.v`

**Change:**
```verilog
// Around line 54-57
// OLD (has race):
// assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
// assign data_mem_access = `IS_DATA_MEM(data_mem_addr) || ...

// NEW (no race):
assign data_mem_access = (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                        (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign timer_access = (`IS_TIMER_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                     (`IS_TIMER_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign uart_access = (`IS_UART_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                    (`IS_UART_MEM(cpu_mem_write_addr) && cpu_mem_write_en);

assign instr_mem_access = (`IS_INSTR_MEM(cpu_mem_read_addr) && cpu_mem_read_en);

// Mux can stay after checks
assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
```

---

## Validation

### Test Suite

Run full test suite after each fix:

```bash
cd tests
source .venv/bin/activate

# Individual tests
pytest system_tests/comprehensive_load_test.py -v
pytest system_tests/combined_stall_test.py -v

# All system tests
pytest system_tests/ -v

# With enhanced debugging
python debug_utils/enhanced_test_runner.py run
```

### Success Criteria

**Before Fixes:**
- ❌ x8 = 100 (should be 142)
- ❌ x13 = 268436023 (should be 701)
- ❌ Bug report shows 10+ occurrences

**After Fixes:**
- ✅ x8 = 142
- ✅ x13 = 701
- ✅ Bug report shows 0 occurrences
- ✅ All register values correct
- ✅ No garbage writes to memory

### GTKWave Verification

After fixes, re-run with waveforms:

```bash
python debug_utils/enhanced_test_runner.py run
gtkwave sim_build/enhanced_combined_stall/dump.vcd gtkwave_views/overview.gtkw
```

**Check:**
1. When `cache_stall=1`, all write enables should be 0
2. `mem_data_reg` shouldn't change during stalls
3. No simultaneous `data_mem_access` and `instr_mem_access`

---

## Troubleshooting

### "Signal not found in VCD"

Some signals might have different hierarchical paths. Use GTKWave's signal search or update the save files.

### "Test still failing after fixes"

1. Verify all module changes were saved
2. Check instantiations have new connections
3. Ensure clean build: `rm -rf sim_build/; pytest ...`
4. Re-run with `force_compile=True`

### "Bugs detected but tests pass"

Partial fixes may improve correctness but not eliminate all bugs. Apply all fixes for complete resolution.

---

## Additional Resources

- `problem.md` - Original problem statement
- `solutions.md` - Quick fix reference
- Research PDF - Academic analysis of bug patterns
- `debug_utils/README.md` - Tool documentation

---

## Summary

The core issue is **ungated write enables during stalls**. Pipeline bubbles have `valid=0` but that alone doesn't prevent writes. You must also check `!stall`:

```verilog
// ❌ WRONG
assign write_enable = valid;

// ✅ CORRECT
assign write_enable = valid && !cache_stall && !hazard_stall;
```

This is a fundamental pipeline design pattern: **computed values can propagate, but architectural state changes must be guarded by both validity AND non-stall conditions**.

Good luck debugging! 🚀
