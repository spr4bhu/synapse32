# Phase 3d: Full Memory Hierarchy Integration Plan

**Date**: December 30, 2024
**Status**: Planning
**Goal**: Integrate load queue, store queue, and dcache_mshr into the CPU pipeline

---

## Executive Summary

We now have **4 production-ready components** with 100% test pass rate:
- ✅ Load Queue (10/10 tests)
- ✅ Store Queue (8/8 tests)
- ✅ D-Cache + MSHR (dcache_mshr.v, 27/27 tests)
- ✅ MSHR Standalone (13/13 tests)

**Phase 3d Goal**: Connect these components to the CPU pipeline in `riscv_cpu.v` and `top.v` to enable:
1. Out-of-order load completion
2. Store-to-load forwarding
3. Non-blocking D-cache with hit-during-refill
4. Multiple outstanding cache misses

---

## Current Architecture (Baseline)

### Data Memory Path (Current - Direct Connection)
```
CPU Pipeline (EX Stage)
    ↓
    mem_rd_en / mem_wr_en
    ↓
top.v (address decoding)
    ↓
data_mem.v (blocking SRAM)
    ↓
module_read_data_in
    ↓
CPU Pipeline (WB Stage)
```

### Key Files
- **riscv_cpu.v**: CPU pipeline (IF/ID/EX/MEM/WB stages)
  - Lines 11-15: Memory interface outputs (module_mem_rd_en, module_mem_wr_en, etc.)
  - Lines 88-98: Direct connection from decoder to memory

- **top.v**: Top-level integration
  - Lines 64-70: Address decoding and data multiplexing
  - Lines 136-149: Direct data memory instantiation

### Current Memory Interface
```verilog
// From riscv_cpu.v
output wire module_mem_wr_en,        // Write enable
output wire module_mem_rd_en,        // Read enable
output wire [31:0] module_read_addr,  // Read address
output wire [31:0] module_write_addr, // Write address
output wire [31:0] module_wr_data_out, // Write data
output wire [3:0] module_write_byte_enable, // Byte enables
output wire [2:0] module_load_type,   // Load type (LB/LH/LW/LBU/LHU)
input wire [31:0] module_read_data_in, // Read data
```

**Problem**: This is a **blocking, single-cycle interface**. Loads/stores complete in 1 cycle or stall the entire pipeline.

---

## Target Architecture (Phase 3d)

### New Data Memory Path (Non-Blocking)
```
CPU Pipeline (EX Stage)
    ↓
    [Load Detector] ────→ Load Queue (in riscv_cpu.v)
    [Store Detector] ───→ Store Queue (in riscv_cpu.v)
    ↓
    Memory Arbiter (in riscv_cpu.v)
    ↓
top.v: D-Cache + MSHR (dcache_mshr.v)
    ↓
    Memory Controller (in top.v)
    ↓
data_mem.v (backing store)
    ↓
    [Refill Data] ────→ dcache_mshr
    ↓
    Load Queue (data ready) ────→ WB Stage
```

### Store-to-Load Forwarding Path
```
Store Queue (CAM lookup in EX)
    ↓
    [Match on address] ────→ Forward data
    ↓
Load Queue (bypass cache)
    ↓
WB Stage (write register file)
```

---

## Implementation Strategy

We'll use **Option B (MSHR-Enhanced)** since we already have dcache_mshr.v working perfectly.

### Incremental Steps (4 levels)

#### **Level 0: Preparation** (1-2 hours)
1. Add `load_queue.v` and `store_queue.v` to `riscv_cpu.v` includes
2. Add `dcache_mshr.v` to `top.v` includes
3. Create new internal wires in `riscv_cpu.v` for queue interfaces
4. Create new internal wires in `top.v` for cache interface
5. **No functional changes** - compile verification only

#### **Level 1: Queue Integration (Blocking Cache)** (4-6 hours)
**Goal**: Get load/store queues working with existing blocking data_mem

**Changes in riscv_cpu.v**:
1. Instantiate `load_queue` and `store_queue` modules
2. Detect loads/stores in EX stage:
   ```verilog
   wire is_load = (id_ex_inst0_instr_id_out == INSTR_LW ||
                   id_ex_inst0_instr_id_out == INSTR_LH || ...);
   wire is_store = (id_ex_inst0_instr_id_out == INSTR_SW || ...);
   ```
