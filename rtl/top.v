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
    output wire [31:0] instr_debug
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
    assign data_mem_access = `IS_DATA_MEM(data_mem_addr);
    assign timer_access = `IS_TIMER_MEM(data_mem_addr);
    assign uart_access = `IS_UART_MEM(data_mem_addr);
    assign instr_mem_access = `IS_INSTR_MEM(data_mem_addr);
    
    // Select the appropriate address for memory access
    assign data_mem_addr = cpu_mem_write_en ? cpu_mem_write_addr : cpu_mem_read_addr;
    
    // Multiplex read data based on address
    assign mem_read_data = timer_access ? timer_read_data : 
                          data_mem_access ? data_mem_read_data :
                          uart_access ? uart_read_data :
                          instr_mem_access ? data_mem_read_data : 32'h00000000;
    
    // Debug outputs
    assign pc_debug = cpu_pc_out;
    assign instr_debug = instr_to_cpu;
    
    // Data memory read data (separate wire for clarity)
    wire [31:0] data_mem_read_data;

    // Instantiate the RISC-V CPU core
    riscv_cpu cpu_inst (
        .clk(clk),
        .rst(rst),
        .timer_interrupt(timer_interrupt),
        .software_interrupt(software_interrupt),
        .external_interrupt(external_interrupt),
        .module_instr_in(instr_to_cpu),
        .module_read_data_in(mem_read_data),
        .module_pc_out(cpu_pc_out),
        .module_wr_data_out(cpu_mem_write_data),
        .module_mem_wr_en(cpu_mem_write_en),
        .module_mem_rd_en(cpu_mem_read_en),
        .module_read_addr(cpu_mem_read_addr),
        .module_write_addr(cpu_mem_write_addr),
        .module_write_byte_enable(cpu_write_byte_enable),
        .module_load_type(cpu_load_type)
    );

    // Address translation for unified memory
    wire [31:0] instr_addr;
    wire [31:0] data_addr;
    wire data_we;
    wire data_re;

    assign instr_addr = cpu_pc_out;
    assign data_addr = instr_mem_access ? (data_mem_addr - `INSTR_MEM_BASE) :
                                          (data_mem_addr - `DATA_MEM_BASE + `INSTR_MEM_SIZE);
    assign data_we = cpu_mem_write_en && data_mem_access;
    assign data_re = cpu_mem_read_en && (data_mem_access || instr_mem_access);

    // Instantiate unified memory
    unified_memory unified_mem_inst (
        .clk(clk),
        .addr_instr(instr_addr),
        .instr_out(instr_to_cpu),
        .addr_data(data_addr),
        .write_data(cpu_mem_write_data),
        .read_data(data_mem_read_data),
        .write_enable(data_we),
        .byte_enable(cpu_write_byte_enable),
        .read_enable(data_re),
        .load_type(cpu_load_type)
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