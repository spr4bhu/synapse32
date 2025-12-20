`default_nettype none
//-----------------------------------------------------------------------------
// icache_nway_multiword.v - N-way Set-Associative Instruction Cache
//
// Configurable instruction cache with:
// - Configurable associativity (N ways: 1, 2, 4, 8, 16, ...)
// - Configurable number of sets
// - Configurable cache line size
// - Round-robin replacement policy
// - FENCE.I cache invalidation support
//-----------------------------------------------------------------------------

module icache #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter NUM_WAYS = 4,           // N-way associativity (1, 2, 4, 8, 16, ...)
    parameter NUM_SETS = 64,          // Number of cache sets
    parameter CACHE_LINE_WORDS = 4    // Words per cache line (16 bytes)
)(
    input wire clk,
    input wire rst,
    
    // CPU Interface
    input wire [ADDR_WIDTH-1:0] cpu_addr,      // Instruction fetch address
    input wire cpu_req,                         // Fetch request from CPU
    output reg [DATA_WIDTH-1:0] cpu_data,      // Instruction to CPU
    output reg cpu_valid,                       // Data valid (hit)
    output reg cpu_stall,                       // Stall CPU on miss
    
    // Memory Interface
    output reg [ADDR_WIDTH-1:0] mem_addr,      // Address to main memory
    output reg mem_req,                         // Memory request
    input wire [DATA_WIDTH-1:0] mem_data,      // Data from memory
    input wire mem_valid,                       // Memory data valid
    
    // Cache control
    input wire invalidate                       // Invalidate entire cache (FENCE.I)
);

    //-------------------------------------------------------------------------
    // Parameter calculations
    //-------------------------------------------------------------------------
    localparam OFFSET_BITS = $clog2(CACHE_LINE_WORDS);  // 2 bits for 4 words
    localparam INDEX_BITS = $clog2(NUM_SETS);            // 6 bits for 64 sets
    localparam TAG_BITS = ADDR_WIDTH - INDEX_BITS - OFFSET_BITS - 2;
    localparam WAY_BITS = (NUM_WAYS == 1) ? 1 : $clog2(NUM_WAYS);
    
    //-------------------------------------------------------------------------
    // State machine states
    //-------------------------------------------------------------------------
    localparam [1:0] STATE_IDLE   = 2'b00;
    localparam [1:0] STATE_MISS   = 2'b01;
    localparam [1:0] STATE_REFILL = 2'b10;
    localparam [1:0] STATE_DONE   = 2'b11;
    
    //-------------------------------------------------------------------------
    // Cache storage
    //-------------------------------------------------------------------------
    // Valid bits: [set][way]
    reg valid [0:NUM_SETS-1][0:NUM_WAYS-1];
    
    // Tag storage: [set][way]
    reg [TAG_BITS-1:0] tags [0:NUM_SETS-1][0:NUM_WAYS-1];
    
    // Data storage: [set][way][word]
    reg [DATA_WIDTH-1:0] data [0:NUM_SETS-1][0:NUM_WAYS-1][0:CACHE_LINE_WORDS-1];
    
    // Round-robin replacement counter per set
    reg [WAY_BITS-1:0] rr_counter [0:NUM_SETS-1];
    
    //-------------------------------------------------------------------------
    // State machine registers
    //-------------------------------------------------------------------------
    reg [1:0] state;
    reg [OFFSET_BITS-1:0] refill_count;
    reg [WAY_BITS-1:0] victim_way;
    reg [ADDR_WIDTH-1:0] saved_addr;
    reg [TAG_BITS-1:0] saved_tag;
    reg [INDEX_BITS-1:0] saved_index;
    
    //-------------------------------------------------------------------------
    // Address field extraction
    //-------------------------------------------------------------------------
    wire [OFFSET_BITS-1:0] word_offset = cpu_addr[OFFSET_BITS+1:2];
    wire [INDEX_BITS-1:0] set_index = cpu_addr[INDEX_BITS+OFFSET_BITS+1:OFFSET_BITS+2];
    wire [TAG_BITS-1:0] tag = cpu_addr[ADDR_WIDTH-1:INDEX_BITS+OFFSET_BITS+2];
    
    //-------------------------------------------------------------------------
    // Hit detection (parallel tag comparison for all ways)
    //-------------------------------------------------------------------------
    reg [NUM_WAYS-1:0] way_hit;
    reg cache_hit;
    reg [WAY_BITS-1:0] hit_way;
    
    // Calculate hit signals
    integer h;
    always @(*) begin
        way_hit = {NUM_WAYS{1'b0}};
        for (h = 0; h < NUM_WAYS; h = h + 1) begin
            way_hit[h] = valid[set_index][h] && (tags[set_index][h] == tag);
        end
        cache_hit = |way_hit;
    end
    
    // Determine which way hit (priority encoder)
    integer w;
    always @(*) begin
        hit_way = {WAY_BITS{1'b0}};
        for (w = NUM_WAYS-1; w >= 0; w = w - 1) begin
            if (way_hit[w]) hit_way = w[WAY_BITS-1:0];
        end
    end
    
    //-------------------------------------------------------------------------
    // Round-robin replacement logic
    // Simple: use counter value as victim, increment after each replacement
    //-------------------------------------------------------------------------
    
    // Find an invalid way first, otherwise use round-robin counter
    reg [WAY_BITS-1:0] selected_victim;
    reg found_invalid;
    integer vi;
    always @(*) begin
        found_invalid = 1'b0;
        selected_victim = rr_counter[set_index];  // Default to round-robin
        // First check for invalid ways (prefer filling empty ways)
        for (vi = 0; vi < NUM_WAYS; vi = vi + 1) begin
            if (!valid[set_index][vi] && !found_invalid) begin
                selected_victim = vi[WAY_BITS-1:0];
                found_invalid = 1'b1;
            end
        end
    end
    
    //-------------------------------------------------------------------------
    // Refill completion check
    //-------------------------------------------------------------------------
    /* verilator lint_off WIDTHTRUNC */
    localparam [OFFSET_BITS-1:0] LAST_WORD_IDX = CACHE_LINE_WORDS - 1;
    /* verilator lint_on WIDTHTRUNC */
    wire refill_done = (refill_count == LAST_WORD_IDX);
    
    //-------------------------------------------------------------------------
    // Output logic (combinational)
    //-------------------------------------------------------------------------
    always @(*) begin
        cpu_data = {DATA_WIDTH{1'b0}};
        cpu_valid = 1'b0;
        cpu_stall = 1'b0;
        mem_req = 1'b0;
        mem_addr = {ADDR_WIDTH{1'b0}};
        
        case (state)
            STATE_IDLE: begin
                if (cpu_req) begin
                    if (cache_hit) begin
                        // Cache hit - return data immediately
                        cpu_data = data[set_index][hit_way][word_offset];
                        cpu_valid = 1'b1;
                        cpu_stall = 1'b0;
                    end else begin
                        // Cache miss - stall and start refill
                        cpu_stall = 1'b1;
                        cpu_valid = 1'b0;
                    end
                end
            end
            
            STATE_MISS: begin
                // Initiate memory request for first word
                cpu_stall = 1'b1;
                mem_req = 1'b1;
                // Calculate base address of cache line (clear offset bits)
                mem_addr = {saved_addr[ADDR_WIDTH-1:OFFSET_BITS+2], {OFFSET_BITS{1'b0}}, 2'b00};
            end
            
            STATE_REFILL: begin
                // Fetching cache line from memory
                cpu_stall = 1'b1;
                mem_req = 1'b1;
                // Request next word in cache line
                mem_addr = {saved_addr[ADDR_WIDTH-1:OFFSET_BITS+2], refill_count, 2'b00};
            end
            
            STATE_DONE: begin
                // Cache line refilled - check if address still matches (branch may have changed it)
                if (cpu_addr == saved_addr) begin
                    // Address matches - serve the requested word
                    cpu_data = data[saved_index][victim_way][saved_addr[OFFSET_BITS+1:2]];
                    cpu_valid = 1'b1;
                    cpu_stall = 1'b0;
                end else begin
                    // Address changed (branch during miss) - don't serve stale data
                    // Check if new address hits in cache
                    if (cache_hit) begin
                        cpu_data = data[set_index][hit_way][word_offset];
                        cpu_valid = 1'b1;
                        cpu_stall = 1'b0;
                    end else begin
                        // New address also misses - stall and restart
                        cpu_stall = 1'b1;
                        cpu_valid = 1'b0;
                    end
                end
            end
            
            default: begin
                cpu_stall = 1'b0;
            end
        endcase
    end
    
    //-------------------------------------------------------------------------
    // State machine and cache update logic (sequential)
    //-------------------------------------------------------------------------
    integer i, j;
    
    always @(posedge clk) begin
        if (rst) begin
            // Reset state
            state <= STATE_IDLE;
            refill_count <= {OFFSET_BITS{1'b0}};
            victim_way <= {WAY_BITS{1'b0}};
            saved_addr <= {ADDR_WIDTH{1'b0}};
            saved_tag <= {TAG_BITS{1'b0}};
            saved_index <= {INDEX_BITS{1'b0}};
            
            // Invalidate all cache lines and reset round-robin counters
            for (i = 0; i < NUM_SETS; i = i + 1) begin
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    valid[i][j] <= 1'b0;
                    tags[i][j] <= {TAG_BITS{1'b0}};
                end
                rr_counter[i] <= {WAY_BITS{1'b0}};
            end
        end else if (invalidate) begin
            // FENCE.I - invalidate entire cache
            state <= STATE_IDLE;
            for (i = 0; i < NUM_SETS; i = i + 1) begin
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    valid[i][j] <= 1'b0;
                end
                // Optionally reset round-robin counters on invalidate
                rr_counter[i] <= {WAY_BITS{1'b0}};
            end
        end else begin
            case (state)
                STATE_IDLE: begin
                    if (cpu_req && !cache_hit) begin
                        // Miss - save address and select victim
                        state <= STATE_MISS;
                        saved_addr <= cpu_addr;
                        saved_tag <= tag;
                        saved_index <= set_index;
                        victim_way <= selected_victim;
                        refill_count <= {OFFSET_BITS{1'b0}};
                    end
                    // No LRU update needed for round-robin on hits
                end
                
                STATE_MISS: begin
                    if (mem_valid) begin
                        // First word received, store it
                        data[saved_index][victim_way][refill_count] <= mem_data;
                        
                        if (refill_done) begin
                            // All words received
                            state <= STATE_DONE;
                            // Mark line as valid and update tag
                            valid[saved_index][victim_way] <= 1'b1;
                            tags[saved_index][victim_way] <= saved_tag;
                        end else begin
                            refill_count <= refill_count + {{(OFFSET_BITS-1){1'b0}}, 1'b1};
                            state <= STATE_REFILL;
                        end
                    end
                end
                
                STATE_REFILL: begin
                    if (mem_valid) begin
                        // Store received word
                        data[saved_index][victim_way][refill_count] <= mem_data;
                        
                        if (refill_done) begin
                            // All words received
                            state <= STATE_DONE;
                            // Mark line as valid and update tag
                            valid[saved_index][victim_way] <= 1'b1;
                            tags[saved_index][victim_way] <= saved_tag;
                        end else begin
                            refill_count <= refill_count + {{(OFFSET_BITS-1){1'b0}}, 1'b1};
                        end
                    end
                end
                
                STATE_DONE: begin
                    // Update round-robin counter for this set (increment for next replacement)
                    if (NUM_WAYS == 1) begin
                        rr_counter[saved_index] <= {WAY_BITS{1'b0}};
                    end else begin
                        // Increment and wrap around
                        /* verilator lint_off WIDTHEXPAND */
                        if (rr_counter[saved_index] == NUM_WAYS[WAY_BITS-1:0] - 1)
                        /* verilator lint_on WIDTHEXPAND */
                            rr_counter[saved_index] <= {WAY_BITS{1'b0}};
                        else
                            rr_counter[saved_index] <= rr_counter[saved_index] + {{(WAY_BITS-1){1'b0}}, 1'b1};
                    end
                    
                    // Check if address changed during miss (branch/jump happened)
                    if (cpu_addr == saved_addr) begin
                        // Normal completion - return to idle
                        state <= STATE_IDLE;
                    end else if (cache_hit) begin
                        // New address hits - return to idle (will serve on next cycle)
                        state <= STATE_IDLE;
                    end else begin
                        // New address misses - start new refill
                        state <= STATE_MISS;
                        saved_addr <= cpu_addr;
                        saved_tag <= tag;
                        saved_index <= set_index;
                        victim_way <= selected_victim;
                        refill_count <= {OFFSET_BITS{1'b0}};
                    end
                end
                
                default: begin
                    state <= STATE_IDLE;
                end
            endcase
        end
    end

endmodule
