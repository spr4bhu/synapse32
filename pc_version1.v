module pc(
   input clk,
   input rst,
   input j_signal,
   input stall,         // Stall input
   input [31:0] jump,
   output[31:0] out
);
   // INDUSTRY STANDARD: Separate current and next PC registers
   // pc_current is STABLE for entire cycle (no race conditions)
   // pc_next is calculated combinationally
   reg [31:0] pc_current = 32'd0;
   wire [31:0] pc_next;

   // Combinational calculation of next PC
   // This settles immediately, no race with clock edge
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

       // DEBUG: Track jumps
       if (j_signal && pc_current >= 32'hC0 && pc_current <= 32'hE0) begin
           $display("[PC] @%t: JUMP from PC=0x%h to PC=0x%h", $time, pc_current, jump);
       end

       // DEBUG: Track PC progression in our range of interest
       if (!rst && !j_signal && !stall && pc_current >= 32'hC0 && pc_current <= 32'hE0) begin
           $display("[PC] @%t: PC advancing from 0x%h to 0x%h (stall=%b j_signal=%b)",
                    $time, pc_current, pc_current + 32'h4, stall, j_signal);
       end
   end

   // Output is the STABLE register (not the one being updated!)
   // This eliminates race conditions with downstream logic
   assign out = pc_current;
endmodule
