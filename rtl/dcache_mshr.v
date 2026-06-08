`default_nettype none

// ============================================================================
// Data Cache with MSHR (D-Cache + MSHR) - RISC-V Memory Hierarchy Component
// ============================================================================
// 4-way set-associative, write-back cache with MSHR support for non-blocking operation.
// Implements a 4-state FSM for cache miss handling with write-back support.
//
// FSM States:
//   IDLE (00)        - Ready for requests, checks hit/miss
//   WRITE_MEM (01)   - Write-back dirty victim line to memory
//   READ_MEM (10)    - Fetch new line from memory
//   UPDATE_CACHE (11) - Write fetched data to cache and update tags
//
// Key Features:
// - Configurable size, associativity, and line size
// - Write-back policy with dirty bit tracking
// - Pseudo-LRU replacement (3-bit tree per set for 4-way)
// - Byte-level write support via byte enables
// - Write-allocate policy for write misses
// - MSHR support for tracking outstanding misses (Level 3: basic tracking + request coalescing + hit-during-refill)
// - RISC-V compliant (supports LB/LH/LW/LBU/LHU, SB/SH/SW)
//
// Industry Standard Configuration:
// - Default: 32KB, 4-way set-associative, 64-byte lines, 8 MSHRs
// - Matches ARM Cortex-A and Intel Core i-series L1D
//
// PARAMETER CONSTRAINTS:
// - NUM_MSHR must be power of 2 (1, 2, 4, 8, 16, ...)
// - NUM_WAYS must be power of 2 (1, 2, 4, 8, ...)
// - WORDS_PER_LINE >= 1 (handled: WORDS_PER_LINE=1 uses 1 bit)
// ============================================================================

module dcache_mshr #(
    parameter ADDR_WIDTH = 32,              // Address width
    parameter DATA_WIDTH = 32,              // Data width (word size)
    parameter CACHE_SIZE = 32768,            // Total cache size in bytes (32KB default)
    parameter NUM_WAYS = 4,                  // Associativity (must be power of 2: 1, 2, 4, 8, ...)
    parameter LINE_SIZE = 64,                 // Cache line size in bytes (64B default)
    parameter NUM_MSHR = 8,                  // Number of MSHR entries (must be power of 2: 1, 2, 4, 8, 16, ...)
    parameter ENABLE_STATS = 1               // Enable performance counters
)(
    input wire clk,
    input wire rst,
    
    // ========================================================================
    // CPU Interface (Load/Store Queue side)
    // ========================================================================
    input  wire                     cpu_req_valid,     // Request valid (READ_WRITE[3])
    output wire                     cpu_req_ready,     // Cache ready for request
    input  wire [ADDR_WIDTH-1:0]    cpu_req_addr,      // Request address
    input  wire                     cpu_req_write,     // 0=load, 1=store
    input  wire [DATA_WIDTH-1:0]    cpu_req_wdata,     // Write data
    input  wire [3:0]               cpu_req_byte_en,   // Byte enable mask
    
    output wire                     cpu_resp_valid,    // Response valid
    output wire [DATA_WIDTH-1:0]    cpu_resp_rdata,    // Read data response
    
    // ========================================================================
    // Memory Interface (to L2/Main Memory)
    // ========================================================================
    output wire                     mem_req_valid,     // Memory request valid
    input  wire                     mem_req_ready,     // Memory ready (MEM_BUSYWAIT=0)
    output wire [ADDR_WIDTH-1:0]    mem_req_addr,      // Memory request address
    output wire                     mem_req_write,      // 0=read, 1=write
    output wire [LINE_SIZE*8-1:0]   mem_req_wdata,     // Write data (full line)
    
    input  wire                     mem_resp_valid,    // Memory response valid
    input  wire [LINE_SIZE*8-1:0]   mem_resp_rdata,    // Read data (full line)
    
    // ========================================================================
    // Control Interface
    // ========================================================================
    input  wire                     flush_req,        // Flush all dirty lines
    output wire                     flush_done,        // Flush complete
    
    // ========================================================================
    // Performance Counters (optional)
    // ========================================================================
    output wire [31:0]              stat_hits,         // Number of cache hits
    output wire [31:0]              stat_misses,       // Number of cache misses
    output wire [31:0]              stat_evictions,    // Number of evictions
    
    // ========================================================================
    // MSHR Status (for testing/debugging)
    // ========================================================================
    output wire                     mshr_full,         // All MSHRs allocated
    output wire [NUM_MSHR-1:0]      mshr_valid,        // Which MSHRs are valid
    output wire [(NUM_MSHR*ADDR_WIDTH)-1:0]         mshr_addr_flat,      // MSHR addresses (flattened)
    output wire [(NUM_MSHR*((LINE_SIZE / (DATA_WIDTH/8))))-1:0] mshr_word_mask_flat  // MSHR word masks (flattened)
);

    // ========================================================================
    // Parameter Calculations
    // ========================================================================
    localparam WORDS_PER_LINE = LINE_SIZE / (DATA_WIDTH/8);  // Words per cache line
    // Handle WORDS_PER_LINE=1 edge case: $clog2(1)=0, but we need at least 1 bit
    localparam WORD_OFFSET_BITS = (WORDS_PER_LINE == 1) ? 1 : $clog2(WORDS_PER_LINE);    // Bits for word offset
    localparam BYTE_OFFSET_BITS = $clog2(DATA_WIDTH/8);      // Bits for byte offset
    
    localparam NUM_SETS = CACHE_SIZE / (NUM_WAYS * LINE_SIZE); // Number of sets
    localparam SET_INDEX_BITS = $clog2(NUM_SETS);              // Bits for set index
    localparam TAG_BITS = ADDR_WIDTH - SET_INDEX_BITS - WORD_OFFSET_BITS - BYTE_OFFSET_BITS;
    
    // Handle NUM_WAYS=1 edge case: $clog2(1)=0, but we need at least 1 bit
    localparam WAY_INDEX_BITS = (NUM_WAYS == 1) ? 1 : $clog2(NUM_WAYS);             // Bits for way selection
    localparam LRU_BITS = NUM_WAYS - 1;                       // Pseudo-LRU tree bits
    
    // MSHR parameter calculations
    // Handle NUM_MSHR=1 edge case: $clog2(1)=0, but we need at least 1 bit
    localparam MSHR_BITS = (NUM_MSHR == 1) ? 1 : $clog2(NUM_MSHR);  // Bits for MSHR ID
    
    // ========================================================================
    // FSM States (4-state as specified)
    // ========================================================================
    localparam [1:0] STATE_IDLE        = 2'b00;  // IDLE: Ready, checking hit/miss
    localparam [1:0] STATE_WRITE_MEM   = 2'b01;  // WRITE_MEM: Write-back dirty line
    localparam [1:0] STATE_READ_MEM   = 2'b10;  // READ_MEM: Fetch new line
    localparam [1:0] STATE_UPDATE_CACHE = 2'b11; // UPDATE_CACHE: Write to cache
    
    reg [1:0] state, next_state;
    
    // ========================================================================
    // Address Breakdown (similar to I-cache)
    // ========================================================================
    // Extract from cpu_req_addr during IDLE, saved_addr during other states
    wire [TAG_BITS-1:0] req_tag = (state == STATE_IDLE) ? 
        cpu_req_addr[ADDR_WIDTH-1:ADDR_WIDTH-TAG_BITS] :
        saved_addr[ADDR_WIDTH-1:ADDR_WIDTH-TAG_BITS];
    
    wire [SET_INDEX_BITS-1:0] req_set = (state == STATE_IDLE) ?
        cpu_req_addr[SET_INDEX_BITS+WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:WORD_OFFSET_BITS+BYTE_OFFSET_BITS] :
        saved_addr[SET_INDEX_BITS+WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:WORD_OFFSET_BITS+BYTE_OFFSET_BITS];
    
    wire [WORD_OFFSET_BITS-1:0] req_word_offset = (state == STATE_IDLE) ?
        cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS] :
        saved_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS];
    
    // ========================================================================
    // Cache Storage Arrays (unpacked like I-cache for compatibility)
    // ========================================================================
    reg valid [0:NUM_SETS-1][0:NUM_WAYS-1];                    // Valid bits
    reg dirty [0:NUM_SETS-1][0:NUM_WAYS-1];                    // Dirty bits
    reg [TAG_BITS-1:0] tags [0:NUM_SETS-1][0:NUM_WAYS-1];      // Tag array
    reg [LINE_SIZE*8-1:0] data [0:NUM_SETS-1][0:NUM_WAYS-1];   // Data array
    reg [NUM_SETS-1:0][LRU_BITS-1:0]                          lru_state;  // LRU state
    
    // ========================================================================
    // Hit Detection Logic
    // ========================================================================
    wire [NUM_WAYS-1:0] way_hit;
    wire cache_hit;  // HIT signal from FSM description
    reg [WAY_INDEX_BITS-1:0] hit_way_idx;
    
    genvar w;
    generate
        for (w = 0; w < NUM_WAYS; w = w + 1) begin : gen_hit_detection
            assign way_hit[w] = valid[req_set][w] && (tags[req_set][w] == req_tag);
        end
    endgenerate
    
    assign cache_hit = |way_hit;
    
    // Priority encoder for hit way
    integer i;
    always @(*) begin
        hit_way_idx = {WAY_INDEX_BITS{1'b0}};
        for (i = 0; i < NUM_WAYS; i = i + 1) begin
            if (way_hit[i]) begin
                hit_way_idx = i[WAY_INDEX_BITS-1:0];
            end
        end
    end
    
    // ========================================================================
    // Pseudo-LRU Replacement Policy
    // ========================================================================
    function [WAY_INDEX_BITS-1:0] get_lru_way;
        input [LRU_BITS-1:0] lru_bits;
        begin
            if (NUM_WAYS == 4) begin
                // Pseudo-LRU tree traversal for 4-way
                if (!lru_bits[0]) begin          // Go left
                    get_lru_way = !lru_bits[1] ? 2'd0 : 2'd1;
                end else begin                   // Go right
                    get_lru_way = !lru_bits[2] ? 2'd2 : 2'd3;
                end
            end else if (NUM_WAYS == 2) begin
                get_lru_way = !lru_bits[0] ? WAY_INDEX_BITS'(0) : WAY_INDEX_BITS'(1);
            end else begin
                get_lru_way = {WAY_INDEX_BITS{1'b0}};  // Direct-mapped
            end
        end
    endfunction
    
    function [LRU_BITS-1:0] update_lru;
        input [LRU_BITS-1:0] current_lru;
        input [WAY_INDEX_BITS-1:0] accessed_way;
        begin
            update_lru = current_lru;
            if (NUM_WAYS == 4) begin
                case (accessed_way)
                    2'd0: begin update_lru[0] = 1'b1; update_lru[1] = 1'b1; end
                    2'd1: begin update_lru[0] = 1'b1; update_lru[1] = 1'b0; end
                    2'd2: begin update_lru[0] = 1'b0; update_lru[2] = 1'b1; end
                    2'd3: begin update_lru[0] = 1'b0; update_lru[2] = 1'b0; end
                endcase
            end else if (NUM_WAYS == 2) begin
                update_lru[0] = (accessed_way == 0) ? 1'b1 : 1'b0;
            end
        end
    endfunction
    
    // ========================================================================
    // Internal Registers
    // ========================================================================
    reg [ADDR_WIDTH-1:0]         saved_addr;        // Saved request address
    reg [TAG_BITS-1:0]           saved_tag;         // Saved tag (like I-cache saved_tag)
    reg [SET_INDEX_BITS-1:0]     saved_set;         // Saved set index (like I-cache saved_index)
    reg                          saved_write;       // Saved write flag
    reg [DATA_WIDTH-1:0]         saved_wdata;       // Saved write data
    reg [3:0]                    saved_byte_en;     // Saved byte enables
    reg [WAY_INDEX_BITS-1:0]     victim_way;       // Selected victim for eviction
    
    // Flush state
    reg [SET_INDEX_BITS-1:0]     flush_set;         // Current set being flushed
    reg [WAY_INDEX_BITS-1:0]     flush_way;         // Current way being flushed
    
    // ========================================================================
    // MSHR Integration (Level 2: Basic Tracking + Request Coalescing)
    // ========================================================================
    // Track which MSHR is currently being serviced (active refill)
    reg active_mshr_valid;                          // Active MSHR valid flag
    reg [MSHR_BITS-1:0] active_mshr_id;             // ID of active MSHR being serviced
    
    // MSHR module interface signals
    wire mshr_alloc_req;                            // Request to allocate MSHR
    wire mshr_alloc_ready;                           // MSHR available for allocation
    wire [ADDR_WIDTH-1:0] mshr_alloc_addr;           // Address that missed
    wire [WORD_OFFSET_BITS-1:0] mshr_alloc_word_offset; // Word offset in line
    wire [MSHR_BITS-1:0] mshr_alloc_id;             // ID of allocated MSHR
    
    wire mshr_match_req;                             // Request to check MSHR match (Level 1: unused)
    wire mshr_match_hit;                              // Address matches existing MSHR (Level 1: unused)
    wire [ADDR_WIDTH-1:0] mshr_match_addr;          // Address to match (Level 1: unused)
    wire [WORD_OFFSET_BITS-1:0] mshr_match_word_offset; // Word offset to match (Level 1: unused)
    wire [MSHR_BITS-1:0] mshr_match_id;             // ID of matching MSHR (Level 1: unused)
    
    wire mshr_retire_req;                            // Request to retire MSHR
    wire [MSHR_BITS-1:0] mshr_retire_id;            // ID of MSHR to retire
    
    // MSHR status outputs (mshr_addr_flat / mshr_word_mask_flat) are driven
    // directly by the inlined MSHR logic further below.
    
    // ========================================================================
    // Data Read/Write Logic
    // ========================================================================
    // Merge write data into cache line
    function [LINE_SIZE*8-1:0] merge_write_data;
        input [LINE_SIZE*8-1:0] old_line;
        input [DATA_WIDTH-1:0] new_word;
        input [WORD_OFFSET_BITS-1:0] word_offset;
        input [3:0] byte_enable;
        integer b;
        begin
            merge_write_data = old_line;
            for (b = 0; b < 4; b = b + 1) begin
                if (byte_enable[b]) begin
                    merge_write_data[word_offset*DATA_WIDTH + b*8 +: 8] = new_word[b*8 +: 8];
                end
            end
        end
    endfunction
    
    // ========================================================================
    // Inlined MSHR (Miss Status Holding Register)
    // ========================================================================
    // Tracks outstanding cache misses to enable non-blocking operation, with
    // request coalescing (multiple requests to the same line share one entry).
    // Previously a separate `mshr` module; inlined here so the cache is a
    // single self-contained file. Reuses the cache's MSHR_BITS / WORD_OFFSET_BITS
    // localparams; the per-entry valid reg is named mshr_entry_valid to avoid
    // colliding with the cache-line `valid` array.
    localparam LINE_ADDR_WIDTH = ADDR_WIDTH - WORD_OFFSET_BITS - 2; // line addr (drop word + byte offset)

    reg [NUM_MSHR-1:0]                       mshr_entry_valid;
    reg [NUM_MSHR-1:0][LINE_ADDR_WIDTH-1:0]  mshr_line_addr;  // address without word offset
    reg [NUM_MSHR-1:0][WORDS_PER_LINE-1:0]   mshr_word_mask;  // bitmap of requested words

    integer mi;

    // Extract line address (remove word offset and byte offset)
    wire [LINE_ADDR_WIDTH-1:0] mshr_alloc_line_addr = mshr_alloc_addr[ADDR_WIDTH-1:WORD_OFFSET_BITS+2];
    wire [LINE_ADDR_WIDTH-1:0] mshr_match_line_addr = mshr_match_addr[ADDR_WIDTH-1:WORD_OFFSET_BITS+2];

    // CAM matching (parallel comparison) for coalescing lookup
    wire [NUM_MSHR-1:0] mshr_cam_match;
    genvar gm;
    generate
        for (gm = 0; gm < NUM_MSHR; gm = gm + 1) begin : gen_cam_match
            assign mshr_cam_match[gm] = mshr_entry_valid[gm] && (mshr_line_addr[gm] == mshr_match_line_addr);
        end
    endgenerate
    assign mshr_match_hit = |mshr_cam_match;

    // Priority encoder for match ID (first match wins)
    reg [MSHR_BITS-1:0] mshr_match_id_reg;
    always @(*) begin
        mshr_match_id_reg = {MSHR_BITS{1'b0}};
        for (mi = 0; mi < NUM_MSHR; mi = mi + 1) begin
            if (mshr_cam_match[mi] && (mshr_match_id_reg == {MSHR_BITS{1'b0}})) begin
                mshr_match_id_reg = mi[MSHR_BITS-1:0];
            end
        end
    end
    assign mshr_match_id = mshr_match_id_reg;

    // Free MSHR selection (priority encoder, first free wins)
    wire [NUM_MSHR-1:0] mshr_free = ~mshr_entry_valid;
    assign mshr_alloc_ready = |mshr_free;
    assign mshr_full = ~mshr_alloc_ready;

    reg [MSHR_BITS-1:0] mshr_alloc_id_reg;
    always @(*) begin
        mshr_alloc_id_reg = {MSHR_BITS{1'b0}};
        for (mi = 0; mi < NUM_MSHR; mi = mi + 1) begin
            if (mshr_free[mi] && (mshr_alloc_id_reg == {MSHR_BITS{1'b0}})) begin
                mshr_alloc_id_reg = mi[MSHR_BITS-1:0];
            end
        end
    end
    assign mshr_alloc_id = mshr_alloc_id_reg;

    // Allocation, coalescing, and retirement
    always @(posedge clk) begin
        if (rst) begin
            mshr_entry_valid <= {NUM_MSHR{1'b0}};
            for (mi = 0; mi < NUM_MSHR; mi = mi + 1) begin
                mshr_line_addr[mi] <= {LINE_ADDR_WIDTH{1'b0}};
                mshr_word_mask[mi] <= {WORDS_PER_LINE{1'b0}};
            end
        end else begin
            // Retire MSHR on completion (clears state first)
            if (mshr_retire_req) begin
                mshr_entry_valid[mshr_retire_id] <= 1'b0;
                mshr_word_mask[mshr_retire_id] <= {WORDS_PER_LINE{1'b0}};
                mshr_line_addr[mshr_retire_id] <= {LINE_ADDR_WIDTH{1'b0}};
            end

            // Allocate new MSHR on miss (alloc wins if retire+alloc hit same id)
            if (mshr_alloc_req && mshr_alloc_ready) begin
                mshr_entry_valid[mshr_alloc_id] <= 1'b1;
                mshr_line_addr[mshr_alloc_id] <= mshr_alloc_line_addr;
                mshr_word_mask[mshr_alloc_id] <= (1 << mshr_alloc_word_offset);
            end

            // Coalesce request into existing MSHR (skip if retiring the same id)
            if (mshr_match_req && mshr_match_hit && (!mshr_retire_req || (mshr_retire_id != mshr_match_id))) begin
                mshr_word_mask[mshr_match_id] <= mshr_word_mask[mshr_match_id] | (1 << mshr_match_word_offset);
            end
        end
    end

    // Status outputs (flattened for cocotb compatibility)
    assign mshr_valid = mshr_entry_valid;
    generate
        for (gm = 0; gm < NUM_MSHR; gm = gm + 1) begin : gen_mshr_outputs
            wire [ADDR_WIDTH-1:0] mshr_recon_addr = {mshr_line_addr[gm], {(WORD_OFFSET_BITS+2){1'b0}}};
            assign mshr_addr_flat[gm*ADDR_WIDTH +: ADDR_WIDTH] = mshr_recon_addr;
            assign mshr_word_mask_flat[gm*WORDS_PER_LINE +: WORDS_PER_LINE] = mshr_word_mask[gm];
        end
    endgenerate
    
    // ========================================================================
    // MSHR Control Signals (Level 1: Basic Tracking)
    // ========================================================================
    // Allocate MSHR on cache miss
    // Level 3: Allocate in all states (non-blocking operation)
    // Only allocate if no match found (coalescing takes priority)
    // NOTE: Use cpu_cache_hit (not cache_hit) because we're checking the current
    // cpu_req_valid request, not the saved request. cache_hit refers to saved_addr
    // when in non-IDLE states.
    assign mshr_alloc_req = cpu_req_valid && !cpu_cache_hit && !mshr_match_hit && mshr_alloc_ready;
    assign mshr_alloc_addr = cpu_req_addr;
    assign mshr_alloc_word_offset = cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS];
    
    // Retire MSHR on refill complete (UPDATE_CACHE always transitions to IDLE)
    assign mshr_retire_req = (state == STATE_UPDATE_CACHE);
    assign mshr_retire_id = active_mshr_id;
    
    // ========================================================================
    // MSHR Match Interface (Level 3: Request Coalescing + Hit-During-Refill)
    // ========================================================================
    // Check if a cache miss matches an existing MSHR (same cache line)
    // If match found, coalesce request into existing MSHR instead of allocating new one
    // Level 3: Check match in all states (IDLE, WRITE_MEM, READ_MEM, UPDATE_CACHE)
    // This enables coalescing during refill (non-blocking operation)
    // NOTE: Use cpu_cache_hit (not cache_hit) because we're checking the current
    // cpu_req_valid request, not the saved request. cache_hit refers to saved_addr
    // when in non-IDLE states.
    assign mshr_match_req = cpu_req_valid && !cpu_cache_hit;
    assign mshr_match_addr = cpu_req_addr;
    assign mshr_match_word_offset = cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS];
    
    // ========================================================================
    // Active MSHR Tracking
    // ========================================================================
    always @(posedge clk) begin
        if (rst) begin
            active_mshr_valid <= 1'b0;
            active_mshr_id <= {MSHR_BITS{1'b0}};
        end else begin
            // Allocate MSHR on miss (capture ID when allocation happens)
            // NOTE: This only tracks ONE active MSHR at a time (the one being serviced
            // by the state machine). If multiple MSHRs are allocated (Level 3 non-blocking),
            // only the one currently being refilled is tracked in active_mshr_id.
            // This is OK for the current implementation which processes refills sequentially
            // (one at a time through the state machine). For true parallel refills, we would
            // need to track multiple active MSHRs separately.
            if (mshr_alloc_req && mshr_alloc_ready) begin
                active_mshr_valid <= 1'b1;
                active_mshr_id <= mshr_alloc_id;
            end
            
            // Retire MSHR on refill complete
            if (mshr_retire_req) begin
                active_mshr_valid <= 1'b0;
            end
        end
    end
    
    // ========================================================================
    // FSM Combinational Logic
    // ========================================================================
    // READ_WRITE[3] = cpu_req_valid
    // HIT = cache_hit
    // DIRTY = dirty[req_set][victim_way] (for victim line)
    // MEM_BUSYWAIT = !mem_req_ready (inverted)
    
    wire read_write_enable = cpu_req_valid;  // READ_WRITE[3]
    wire hit = cache_hit;                     // HIT
    
    // Pre-select victim way for dirty check (needed for combinational logic)
    // Use cpu_req_addr set for IDLE state, saved_addr set for other states
    wire [SET_INDEX_BITS-1:0] check_set = (state == STATE_IDLE) ? 
        cpu_req_addr[SET_INDEX_BITS+WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:WORD_OFFSET_BITS+BYTE_OFFSET_BITS] :
        saved_addr[SET_INDEX_BITS+WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:WORD_OFFSET_BITS+BYTE_OFFSET_BITS];
    wire [WAY_INDEX_BITS-1:0] pre_victim_way = get_lru_way(lru_state[check_set]);
    wire dirty_victim = valid[check_set][pre_victim_way] && dirty[check_set][pre_victim_way];  // DIRTY
    wire mem_busywait = !mem_req_ready;       // MEM_BUSYWAIT (inverted ready)
    
    always @(*) begin
        next_state = state;
        
        case (state)
            STATE_IDLE: begin
                // Scenario A: Do Nothing Loop
                if (!read_write_enable) begin
                    next_state = STATE_IDLE;
                end
                // Cache Hit: Stay in IDLE (handled in sequential logic)
                else if (read_write_enable && hit) begin
                    next_state = STATE_IDLE;
                end
                // Cache Miss: Check MSHR for coalescing, then allocate if needed
                else                     if (read_write_enable && !hit) begin
                        // Priority: Coalescing > Allocation > Stall
                        // Use if-else to make priority clear (SystemVerilog last assignment wins,
                        // but if-else is clearer and more maintainable)
                        if (mshr_match_hit) begin
                            // Level 2: Match found - coalesce request, stay in IDLE
                            // Word mask updated by MSHR module, no refill needed yet
                            // (Refill is already in progress for the matched MSHR)
                            next_state = STATE_IDLE;
                        end else if (mshr_alloc_ready) begin
                            // No match - allocate new MSHR and proceed with refill
                            // Level 2: Start refill immediately (coalescing happens before allocation)
                            if (dirty_victim) begin
                                next_state = STATE_WRITE_MEM;
                            end else begin
                                next_state = STATE_READ_MEM;
                            end
                        end else begin
                            // MSHR full - stall in IDLE
                            next_state = STATE_IDLE;
                        end
                    end
            end
            
            STATE_WRITE_MEM: begin
                // Wait for memory to finish write-back (MEM_BUSYWAIT=0 means ready)
                // Level 3: Can accept new requests during write-back (non-blocking)
                if (!mem_busywait) begin
                    next_state = STATE_READ_MEM;
                end else begin
                    // Still waiting for write-back, but can accept new requests
                    next_state = STATE_WRITE_MEM;
                end
            end
            
            STATE_READ_MEM: begin
                // Wait for memory to finish fetch (MEM_BUSYWAIT=0 means ready)
                // Level 3: Can accept new requests during fetch (non-blocking)
                if (!mem_busywait && mem_resp_valid) begin
                    next_state = STATE_UPDATE_CACHE;
                end else begin
                    // Still waiting for fetch, but can accept new requests
                    next_state = STATE_READ_MEM;
                end
            end
            
            STATE_UPDATE_CACHE: begin
                // Update cache and return to IDLE (single cycle)
                // Level 3: Can accept new requests during cache update
                next_state = STATE_IDLE;
            end
        endcase
    end
    
    // ========================================================================
    // FSM Sequential Logic
    // ========================================================================
    // Track previous reset state for debug
    
    always @(posedge clk) begin
        if (rst) begin
            state <= STATE_IDLE;
            saved_addr <= 0;
            saved_tag <= 0;
            saved_set <= 0;
            saved_write <= 0;
            saved_wdata <= 0;
            saved_byte_en <= 0;
            victim_way <= 0;
            flush_set <= 0;
            flush_way <= 0;
            active_mshr_valid <= 1'b0;
            active_mshr_id <= {MSHR_BITS{1'b0}};
            
            // Initialize cache arrays
            begin
                integer i, j;
                for (i = 0; i < NUM_SETS; i = i + 1) begin
                    for (j = 0; j < NUM_WAYS; j = j + 1) begin
                        valid[i][j] <= 0;
                        dirty[i][j] <= 0;
                        tags[i][j] <= 0;  // CRITICAL: Clear tags array too!
                    end
                    lru_state[i] <= 0;
                end
            end
        end else begin
            
            case (state)
                STATE_IDLE: begin
                if (read_write_enable) begin
                    if (hit) begin
                        // Cache hit: update data if write, update LRU
                        lru_state[req_set] <= update_lru(lru_state[req_set], hit_way_idx);
                        
                        if (cpu_req_write) begin
                            data[req_set][hit_way_idx] <= merge_write_data(
                                data[req_set][hit_way_idx],
                                cpu_req_wdata,
                                req_word_offset,
                                cpu_req_byte_en
                            );
                            dirty[req_set][hit_way_idx] <= 1'b1;
                        end
                    end else begin
                        // Cache miss: check for coalescing, then allocate if needed
                        
                        // Level 2: Check for coalescing first
                        if (mshr_match_hit) begin
                            // Match found - coalesce request into existing MSHR
                            // MSHR module updates word mask automatically
                            // Stay in IDLE (no refill needed, already in progress)
                            // Don't save request info (coalesced request doesn't need its own state)
                            // Don't allocate new MSHR
                            // Stay in IDLE - refill will serve all coalesced requests when complete
                            state <= next_state;  // next_state is IDLE for coalescing
                        end else if (mshr_alloc_ready) begin
                            // No match - allocate new MSHR and start refill
                            
                            // MSHR available - allocate (happens via mshr_alloc_req signal)
                            // active_mshr_id captured in separate always block
                            saved_addr <= cpu_req_addr;
                            saved_tag <= req_tag;  // Save tag from current request
                            saved_set <= req_set;  // Save set index from current request
                            saved_write <= cpu_req_write;
                            saved_wdata <= cpu_req_wdata;
                            saved_byte_en <= cpu_req_byte_en;
                            victim_way <= pre_victim_way;
                            
                            // Follow next_state (set by combinational logic based on dirty_victim)
                            state <= next_state;
                        end else begin
                            // MSHR full - stall (stay in IDLE, don't save request)
                            // Stay in IDLE (next_state will also be IDLE)
                            state <= next_state;
                        end
                    end
                end
            end
                
                STATE_WRITE_MEM: begin
                    // Write-back in progress, wait for completion
                    // Level 3: Handle hits during write-back
                    if (cpu_req_valid && !flush_req && cpu_cache_hit) begin
                        if (cpu_req_write) begin
                            // Write hit during write-back: update cache
                            data[cpu_req_set][cpu_hit_way] <= merge_write_data(
                                data[cpu_req_set][cpu_hit_way],
                                cpu_req_wdata,
                                cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS],
                                cpu_req_byte_en
                            );
                            dirty[cpu_req_set][cpu_hit_way] <= 1'b1;
                            lru_state[cpu_req_set] <= update_lru(lru_state[cpu_req_set], cpu_hit_way);
                        end
                        // Read hits handled in output logic
                    end
                    // State transition handled by combinational logic (next_state)
                    // Follow next_state (set by combinational logic)
                    state <= next_state;
                end
                
                STATE_READ_MEM: begin
                    // Fetch in progress, wait for completion
                    // Level 3: Handle hits during fetch
                    if (cpu_req_valid && !flush_req && cpu_cache_hit) begin
                        if (cpu_req_write) begin
                            // Write hit during fetch: update cache
                            data[cpu_req_set][cpu_hit_way] <= merge_write_data(
                                data[cpu_req_set][cpu_hit_way],
                                cpu_req_wdata,
                                cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS],
                                cpu_req_byte_en
                            );
                            dirty[cpu_req_set][cpu_hit_way] <= 1'b1;
                            lru_state[cpu_req_set] <= update_lru(lru_state[cpu_req_set], cpu_hit_way);
                        end
                        // Read hits handled in output logic
                    end
                    // State transition handled by combinational logic (next_state)
                    // Follow next_state (set by combinational logic)
                    state <= next_state;
                end
                
                STATE_UPDATE_CACHE: begin
                    // Write new line to cache (data already available from READ_MEM)
                    // Match I-cache structure: use saved_set and saved_tag (like I-cache uses saved_index and saved_tag)
                    // Also retire MSHR (happens via mshr_retire_req signal)
                    
                    // Level 3: Handle hits during cache update
                    if (cpu_req_valid && !flush_req && cpu_cache_hit) begin
                        if (cpu_req_write) begin
                            // Write hit during update: update cache
                            data[cpu_req_set][cpu_hit_way] <= merge_write_data(
                                data[cpu_req_set][cpu_hit_way],
                                cpu_req_wdata,
                                cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS],
                                cpu_req_byte_en
                            );
                            dirty[cpu_req_set][cpu_hit_way] <= 1'b1;
                            lru_state[cpu_req_set] <= update_lru(lru_state[cpu_req_set], cpu_hit_way);
                        end
                        // Read hits handled in output logic
                    end
                    
                    // Follow next_state (always IDLE for UPDATE_CACHE)
                    state <= next_state;
                    // Track array writes with before values
                    valid[saved_set][victim_way] <= 1;
                    tags[saved_set][victim_way] <= saved_tag;
                    
                    // For write miss, merge write data into fetched line
                    if (saved_write) begin
                        // Use word offset from saved_addr (req_word_offset is calculated from saved_addr when not in IDLE)
                        data[saved_set][victim_way] <= merge_write_data(
                            mem_resp_rdata,
                            saved_wdata,
                            saved_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS],  // Word offset from saved_addr
                            saved_byte_en
                        );
                        dirty[saved_set][victim_way] <= 1'b1;
                    end else begin
                        data[saved_set][victim_way] <= mem_resp_rdata;
                        dirty[saved_set][victim_way] <= 1'b0;
                    end
                    
                    // Update LRU
                    lru_state[saved_set] <= update_lru(lru_state[saved_set], victim_way);
                    
                end
            endcase
        end
    end
    
    // ========================================================================
    // Output Logic (Combinational, similar to I-cache)
    // ========================================================================
    reg [DATA_WIDTH-1:0] cpu_resp_rdata_reg;
    reg cpu_resp_valid_reg;
    reg cpu_req_ready_reg;
    reg mem_req_valid_reg;
    reg mem_req_write_reg;
    reg [ADDR_WIDTH-1:0] mem_req_addr_reg;
    reg [LINE_SIZE*8-1:0] mem_req_wdata_reg;
    
    // Extract address fields for current request (like I-cache)
    wire [TAG_BITS-1:0] cpu_req_tag = cpu_req_addr[ADDR_WIDTH-1:ADDR_WIDTH-TAG_BITS];
    wire [SET_INDEX_BITS-1:0] cpu_req_set = cpu_req_addr[SET_INDEX_BITS+WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:WORD_OFFSET_BITS+BYTE_OFFSET_BITS];
    wire [WORD_OFFSET_BITS-1:0] cpu_req_word_offset = cpu_req_addr[WORD_OFFSET_BITS+BYTE_OFFSET_BITS-1:BYTE_OFFSET_BITS];
    
    // Hit detection for current CPU request (combinational)
    wire [NUM_WAYS-1:0] cpu_way_hit;
    wire cpu_cache_hit;
    reg [WAY_INDEX_BITS-1:0] cpu_hit_way;
    
    genvar cw;
    generate
        for (cw = 0; cw < NUM_WAYS; cw = cw + 1) begin : gen_cpu_hit
            assign cpu_way_hit[cw] = valid[cpu_req_set][cw] && (tags[cpu_req_set][cw] == cpu_req_tag);
        end
    endgenerate
    
    assign cpu_cache_hit = |cpu_way_hit;
    
    
    integer ci;
    always @(*) begin
        cpu_hit_way = {WAY_INDEX_BITS{1'b0}};
        for (ci = NUM_WAYS-1; ci >= 0; ci = ci - 1) begin
            if (cpu_way_hit[ci]) cpu_hit_way = ci[WAY_INDEX_BITS-1:0];
        end
    end
    
    // Extract word from cache for current request
    wire [LINE_SIZE*8-1:0] cpu_line_data = data[cpu_req_set][cpu_hit_way];
    wire [DATA_WIDTH-1:0] cpu_word_data = cpu_line_data[cpu_req_word_offset*DATA_WIDTH +: DATA_WIDTH];
    
    always @(*) begin
        // Defaults
        cpu_resp_rdata_reg = {DATA_WIDTH{1'b0}};
        cpu_resp_valid_reg = 1'b0;
        cpu_req_ready_reg = 1'b0;
        mem_req_valid_reg = 1'b0;
        mem_req_write_reg = 1'b0;
        mem_req_addr_reg = {ADDR_WIDTH{1'b0}};
        mem_req_wdata_reg = {(LINE_SIZE*8){1'b0}};
        
        case (state)
            STATE_IDLE: begin
                if (cpu_req_valid && !flush_req) begin
                    
                    if (cpu_cache_hit) begin
                        // Cache hit: provide data immediately (like I-cache)
                        
                        if (!cpu_req_write) begin
                            // Read hit
                            cpu_resp_rdata_reg = cpu_word_data;
                            cpu_resp_valid_reg = 1'b1;
                        end else begin
                            // Write hit: assert valid to acknowledge write acceptance
                            cpu_resp_valid_reg = 1'b1;
                        end
                        // Write hits also update cache in sequential block
                        cpu_req_ready_reg = 1'b1;
                    end else begin
                        // Cache miss: check for coalescing or MSHR availability
                        if (mshr_match_hit) begin
                            // Level 2: Match found - coalesce request
                            // Request is accepted and coalesced into existing MSHR
                            cpu_req_ready_reg = 1'b1;  // Accept request (coalescing happens this cycle)
                        end else if (mshr_alloc_ready) begin
                            // No match - MSHR available - accept request (will allocate and start refill)
                            // Request is accepted, but will stall after this cycle during refill
                            cpu_req_ready_reg = 1'b1;  // Accept request (allocation happens this cycle)
                        end else begin
                            // MSHR full - cannot accept request
                            cpu_req_ready_reg = 1'b0;  // Cannot accept (MSHR full)
                        end
                    end
                end else begin
                    cpu_req_ready_reg = 1'b1;
                end
            end
            
            STATE_WRITE_MEM: begin
                // Write-back in progress
                mem_req_valid_reg = 1'b1;
                mem_req_write_reg = 1'b1;
                mem_req_addr_reg = {tags[saved_set][victim_way], saved_set, {(WORD_OFFSET_BITS+BYTE_OFFSET_BITS){1'b0}}};
                mem_req_wdata_reg = data[saved_set][victim_way];
                
                // Level 3: Accept new requests during write-back (non-blocking)
                if (cpu_req_valid && !flush_req) begin
                    if (cpu_cache_hit) begin
                        // Hit during write-back: serve immediately
                        if (!cpu_req_write) begin
                            // Read hit
                            cpu_resp_rdata_reg = cpu_word_data;
                            cpu_resp_valid_reg = 1'b1;
                        end else begin
                            // Write hit: assert valid to acknowledge write acceptance
                            cpu_resp_valid_reg = 1'b1;
                        end
                        // Write hits also update cache in sequential block
                        cpu_req_ready_reg = 1'b1;
                    end else begin
                        // Miss during write-back: check for coalescing or stall
                        if (mshr_match_hit) begin
                            // Level 2: Match found - coalesce request
                            cpu_req_ready_reg = 1'b1;
                        end else if (mshr_alloc_ready) begin
                            // No match - MSHR available - accept (will allocate after write-back)
                            cpu_req_ready_reg = 1'b1;
                        end else begin
                            // MSHR full - cannot accept
                            cpu_req_ready_reg = 1'b0;
                        end
                    end
                end else begin
                    cpu_req_ready_reg = 1'b0;  // No new request, continue write-back
                end
            end
            
            STATE_READ_MEM: begin
                // Fetch in progress
                mem_req_valid_reg = 1'b1;
                mem_req_write_reg = 1'b0;
                mem_req_addr_reg = {saved_tag, saved_set, {(WORD_OFFSET_BITS+BYTE_OFFSET_BITS){1'b0}}};
                
                // Level 3: Accept new requests during fetch (non-blocking)
                if (cpu_req_valid && !flush_req) begin
                    if (cpu_cache_hit) begin
                        // Hit during fetch: serve immediately
                        if (!cpu_req_write) begin
                            // Read hit
                            cpu_resp_rdata_reg = cpu_word_data;
                            cpu_resp_valid_reg = 1'b1;
                        end else begin
                            // Write hit: assert valid to acknowledge write acceptance
                            cpu_resp_valid_reg = 1'b1;
                        end
                        // Write hits also update cache in sequential block
                        cpu_req_ready_reg = 1'b1;
                    end else begin
                        // Miss during fetch: check for coalescing or stall
                        if (mshr_match_hit) begin
                            // Level 2: Match found - coalesce request
                            cpu_req_ready_reg = 1'b1;
                        end else if (mshr_alloc_ready) begin
                            // No match - MSHR available - accept (will allocate after fetch)
                            cpu_req_ready_reg = 1'b1;
                        end else begin
                            // MSHR full - cannot accept
                            cpu_req_ready_reg = 1'b0;
                        end
                    end
                end else begin
                    cpu_req_ready_reg = 1'b0;  // No new request, continue fetch
                end
            end
            
            STATE_UPDATE_CACHE: begin
                // After refill, serve the original request from refilled data
                // Data is available from mem_resp_rdata (just received)
                if (!saved_write) begin
                    // Read miss: extract word from mem_resp_rdata
                    cpu_resp_rdata_reg = mem_resp_rdata[req_word_offset*DATA_WIDTH +: DATA_WIDTH];
                    cpu_resp_valid_reg = 1'b1;
                end
                // Write miss: data already merged in sequential block
                
                // Level 3: Accept new requests during cache update (non-blocking)
                if (cpu_req_valid && !flush_req) begin
                    if (cpu_cache_hit) begin
                        // Hit during update: serve immediately
                        if (!cpu_req_write) begin
                            // Read hit
                            cpu_resp_rdata_reg = cpu_word_data;
                            cpu_resp_valid_reg = 1'b1;
                        end else begin
                            // Write hit: assert valid to acknowledge write acceptance
                            cpu_resp_valid_reg = 1'b1;
                        end
                        // Write hits also update cache in sequential block
                        cpu_req_ready_reg = 1'b1;
                    end else begin
                        // Miss during update: check for coalescing or stall
                        if (mshr_match_hit) begin
                            // Level 2: Match found - coalesce request
                            cpu_req_ready_reg = 1'b1;
                        end else if (mshr_alloc_ready) begin
                            // No match - MSHR available - accept (will allocate after update)
                            cpu_req_ready_reg = 1'b1;
                        end else begin
                            // MSHR full - cannot accept
                            cpu_req_ready_reg = 1'b0;
                        end
                    end
                end else begin
                    cpu_req_ready_reg = 1'b1;  // Original request is complete
                end
            end
        endcase
    end
    
    // Assign outputs
    assign cpu_req_ready = cpu_req_ready_reg;
    assign cpu_resp_valid = cpu_resp_valid_reg;
    assign cpu_resp_rdata = cpu_resp_rdata_reg;
    assign mem_req_valid = mem_req_valid_reg;
    assign mem_req_write = mem_req_write_reg;
    assign mem_req_addr = mem_req_addr_reg;
    assign mem_req_wdata = mem_req_wdata_reg;
    
    // Control interface
    assign flush_done = (state == STATE_IDLE) && (flush_set == 0) && (flush_way == 0);
    
    // ========================================================================
    // Performance Counters
    // ========================================================================
    generate
        if (ENABLE_STATS) begin : gen_stats
            reg [31:0] hit_count;
            reg [31:0] miss_count;
            reg [31:0] evict_count;
            
            always @(posedge clk) begin
                if (rst) begin
                    hit_count <= 0;
                    miss_count <= 0;
                    evict_count <= 0;
                end else begin
                    // Count hits and misses
                    if (state == STATE_IDLE && read_write_enable) begin
                        if (hit) begin
                            hit_count <= hit_count + 1;
                        end else begin
                            miss_count <= miss_count + 1;
                        end
                    end
                    
                    // Count evictions
                    if (state == STATE_WRITE_MEM && !mem_busywait) begin
                        evict_count <= evict_count + 1;
                    end
                end
            end
            
            assign stat_hits = hit_count;
            assign stat_misses = miss_count;
            assign stat_evictions = evict_count;
        end else begin : no_stats
            assign stat_hits = 32'h0;
            assign stat_misses = 32'h0;
            assign stat_evictions = 32'h0;
        end
    endgenerate

endmodule

`default_nettype wire