3. Connect EX stage → Load Queue:
   - `lq_enqueue` when `is_load` detected
   - `lq_enqueue_addr` = EX stage address
   - `lq_enqueue_type` = load type
   - `lq_enqueue_rd` = destination register
4. Connect EX stage → Store Queue:
   - `sq_enqueue` when `is_store` detected
   - `sq_enqueue_addr` = EX stage address
   - `sq_enqueue_data` = EX stage write data
   - `sq_enqueue_byte_en` = byte enables
5. Memory arbiter (simple priority):
   ```verilog
   // Priority: Store queue almost full → loads → stores
   assign grant_store = sq_mem_write_valid && (
       !lq_mem_req_valid || sq_almost_full || !lq_almost_full
   );
   assign grant_load = lq_mem_req_valid && !grant_store;

   // Mux to top-level
   assign module_mem_rd_en = grant_load;
   assign module_mem_wr_en = grant_store;
   assign module_read_addr = grant_load ? lq_mem_req_addr : 32'h0;
   assign module_write_addr = grant_store ? sq_mem_write_addr : 32'h0;
   // ... etc
   ```
6. Connect memory responses back to queues:
   ```verilog
   assign lq_mem_resp_valid = module_read_data_valid && grant_load;
   assign lq_mem_resp_data = module_read_data_in;
   ```
7. Connect Load Queue → WB stage:
   ```verilog
   // WB stage sources: Load queue, store queue (for SC), or normal pipeline
   wire [31:0] wb_data = lq_dequeue_valid ? lq_dequeue_data :
                         sq_retire_sc_valid ? sq_retire_sc_result :
                         mem_wb_inst0_result_out;
   ```
8. Store-to-load forwarding:
   ```verilog
   // In EX stage: Check if load matches store queue
   wire sq_forward_valid;
   wire [31:0] sq_forward_data;

   // Connect to store queue CAM
   assign sq_lookup_addr = ex_stage_address;  // Load address
   assign sq_lookup_type = ex_stage_load_type;
   assign sq_forward_valid = sq_lookup_hit;
   assign sq_forward_data = sq_lookup_data;

   // Bypass to load queue (don't issue memory request if forwarded)
   assign lq_enqueue_data_valid = sq_forward_valid;
   assign lq_enqueue_data = sq_forward_data;
   ```

**Testing Strategy**:
- Write simple test with 1 load, 1 store
- Verify load queue allocates, issues memory request, retires
- Verify store queue allocates, retires to memory
- Test store-to-load forwarding (store then load same address)

#### **Level 2: D-Cache Integration** (3-4 hours)
**Goal**: Replace blocking data_mem with dcache_mshr.v in top.v

**Changes in top.v**:
1. Instantiate `dcache_mshr` instead of direct `data_mem`:
   ```verilog
   dcache_mshr #(
       .ADDR_WIDTH(32),
       .DATA_WIDTH(32),
       .NUM_WAYS(4),
       .NUM_SETS(128),
       .LINE_SIZE(64),
       .NUM_MSHR(8)
   ) dcache_inst (
       .clk(clk),
       .rst(rst),

       // CPU interface (from riscv_cpu.v via top-level wires)
       .cpu_req_valid(cpu_dcache_req_valid),
       .cpu_req_addr(cpu_dcache_req_addr),
       .cpu_req_write(cpu_dcache_req_write),
       .cpu_req_wdata(cpu_dcache_req_wdata),
       .cpu_req_byte_en(cpu_dcache_req_byte_en),
       .cpu_req_ready(cpu_dcache_req_ready),
       .cpu_resp_valid(cpu_dcache_resp_valid),
       .cpu_resp_rdata(cpu_dcache_resp_rdata),

       // Memory interface (to data_mem backing store)
       .mem_req_valid(dcache_mem_req_valid),
       .mem_req_addr(dcache_mem_req_addr),
       .mem_req_write(dcache_mem_req_write),
       .mem_req_wdata(dcache_mem_req_wdata),
       .mem_req_ready(dcache_mem_req_ready),
       .mem_resp_valid(dcache_mem_resp_valid),
       .mem_resp_rdata(dcache_mem_resp_rdata),

       // Flush interface
       .flush_req(1'b0)  // TODO: Add FENCE.D support later
   );
   ```

