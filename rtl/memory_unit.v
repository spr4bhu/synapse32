`default_nettype none
`include "instr_defines.vh"

module memory_unit (
    input wire clk,
    input wire rst,
    input wire valid_in,
    input wire cache_stall,
    input wire hazard_stall,
    input wire [5:0] instr_id,
    input wire [31:0] rs2_value,
    input wire [31:0] mem_addr,

    // Store buffer interface
    output wire capture_store,
    output wire [31:0] store_addr_out,
    output wire [31:0] store_data_out,
    output wire [3:0] store_byte_en_out,

    // Load forwarding from store buffer
    input wire buffer_forward_valid,
    input wire [31:0] buffer_forward_data,
    output wire load_request,

    // Memory read interface
    output wire read_enable,
    output wire [31:0] read_addr,
    output wire [2:0] load_type,

    // Load data
    input wire [31:0] mem_read_data,
    output wire [31:0] load_data_out
);

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

    assign capture_store = is_store && valid_in && !cache_stall;
    assign store_addr_out = mem_addr;

    assign store_data_out =
        (instr_id == INSTR_SB) ? {24'b0, rs2_value[7:0]} :
        (instr_id == INSTR_SH) ? {16'b0, rs2_value[15:0]} :
        (instr_id == INSTR_SW) ? rs2_value :
        32'b0;

    assign store_byte_en_out =
        (instr_id == INSTR_SB) ? 4'b0001 :
        (instr_id == INSTR_SH) ? ((mem_addr[0] == 1'b0) ? 4'b0011 : 4'b0000) :
        (instr_id == INSTR_SW) ? ((mem_addr[1:0] == 2'b00) ? 4'b1111 : 4'b0000) :
        4'b0000;

    assign load_request = is_load && valid_in && !cache_stall;

    assign read_enable = is_load && valid_in && !cache_stall && !hazard_stall;
    assign read_addr = mem_addr;

    assign load_type =
        (instr_id == INSTR_LB) ? 3'b000 :
        (instr_id == INSTR_LH) ? 3'b001 :
        (instr_id == INSTR_LW) ? 3'b010 :
        (instr_id == INSTR_LBU) ? 3'b100 :
        (instr_id == INSTR_LHU) ? 3'b101 :
        3'b111;

    assign load_data_out = buffer_forward_valid ? buffer_forward_data : mem_read_data;

endmodule
