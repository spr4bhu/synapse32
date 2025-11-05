module pc(
   input clk,
   input rst,
   input j_signal,
   input stall,         // Stall input
   input [31:0] jump,
   output[31:0] out
);
   // pc_next is calculated combinationally
   reg [31:0] pc_current = 32'd0;
   wire [31:0] pc_next;

   // Combinational calculation of next PC
   assign pc_next = j_signal ? jump :
                    stall    ? pc_current :
                               pc_current + 32'h4;

   // Update PC register on clock edge with async reset
   always @ (posedge clk or posedge rst) begin
       if (rst) begin
           pc_current <= 32'b0;
       end else begin
           pc_current <= pc_next;
       end

   end

   assign out = pc_current;

endmodule
