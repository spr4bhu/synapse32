`default_nettype none

// unified_memory.v - Unified dual-port memory for instructions and data

module unified_memory #(
    parameter ADDR_WIDTH = 32,
    parameter DATA_WIDTH = 32,
    parameter MEM_SIZE = 2097152  // 2MB total (covers both instruction and data regions)
) (
    input wire clk,

    // Instruction port (read-only)
    input  wire [ADDR_WIDTH-1:0] addr_instr,
    output reg  [DATA_WIDTH-1:0] instr_out,

    // Data port (read/write)
    input  wire [ADDR_WIDTH-1:0] addr_data,
    input  wire [DATA_WIDTH-1:0] write_data,
    output reg  [DATA_WIDTH-1:0] read_data,
    input  wire                  write_enable,
    input  wire [3:0]            byte_enable,      // Byte enables for partial writes
    input  wire                  read_enable,
    input  wire [2:0]            load_type         // Load type for sign/zero extension
);

    // Byte-addressed memory array
    reg [7:0] ram [0:MEM_SIZE-1];
    reg [31:0] word_mem [0:MEM_SIZE/4-1];

    // Initialize memory with NOPs
    initial begin
        integer i;

        // Initialize all memory with NOPs
        for (i = 0; i < MEM_SIZE; i = i + 4) begin
            ram[i + 0] = 8'h13;  // NOP = 0x00000013
            ram[i + 1] = 8'h00;
            ram[i + 2] = 8'h00;
            ram[i + 3] = 8'h00;
        end

        // Load program from hex file if defined (simulation only)
        `ifdef INSTR_HEX_FILE
            $display("Loading unified memory from file: %s", `INSTR_HEX_FILE);

            // Read program as words
            for (i = 0; i < MEM_SIZE/4; i = i + 1) begin
                word_mem[i] = 32'h00000013; // NOP
            end
            $readmemh(`INSTR_HEX_FILE, word_mem);

            // Unpack words into byte array (little-endian)
            for (i = 0; i < MEM_SIZE/4; i = i + 1) begin
                ram[i*4 + 0] = word_mem[i][7:0];
                ram[i*4 + 1] = word_mem[i][15:8];
                ram[i*4 + 2] = word_mem[i][23:16];
                ram[i*4 + 3] = word_mem[i][31:24];
            end
        `endif
    end

    // Instruction port (word-aligned, read-only)
    // Combinational read for zero-latency instruction fetch
    wire [ADDR_WIDTH-1:0] aligned_instr_addr;
    assign aligned_instr_addr = {addr_instr[ADDR_WIDTH-1:2], 2'b00};

    always @(*) begin
        if (aligned_instr_addr < MEM_SIZE - 3) begin
            // Little-endian: LSB first
            instr_out = {ram[aligned_instr_addr + 3], ram[aligned_instr_addr + 2], ram[aligned_instr_addr + 1], ram[aligned_instr_addr + 0]};
        end else begin
            instr_out = 32'h00000013; // NOP for out-of-bounds
        end
    end

    // Data port (byte-aligned, read/write)
    // Combinational read logic
    wire [7:0]  byte_data;
    wire [15:0] halfword_data;
    wire [31:0] word_data;

    // Read data directly from memory (byte-addressed)
    assign byte_data = (addr_data < MEM_SIZE) ? ram[addr_data] : 8'h00;

    // Read halfword (little-endian)
    assign halfword_data = (addr_data < MEM_SIZE - 1) ?
        {ram[addr_data + 1], ram[addr_data + 0]} : 16'h0000;

    // Read word (little-endian)
    assign word_data = (addr_data < MEM_SIZE - 3) ?
        {ram[addr_data + 3], ram[addr_data + 2], ram[addr_data + 1], ram[addr_data + 0]} : 32'h00000000;

    // Format output based on load type
    always @(*) begin
        if (read_enable) begin
            case (load_type)
                3'b000:  read_data = {{24{byte_data[7]}}, byte_data};           // LB (sign-extend)
                3'b100:  read_data = {24'h0, byte_data};                        // LBU (zero-extend)
                3'b001:  read_data = {{16{halfword_data[15]}}, halfword_data};  // LH (sign-extend)
                3'b101:  read_data = {16'h0, halfword_data};                    // LHU (zero-extend)
                3'b010:  read_data = word_data;                                 // LW
                default: read_data = 32'h0;
            endcase
        end else begin
            read_data = 32'h0;
        end
    end

    // Synchronous write logic with byte enables
    always @(posedge clk) begin
        if (write_enable && (addr_data < MEM_SIZE)) begin
            if (byte_enable[0]) ram[addr_data + 0] <= write_data[7:0];
            if (byte_enable[1] && (addr_data < MEM_SIZE - 1)) ram[addr_data + 1] <= write_data[15:8];
            if (byte_enable[2] && (addr_data < MEM_SIZE - 2)) ram[addr_data + 2] <= write_data[23:16];
            if (byte_enable[3] && (addr_data < MEM_SIZE - 3)) ram[addr_data + 3] <= write_data[31:24];
        end
    end

endmodule
`default_nettype wire
