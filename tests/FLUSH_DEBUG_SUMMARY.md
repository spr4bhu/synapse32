# Flush Mechanism Debug Summary

**Date:** 2025-10-30
**Session:** Continuation of valid bit investigation
**Status:** Debugging in progress

---

## Problem Statement

The complex_valid_bit_test.py fails with 5 register corruptions even WITH valid bits present:
- x13 = 777 (expected 0) - flushed instruction executed
- x16 = 555 (expected 0) - flushed instruction executed
- x21 = 444 (expected 0) - flushed instruction executed
- x26 = 222 (expected 0) - flushed instruction executed
- x30 = 66 (expected 0) - flushed instruction executed

These are all instructions that should have been flushed by branch instructions but executed anyway.

---

## Investigation Steps Taken

### 1. Initial Fix Attempt (FAILED)
**File:** `/home/shashvat/synapse32/rtl/riscv_cpu.v` line 219
**Change:** `.valid_in(!cache_stall && !branch_flush)`
**Rationale:** Prevent new instructions from entering IF_ID with valid=1 when flush occurs
**Result:** Test still fails - this only prevents NEW instructions, not already-latched ones

### 2. Added Flush Input to IF_ID (PARTIAL)
**Files Modified:**
- `rtl/pipeline_stages/IF_ID.v` - added `flush` input port
- `rtl/riscv_cpu.v` line 219 - connected `branch_flush` to IF_ID

**Issue Discovered:** Timing mismatch!
- IF_ID samples on **negedge** clock (for cache timing)
- ID_EX samples on **posedge** clock
- When branch flushes at posedge, ID_EX sees it immediately
- But IF_ID doesn't see it until negedge (half cycle later)
- By then, ID_EX has already sampled the un-flushed instruction from IF_ID!

### 3. Combinational Override (ATTEMPTED)
**File:** `rtl/pipeline_stages/IF_ID.v` line 22
**Change:** `assign valid_out = flush ? 1'b0 : valid_out_reg;`
**Rationale:** Force valid_out to 0 combinationally when flush is high, bypassing clock edge timing
**Result:** Test still fails

---

## Key Findings from Debug Output

### Timing Analysis

```
@480000: BEQ taken! Flushing pipeline, jump_addr=0x00000028
@485000: IF_ID FLUSH! Invalidating instruction
@490000: ID_EX FLUSH! Inserting bubble
@520000: CRITICAL WRITE to x13 = 777 valid_in=1 ← BUG!
```

**Timeline:**
1. Branch executes at 480ns (in EX stage)
2. IF_ID flushes at 485ns (negedge, 5ns later)
3. ID_EX flushes at 490ns (posedge, 10ns after branch)
4. Instruction writes at 520ns (40ns after branch = 4 clock cycles)
5. **The instruction reaches writeback with valid_in=1** ← This is the bug!

### Pipeline State When Branch Executes

When `beq x9, x10, +12` is in EX stage:
```
WB:   (older instruction)
MEM:  (older instruction)
EX:   beq x9, x10, +12      ← Branch detects here, sets flush=1
ID:   addi x11, x0, 999      ← Should be flushed (in ID_EX register)
IF:   addi x12, x0, 888      ← Should be flushed (in IF_ID register)
      addi x13, x0, 777      ← Not yet fetched
```

**Expected:** x11, x12 should be flushed. x13 should never execute.
**Actual:** x13=777 is written with valid_in=1

---

## Hypothesis: The Real Bug

The instruction writing 777 to x13 shouldn't even be in the pipeline when the branch executes. But it DOES execute and reaches writeback with `valid_in=1`.

### Possible Causes:

1. **Multi-cycle execution:** The branch might be taking multiple cycles to execute, during which more instructions enter the pipeline

2. **Flush signal timing:** The flush might not be properly synchronized across all pipeline stages

3. **Valid bit not propagating through all stages:** One of EX_MEM or MEM_WB might not be checking/propagating valid bits correctly

4. **Instruction re-execution:** After flush, the wrong instructions might be getting re-fetched and executed

---

## Files Modified in This Session

1. `/home/shashvat/synapse32/rtl/riscv_cpu.v`
   - Line 219: Added `!branch_flush` check to valid_in
   - Line 219: Added `.flush(branch_flush)` connection to IF_ID

2. `/home/shashvat/synapse32/rtl/pipeline_stages/IF_ID.v`
   - Added `flush` input port
   - Added flush handling in always block
   - Changed `valid_out` to wire with combinational override
   - Added debug output for flush events

3. `/home/shashvat/synapse32/rtl/pipeline_stages/ID_EX.v`
   - Added debug output when flush occurs

4. `/home/shashvat/synapse32/rtl/execution_unit.v`
   - Added debug output when BEQ taken

5. `/home/shashvat/synapse32/rtl/writeback.v`
   - Added debug output for critical register writes (x13, x16, x21, x26, x30)

---

## Next Steps to Debug

### Option 1: Track Valid Bit Through All Stages
Add debug output to track the valid bit as it propagates:
- EX_MEM: When instruction with rd=13 enters
- MEM_WB: When instruction with rd=13 enters
- Writeback: Already has debug

### Option 2: Check EX_MEM and MEM_WB Flush Handling
Currently only IF_ID and ID_EX have flush inputs. Check if EX_MEM or MEM_WB need flush capability.

**Standard pipeline flush for branch:**
- Flush IF_ID: instruction on wrong path just fetched
- Flush ID_EX: instruction on wrong path being decoded
- DON'T flush EX_MEM: that's the branch itself or older valid instruction

### Option 3: Check PC Behavior
Verify that PC is correctly jumping to branch target and not looping back.

### Option 4: Simplify Test
Create minimal test with just:
```
addi x9, x0, 5
addi x10, x0, 5
beq x9, x10, +12
addi x13, x0, 777  # Should be flushed
nop
nop
# Target:
addi x13, x0, 42   # Should execute
```

Run with cycle-by-cycle debug to see exact pipeline state.

---

## Current CPU State

- All valid bits are present and connected
- IF_ID, ID_EX, EX_MEM, MEM_WB all propagate valid bits
- Execution unit gates execution on valid_in=0
- Memory unit gates operations on valid_in=0
- Writeback gates register writes on valid_in=0
- Flush signals are connected to IF_ID and ID_EX

---

## Test Results

- `combined_stall_test.py`: ✅ PASS (5/5)
- `complex_valid_bit_test.py`: ❌ FAIL (20/25, 80%)
  - 5 critical failures: flushed instructions still execute

---

**Conclusion:** The flush mechanism has a subtle bug where instructions that should be flushed are still reaching writeback with valid_in=1. The root cause is not yet identified but is likely related to timing, valid bit propagation through later pipeline stages, or PC/fetch behavior after a flush.