2. Adapt CPU interface to cache:
   ```verilog
   // In riscv_cpu.v, expose new cache interface:
   output wire cpu_dcache_req_valid,
   output wire [31:0] cpu_dcache_req_addr,
   output wire cpu_dcache_req_write,
   // ... etc

   // Arbiter drives cache:
   assign cpu_dcache_req_valid = grant_load || grant_store;
   assign cpu_dcache_req_write = grant_store;
   assign cpu_dcache_req_addr = grant_store ? sq_mem_write_addr : lq_mem_req_addr;
   // ... etc
   ```

3. Connect cache → data_mem backing store:
   ```verilog
   // Cache refills go to data_mem
   assign dcache_mem_req_ready = 1'b1;  // data_mem always ready (1-cycle)

   // Multi-cycle refill simulation
   reg mem_resp_valid_r;
   reg [511:0] mem_resp_rdata_r;

   always @(posedge clk) begin
       if (dcache_mem_req_valid && !dcache_mem_req_write) begin
           // Read: Load full cache line from data_mem
           // (Simulate 512-bit read by reading 16 words)
           mem_resp_valid_r <= 1'b1;
           // ... construct 512-bit line from data_mem
       end else if (dcache_mem_req_valid && dcache_mem_req_write) begin
           // Write: Store full cache line to data_mem
           // (Simulate by writing 16 words)
           // ... write 512-bit line to data_mem
       end else begin
           mem_resp_valid_r <= 1'b0;
       end
   end

   assign dcache_mem_resp_valid = mem_resp_valid_r;
   assign dcache_mem_resp_rdata = mem_resp_rdata_r;
   ```

**Testing Strategy**:
- Test cache hit (load from cached address)
- Test cache miss (load triggers refill)
- Test hit-during-refill (load hits while refill in progress)
- Test write-back (dirty eviction writes to backing store)

#### **Level 3: Pipeline Stall Removal** (2-3 hours)
**Goal**: Remove blocking stalls from load/store operations

**Changes in riscv_cpu.v**:
1. Remove old load-use stall logic (keep only for special cases):
   ```verilog
   // Old: Stall pipeline on any load
   // New: Only stall if load queue full
   assign stall_pipeline = lq_full || sq_full || icache_stall;
   ```

2. Add queue full signals to hazard detection:
   ```verilog
   // In load_use_detector.v: Only stall if queue can't accept
   assign stall_pipeline = (is_load && lq_full) ||
                          (is_store && sq_full) ||
                          // Keep original RAW hazard detection for non-memory ops
                          (original_raw_hazard && !is_load && !is_store);
   ```

3. Update WB stage to handle out-of-order completion:
   ```verilog
   // WB arbiter: Load queue, store queue, or normal pipeline
   wire wb_source_lq = lq_dequeue_valid;
   wire wb_source_sq = sq_retire_sc_valid;
   wire wb_source_pipeline = !wb_source_lq && !wb_source_sq;

   assign rf_inst0_wr_en = wb_source_lq || wb_source_sq ||
                           (mem_wb_inst0_rd_valid_out && wb_source_pipeline);
   assign rf_inst0_rd_in = wb_source_lq ? lq_dequeue_rd :
                           wb_source_sq ? sq_retire_rd :
                           mem_wb_inst0_rd_addr_out;
   assign rf_inst0_rd_value_in = wb_source_lq ? lq_dequeue_data :
                                 wb_source_sq ? sq_retire_sc_result :
                                 mem_wb_inst0_result_out;
   ```

**Testing Strategy**:
- Test multiple outstanding loads (issue 3 loads back-to-back)
- Test loads completing out-of-order
- Test pipeline continues during cache miss (not stalled)

#### **Level 4: Full Integration Testing** (4-6 hours)
**Goal**: Verify end-to-end correctness with real programs

**Test Cases**:
1. **Basic Functionality**:
   - Load/store sequences
   - Store-to-load forwarding (SW then LW same address)
   - Queue wraparound (allocate/retire 20+ loads)

2. **Cache Behavior**:
   - Cache hit path (repeated loads from same address)
   - Cache miss path (load from uncached address)
   - Hit-during-refill (load different address while refill pending)
   - Write-back eviction (write dirty line, load conflicting address)

3. **Edge Cases**:
   - Queue full conditions (issue 9 loads, verify 9th stalls)
   - Multiple outstanding misses (8 MSHRs, issue 8 loads to different lines)
   - MSHR coalescing (2 loads to same line during refill)

4. **Hazards**:
   - RAW hazard with forwarding (ADD then use result in load address)
   - Load-use with queue (load then use data immediately)
   - Store-load aliasing (SW then LW same address, verify forwarding)

