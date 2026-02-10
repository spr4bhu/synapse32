`default_nettype none

// D-Cache with inline MSHR - Fully Non-Blocking (Miss-Under-Miss)
// 4-way set-associative, write-back, write-allocate
// Per-MSHR FSM: IDLE, WRITEBACK, FETCH, ALLOCATE
// Supports 2 independent outstanding misses + hit-under-miss
module dcache #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter NUM_WAYS = 4,
    parameter NUM_SETS = 64,
    parameter CACHE_LINE_WORDS = 4,
    parameter NUM_MSHR = 2
)(
    input wire clk,
    input wire rst,

    // CPU Interface (matches I-cache + write support)
    input wire [ADDR_WIDTH-1:0] cpu_addr,
    input wire cpu_req,
    input wire cpu_write,
    input wire [DATA_WIDTH-1:0] cpu_wdata,
    input wire [3:0] cpu_byte_en,
    output reg [DATA_WIDTH-1:0] cpu_data,
    output reg cpu_valid,
    output reg cpu_stall,

    // Memory Interface (matches I-cache + write support)
    output reg [ADDR_WIDTH-1:0] mem_addr,
    output reg mem_req,
    output reg mem_write,
    output reg [DATA_WIDTH-1:0] mem_wdata,
    input wire [DATA_WIDTH-1:0] mem_data,
    input wire mem_valid,

    // Cache control
    input wire invalidate
);

    // Parameter calculations
    localparam OFFSET_BITS = $clog2(CACHE_LINE_WORDS);
    localparam INDEX_BITS = $clog2(NUM_SETS);
    localparam TAG_BITS = ADDR_WIDTH - INDEX_BITS - OFFSET_BITS - 2;
    localparam WAY_BITS = (NUM_WAYS == 1) ? 1 : $clog2(NUM_WAYS);
    localparam LRU_BITS = NUM_WAYS - 1;
    localparam MSHR_ID_BITS = (NUM_MSHR == 1) ? 1 : $clog2(NUM_MSHR);

    // FSM states (4-state, matching plan naming)
    localparam [1:0] IDLE      = 2'd0;
    localparam [1:0] WRITEBACK = 2'd1;
    localparam [1:0] FETCH     = 2'd2;
    localparam [1:0] ALLOCATE  = 2'd3;

    // Cache storage (3D like I-cache)
    reg valid [0:NUM_SETS-1][0:NUM_WAYS-1];
    reg dirty [0:NUM_SETS-1][0:NUM_WAYS-1];
    reg [TAG_BITS-1:0] tags [0:NUM_SETS-1][0:NUM_WAYS-1];
    reg [DATA_WIDTH-1:0] data [0:NUM_SETS-1][0:NUM_WAYS-1][0:CACHE_LINE_WORDS-1];
    reg [LRU_BITS-1:0] lru_state [0:NUM_SETS-1];

    // Per-MSHR state machines
    reg [NUM_MSHR-1:0] mshr_valid;
    reg [1:0] mshr_state [0:NUM_MSHR-1];

    // Per-MSHR tracking
    reg [TAG_BITS-1:0] mshr_tag [0:NUM_MSHR-1];
    reg [INDEX_BITS-1:0] mshr_index [0:NUM_MSHR-1];
    reg [OFFSET_BITS-1:0] mshr_word [0:NUM_MSHR-1];
    reg [WAY_BITS-1:0] mshr_victim_way [0:NUM_MSHR-1];
    reg [TAG_BITS-1:0] mshr_victim_tag [0:NUM_MSHR-1];
    reg [OFFSET_BITS-1:0] mshr_refill_count [0:NUM_MSHR-1];
    reg [OFFSET_BITS-1:0] mshr_writeback_count [0:NUM_MSHR-1];

    // Per-MSHR request info (for write-allocate)
    reg mshr_is_write [0:NUM_MSHR-1];
    reg [DATA_WIDTH-1:0] mshr_wdata [0:NUM_MSHR-1];
    reg [3:0] mshr_byte_en [0:NUM_MSHR-1];

    // Address extraction
    wire [OFFSET_BITS-1:0] word_offset = cpu_addr[OFFSET_BITS+1:2];
    wire [INDEX_BITS-1:0] set_index = cpu_addr[INDEX_BITS+OFFSET_BITS+1:OFFSET_BITS+2];
    wire [TAG_BITS-1:0] tag = cpu_addr[ADDR_WIDTH-1:INDEX_BITS+OFFSET_BITS+2];

    // Hit detection (integer loop, not genvar)
    reg [NUM_WAYS-1:0] way_hit;
    reg cache_hit;
    reg [WAY_BITS-1:0] hit_way;

    integer h;
    always @(*) begin
        way_hit = {NUM_WAYS{1'b0}};
        for (h = 0; h < NUM_WAYS; h = h + 1) begin
            way_hit[h] = valid[set_index][h] && (tags[set_index][h] == tag);
        end
        cache_hit = |way_hit;
    end

    integer w;
    always @(*) begin
        hit_way = {WAY_BITS{1'b0}};
        for (w = NUM_WAYS-1; w >= 0; w = w - 1) begin
            if (way_hit[w]) hit_way = w[WAY_BITS-1:0];
        end
    end

    // Victim selection - pseudo-LRU with same-set conflict avoidance
    reg [WAY_BITS-1:0] selected_victim;
    reg [WAY_BITS-1:0] final_victim;
    reg found_invalid;
    reg same_set_conflict;
    integer vi;

    // Same-set MSHR conflict detection - track which ways are reserved
    reg [NUM_WAYS-1:0] way_reserved_by_mshr;
    integer rsv;
    always @(*) begin
        way_reserved_by_mshr = {NUM_WAYS{1'b0}};
        for (rsv = 0; rsv < NUM_MSHR; rsv = rsv + 1) begin
            if (mshr_valid[rsv] && (mshr_index[rsv] == set_index)) begin
                way_reserved_by_mshr[mshr_victim_way[rsv]] = 1'b1;
            end
        end
    end

    // Check if all ways in set are reserved by MSHRs (can't allocate)
    wire all_ways_reserved_in_set = &way_reserved_by_mshr;

    // Victim selection and final victim computation in single block
    integer av;
    always @(*) begin
        found_invalid = 1'b0;

        // Default: use pseudo-LRU
        if (NUM_WAYS == 4) begin
            if (!lru_state[set_index][0])
                selected_victim = !lru_state[set_index][1] ? 2'd0 : 2'd1;
            else
                selected_victim = !lru_state[set_index][2] ? 2'd2 : 2'd3;
        end else begin
            selected_victim = {WAY_BITS{1'b0}};
        end

        // Override with first invalid way that's not reserved by another MSHR
        for (vi = 0; vi < NUM_WAYS; vi = vi + 1) begin
            if (!valid[set_index][vi] && !found_invalid && !way_reserved_by_mshr[vi]) begin
                selected_victim = vi[WAY_BITS-1:0];
                found_invalid = 1'b1;
            end
        end

        // Check if selected victim conflicts with an active MSHR
        same_set_conflict = way_reserved_by_mshr[selected_victim];

        // Compute final_victim: use alternative if selected conflicts with active MSHR
        final_victim = selected_victim;
        if (same_set_conflict) begin
            // Pick first way that's not reserved (early exit once found)
            for (av = 0; av < NUM_WAYS; av = av + 1) begin
                if (!way_reserved_by_mshr[av] && (final_victim == selected_victim)) begin
                    final_victim = av[WAY_BITS-1:0];
                end
            end
        end
    end

    // Dirty victim check - use final_victim
    wire dirty_victim = valid[set_index][final_victim] && dirty[set_index][final_victim];

    // MSHR match check (inline, combinational)
    reg mshr_match;
    integer m;
    always @(*) begin
        mshr_match = 1'b0;
        for (m = 0; m < NUM_MSHR; m = m + 1) begin
            if (mshr_valid[m] && mshr_tag[m] == tag && mshr_index[m] == set_index)
                mshr_match = 1'b1;
        end
    end

    // MSHR allocation logic
    wire mshr_available = !mshr_valid[0] || (NUM_MSHR > 1 && !mshr_valid[1]);
    wire [MSHR_ID_BITS-1:0] free_mshr_id = !mshr_valid[0] ? {MSHR_ID_BITS{1'b0}} : {{(MSHR_ID_BITS-1){1'b0}}, 1'b1};

    // Refill/writeback completion
    localparam [OFFSET_BITS-1:0] LAST_WORD_IDX = OFFSET_BITS'(CACHE_LINE_WORDS - 1);

    // Memory arbitration - which MSHR gets memory access this cycle (priority encoder)
    reg mem_grant_valid;
    reg [MSHR_ID_BITS-1:0] mem_grant_mshr;

    integer arb;
    always @(*) begin
        mem_grant_valid = 1'b0;
        mem_grant_mshr = {MSHR_ID_BITS{1'b0}};
        for (arb = 0; arb < NUM_MSHR; arb = arb + 1) begin
            if (!mem_grant_valid && mshr_valid[arb] &&
                (mshr_state[arb] == WRITEBACK || mshr_state[arb] == FETCH)) begin
                mem_grant_valid = 1'b1;
                mem_grant_mshr = arb[MSHR_ID_BITS-1:0];
            end
        end
    end

    // Victim conflict detection - hit to line being refilled would evict
    reg victim_conflict;
    integer vc;
    always @(*) begin
        victim_conflict = 1'b0;
        for (vc = 0; vc < NUM_MSHR; vc = vc + 1) begin
            if (mshr_valid[vc] && (set_index == mshr_index[vc]) &&
                (mshr_state[vc] == FETCH || mshr_state[vc] == WRITEBACK) &&
                cache_hit && (hit_way == mshr_victim_way[vc])) begin
                victim_conflict = 1'b1;
            end
        end
    end

    // LRU update function
    function [LRU_BITS-1:0] update_lru;
        input [LRU_BITS-1:0] current;
        input [WAY_BITS-1:0] accessed;
        begin
            update_lru = current;
            if (NUM_WAYS == 4) begin
                case (accessed)
                    2'd0: begin update_lru[0] = 1'b1; update_lru[1] = 1'b1; end
                    2'd1: begin update_lru[0] = 1'b1; update_lru[1] = 1'b0; end
                    2'd2: begin update_lru[0] = 1'b0; update_lru[2] = 1'b1; end
                    2'd3: begin update_lru[0] = 1'b0; update_lru[2] = 1'b0; end
                endcase
            end
        end
    endfunction

    // Sequential logic - single always block
    integer i, j, mshr_i;
    always @(posedge clk) begin
        if (rst) begin
            // Reset all MSHRs
            mshr_valid <= {NUM_MSHR{1'b0}};
            for (mshr_i = 0; mshr_i < NUM_MSHR; mshr_i = mshr_i + 1) begin
                mshr_state[mshr_i] <= IDLE;
                mshr_refill_count[mshr_i] <= 0;
                mshr_writeback_count[mshr_i] <= 0;
                mshr_tag[mshr_i] <= 0;
                mshr_index[mshr_i] <= 0;
                mshr_word[mshr_i] <= 0;
                mshr_victim_way[mshr_i] <= 0;
                mshr_victim_tag[mshr_i] <= 0;
                mshr_is_write[mshr_i] <= 0;
                mshr_wdata[mshr_i] <= 0;
                mshr_byte_en[mshr_i] <= 0;
            end

            // Reset cache arrays
            for (i = 0; i < NUM_SETS; i = i + 1) begin
                lru_state[i] <= 0;
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    valid[i][j] <= 0;
                    dirty[i][j] <= 0;
                    tags[i][j] <= 0;
                end
            end

        end else if (invalidate) begin
            // Invalidate all lines and clear MSHRs
            mshr_valid <= {NUM_MSHR{1'b0}};
            for (mshr_i = 0; mshr_i < NUM_MSHR; mshr_i = mshr_i + 1) begin
                mshr_state[mshr_i] <= IDLE;
            end
            for (i = 0; i < NUM_SETS; i = i + 1) begin
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    valid[i][j] <= 0;
                end
            end

        end else begin
            // MSHR allocation on new miss (only if not already matched and MSHR available)
            // Block allocation when all ways in set are reserved by active MSHRs
            if (cpu_req && !cache_hit && !mshr_match && mshr_available &&
                !victim_conflict && !all_ways_reserved_in_set) begin
                mshr_valid[free_mshr_id] <= 1'b1;
                mshr_tag[free_mshr_id] <= tag;
                mshr_index[free_mshr_id] <= set_index;
                mshr_word[free_mshr_id] <= word_offset;
                mshr_victim_way[free_mshr_id] <= final_victim;
                mshr_victim_tag[free_mshr_id] <= tags[set_index][final_victim];
                mshr_is_write[free_mshr_id] <= cpu_write;
                mshr_wdata[free_mshr_id] <= cpu_wdata;
                mshr_byte_en[free_mshr_id] <= cpu_byte_en;
                mshr_refill_count[free_mshr_id] <= 0;
                mshr_writeback_count[free_mshr_id] <= 0;

                if (dirty_victim) begin
                    mshr_state[free_mshr_id] <= WRITEBACK;
                end else begin
                    mshr_state[free_mshr_id] <= FETCH;
                    valid[set_index][final_victim] <= 1'b0;  // Invalidate victim
                end
            end

            // Process all MSHRs with single parameterized loop
            for (mshr_i = 0; mshr_i < NUM_MSHR; mshr_i = mshr_i + 1) begin
                // Only process if this MSHR has memory grant
                if (mshr_valid[mshr_i] && mem_grant_valid &&
                    (mem_grant_mshr == mshr_i[MSHR_ID_BITS-1:0])) begin
                    case (mshr_state[mshr_i])
                        WRITEBACK: begin
                            if (mem_valid) begin
                                if (mshr_writeback_count[mshr_i] == LAST_WORD_IDX) begin
                                    mshr_writeback_count[mshr_i] <= 0;
                                    mshr_state[mshr_i] <= FETCH;
                                    valid[mshr_index[mshr_i]][mshr_victim_way[mshr_i]] <= 1'b0;
                                end else begin
                                    mshr_writeback_count[mshr_i] <= mshr_writeback_count[mshr_i] + 1;
                                end
                            end
                        end

                        FETCH: begin
                            if (mem_valid) begin
                                data[mshr_index[mshr_i]][mshr_victim_way[mshr_i]][mshr_refill_count[mshr_i]] <= mem_data;
                                if (mshr_refill_count[mshr_i] == LAST_WORD_IDX) begin
                                    mshr_state[mshr_i] <= ALLOCATE;
                                    valid[mshr_index[mshr_i]][mshr_victim_way[mshr_i]] <= 1;
                                    tags[mshr_index[mshr_i]][mshr_victim_way[mshr_i]] <= mshr_tag[mshr_i];
                                end else begin
                                    mshr_refill_count[mshr_i] <= mshr_refill_count[mshr_i] + 1;
                                end
                            end
                        end

                        default: ; // IDLE, ALLOCATE handled separately
                    endcase
                end

                // ALLOCATE state runs without memory grant (single cycle)
                if (mshr_valid[mshr_i] && mshr_state[mshr_i] == ALLOCATE) begin
                    // Update LRU
                    lru_state[mshr_index[mshr_i]] <= update_lru(lru_state[mshr_index[mshr_i]], mshr_victim_way[mshr_i]);

                    // Handle write-allocate
                    if (mshr_is_write[mshr_i]) begin
                        dirty[mshr_index[mshr_i]][mshr_victim_way[mshr_i]] <= 1'b1;
                        if (mshr_byte_en[mshr_i][0]) data[mshr_index[mshr_i]][mshr_victim_way[mshr_i]][mshr_word[mshr_i]][7:0] <= mshr_wdata[mshr_i][7:0];
                        if (mshr_byte_en[mshr_i][1]) data[mshr_index[mshr_i]][mshr_victim_way[mshr_i]][mshr_word[mshr_i]][15:8] <= mshr_wdata[mshr_i][15:8];
                        if (mshr_byte_en[mshr_i][2]) data[mshr_index[mshr_i]][mshr_victim_way[mshr_i]][mshr_word[mshr_i]][23:16] <= mshr_wdata[mshr_i][23:16];
                        if (mshr_byte_en[mshr_i][3]) data[mshr_index[mshr_i]][mshr_victim_way[mshr_i]][mshr_word[mshr_i]][31:24] <= mshr_wdata[mshr_i][31:24];
                    end else begin
                        dirty[mshr_index[mshr_i]][mshr_victim_way[mshr_i]] <= 1'b0;
                    end

                    // Free MSHR
                    mshr_valid[mshr_i] <= 1'b0;
                    mshr_state[mshr_i] <= IDLE;
                end
            end

            // Handle cache hits (update LRU, handle writes) - can happen anytime
            if (cpu_req && cache_hit && !victim_conflict) begin
                lru_state[set_index] <= update_lru(lru_state[set_index], hit_way);
                if (cpu_write) begin
                    dirty[set_index][hit_way] <= 1'b1;
                    if (cpu_byte_en[0]) data[set_index][hit_way][word_offset][7:0] <= cpu_wdata[7:0];
                    if (cpu_byte_en[1]) data[set_index][hit_way][word_offset][15:8] <= cpu_wdata[15:8];
                    if (cpu_byte_en[2]) data[set_index][hit_way][word_offset][23:16] <= cpu_wdata[23:16];
                    if (cpu_byte_en[3]) data[set_index][hit_way][word_offset][31:24] <= cpu_wdata[31:24];
                end
            end
        end
    end

    // Check if any MSHR is completing (in ALLOCATE) for the current request address
    reg mshr_completing;
    reg [MSHR_ID_BITS-1:0] completing_mshr_id;
    integer cc;
    always @(*) begin
        mshr_completing = 1'b0;
        completing_mshr_id = {MSHR_ID_BITS{1'b0}};
        for (cc = 0; cc < NUM_MSHR; cc = cc + 1) begin
            if (mshr_valid[cc] && mshr_state[cc] == ALLOCATE &&
                mshr_tag[cc] == tag && mshr_index[cc] == set_index) begin
                mshr_completing = 1'b1;
                completing_mshr_id = cc[MSHR_ID_BITS-1:0];
            end
        end
    end

    // Output logic - single always block
    always @(*) begin
        cpu_data = {DATA_WIDTH{1'b0}};
        cpu_valid = 1'b0;
        cpu_stall = 1'b0;
        mem_req = 1'b0;
        mem_write = 1'b0;
        mem_addr = {ADDR_WIDTH{1'b0}};
        mem_wdata = {DATA_WIDTH{1'b0}};

        // Cache hit - serve immediately (unless victim conflict)
        if (cpu_req && cache_hit && !victim_conflict) begin
            cpu_data = data[set_index][hit_way][word_offset];
            cpu_valid = 1'b1;
        end
        // MSHR completing for this address - serve from refilled line
        else if (cpu_req && mshr_completing) begin
            cpu_data = data[mshr_index[completing_mshr_id]][mshr_victim_way[completing_mshr_id]][word_offset];
            cpu_valid = 1'b1;
        end
        // MSHR match (not completing) - stall (coalescing)
        else if (cpu_req && mshr_match) begin
            cpu_stall = 1'b1;
            cpu_valid = 1'b0;
        end
        // New miss - stall only if MSHRs full, victim conflict, or all ways reserved
        else if (cpu_req && !cache_hit) begin
            cpu_stall = !mshr_available || victim_conflict || all_ways_reserved_in_set;
            cpu_valid = 1'b0;
        end

        // Memory interface - driven by granted MSHR
        if (mem_grant_valid) begin
            case (mshr_state[mem_grant_mshr])
                WRITEBACK: begin
                    mem_req = 1'b1;
                    mem_write = 1'b1;
                    mem_addr = {mshr_victim_tag[mem_grant_mshr], mshr_index[mem_grant_mshr],
                               mshr_writeback_count[mem_grant_mshr], 2'b00};
                    mem_wdata = data[mshr_index[mem_grant_mshr]][mshr_victim_way[mem_grant_mshr]]
                                   [mshr_writeback_count[mem_grant_mshr]];
                end
                FETCH: begin
                    mem_req = 1'b1;
                    mem_write = 1'b0;
                    mem_addr = {mshr_tag[mem_grant_mshr], mshr_index[mem_grant_mshr],
                               mshr_refill_count[mem_grant_mshr], 2'b00};
                end
                default: ; // IDLE, ALLOCATE don't need memory
            endcase
        end
    end

endmodule

`default_nettype wire
