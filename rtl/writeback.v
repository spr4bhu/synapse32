`default_nettype none
`include "instr_defines.vh"

module writeback (
    input wire valid_in,
    input wire rd_valid_in,
    input wire [4:0] rd_addr_in,
    input wire [31:0] rd_value_in,
    input wire [31:0] mem_data_in,
    input wire [5:0] instr_id_in,
    output wire [4:0] rd_addr_out,
    output wire [31:0] rd_value_out,
    output wire wr_en_out
);
    wire is_load_instr;
    assign is_load_instr = (instr_id_in == INSTR_LB) || 
                           (instr_id_in == INSTR_LH) || 
                           (instr_id_in == INSTR_LW) || 
                           (instr_id_in == INSTR_LBU) || 
                           (instr_id_in == INSTR_LHU);
    
    assign rd_addr_out = rd_addr_in;
    assign rd_value_out = is_load_instr ? mem_data_in : rd_value_in;

    assign wr_en_out = valid_in &&              // Instruction is valid (not a bubble)
                       rd_valid_in &&            // Instruction requires write
                       (rd_addr_in != 5'b0);     // Not writing to x0 (RISC-V hardwired zero)

endmodule