5. **Regression**:
   - Run existing CPU tests (system_tests/test_full_integration.py)
   - Verify no existing functionality broken

---

## File Changes Summary

### New Files
- None (all components already exist)

### Modified Files

#### rtl/riscv_cpu.v (Major Changes)
**Lines to modify**:
- ~11-15: Add new outputs for dcache interface
- ~98-150: Add load/store queue instantiations
- ~200-250: Add memory arbiter logic
- ~300-350: Update WB stage for out-of-order completion

**Estimated changes**: +300 lines

#### rtl/top.v (Major Changes)
**Lines to modify**:
- ~20-32: Add dcache interface wires
- ~64-70: Update memory path (riscv_cpu → dcache → data_mem)
- ~136-149: Replace direct data_mem with dcache_mshr + backing store

**Estimated changes**: +150 lines

#### tests/ (New Test Files)
- `system_tests/test_memory_hierarchy_integration.py` - End-to-end tests
- Estimated: +500 lines

---

## Detailed Interface Specifications

### Load Queue Interface (in riscv_cpu.v)
```verilog
// Enqueue (from EX stage)
wire lq_enqueue_valid;
wire [31:0] lq_enqueue_addr;
wire [2:0] lq_enqueue_type;  // LB/LH/LW/LBU/LHU
wire [4:0] lq_enqueue_rd;
wire lq_enqueue_ready;
wire lq_full;
wire lq_almost_full;

// Forwarding (from store queue in EX stage)
wire lq_enqueue_data_valid;  // Forwarded from store queue
wire [31:0] lq_enqueue_data;

// Memory request (to arbiter)
wire lq_mem_req_valid;
wire [31:0] lq_mem_req_addr;
wire [2:0] lq_mem_req_type;
wire lq_mem_req_ready;  // Granted by arbiter

// Memory response (from cache)
wire lq_mem_resp_valid;
wire [31:0] lq_mem_resp_data;

// Dequeue (to WB stage)
wire lq_dequeue_valid;
wire [4:0] lq_dequeue_rd;
wire [31:0] lq_dequeue_data;
wire lq_dequeue_ready;
```

### Store Queue Interface (in riscv_cpu.v)
```verilog
// Enqueue (from EX stage)
wire sq_enqueue_valid;
wire [31:0] sq_enqueue_addr;
wire [31:0] sq_enqueue_data;
wire [3:0] sq_enqueue_byte_en;
wire sq_enqueue_ready;
wire sq_full;
wire sq_almost_full;

// Lookup (from EX stage for forwarding to loads)
wire [31:0] sq_lookup_addr;
wire [2:0] sq_lookup_type;
wire sq_lookup_hit;
wire [31:0] sq_lookup_data;

// Memory write (to arbiter)
wire sq_mem_write_valid;
wire [31:0] sq_mem_write_addr;
wire [31:0] sq_mem_write_data;
wire [3:0] sq_mem_write_byte_en;
wire sq_mem_write_ready;  // Granted by arbiter

// Retire (from WB stage for SC instructions)
wire sq_retire_sc_valid;
wire [4:0] sq_retire_rd;
wire [31:0] sq_retire_sc_result;
```

### D-Cache Interface (riscv_cpu.v ↔ top.v)
```verilog
// CPU → Cache (from riscv_cpu.v arbiter)
wire cpu_dcache_req_valid;
wire [31:0] cpu_dcache_req_addr;
wire cpu_dcache_req_write;
wire [31:0] cpu_dcache_req_wdata;
wire [3:0] cpu_dcache_req_byte_en;
wire cpu_dcache_req_ready;

// Cache → CPU (to riscv_cpu.v queues)
wire cpu_dcache_resp_valid;
wire [31:0] cpu_dcache_resp_rdata;
```

### Memory Backing Store Interface (top.v: dcache ↔ data_mem)
```verilog
// Cache → Memory (refill/writeback requests)
wire dcache_mem_req_valid;
wire [31:0] dcache_mem_req_addr;  // Line address
wire dcache_mem_req_write;
wire [511:0] dcache_mem_req_wdata;  // Full cache line (64 bytes)
wire dcache_mem_req_ready;

// Memory → Cache (refill data)
wire dcache_mem_resp_valid;
wire [511:0] dcache_mem_resp_rdata;  // Full cache line (64 bytes)
```

---

## Memory Arbiter Logic (in riscv_cpu.v)

