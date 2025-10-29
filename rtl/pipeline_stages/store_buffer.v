`default_nettype none

module store_buffer (
    input wire clk,
    input wire rst,
    input wire cache_stall,
    input wire hazard_stall,

    // Store capture interface (from memory_unit)
    input wire capture_store,           // Pulse to capture a store
    input wire [31:0] store_addr,       // Address to store to
    input wire [31:0] store_data,       // Data to store
    input wire [3:0] store_byte_enable, // Which bytes to write

    // Load forwarding interface (to memory_unit)
    input wire load_request,            // Load is requesting data
    input wire [31:0] load_addr,        // Address being loaded
    output wire forward_valid,          // Buffer has matching data to forward
    output wire [31:0] forward_data,    // Data to forward to load

    // Memory write interface (to data_mem)
    output reg mem_wr_en,               // Write enable to memory
    output reg [31:0] mem_wr_addr,      // Write address
    output reg [31:0] mem_wr_data,      // Write data
    output reg [3:0] mem_wr_byte_enable // Byte enables
);

    // Store buffer entry
    reg buffer_valid;
    reg [31:0] buffer_addr;
    reg [31:0] buffer_data;
    reg [3:0] buffer_byte_enable;

    // Forwarding logic
    wire addr_match = (buffer_addr == load_addr);
    assign forward_valid = buffer_valid && addr_match && load_request;
    assign forward_data = buffer_data;

    // Debug output (can be enabled for debugging)
    // always @(posedge clk) begin
    //     if (capture_store) begin
    //         $display("[STORE_BUFFER] @%t: CAPTURE store addr=0x%h data=0x%h", $time, store_addr, store_data);
    //     end
    //     if (load_request) begin
    //         $display("[STORE_BUFFER] @%t: LOAD REQUEST addr=0x%h buffer_valid=%b addr_match=%b forward=%b data=0x%h",
    //                  $time, load_addr, buffer_valid, addr_match, forward_valid, forward_data);
    //     end
    // end

    // Buffer management
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            buffer_valid <= 1'b0;
            buffer_addr <= 32'b0;
            buffer_data <= 32'b0;
            buffer_byte_enable <= 4'b0;
            mem_wr_en <= 1'b0;
            mem_wr_addr <= 32'b0;
            mem_wr_data <= 32'b0;
            mem_wr_byte_enable <= 4'b0;
        end else if (!cache_stall) begin
            // Pipeline is running normally (only gate with cache_stall, not hazard_stall)
            // hazard_stall affects instruction fetch/decode, not memory operations in progress

            if (capture_store) begin
                // New store to capture
                // First, write current buffer contents to memory if valid
                if (buffer_valid) begin
                    mem_wr_en <= 1'b1;
                    mem_wr_addr <= buffer_addr;
                    mem_wr_data <= buffer_data;
                    mem_wr_byte_enable <= buffer_byte_enable;
                end else begin
                    mem_wr_en <= 1'b0;
                end

                // Then capture the new store
                buffer_valid <= 1'b1;
                buffer_addr <= store_addr;
                buffer_data <= store_data;
                buffer_byte_enable <= store_byte_enable;
            end else begin
                // No new store, write buffer to memory if valid
                if (buffer_valid) begin
                    mem_wr_en <= 1'b1;
                    mem_wr_addr <= buffer_addr;
                    mem_wr_data <= buffer_data;
                    mem_wr_byte_enable <= buffer_byte_enable;
                    buffer_valid <= 1'b0; // Clear buffer after writing
                end else begin
                    mem_wr_en <= 1'b0;
                end
            end
        end else begin
            // Pipeline is stalled - freeze buffer and disable writes
            mem_wr_en <= 1'b0;
            // Keep buffer_valid, buffer_addr, buffer_data, buffer_byte_enable unchanged
        end
    end

endmodule
