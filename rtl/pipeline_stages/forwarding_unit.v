`default_nettype none
`include "instr_defines.vh"
module forwarding_unit (
    // Current instruction registers to check
    input wire [4:0] rs1_addr_ex,
    input wire [4:0] rs2_addr_ex,
    input wire rs1_valid_ex,
    input wire rs2_valid_ex,
    
    // Previous instructions (in MEM stage)
    input wire [4:0] rd_addr_mem,
    input wire rd_valid_mem,
    input wire [5:0] instr_id_mem,
    
    // Two-stages ago instructions (in WB stage)
    input wire [4:0] rd_addr_wb,
    input wire rd_valid_wb,
    input wire wr_en_wb,
    
    // Forwarding control signals
    output reg [1:0] forward_a, // For rs1
    output reg [1:0] forward_b  // For rs2
);

    // Forwarding control values
    localparam NO_FORWARDING = 2'b00;
    localparam FORWARD_FROM_MEM = 2'b01;
    localparam FORWARD_FROM_WB = 2'b10;
    
    always @(*) begin
        // Default: no forwarding
        forward_a = NO_FORWARDING;
        forward_b = NO_FORWARDING;
        
        // Forward to RS1 if needed
        if (rs1_valid_ex && (rs1_addr_ex != 5'b0)) begin
            // Check MEM stage forwarding first (now works for loads too!)
            if (rd_valid_mem && (rd_addr_mem != 5'b0) && (rd_addr_mem == rs1_addr_ex)) begin
                forward_a = FORWARD_FROM_MEM;
            end
            // Check WB stage forwarding (lower priority)
            else if (rd_valid_wb && wr_en_wb && (rd_addr_wb != 5'b0) && (rd_addr_wb == rs1_addr_ex)) begin
                forward_a = FORWARD_FROM_WB;
            end
        end
        
        // Forward to RS2 if needed
        if (rs2_valid_ex && (rs2_addr_ex != 5'b0)) begin
            // Check MEM stage forwarding first
            if (rd_valid_mem && (rd_addr_mem != 5'b0) && (rd_addr_mem == rs2_addr_ex)) begin
                forward_b = FORWARD_FROM_MEM;
            end
            // Check WB stage forwarding (lower priority)  
            else if (rd_valid_wb && wr_en_wb && (rd_addr_wb != 5'b0) && (rd_addr_wb == rs2_addr_ex)) begin
                forward_b = FORWARD_FROM_WB;
            end
        end
    end

    // Debug output
    always @(*) begin
        if (rs1_valid_ex || rs2_valid_ex) begin
            $display("FORWARD DEBUG: rs1_addr=%0d rs2_addr=%0d", rs1_addr_ex, rs2_addr_ex);
            $display("  MEM: rd_addr=%0d valid=%0d instr_id=%0d", rd_addr_mem, rd_valid_mem, instr_id_mem);
            $display("  WB:  rd_addr=%0d valid=%0d wr_en=%0d", rd_addr_wb, rd_valid_wb, wr_en_wb);
            $display("  Result: forward_a=%0d forward_b=%0d", forward_a, forward_b);
        end
    end

endmodule