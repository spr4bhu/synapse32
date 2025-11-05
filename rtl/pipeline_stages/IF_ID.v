`timescale 1ns/1ps
`default_nettype none

module IF_ID(
    input wire clk,
    input wire rst,
    input wire [31:0] pc_in,
    input wire [31:0] instruction_in,
    input wire enable,                 // Enable signal for stalls
    input wire valid_in,
    output reg [31:0] pc_out,
    output reg [31:0] instruction_out,
    output reg valid_out
);

always @(negedge clk or posedge rst) begin
    if (rst) begin
        pc_out <= 32'b0;
        instruction_out <= 32'b0;
        valid_out <= 1'b0;
    end else if (enable) begin
        pc_out <= pc_in;
        instruction_out <= instruction_in;
        valid_out <= valid_in;
    end
    // else hold all values (stalled)
end

endmodule