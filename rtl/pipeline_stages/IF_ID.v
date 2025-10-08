`timescale 1ns/1ps
`default_nettype none

module IF_ID(
    input wire clk,
    input wire rst,
    input wire [31:0] pc_in,
    input wire [31:0] instruction_in,
    input wire stall,
    input wire valid_in,              // NEW
    output reg [31:0] pc_out,
    output reg [31:0] instruction_out,
    output reg valid_out               // NEW
);

always @(posedge clk or posedge rst) begin
    if (rst) begin
        pc_out <= 32'b0;
        instruction_out <= 32'b0;
        valid_out <= 1'b0;            // NEW
    end else if (!stall) begin        // Simplified - just check !stall
        pc_out <= pc_in;
        instruction_out <= instruction_in;
        valid_out <= valid_in;        // NEW
    end
    // else hold all values (including valid)
end

endmodule