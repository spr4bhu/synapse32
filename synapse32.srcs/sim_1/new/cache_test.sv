`timescale 1ns/1ps

module tb_cache_cpu_integration();

    // Clock and reset
    reg clk;
    reg rst;
    
    // Interrupts
    reg software_interrupt;
    reg external_interrupt;
    
    // Debug outputs
    wire [31:0] pc_debug;
    wire [31:0] instr_debug;
    wire uart_tx;
    
    // DUT instantiation
    top dut (
        .clk(clk),
        .rst(rst),
        .software_interrupt(software_interrupt),
        .external_interrupt(external_interrupt),
        .uart_tx(uart_tx),
        .pc_debug(pc_debug),
        .instr_debug(instr_debug)
    );
    
    // Clock generation - 100MHz (10ns period)
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end
    
    // Monitoring variables
    integer cycle_count;
    integer cache_stalls;
    integer load_use_stalls;
    integer cache_misses;
    
    // Test status
    reg [255:0] current_test;
    
    // Task for reset
    task automatic reset_system();
        begin
            rst = 1;
            software_interrupt = 0;
            external_interrupt = 0;
            #100;
            rst = 0;
            #20;
            $display("[%0t] System reset complete", $time);
        end
    endtask
    
    // Task to wait for cycles
    task automatic wait_cycles(input integer n);
        begin
            repeat(n) @(posedge clk);
        end
    endtask
    
    // Task to read register value
    task automatic read_register(input integer reg_num, output logic [31:0] value);
        begin
            if (reg_num == 0) begin
                value = 32'h0;
            end else begin
                value = dut.cpu_inst.rf_inst0.register_file[reg_num];
            end
        end
    endtask
    
    // Task to read memory value
    task automatic read_memory(input [31:0] addr, output logic [31:0] value);
        begin
            logic [31:0] offset;
            offset = addr - 32'h10000000; // DATA_MEM_BASE
            if (offset < 32'h100000) begin // Within 1MB
                value = {dut.data_mem_inst.data_ram[offset+3],
                        dut.data_mem_inst.data_ram[offset+2],
                        dut.data_mem_inst.data_ram[offset+1],
                        dut.data_mem_inst.data_ram[offset]};
            end else begin
                value = 32'h0;
            end
        end
    endtask
    
    // Continuous monitoring
    always @(posedge clk) begin
        if (!rst) begin
            cycle_count = cycle_count + 1;
            
            // Monitor cache stalls
            if (dut.cache_stall) begin
                cache_stalls = cache_stalls + 1;
            end
            
            // Monitor cache misses
            if (dut.icache_inst.cache_miss) begin
                cache_misses = cache_misses + 1;
                $display("[%0t] CACHE MISS at PC=0x%08x", $time, pc_debug);
            end
            
            // Monitor load-use hazards
            if (dut.cpu_inst.stall_pipeline) begin
                load_use_stalls = load_use_stalls + 1;
                $display("[%0t] LOAD-USE STALL at PC=0x%08x", $time, pc_debug);
            end
        end
    end
    
    // Main test sequence
    initial begin
        // Initialize
        cycle_count = 0;
        cache_stalls = 0;
        load_use_stalls = 0;
        cache_misses = 0;
        
        $display("========================================");
        $display("CACHE-CPU INTEGRATION TEST SUITE");
        $display("========================================");
        
        // Setup waveform dumping
        $dumpfile("cache_integration.vcd");
        $dumpvars(0, tb_cache_cpu_integration);
        
        //=====================================================
        // TEST 1: COMPREHENSIVE LOAD-USE HAZARD TEST
        //=====================================================
        current_test = "TEST 1: Comprehensive Load-Use";
        $display("\n[%0t] === %s ===", $time, current_test);
        
        reset_system();
        
        // Run for enough cycles to complete test
        wait_cycles(200);
        
        // Verify results
        begin
            logic [31:0] x5, x6, x7, x8, x9, x10, x11, x12, x13, x14;
            integer errors;
            errors = 0;
            
            read_register(5, x5);
            read_register(6, x6);
            read_register(7, x7);
            read_register(8, x8);
            read_register(9, x9);
            read_register(10, x10);
            read_register(11, x11);
            read_register(12, x12);
            read_register(13, x13);
            read_register(14, x14);
            
            $display("\nTest 1 Results:");
            $display("  x5  = %0d (expected 1) %s", x5, (x5 == 1) ? "PASS" : "FAIL");
            $display("  x6  = %0d (expected 6) %s", x6, (x6 == 6) ? "PASS" : "FAIL");
            $display("  x7  = %0d (expected 5) %s", x7, (x7 == 5) ? "PASS" : "FAIL");
            $display("  x8  = %0d (expected 3) %s", x8, (x8 == 3) ? "PASS" : "FAIL");
            $display("  x9  = %0d (expected 1) %s", x9, (x9 == 1) ? "PASS" : "FAIL");
            $display("  x10 = %0d (expected 10) %s", x10, (x10 == 10) ? "PASS" : "FAIL");
            $display("  x11 = %0d (expected 10) %s", x11, (x11 == 10) ? "PASS" : "FAIL");
            $display("  x12 = %0d (expected 2) %s", x12, (x12 == 2) ? "PASS" : "FAIL");
            $display("  x13 = %0d (expected 2) %s", x13, (x13 == 2) ? "PASS" : "FAIL");
            $display("  x14 = %0d (expected 3) %s", x14, (x14 == 3) ? "PASS" : "FAIL");
            
            if (x5 != 1) errors++;
            if (x6 != 6) errors++;
            if (x7 != 5) errors++;
            if (x8 != 3) errors++;
            if (x9 != 1) errors++;
            if (x10 != 10) errors++;
            if (x11 != 10) errors++;
            if (x12 != 2) errors++;
            if (x13 != 2) errors++;
            if (x14 != 3) errors++;
            
            $display("\nTest 1 Summary: %0d/10 checks passed", 10 - errors);
            if (errors == 0) $display("TEST 1: PASS");
            else $display("TEST 1: FAIL");
        end
        
        $display("\nStatistics after Test 1:");
        $display("  Total Cycles:     %0d", cycle_count);
        $display("  Cache Stalls:     %0d", cache_stalls);
        $display("  Load-Use Stalls:  %0d", load_use_stalls);
        $display("  Cache Misses:     %0d", cache_misses);
        
        //=====================================================
        // TEST 2: COMBINED CACHE + LOAD-USE STALL TEST
        //=====================================================
        current_test = "TEST 2: Combined Stalls";
        $display("\n[%0t] === %s ===", $time, current_test);
        
        // Reset counters
        cycle_count = 0;
        cache_stalls = 0;
        load_use_stalls = 0;
        cache_misses = 0;
        
        reset_system();
        wait_cycles(400);
        
        // Verify results
        begin
            logic [31:0] x6_t2, x8_t2, x10_t2, x13_t2, x14_t2;
            integer errors_t2;
            errors_t2 = 0;
            
            read_register(6, x6_t2);
            read_register(8, x8_t2);
            read_register(10, x10_t2);
            read_register(13, x13_t2);
            read_register(14, x14_t2);
            
            $display("\nTest 2 Results:");
            $display("  x6  = %0d (expected 6) %s", x6_t2, (x6_t2 == 6) ? "PASS" : "FAIL");
            $display("  x8  = %0d (expected 142) %s", x8_t2, (x8_t2 == 142) ? "PASS" : "FAIL");
            $display("  x10 = %0d (expected 143) %s", x10_t2, (x10_t2 == 143) ? "PASS" : "FAIL");
            $display("  x13 = %0d (expected 701) %s", x13_t2, (x13_t2 == 701) ? "PASS" : "FAIL");
            $display("  x14 = %0d (expected 511) %s", x14_t2, (x14_t2 == 511) ? "PASS" : "FAIL");
            
            if (x6_t2 != 6) errors_t2++;
            if (x8_t2 != 142) errors_t2++;
            if (x10_t2 != 143) errors_t2++;
            if (x13_t2 != 701) errors_t2++;
            if (x14_t2 != 511) errors_t2++;
            
            $display("\nTest 2 Summary: %0d/5 checks passed", 5 - errors_t2);
            if (errors_t2 == 0) $display("TEST 2: PASS");
            else $display("TEST 2: FAIL");
        end
        
        $display("\nStatistics after Test 2:");
        $display("  Total Cycles:     %0d", cycle_count);
        $display("  Cache Stalls:     %0d", cache_stalls);
        $display("  Load-Use Stalls:  %0d", load_use_stalls);
        $display("  Cache Misses:     %0d", cache_misses);
        
        //=====================================================
        // TEST 3: MEMORY VERIFICATION
        //=====================================================
        current_test = "TEST 3: Memory Verification";
        $display("\n[%0t] === %s ===", $time, current_test);
        
        begin
            logic [31:0] mem0, mem4, mem8, mem12;
            
            read_memory(32'h10000000, mem0);
            read_memory(32'h10000004, mem4);
            read_memory(32'h10000008, mem8);
            read_memory(32'h1000000C, mem12);
            
            $display("\nMemory Contents:");
            $display("  mem[0]  = %0d (expected 1)", mem0);
            $display("  mem[4]  = %0d (expected 2)", mem4);
            $display("  mem[8]  = %0d (expected 3)", mem8);
            $display("  mem[12] = %0d", mem12);
            
            if (mem0 == 1 && mem4 == 2 && mem8 == 3) begin
                $display("TEST 3: PASS");
            end else begin
                $display("TEST 3: FAIL");
            end
        end
        
        //=====================================================
        // FINAL SUMMARY
        //=====================================================
        $display("\n========================================");
        $display("TEST SUITE COMPLETE");
        $display("========================================");
        $display("Check waveform file: cache_integration.vcd");
        $display("Use: gtkwave cache_integration.vcd");
        $display("Or import into Vivado for analysis");
        $display("========================================\n");
        
        #1000;
        $finish;
    end
    
    // Timeout watchdog
    initial begin
        #100000; // 100us timeout
        $display("\n[ERROR] Simulation timeout!");
        $finish;
    end
    
endmodule