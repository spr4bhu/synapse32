`default_nettype none

// N-way set-associative instruction cache with FENCE.I support
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

    // Cache control
    input wire invalidate
);

    localparam OFFSET_BITS = $clog2(CACHE_LINE_WORDS);
    localparam INDEX_BITS = $clog2(NUM_SETS);
    localparam TAG_BITS = ADDR_WIDTH - INDEX_BITS - OFFSET_BITS - 2;
    localparam WAY_BITS = (NUM_WAYS == 1) ? 1 : $clog2(NUM_WAYS);

    // 3-State FSM
    localparam [1:0] IDLE     = 2'd0;
    localparam [1:0] FETCH    = 2'd1;
    localparam [1:0] ALLOCATE = 2'd2;

    // Cache storage
    reg valid [0:NUM_SETS-1][0:NUM_WAYS-1];
    reg [TAG_BITS-1:0] tags [0:NUM_SETS-1][0:NUM_WAYS-1];
    reg [DATA_WIDTH-1:0] data [0:NUM_SETS-1][0:NUM_WAYS-1][0:CACHE_LINE_WORDS-1];
    reg [WAY_BITS-1:0] rr_counter [0:NUM_SETS-1];

    // State machine registers
    reg [1:0] state;
    reg [OFFSET_BITS-1:0] refill_count;
    reg [WAY_BITS-1:0] victim_way;
    reg [ADDR_WIDTH-1:0] saved_addr;
    reg [TAG_BITS-1:0] saved_tag;
    reg [INDEX_BITS-1:0] saved_index;

    // Address field extraction
    wire [OFFSET_BITS-1:0] word_offset = cpu_addr[OFFSET_BITS+1:2];
    wire [INDEX_BITS-1:0] set_index = cpu_addr[INDEX_BITS+OFFSET_BITS+1:OFFSET_BITS+2];
    wire [TAG_BITS-1:0] tag = cpu_addr[ADDR_WIDTH-1:INDEX_BITS+OFFSET_BITS+2];

    // Hit detection
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

    // Round-robin replacement logic
    reg [WAY_BITS-1:0] selected_victim;
    reg found_invalid;
    integer vi;
    always @(*) begin
        found_invalid = 1'b0;
        selected_victim = rr_counter[set_index];
        for (vi = 0; vi < NUM_WAYS; vi = vi + 1) begin
            if (!valid[set_index][vi] && !found_invalid) begin
                selected_victim = vi[WAY_BITS-1:0];
                found_invalid = 1'b1;
            end
        end
    end

    // Refill completion check
    localparam [OFFSET_BITS-1:0] LAST_WORD_IDX = OFFSET_BITS'(CACHE_LINE_WORDS - 1);
    wire refill_done = (refill_count == LAST_WORD_IDX);

    // State machine and cache update logic
    integer i, j;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            saved_tag <= 0;
            saved_index <= 0;
            saved_addr <= 0;
            victim_way <= 0;
            refill_count <= 0;

            for (i = 0; i < NUM_SETS; i = i + 1) begin
                rr_counter[i] <= 0;
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    tags[i][j] <= 0;
                    valid[i][j] <= 0;
                end
            end

        end else if (invalidate) begin
            state <= IDLE;
            for (i = 0; i < NUM_SETS; i = i + 1) begin
                for (j = 0; j < NUM_WAYS; j = j + 1) begin
                    valid[i][j] <= 0;
                end
                rr_counter[i] <= 0;
            end

        end else begin
            case (state)
                IDLE: begin
                    if (cpu_req && !cache_hit) begin
                        state <= FETCH;
                        saved_addr <= cpu_addr;
                        saved_tag <= tag;
                        saved_index <= set_index;
                        victim_way <= selected_victim;
                        refill_count <= 0;
                    end
                end

                FETCH: begin
                    if (mem_valid) begin
                        data[saved_index][victim_way][refill_count] <= mem_data;

                        if (refill_done) begin
                            state <= ALLOCATE;
                            valid[saved_index][victim_way] <= 1;
                            tags[saved_index][victim_way] <= saved_tag;
                        end else begin
                            refill_count <= refill_count + 1;
                        end
                    end
                end

                ALLOCATE: begin
                    if (NUM_WAYS > 1) begin
                        if (rr_counter[saved_index] == WAY_BITS'(NUM_WAYS - 1)) begin
                            rr_counter[saved_index] <= 0;
                        end else begin
                            rr_counter[saved_index] <= rr_counter[saved_index] + 1;
                        end
                    end

                    // Check if address changed during miss (branch/jump)
                    if (cpu_addr == saved_addr) begin
                        state <= IDLE;
                    end else if (cache_hit) begin
                        state <= IDLE;
                    end else begin
                        // New address misses - start new refill
                        state <= FETCH;
                        saved_addr <= cpu_addr;
                        saved_tag <= tag;
                        saved_index <= set_index;
                        victim_way <= selected_victim;
                        refill_count <= 0;
                    end
                end

                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end

    // Output logic
    always @(*) begin
        cpu_data = {DATA_WIDTH{1'b0}};
        cpu_valid = 1'b0;
        cpu_stall = 1'b0;
        mem_req = 1'b0;
        mem_addr = {ADDR_WIDTH{1'b0}};

        case (state)
            IDLE: begin
                if (cpu_req) begin
                    if (cache_hit) begin
                        cpu_data = data[set_index][hit_way][word_offset];
                        cpu_valid = 1'b1;
                        cpu_stall = 1'b0;
                    end else begin
                        cpu_stall = 1'b1;
                        cpu_valid = 1'b0;
                        mem_req = 1'b1;
                        mem_addr = {cpu_addr[ADDR_WIDTH-1:OFFSET_BITS+2], {OFFSET_BITS{1'b0}}, 2'b00};
                    end
                end
            end

            FETCH: begin
                cpu_stall = 1'b1;
                mem_req = 1'b1;
                mem_addr = {saved_addr[ADDR_WIDTH-1:OFFSET_BITS+2], refill_count, 2'b00};
            end

            ALLOCATE: begin
                // Check if address matches saved address
                if (cpu_addr == saved_addr) begin
                    cpu_data = data[saved_index][victim_way][saved_addr[OFFSET_BITS+1:2]];
                    cpu_valid = 1'b1;
                    cpu_stall = 1'b0;
                end else begin
                    // Address changed - check if new address hits
                    if (cache_hit) begin
                        cpu_data = data[set_index][hit_way][word_offset];
                        cpu_valid = 1'b1;
                        cpu_stall = 1'b0;
                    end else begin
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

endmodule
