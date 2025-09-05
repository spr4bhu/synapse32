`default_nettype none
`include "memory_map.vh"

module top (
    input wire clk,
    input wire rst,
    
    // External interrupt inputs
    input wire software_interrupt,
    input wire external_interrupt,
    
    // UART output
    output wire uart_tx,
    
    // Optional debug outputs
    output wire [31:0] pc_debug,
    output wire [31:0] instr_debug,

    output wire cache_hit_debug,
    output wire cache_miss_debug,
    output wire cache_stall_debug
);

    // Wires to connect CPU and memories
    wire [31:0] cpu_pc_out;
    wire [31:0] instr_to_cpu;
    wire [31:0] cpu_mem_read_addr;
    wire [31:0] cpu_mem_write_addr;
    wire [31:0] cpu_mem_write_data;
    wire [31:0] mem_read_data;
    wire cpu_mem_write_en;
    wire cpu_mem_read_en;
    wire [31:0] data_mem_addr;
    wire [3:0] cpu_write_byte_enable;  // Write byte enables
    wire [2:0] cpu_load_type;          // Load type
    wire [31:0] instr_read_data;

    // NEW: I-Cache related wires
    wire cache_stall;               // Stall signal from I-cache to CPU
    wire cache_hit, cache_miss;     // Cache statistics
    
    // I-Cache to Burst Controller interface
    wire icache_mem_req;
    wire [31:0] icache_mem_addr;
    wire [3:0] icache_mem_burst_len;  // For 8-word blocks: 0-7
    wire [31:0] icache_mem_data;
    wire icache_mem_ready;
    wire icache_mem_valid;
    wire icache_mem_last;
    
    // Burst Controller to Instruction Memory interface
    wire [31:0] burst_to_instr_addr;
    wire [31:0] instr_to_burst_data;
     
    // Timer module wires
    wire [31:0] timer_read_data;
    wire timer_valid;
    wire timer_interrupt;
    
    // UART module wires
    wire [31:0] uart_read_data;
    wire uart_valid;
    wire uart_access;
    
    // Memory address decoding using memory map
    wire data_mem_access;
    wire timer_access;
    wire instr_mem_access;
    
    // Use memory map macros for clean address decoding
    assign data_mem_access = `IS_DATA_MEM(data_mem_addr) || 
                            (`IS_DATA_MEM(cpu_mem_read_addr) && cpu_mem_read_en) ||
                            (`IS_DATA_MEM(cpu_mem_write_addr) && cpu_mem_write_en);
    assign timer_access = `IS_TIMER_MEM(data_mem_addr);
    assign uart_access = `IS_UART_MEM(data_mem_addr);
    assign instr_mem_access = `IS_INSTR_MEM(data_mem_addr);
    
    // Select the appropriate address for memory access
    assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
    
    // Multiplex read data based on address
    assign mem_read_data = timer_access ? timer_read_data : 
                          data_mem_access ? data_mem_read_data :
                          uart_access ? uart_read_data :
                            instr_mem_access ? instr_read_data : 32'h00000000;
    
    // Debug outputs
    assign pc_debug = cpu_pc_out;
    assign instr_debug = instr_to_cpu;
    assign cache_hit_debug = cache_hit;
    assign cache_miss_debug = cache_miss;
    assign cache_stall_debug = cache_stall;
    
    // Data memory read data (separate wire for clarity)
    wire [31:0] data_mem_read_data;

        // Instantiate I-Cache
    icache_nway_multiword #(
        .ADDR_WIDTH(32),
        .DATA_WIDTH(32),
        .CACHE_SIZE(1024),      // 1KB cache
        .ASSOCIATIVITY(4),      // 4-way set associative
        .BLOCK_SIZE(8)          // 8 words per block
    ) icache_inst (
        .clk(clk),
        .rst(rst),
        
        // CPU Interface
        .cpu_req(1'b1),                 // CPU always requests instructions
        .cpu_addr(cpu_pc_out),          // PC from CPU
        .cpu_data(instr_to_cpu),        // Instruction to CPU
        .cpu_valid(),                   // Not used - instruction always available when not stalled
        .cpu_stall(cache_stall),        // Stall signal to CPU
        
        // Memory Interface (to Burst Controller)
        .mem_req(icache_mem_req),
        .mem_addr(icache_mem_addr),
        .mem_burst_len(icache_mem_burst_len),
        .mem_data(icache_mem_data),
        .mem_ready(icache_mem_ready),
        .mem_valid(icache_mem_valid),
        .mem_last(icache_mem_last),
        
        // Cache Statistics
        .cache_hit(cache_hit),
        .cache_miss(cache_miss),
        .cache_evict()                  // Not used
    );
    
    // Instantiate Burst Controller
    burst_controller #(
        .ADDR_WIDTH(32),
        .DATA_WIDTH(32),
        .BLOCK_SIZE(8)                  // Match cache block size
    ) burst_ctrl_inst (
        .clk(clk),
        .rst(rst),
        
        // Interface to I-Cache
        .cache_mem_req(icache_mem_req),
        .cache_mem_addr(icache_mem_addr),
        .cache_mem_burst_len(icache_mem_burst_len),
        .cache_mem_data(icache_mem_data),
        .cache_mem_ready(icache_mem_ready),
        .cache_mem_valid(icache_mem_valid),
        .cache_mem_last(icache_mem_last),
        
        // Interface to Instruction Memory
        .mem_addr(burst_to_instr_addr),
        .mem_data(instr_to_burst_data)
    );

    reg [31:0] mem_data_reg;

    always @(posedge clk) begin
        if (rst) begin
            mem_data_reg <= 32'b0;
        end else if (cpu_mem_read_en) begin
            mem_data_reg <= mem_read_data;  // Capture the data when reading
        end
    end

    // Instantiate the RISC-V CPU core
    riscv_cpu cpu_inst (
        .clk(clk),
        .rst(rst),
        .timer_interrupt(timer_interrupt),
        .software_interrupt(software_interrupt),
        .external_interrupt(external_interrupt),
        .module_instr_in(instr_to_cpu),
        .module_read_data_in(cpu_mem_read_en ? mem_read_data : mem_data_reg),
        .module_pc_out(cpu_pc_out),
        .module_wr_data_out(cpu_mem_write_data),
        .module_mem_wr_en(cpu_mem_write_en),
        .module_mem_rd_en(cpu_mem_read_en),
        .module_read_addr(cpu_mem_read_addr),
        .module_write_addr(cpu_mem_write_addr),
        .module_write_byte_enable(cpu_write_byte_enable),
        .module_load_type(cpu_load_type),
        .cache_stall(cache_stall)
    );

    // Instantiate instruction memory (dual-port for cache and direct access)
    instr_mem #(
        .DATA_WIDTH(32),
        .ADDR_WIDTH(32),
        .MEM_SIZE(131072)  // 512KB / 4 bytes = 128K words
    ) instr_mem_inst (
        // Port 1: For cache/burst controller access
        .instr_addr(burst_to_instr_addr),
        .instr(instr_to_burst_data),
        
        // Port 2: For direct data memory access (when accessing instruction memory as data)
        .instr_addr_p2(data_mem_addr),
        .load_type(cpu_load_type),
        .instr_p2(instr_read_data)
    );

    // Instantiate data memory  
    data_mem #(
        .DATA_WIDTH(32),
        .ADDR_WIDTH(32),
        .MEM_SIZE(1048576)  // 1MB in bytes
    ) data_mem_inst (
        .clk(clk),
        .wr_en(cpu_mem_write_en && data_mem_access),
        .rd_en(cpu_mem_read_en && data_mem_access),
        .write_byte_enable(cpu_write_byte_enable),
        .load_type(cpu_load_type),
        .addr(data_mem_addr - `DATA_MEM_BASE),
        .wr_data(cpu_mem_write_data),
        .rd_data_out(data_mem_read_data)
    );
    
    // Instantiate timer module
    timer timer_inst (
        .clk(clk),
        .rst(rst),
        .addr(data_mem_addr),
        .write_data(cpu_mem_write_data),
        .write_enable(cpu_mem_write_en && timer_access),
        .read_enable(cpu_mem_read_en && timer_access),
        .read_data(timer_read_data),
        .timer_valid(timer_valid),
        .timer_interrupt(timer_interrupt)
    );

    // Instantiate the UART module
    uart uart_inst (
        .clk(clk),
        .rst(rst),
        .addr(data_mem_addr),
        .write_data(cpu_mem_write_data),
        .write_enable(cpu_mem_write_en && uart_access),
        .read_enable(cpu_mem_read_en && uart_access),
        .read_data(uart_read_data),
        .uart_valid(uart_valid),
        .tx(uart_tx)
    );

`ifdef COCOTB_SIM
    // Add parameter to control FST file path
    reg [1023:0] dumpfile_path = "riscv_cpu.fst"; // Default path
    
    initial begin
        // Check for custom dump file name from plusargs
        if (!$value$plusargs("dumpfile=%s", dumpfile_path)) begin
            // Use default if not specified
            dumpfile_path = "riscv_cpu.fst";
        end
        
        // Set up wave dumping
        $dumpfile(dumpfile_path);
        $dumpvars(0, top);
        $display("FST dump file: %s", dumpfile_path);
    end
`endif

endmodule