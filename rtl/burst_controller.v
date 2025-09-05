`timescale 1ns/1ps

module burst_controller #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter BLOCK_SIZE = 8  // Number of words per block
)(
    input wire clk,
    input wire rst,
    
    // Interface to Cache (input side)
    input wire cache_mem_req,
    input wire [ADDR_WIDTH-1:0] cache_mem_addr,
    input wire [$clog2(BLOCK_SIZE):0] cache_mem_burst_len,
    output reg [DATA_WIDTH-1:0] cache_mem_data,
    output reg cache_mem_ready,
    output reg cache_mem_valid,
    output reg cache_mem_last,
    
    // Interface to Instruction Memory Port 1 (output side)
    output reg [ADDR_WIDTH-1:0] mem_addr,
    input wire [DATA_WIDTH-1:0] mem_data  // Direct combinational from instr_mem
);

    // State machine states
    localparam IDLE = 2'b00;
    localparam FETCH = 2'b01;
    localparam DELIVER = 2'b10;
    
    reg [1:0] state, next_state;
    reg [$clog2(BLOCK_SIZE):0] word_counter; 
    reg [$clog2(BLOCK_SIZE):0] words_to_fetch;
    reg [ADDR_WIDTH-1:0] current_addr;
    reg [DATA_WIDTH-1:0] fetched_data;

    // State machine - sequential logic
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= IDLE;
            word_counter <= 0;
            words_to_fetch <= 0;
            current_addr <= 0;
            fetched_data <= 0;
        end else begin
            state <= next_state;
            
            case (state)
                IDLE: begin
                    if (cache_mem_req) begin
                        current_addr <= cache_mem_addr;
                        words_to_fetch <= cache_mem_burst_len + 1;
                        word_counter <= 0;
                    end
                end
                
                FETCH: begin
                    fetched_data <= mem_data;
                end
                
                DELIVER: begin
                    if (word_counter < words_to_fetch - 1) begin
                        word_counter <= word_counter + 1;
                        current_addr <= current_addr + 4;
                    end else begin
                        word_counter <= 0;
                    end
                end
                
                default: begin  // FIXED: Added default case
                    // Do nothing, maintain current state
                end
            endcase
        end
    end
    
    // Next state logic - combinational
    always @(*) begin
        next_state = state;
        
        case (state)
            IDLE: begin
                if (cache_mem_req) begin
                    next_state = FETCH;
                end
            end
            
            FETCH: begin
                next_state = DELIVER;
            end
            
            DELIVER: begin
                if (word_counter >= words_to_fetch - 1) begin
                    next_state = IDLE;
                end else begin
                    next_state = FETCH;
                end
            end
            
            default: begin  // FIXED: Added default case
                next_state = IDLE;
            end
        endcase
    end
    
    // Output logic - combinational
    always @(*) begin
        // Default values
        cache_mem_ready = 0;
        cache_mem_valid = 0;
        cache_mem_last = 0;
        cache_mem_data = 0;
        mem_addr = current_addr;
        
        case (state)
            IDLE: begin
                cache_mem_ready = 1;  // Ready to accept new requests
                mem_addr = cache_mem_addr; 
            end
            
            FETCH: begin
                // Set address for memory to read
                mem_addr = current_addr;
                // Memory is combinational, so data will be available same cycle
            end
            
            DELIVER: begin
                // Send the previously fetched data to cache
                cache_mem_valid = 1;
                cache_mem_data = fetched_data;
                
                // Signal last word
                if (word_counter >= words_to_fetch - 1) begin
                    cache_mem_last = 1;
                end
            end
            default: begin
                // Default case for completeness
            end
        endcase
    end

endmodule