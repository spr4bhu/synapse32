# D-Cache + MSHR Implementation Plan
**Date**: December 30, 2024
**Goal**: Create `dcache_mshr.v` by integrating bulletproof dcache.v and mshr.v
**Approach**: Incremental, testable at each level

---

## Starting Point

### Bulletproof Components ✅
1. **dcache.v** - 22/22 tests passing (100%)
   - 4-state FSM: IDLE → WRITE_MEM → READ_MEM → UPDATE_CACHE
   - Blocking operation (one miss at a time)
   - Clean hit/miss detection
   - Proper LRU replacement
   - Write-back policy

2. **mshr.v** - 13/13 tests passing (100%)
   - 8 MSHR entries
   - CAM-based matching
   - Request coalescing
   - Word-granularity tracking
   - All edge cases handled

---

## Implementation Levels (Incremental)

### Level 1: Basic MSHR Tracking (Simplest)
**Goal**: Track outstanding misses, NO hit-during-refill yet
**Complexity**: Low
**Timeline**: 4-6 hours

**What Changes**:
- Add MSHR instantiation
- Allocate MSHR on cache miss
- Retire MSHR on refill complete
- Keep blocking behavior (no hit-during-refill)

**What Stays Same**:
- Same 4-state FSM
- Same hit detection
- Same refill logic
- Only ONE active miss at a time (like blocking cache)

**Tests**: Basic read/write miss tests (should pass immediately)

---

### Level 2: Request Coalescing
**Goal**: Multiple requests to same line share one MSHR
**Complexity**: Medium
**Timeline**: 2-3 hours

