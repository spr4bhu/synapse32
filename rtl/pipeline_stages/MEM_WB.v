`default_nettype none
module MEM_WB (
    input wire clk,
    input wire rst,
    
    // Standard pipeline register inputs
    input wire [4:0] rs1_addr_in,
    input wire [4:0] rs2_addr_in,
    input wire [4:0] rd_addr_in,
    input wire [31:0] rs1_value_in,
    input wire [31:0] rs2_value_in,
    input wire [31:0] pc_in,
    input wire [31:0] mem_addr_in,
    input wire [31:0] exec_output_in,    // ALU result
    input wire jump_signal_in,
    input wire [31:0] jump_addr_in,
    input wire [5:0] instr_id_in,
    input wire rd_valid_in,
    // REMOVED: mem_data_in - no longer latch memory data here
    
    // Store-load forwarding inputs (keep if needed)
    input wire store_load_hazard,
    input wire [31:0] store_data,
    
    // Standard pipeline register outputs
    output reg [4:0] rs1_addr_out,
    output reg [4:0] rs2_addr_out,
    output reg [4:0] rd_addr_out,
    output reg [31:0] rs1_value_out,
    output reg [31:0] rs2_value_out,
    output reg [31:0] pc_out,
    output reg [31:0] mem_addr_out,
    output reg [31:0] exec_output_out,   // ALU result to WB
    output reg jump_signal_out,
    output reg [31:0] jump_addr_out,
    output reg [5:0] instr_id_out,
    output reg rd_valid_out
    // REMOVED: mem_data_out - WB gets memory data directly from top level
);

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            // Reset all registers
            rs1_addr_out <= 5'b0;
            rs2_addr_out <= 5'b0;
            rd_addr_out <= 5'b0;
            rs1_value_out <= 32'b0;
            rs2_value_out <= 32'b0;
            pc_out <= 32'b0;
            mem_addr_out <= 32'b0;
            exec_output_out <= 32'b0;
            jump_signal_out <= 1'b0;
            jump_addr_out <= 32'b0;
            instr_id_out <= 6'b0;
            rd_valid_out <= 1'b0;
        end
        else begin
            // Transfer all register values (no memory data latching)
            rs1_addr_out <= rs1_addr_in;
            rs2_addr_out <= rs2_addr_in;
            rd_addr_out <= rd_addr_in;
            rs1_value_out <= rs1_value_in;
            rs2_value_out <= rs2_value_in;
            pc_out <= pc_in;
            mem_addr_out <= mem_addr_in;
            exec_output_out <= exec_output_in;  // Pass ALU result through
            jump_signal_out <= jump_signal_in;
            jump_addr_out <= jump_addr_in;
            instr_id_out <= instr_id_in;
            rd_valid_out <= rd_valid_in;
            
            // NOTE: No memory data latching - WB gets it directly from top level
        end
    end
endmodule