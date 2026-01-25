`default_nettype none

// ============================================================================
// MSHR (Miss Status Holding Register)
// ============================================================================
// Tracks outstanding cache misses to enable non-blocking cache operation.
// Supports request coalescing: multiple requests to the same cache line
// share a single MSHR entry and memory refill.
//
// Key Features:
// - Configurable number of MSHR entries (default 8)
// - CAM-based matching for fast coalescing lookup
// - Word-granularity tracking via bitmap (16 words per 64-byte line)
// - Priority-based allocation (first free MSHR)
//
// Industry Standard: ARM Cortex-A uses 8-10 MSHRs, RISC-V Rocket uses 2-4
//
// PARAMETER CONSTRAINTS:
// - NUM_MSHR must be power of 2 (1, 2, 4, 8, 16, ...) - NUM_MSHR=1 handled with 1 bit
// - WORDS_PER_LINE >= 1 - WORDS_PER_LINE=1 handled with 1 bit
// ============================================================================

module mshr #(
    parameter NUM_MSHR = 8,              // Number of MSHR entries (must be power of 2: 1, 2, 4, 8, 16, ...)
    parameter ADDR_WIDTH = 32,           // Address width
    parameter WORDS_PER_LINE = 16        // Words per cache line (must be >= 2)
)(
    input wire clk,
    input wire rst,

    // ========================================================================
    // Allocation Interface (on cache miss)
    // ========================================================================
    input  wire                     alloc_req,       // Request to allocate MSHR
    input  wire [ADDR_WIDTH-1:0]    alloc_addr,      // Address that missed
    input  wire [$clog2(WORDS_PER_LINE)-1:0] alloc_word_offset, // Which word in line
    output wire                     alloc_ready,     // MSHR available for allocation
    output wire [(NUM_MSHR == 1) ? 0 : ($clog2(NUM_MSHR)-1):0] alloc_id,     // ID of allocated MSHR

    // ========================================================================
    // Matching Interface (for coalescing)
    // ========================================================================
    input  wire                     match_req,       // Check if address matches any MSHR
    input  wire [ADDR_WIDTH-1:0]    match_addr,      // Address to match
    input  wire [$clog2(WORDS_PER_LINE)-1:0] match_word_offset, // Which word in line
    output wire                     match_hit,       // Address matches an MSHR
    output wire [(NUM_MSHR == 1) ? 0 : ($clog2(NUM_MSHR)-1):0] match_id,     // ID of matching MSHR

    // ========================================================================
    // Completion Interface (on refill done)
    // ========================================================================
    input  wire                     retire_req,      // Retire MSHR (refill complete)
    input  wire [(NUM_MSHR == 1) ? 0 : ($clog2(NUM_MSHR)-1):0] retire_id,    // Which MSHR to retire

    // ========================================================================
    // Status Outputs
    // ========================================================================
    output wire                     mshr_full,       // All MSHRs allocated
    output wire [NUM_MSHR-1:0]      mshr_valid,      // Which MSHRs are valid

    // Per-MSHR outputs (flattened for cocotb compatibility)
    output wire [(NUM_MSHR*ADDR_WIDTH)-1:0]         mshr_addr_flat,
    output wire [(NUM_MSHR*WORDS_PER_LINE)-1:0]     mshr_word_mask_flat
);

    // ========================================================================
    // Internal State
    // ========================================================================
    // Handle NUM_MSHR=1 edge case: $clog2(1)=0, but we need at least 1 bit
    localparam MSHR_BITS = (NUM_MSHR == 1) ? 1 : $clog2(NUM_MSHR);
    // Handle WORDS_PER_LINE=1 edge case: $clog2(1)=0, but we need at least 1 bit
    localparam OFFSET_BITS = (WORDS_PER_LINE == 1) ? 1 : $clog2(WORDS_PER_LINE);
    localparam LINE_ADDR_WIDTH = ADDR_WIDTH - OFFSET_BITS - 2; // Remove word offset and byte offset

    reg [NUM_MSHR-1:0]                       valid;
    reg [NUM_MSHR-1:0][LINE_ADDR_WIDTH-1:0]  line_addr;  // Address without word offset
    reg [NUM_MSHR-1:0][WORDS_PER_LINE-1:0]   word_mask;  // Bitmap of requested words

    integer i;

    // Extract line address (remove word offset and byte offset)
    wire [LINE_ADDR_WIDTH-1:0] alloc_line_addr = alloc_addr[ADDR_WIDTH-1:OFFSET_BITS+2];
    wire [LINE_ADDR_WIDTH-1:0] match_line_addr = match_addr[ADDR_WIDTH-1:OFFSET_BITS+2];

    // ========================================================================
    // CAM Matching Logic (parallel comparison)
    // ========================================================================
    wire [NUM_MSHR-1:0] cam_match;

    genvar g;
    generate
        for (g = 0; g < NUM_MSHR; g = g + 1) begin : gen_cam_match
            assign cam_match[g] = valid[g] && (line_addr[g] == match_line_addr);
        end
    endgenerate

    assign match_hit = |cam_match;

    // Priority encoder for match ID (returns FIRST match, not last)
    reg [MSHR_BITS-1:0] match_id_reg;
    always @(*) begin
        match_id_reg = {MSHR_BITS{1'b0}};
        for (i = 0; i < NUM_MSHR; i = i + 1) begin
            if (cam_match[i] && (match_id_reg == {MSHR_BITS{1'b0}})) begin
                // Only assign if we haven't found a match yet (first match wins)
                match_id_reg = i[MSHR_BITS-1:0];
            end
        end
    end
    assign match_id = match_id_reg;

    // ========================================================================
    // Free MSHR Selection (priority encoder)
    // ========================================================================
    wire [NUM_MSHR-1:0] free_mshr = ~valid;
    assign alloc_ready = |free_mshr;
    assign mshr_full = ~alloc_ready;

    // Priority encoder for free MSHR (returns FIRST free, not last)
    reg [MSHR_BITS-1:0] alloc_id_reg;
    always @(*) begin
        alloc_id_reg = {MSHR_BITS{1'b0}};
        for (i = 0; i < NUM_MSHR; i = i + 1) begin
            if (free_mshr[i] && (alloc_id_reg == {MSHR_BITS{1'b0}})) begin
                // Only assign if we haven't found a free MSHR yet (first free wins)
                alloc_id_reg = i[MSHR_BITS-1:0];
            end
        end
    end
    assign alloc_id = alloc_id_reg;

    // ========================================================================
    // MSHR Allocation and Management
    // ========================================================================
    always @(posedge clk) begin
        if (rst) begin
            valid <= {NUM_MSHR{1'b0}};
            for (i = 0; i < NUM_MSHR; i = i + 1) begin
                line_addr[i] <= {LINE_ADDR_WIDTH{1'b0}};
                word_mask[i] <= {WORDS_PER_LINE{1'b0}};
            end
        end else begin
            // Retire MSHR on completion (highest priority - clears state first)
            if (retire_req) begin
                valid[retire_id] <= 1'b0;
                word_mask[retire_id] <= {WORDS_PER_LINE{1'b0}};
                line_addr[retire_id] <= {LINE_ADDR_WIDTH{1'b0}}; // Clear stale address
            end

            // Allocate new MSHR on miss
            // Note: If retire and alloc target same MSHR, both execute:
            //   - Retire clears state (valid=0, word_mask=0, line_addr=0)
            //   - Alloc sets new state (valid=1, word_mask=new, line_addr=new)
            //   - Result: Immediate reuse (alloc wins due to non-blocking assignment order)
            if (alloc_req && alloc_ready) begin
                valid[alloc_id] <= 1'b1;
                line_addr[alloc_id] <= alloc_line_addr;
                word_mask[alloc_id] <= (1 << alloc_word_offset); // Set bit for this word
            end

            // Coalesce request into existing MSHR
            // Note: If retire and match target same MSHR, retire clears mask first,
            // then match updates it. To prevent corruption, we skip match if retiring same MSHR.
            // (In practice, match should happen before retire, but defensive coding here)
            if (match_req && match_hit && (!retire_req || (retire_id != match_id))) begin
                word_mask[match_id] <= word_mask[match_id] | (1 << match_word_offset);
            end
        end
    end

    // ========================================================================
    // Status Outputs
    // ========================================================================
    assign mshr_valid = valid;

    // Flatten 2D arrays to 1D outputs for cocotb compatibility
    generate
        for (g = 0; g < NUM_MSHR; g = g + 1) begin : gen_outputs
            // Reconstruct full address from line_addr and assign to flattened output
            wire [ADDR_WIDTH-1:0] reconstructed_addr = {line_addr[g], {(OFFSET_BITS+2){1'b0}}};
            assign mshr_addr_flat[g*ADDR_WIDTH +: ADDR_WIDTH] = reconstructed_addr;
            assign mshr_word_mask_flat[g*WORDS_PER_LINE +: WORDS_PER_LINE] = word_mask[g];
        end
    endgenerate

endmodule

`default_nettype wire