**What Changes**:
- On miss, check MSHR CAM for matching line
- If match, coalesce (update word mask)
- If no match, allocate new MSHR
- Return to IDLE after coalescing (don't start refill)

**What Stays Same**:
- Still blocking (one refill at a time)
- Same FSM states
- Same refill logic

**Tests**: Secondary miss coalescing test

---

### Level 3: Hit-During-Refill
**Goal**: Serve cache hits while refill in progress
**Complexity**: High
**Timeline**: 3-4 hours

**What Changes**:
- Accept new requests in READ_MEM/UPDATE_CACHE states
- Check cache hit combinationally
- Generate response for hits during refill
- Route responses correctly (refill vs hit-during-refill)

**Tests**: Hit-during-refill, write-during-refill tests

---

## Detailed Design: Level 1

### Architecture
```
CPU Request
    ↓
[IDLE: Check hit/miss]
    ↓
Cache miss?
    ↓
[Allocate MSHR] ← NEW
    ↓
[Check if victim dirty]
    ↓
[WRITE_MEM] (if victim dirty)
    ↓
[READ_MEM] (fetch new line)
    ↓
[UPDATE_CACHE] (install line)
    ↓
[Retire MSHR] ← NEW
    ↓
[IDLE]
```

### MSHR Integration Points

#### 1. Module Interface (Same as dcache.v)
```verilog
module dcache_mshr #(
    // Same parameters as dcache.v
    parameter CACHE_SIZE = 32768,
    parameter LINE_SIZE = 64,
    parameter NUM_WAYS = 4,
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter NUM_MSHR = 8  // NEW parameter
)(
    // Same ports as dcache.v
    input wire clk,
    input wire rst,

    // CPU interface (identical to dcache.v)
    input  wire cpu_req_valid,
    input  wire [ADDR_WIDTH-1:0] cpu_req_addr,
    input  wire cpu_req_write,
    input  wire [DATA_WIDTH-1:0] cpu_req_wdata,
    input  wire [3:0] cpu_req_byte_en,
    output wire cpu_req_ready,
    output wire cpu_resp_valid,
    output wire [DATA_WIDTH-1:0] cpu_resp_rdata,

    // Memory interface (identical to dcache.v)
    output wire mem_req_valid,
    output wire [ADDR_WIDTH-1:0] mem_req_addr,
    output wire mem_req_write,
    output wire [511:0] mem_req_wdata,
    input  wire mem_req_ready,
    input  wire mem_resp_valid,
    input  wire [511:0] mem_resp_rdata,
    output wire mem_resp_ready
);
```

**Key Point**: **SAME INTERFACE as dcache.v** - makes it a drop-in replacement!

#### 2. MSHR Instantiation
```verilog
// MSHR module (from rtl/mshr.v)
wire mshr_alloc_req, mshr_alloc_ready;
wire [ADDR_WIDTH-1:0] mshr_alloc_addr;
wire [$clog2(WORDS_PER_LINE)-1:0] mshr_alloc_word_offset;
wire [$clog2(NUM_MSHR)-1:0] mshr_alloc_id;

wire mshr_match_req, mshr_match_hit;
wire [ADDR_WIDTH-1:0] mshr_match_addr;
wire [$clog2(WORDS_PER_LINE)-1:0] mshr_match_word_offset;
wire [$clog2(NUM_MSHR)-1:0] mshr_match_id;

wire mshr_retire_req;
wire [$clog2(NUM_MSHR)-1:0] mshr_retire_id;
wire mshr_full;
wire [NUM_MSHR-1:0] mshr_valid;

mshr #(
    .NUM_MSHR(NUM_MSHR),
    .ADDR_WIDTH(ADDR_WIDTH),
    .WORDS_PER_LINE(LINE_SIZE/4)
) u_mshr (
    .clk(clk),
    .rst(rst),
    .alloc_req(mshr_alloc_req),
    .alloc_addr(mshr_alloc_addr),
    .alloc_word_offset(mshr_alloc_word_offset),
    .alloc_ready(mshr_alloc_ready),
    .alloc_id(mshr_alloc_id),
    .match_req(mshr_match_req),
    .match_addr(mshr_match_addr),
    .match_word_offset(mshr_match_word_offset),
    .match_hit(mshr_match_hit),
    .match_id(mshr_match_id),
    .retire_req(mshr_retire_req),
    .retire_id(mshr_retire_id),
    .mshr_full(mshr_full),
    .mshr_valid(mshr_valid),
    .mshr_addr_flat(),
    .mshr_word_mask_flat()
);
```

#### 3. Active MSHR Tracking
```verilog
// Track which MSHR is currently being serviced
reg active_mshr_valid;
reg [$clog2(NUM_MSHR)-1:0] active_mshr_id;

always @(posedge clk) begin
    if (rst) begin
        active_mshr_valid <= 1'b0;
        active_mshr_id <= 0;
    end else begin
        // Allocate on miss
        if (state == STATE_IDLE && !cache_hit && cpu_req_valid && mshr_alloc_ready) begin
            active_mshr_valid <= 1'b1;
            active_mshr_id <= mshr_alloc_id;
        end

        // Retire on refill complete
        if (state == STATE_UPDATE_CACHE && transition_to_idle) begin
            active_mshr_valid <= 1'b0;
        end
    end
end
```

#### 4. FSM Modifications (Minimal for Level 1)

**IDLE State**:
```verilog
STATE_IDLE: begin
    if (cpu_req_valid) begin
        if (cache_hit) begin
            // Hit - handle normally (same as dcache.v)
            // ...
            state <= STATE_IDLE;  // Stay in IDLE
        end else begin
            // Miss - allocate MSHR, then proceed
            if (mshr_alloc_ready) begin
                // Allocate MSHR (happens via alloc_req signal)
                // Then check victim
                if (victim_dirty) begin
                    state <= STATE_WRITE_MEM;
                end else begin
                    state <= STATE_READ_MEM;
                end
            end else begin
                // MSHR full - stall (stay in IDLE)
                state <= STATE_IDLE;
            end
        end
    end
end
```

**UPDATE_CACHE State**:
```verilog
STATE_UPDATE_CACHE: begin
    // Same as dcache.v, but also retire MSHR
    if (transition_to_idle) begin
        // Retire active MSHR (happens via retire_req signal)
        state <= STATE_IDLE;
    end
end
```

#### 5. MSHR Control Signals

```verilog
// Allocate MSHR on miss
assign mshr_alloc_req = (state == STATE_IDLE) && cpu_req_valid &&
                        !cache_hit && mshr_alloc_ready;
assign mshr_alloc_addr = cpu_req_addr;
assign mshr_alloc_word_offset = cpu_req_addr[5:2];  // Word offset in 64-byte line

// Retire MSHR on refill complete
assign mshr_retire_req = (state == STATE_UPDATE_CACHE) && transition_to_idle;
assign mshr_retire_id = active_mshr_id;

// Match not used in Level 1 (blocking operation)
assign mshr_match_req = 1'b0;
assign mshr_match_addr = 32'h0;
assign mshr_match_word_offset = 4'h0;
```

#### 6. What Stays EXACTLY the Same
- All cache arrays (tags, data, valid, dirty, LRU)
- Hit detection logic
- LRU replacement logic
- Victim selection logic
- Refill logic (UPDATE_CACHE state)
- Write logic
- Memory interface logic
- Response generation

**Copy-paste from dcache.v**:
- Cache array declarations
- Hit detection logic (lines 131-163 of dcache.v)
- LRU functions (lines 168-213 of dcache.v)
- Write logic (all write operations)
- Refill logic (UPDATE_CACHE state logic)

---

## Detailed Design: Level 2 (Request Coalescing)

### What Changes from Level 1

#### 1. MSHR Match Check on Miss
```verilog
STATE_IDLE: begin
    if (cpu_req_valid) begin
        if (cache_hit) begin
            // Same as Level 1
        end else begin
            // Miss - check if already being fetched
            // MSHR match check (happens next cycle)
            state <= STATE_MISS_CHECK;  // NEW STATE
        end
    end
end

// NEW STATE: Wait for MSHR CAM result
STATE_MISS_CHECK: begin
    if (mshr_match_hit) begin
        // Request coalesced into existing MSHR
        // MSHR module automatically updates word_mask
        state <= STATE_IDLE;  // Return to IDLE (don't refill)
    end else begin
        // No match - allocate new MSHR
        if (mshr_alloc_ready) begin
            // Same as Level 1
        end else begin
            // MSHR full - wait
            state <= STATE_MISS_CHECK;
        end
    end
end
```

#### 2. MSHR Match Signals
```verilog
// Check MSHR on miss
assign mshr_match_req = (state == STATE_MISS_CHECK);
assign mshr_match_addr = saved_addr;  // Use saved request address
assign mshr_match_word_offset = saved_addr[5:2];

// Allocate if no match
assign mshr_alloc_req = (state == STATE_MISS_CHECK) &&
                        !mshr_match_hit && mshr_alloc_ready;
```

#### 3. Request Saving
```verilog
// Save request when transitioning to MISS_CHECK
always @(posedge clk) begin
    if (state == STATE_IDLE && cpu_req_valid && !cache_hit) begin
        saved_addr <= cpu_req_addr;
        saved_write <= cpu_req_write;
        saved_wdata <= cpu_req_wdata;
        saved_byte_en <= cpu_req_byte_en;
        saved_tag <= req_tag;
        saved_set <= req_set;
        saved_word_offset <= req_word_offset;
    end
end
```

### FSM States for Level 2
- STATE_IDLE (same)
- STATE_MISS_CHECK (NEW - wait for MSHR CAM result)
- STATE_WRITE_MEM (same)
- STATE_READ_MEM (same)
- STATE_UPDATE_CACHE (same)

---

## Detailed Design: Level 3 (Hit-During-Refill)

### What Changes from Level 2

#### 1. Accept Requests During Refill
```verilog
// cpu_req_ready now true in more states
assign cpu_req_ready = (state == STATE_IDLE) ||
                       (state == STATE_READ_MEM) ||     // NEW
                       (state == STATE_UPDATE_CACHE);   // NEW
```

#### 2. Combinational Hit Check During Refill
```verilog
// Current request hit detection (for hit-during-refill)
wire [NUM_WAYS-1:0] way_hit_current;
wire cache_hit_current;
wire [WAY_INDEX_BITS-1:0] hit_way_current;

genvar w;
generate
    for (w = 0; w < NUM_WAYS; w = w + 1) begin
        assign way_hit_current[w] = valid[req_set][w] &&
                                    (tags[req_set][w] == req_tag);
    end
endgenerate

assign cache_hit_current = |way_hit_current;

// Priority encoder for current hit way
// ... (same pattern as saved request)
```

#### 3. Hit-During-Refill Response
```verilog
// Response valid sources:
// 1. Normal hit in IDLE state (saved request)
// 2. Refill complete (active MSHR)
// 3. Hit during refill (current request)

wire hit_during_refill = (state == STATE_READ_MEM || state == STATE_UPDATE_CACHE) &&
                         cpu_req_valid && cache_hit_current;

assign cpu_resp_valid = (state == STATE_IDLE && cache_hit) ||        // Normal hit
                        (state == STATE_UPDATE_CACHE && refill_done) || // Refill complete
                        hit_during_refill;                            // Hit during refill
```

#### 4. Response Data Mux
```verilog
// Response data selection
wire [DATA_WIDTH-1:0] hit_data_saved = ...; // From saved request (IDLE hit)
wire [DATA_WIDTH-1:0] hit_data_current = ...; // From current request (hit-during-refill)
wire [DATA_WIDTH-1:0] refill_data = ...; // From refill (miss completion)

assign cpu_resp_rdata = hit_during_refill ? hit_data_current :
                        (state == STATE_IDLE) ? hit_data_saved :
                        refill_data;
```

#### 5. Write Hit During Refill
```verilog
// Write logic - handle both saved and current requests
always @(posedge clk) begin
    // Normal write hit (IDLE state, saved request)
    if (state == STATE_IDLE && cache_hit && saved_write) begin
        // Write to cache using saved_* signals
    end

    // Write hit during refill (current request)
    if (hit_during_refill && cpu_req_write) begin
        // Write to cache using current request signals (req_*)
    end
end
```

---

## Implementation Strategy

### Step 1: Copy dcache.v as Base
```bash
cp rtl/dcache.v rtl/dcache_mshr.v
```

Then modify incrementally.

### Step 2: Add MSHR Infrastructure (Level 1)
1. Add MSHR parameter to module
2. Instantiate MSHR module
3. Add active_mshr tracking registers
4. Add MSHR control signal assignments
5. Modify IDLE state to allocate MSHR on miss
6. Modify UPDATE_CACHE state to retire MSHR
7. **Test**: Run basic read/write miss tests

### Step 3: Add Coalescing (Level 2)
1. Add STATE_MISS_CHECK state
2. Add saved request registers (already in dcache.v)
3. Modify state transitions (IDLE → MISS_CHECK)
4. Add MSHR match signals
5. **Test**: Run secondary miss coalescing test

### Step 4: Add Hit-During-Refill (Level 3)
1. Add current request hit detection logic
2. Modify cpu_req_ready (accept during refill)
3. Add hit_during_refill signal
4. Modify cpu_resp_valid logic
5. Add response data mux
6. Add write-during-refill logic
7. **Test**: Run hit-during-refill tests

---

## Testing Strategy

### Level 1 Tests (Should Pass Immediately)
From `test_dcache_basic.py`:
- ✅ test_read_miss_refill_hit
- ✅ test_write_hit_dirty
- ✅ test_miss_clean_eviction
- ✅ test_miss_dirty_eviction
- ✅ test_byte_write
- ✅ test_different_offsets

**Expected**: 6/6 pass (same as blocking dcache)

### Level 2 Tests (Request Coalescing)
From `test_dcache_mshr.py`:
- ✅ test_basic_read_miss (regression)
- ✅ test_secondary_miss_coalesce (NEW functionality)

**Expected**: 2/2 pass

### Level 3 Tests (Hit-During-Refill)
From `test_dcache_mshr.py`:
- ✅ test_hit_during_refill
- ✅ test_write_during_refill

**Expected**: 2/2 pass

### Regression Tests (All Levels)
Run ALL dcache tests to ensure no regression:
- ✅ test_dcache_basic.py (6 tests)
- ✅ test_dcache_comprehensive.py (8 tests)
- ✅ test_dcache_edge_cases.py (8 tests)

**Expected**: 22/22 pass

---

## Risk Mitigation

### Low-Risk Approach
1. **Start with Level 1** - minimal changes, should work immediately
2. **Test thoroughly** - verify all basic tests pass before proceeding
3. **Incremental build** - add one feature at a time
4. **Regression test** - ensure existing tests still pass after each level

### High-Risk Areas
1. **MSHR timing** - Match check takes 1 cycle (STATE_MISS_CHECK handles this)
2. **Response routing** - Multiple sources (use clear priority: hit-during-refill > refill > normal hit)
3. **Saved vs current** - Two sets of signals (clear naming: saved_* vs req_*)

### Debug Strategy
1. **Add debug prints** - Use `ifdef COCOTB_SIM` for visibility
2. **Waveforms** - GTKWave to trace state transitions
3. **Assertions** - Add safety checks for impossible states
4. **Test one feature** - Don't combine levels until each passes

---

## File Structure

```
rtl/
├── dcache.v                  (Original blocking - 22/22 tests)
├── mshr.v                    (MSHR module - 13/13 tests)
└── dcache_mshr.v             (NEW - MSHR-integrated)

tests/memory_hierarchy/
├── test_dcache_basic.py      (6 tests - Level 1 validation)
├── test_dcache_comprehensive.py (8 tests - regression)
├── test_dcache_edge_cases.py    (8 tests - regression)
└── test_dcache_mshr.py          (5 tests - Level 2+3 validation)
```

---

## Success Criteria

### Level 1 Complete When:
- ✅ All 6 basic tests pass
- ✅ MSHR allocation happens on miss
- ✅ MSHR retirement happens on refill complete
- ✅ Blocking behavior preserved

### Level 2 Complete When:
- ✅ Level 1 tests still pass
- ✅ Secondary miss coalescing test passes
- ✅ MSHR CAM matching works
- ✅ Coalesced requests don't cause refill

### Level 3 Complete When:
- ✅ Level 1+2 tests still pass
- ✅ Hit-during-refill tests pass
- ✅ All 22 regression tests pass
- ✅ Write-during-refill works

### Full Integration Complete When:
- ✅ **ALL 53 tests pass** (22 dcache + 5 mshr integration + 8 LQ + 8 SQ + 13 MSHR)
- ✅ No regression in any component
- ✅ Performance improvement measurable

---

## Timeline Estimate

| Level | Task | Duration | Cumulative |
|-------|------|----------|------------|
| **Level 1** | Add MSHR infrastructure | 2 hours | 2 hours |
| **Level 1** | Test and debug | 2 hours | 4 hours |
| **Level 2** | Add coalescing | 1 hour | 5 hours |
| **Level 2** | Test and debug | 1 hour | 6 hours |
| **Level 3** | Add hit-during-refill | 2 hours | 8 hours |
| **Level 3** | Test and debug | 2 hours | 10 hours |
| **Regression** | Full test suite | 1 hour | 11 hours |
| **TOTAL** | | **~11 hours** | **~1.5 days** |

---

## Next Steps

1. **Review this plan** - Confirm approach
2. **Create dcache_mshr.v** - Start with Level 1
3. **Test incrementally** - Don't skip levels
4. **Maintain test pass rate** - Keep all tests green
5. **Document changes** - Comment new logic clearly

**Ready to implement Level 1?**

---

**Plan Created**: December 30, 2024
**Approach**: Incremental, low-risk, testable
**Timeline**: ~1.5 days to full MSHR integration