### Priority-Based Arbitration
```verilog
// Arbiter inputs
wire lq_mem_req_valid;       // Load queue wants memory access
wire sq_mem_write_valid;     // Store queue wants memory access
wire lq_almost_full;         // Load queue almost full (>75%)
wire sq_almost_full;         // Store queue almost full (>75%)

// Arbiter outputs
wire grant_load;
wire grant_store;

// Priority logic (matches existing store_queue.v arbitration)
assign grant_store = sq_mem_write_valid && (
    !lq_mem_req_valid ||        // No competing load
    sq_almost_full ||           // SQ almost full - prioritize draining
    !lq_almost_full             // Neither full, stores get chance
);

assign grant_load = lq_mem_req_valid && !grant_store;

// Multiplex to cache interface
assign cpu_dcache_req_valid = grant_load || grant_store;
assign cpu_dcache_req_write = grant_store;
assign cpu_dcache_req_addr = grant_store ? sq_mem_write_addr : lq_mem_req_addr;
assign cpu_dcache_req_wdata = grant_store ? sq_mem_write_data : 32'h0;
assign cpu_dcache_req_byte_en = grant_store ? sq_mem_write_byte_en : 4'hF;

// Feedback to queues
assign lq_mem_req_ready = grant_load && cpu_dcache_req_ready;
assign sq_mem_write_ready = grant_store && cpu_dcache_req_ready;

// Demultiplex cache responses
assign lq_mem_resp_valid = cpu_dcache_resp_valid && !last_grant_was_store;
assign lq_mem_resp_data = cpu_dcache_resp_rdata;

// Track which queue got grant (for response routing)
reg last_grant_was_store;
always @(posedge clk) begin
    if (cpu_dcache_req_valid && cpu_dcache_req_ready) begin
        last_grant_was_store <= grant_store;
    end
end
```

---

## Testing Plan

### Level 1 Tests (Queue Integration)
**File**: `tests/system_tests/test_lsq_integration.py`

```python
# Test 1: Basic load
# LW x1, 0(x0)  # Load from address 0
# Verify: Load queue allocates, issues request, retires

# Test 2: Basic store
# SW x1, 0(x0)  # Store to address 0
# Verify: Store queue allocates, retires to memory

# Test 3: Store-to-load forwarding
# SW x1, 0(x0)  # Store 0xDEADBEEF to address 0
# LW x2, 0(x0)  # Load from address 0 (should forward)
# Verify: x2 = 0xDEADBEEF (forwarded, not from memory)

# Test 4: Multiple loads
# LW x1, 0(x0)
# LW x2, 4(x0)
# LW x3, 8(x0)
# Verify: 3 entries in load queue, all retire in order

# Test 5: Queue full stall
# Issue 9 loads (queue depth = 8)
# Verify: 9th load stalls pipeline until 1st retires
```

### Level 2 Tests (D-Cache Integration)
**File**: `tests/system_tests/test_dcache_integration.py`

```python
# Test 1: Cache hit
# SW x1, 0x1000(x0)  # Prime cache
# LW x2, 0x1000(x0)  # Should hit
# Verify: cpu_dcache_resp_valid immediately (1 cycle)

# Test 2: Cache miss
# LW x1, 0x2000(x0)  # Cold miss
# Verify: dcache_mem_req_valid asserted, refill occurs

# Test 3: Hit during refill
# LW x1, 0x3000(x0)  # Miss, starts refill
# SW x2, 0x1000(x0)  # Hit different line (should not stall)
# Verify: Write completes while refill in progress

# Test 4: Write-back
# SW x1, 0x4000(x0)  # Make line dirty
# LW x2, 0x5000(x0)  # Evict dirty line (same set)
# Verify: dcache_mem_req_write asserted for writeback

# Test 5: MSHR coalescing
# LW x1, 0x6000(x0)  # Miss, allocate MSHR
# LW x2, 0x6004(x0)  # Same line, coalesce
# Verify: Only 1 refill, both loads complete
```

### Level 3 Tests (Non-Blocking Operation)
**File**: `tests/system_tests/test_nonblocking_mem.py`

