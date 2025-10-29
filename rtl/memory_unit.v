`default_nettype none
`include "instr_defines.vh"

module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire cache_stall,        // NEW: Cache stall signal for comprehensive gating
    input wire hazard_stall,       // NEW: Hazard stall signal for comprehensive gating
    input wire [5:0] instr_id,
    input wire [31:0] rs2_value,
    input wire [31:0] mem_addr,

    // Store buffer interface
    output wire capture_store,          // Signal to capture store in buffer
    output wire [31:0] store_addr_out,  // Address for store buffer
    output wire [31:0] store_data_out,  // Data for store buffer
    output wire [3:0] store_byte_en_out,// Byte enables for store buffer

    // Load forwarding from store buffer
    input wire buffer_forward_valid,    // Buffer has matching data
    input wire [31:0] buffer_forward_data, // Forwarded data from buffer
    output wire load_request,           // This stage is requesting a load

    // Original memory interface (now driven by store buffer)
    output wire wr_enable,              // DEPRECATED: driven by store buffer now
    output wire read_enable,
    output wire [31:0] wr_data,         // DEPRECATED: driven by store buffer now
    output wire [31:0] read_addr,
    output wire [31:0] wr_addr,         // DEPRECATED: driven by store buffer now
    output wire [3:0] write_byte_enable,// DEPRECATED: driven by store buffer now
    output wire [2:0] load_type,

    // Load data input (can be from memory or forwarded)
    input wire [31:0] mem_read_data,
    output wire [31:0] load_data_out    // Final load data (forwarded or from memory)
);

    // Instruction type detection
    wire is_store;
    wire is_load;

    assign is_store = (instr_id == INSTR_SB) ||
                      (instr_id == INSTR_SH) ||
                      (instr_id == INSTR_SW);

    assign is_load = (instr_id == INSTR_LB) ||
                     (instr_id == INSTR_LH) ||
                     (instr_id == INSTR_LW) ||
                     (instr_id == INSTR_LBU) ||
                     (instr_id == INSTR_LHU);

    // Store buffer capture signals
    // Capture store when it's valid and not cache-stalled
    // Note: Don't gate with hazard_stall - that's for the NEXT instruction, not current MEM stage
    assign capture_store = is_store && valid_in && !cache_stall;
    assign store_addr_out = mem_addr;

    // Debug (can be enabled for debugging)
    // always @(posedge clk) begin
    //     if (capture_store) begin
    //         $display("[MEM_UNIT] @%t: CAPTURE_STORE signal=1 addr=0x%h data=0x%h valid=%b is_store=%b",
    //                  $time, mem_addr, store_data_out, valid_in, is_store);
    //     end
    //     if (is_store && valid_in) begin
    //         $display("[MEM_UNIT] @%t: STORE instr_id=%d addr=0x%h data=0x%h cache_stall=%b hazard_stall=%b capture=%b",
    //                  $time, instr_id, mem_addr, store_data_out, cache_stall, hazard_stall, capture_store);
    //     end
    // end

    // Store data formatting (same as before)
    assign store_data_out =
        (instr_id == INSTR_SB) ? {24'b0, rs2_value[7:0]} :
        (instr_id == INSTR_SH) ? {16'b0, rs2_value[15:0]} :
        (instr_id == INSTR_SW) ? rs2_value :
        32'b0;

    // Byte enable for stores
    assign store_byte_en_out =
        (instr_id == INSTR_SB) ? 4'b0001 :
        (instr_id == INSTR_SH) ? ((mem_addr[0] == 1'b0) ? 4'b0011 : 4'b0000) :
        (instr_id == INSTR_SW) ? ((mem_addr[1:0] == 2'b00) ? 4'b1111 : 4'b0000) :
        4'b0000;

    // Load request signal
    // Note: Don't gate with hazard_stall - that affects dependent instructions, not the load itself
    assign load_request = is_load && valid_in && !cache_stall;

    // DEPRECATED: These are now driven by store buffer, but kept for compatibility
    // They will be overridden in top-level by store buffer outputs
    assign wr_enable = 1'b0;  // Store buffer drives this now
    assign wr_data = 32'b0;   // Store buffer drives this now
    assign wr_addr = 32'b0;   // Store buffer drives this now
    assign write_byte_enable = 4'b0; // Store buffer drives this now

    // Load path
    assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;
    assign read_addr = mem_addr;

    // Load type encoding
    assign load_type =
        (instr_id == INSTR_LB) ? 3'b000 :
        (instr_id == INSTR_LH) ? 3'b001 :
        (instr_id == INSTR_LW) ? 3'b010 :
        (instr_id == INSTR_LBU) ? 3'b100 :
        (instr_id == INSTR_LHU) ? 3'b101 :
        3'b111;

    // Load data output - use forwarded data if available, otherwise memory data
    assign load_data_out = buffer_forward_valid ? buffer_forward_data : mem_read_data;

endmodule