```python
# Test 1: Load doesn't stall pipeline
# LW x1, 0x1000(x0)  # Miss, takes 5+ cycles
# ADDI x2, x0, 1     # Should execute immediately (not stalled)
# ADDI x3, x0, 2     # Should execute immediately
# Verify: PC advances without waiting for load

# Test 2: Multiple outstanding loads
# LW x1, 0x1000(x0)  # Miss 1
# LW x2, 0x2000(x0)  # Miss 2 (different line)
# LW x3, 0x3000(x0)  # Miss 3
# Verify: All 3 loads outstanding, 3 MSHRs allocated

# Test 3: Out-of-order completion
# LW x1, 0x1000(x0)  # Miss, slow refill (simulate latency)
# LW x2, 0x1000(x0)  # Hit (same line after refill)
# Verify: x2 gets data before x1 completes

# Test 4: Load-use with queue
# LW x1, 0(x2)       # Load into x1
# ADD x3, x1, x4     # Use x1 immediately
# Verify: ADD waits for load queue to retire x1
```

### Level 4 Tests (Full Regression)
**Run existing test suite**:
```bash
pytest system_tests/test_full_integration.py
pytest system_tests/test_stress_fixed.py
pytest system_tests/test_edge_cases.py
```

**Verify**: All 44 existing tests pass (no regressions)

---

## Risk Mitigation

### High-Risk Areas
1. **WB stage arbitration** - Multiple sources (load queue, store queue, pipeline)
   - Mitigation: Extensive testing of priority logic
   - Test all 3 sources active simultaneously

2. **Store-to-load forwarding timing** - CAM lookup in EX, forward to WB
   - Mitigation: Register forwarded data (single-cycle latency)
   - Test with consecutive SW/LW to same address

3. **Memory arbiter deadlock** - Load queue full, store queue full
   - Mitigation: Priority-based arbitration with almost-full signals
   - Test queue full scenarios extensively

4. **Cache refill timing** - 512-bit line from word-based data_mem
   - Mitigation: Simulate multi-cycle refill with registered data
   - Test with multiple concurrent refills

### Medium-Risk Areas
1. **Queue full stalls** - Pipeline stalls when queues full
   - Mitigation: Reuse existing stall logic (icache_stall pattern)
   - Test queue full conditions

2. **Address alignment** - D-cache uses line addresses, queues use word addresses
   - Mitigation: Careful address slicing in arbiter
   - Test unaligned accesses (if supported)

### Low-Risk Areas
1. **Load/store detection** - Already have instruction IDs in EX stage
2. **Queue modules** - Already tested (18/18 tests passing)
3. **Cache module** - Already tested (27/27 tests passing)

---

## Timeline Estimate

| Level | Task | Time | Cumulative |
|-------|------|------|------------|
| 0 | Preparation (wiring, includes) | 1-2h | 1-2h |
| 1 | Queue integration + arbiter | 4-6h | 5-8h |
| 1 | Level 1 testing (5 tests) | 2h | 7-10h |
| 2 | D-cache integration | 3-4h | 10-14h |
| 2 | Level 2 testing (5 tests) | 2h | 12-16h |
| 3 | Pipeline stall removal | 2-3h | 14-19h |
| 3 | Level 3 testing (4 tests) | 2h | 16-21h |
| 4 | Full integration testing | 4-6h | 20-27h |
| **TOTAL** | **End-to-end** | **20-27h** | **~3-4 days** |

---

## Success Criteria

✅ **Phase 3d Complete When**:
1. Load queue integrated into riscv_cpu.v (enqueue in EX, retire in WB)
2. Store queue integrated into riscv_cpu.v (enqueue in EX, retire to memory)
3. D-cache + MSHR integrated into top.v (replaces direct data_mem)
4. Memory arbiter working (priority-based load/store selection)
5. Store-to-load forwarding working (CAM lookup in EX)
6. WB stage arbitration working (load queue, store queue, pipeline)
7. All Level 1-4 tests passing (18 new tests)
8. All regression tests passing (44 existing tests)
9. **Total: 62 tests passing (100%)**

---

## Next Steps After Phase 3d

Once Phase 3d complete, we'll have a **fully functional non-blocking memory hierarchy**:
- ✅ Out-of-order load completion
- ✅ Store-to-load forwarding
- ✅ Non-blocking D-cache
- ✅ Multiple outstanding cache misses (8 MSHRs)

**Then proceed to**:
- **Phase 4**: I-cache MSHR upgrade (apply same pattern to I-cache)
- **Phase 5**: Sequential prefetcher for I-cache
- **Phase 6**: Stride prefetcher for D-cache
- **Phase 7**: L2 unified cache (512KB)
- **Phase 8**: Performance tuning and optimization

---

**Document Status**: Ready for implementation
**Confidence Level**: Very High (all components proven, 100% test pass rate)
**Recommended Start**: Immediate (all prerequisites met)
