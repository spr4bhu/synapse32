`default_nettype none
// Memory adapter: turns the combinational backing store into a request/response port (GOAL S1).
//
// Protocol (the shape Ibex, CV32E40P and the OBI spec use, one outstanding transaction):
//   address phase:  the core holds req, addr, we, be and wdata until gnt;
//   response phase: the adapter answers later with rvalid and rdata, and a write commits once,
//                   in the cycle write_fire is high.
// The storage side is a plain array with combinational reads (a BRAM macro or, here,
// unified_mem plus the peripheral read mux): this module owns the protocol, the array owns
// the bits, which is how an SRAM macro and its controller are split in real designs.
//
// RESPONSE_LATENCY 0 answers in the same cycle as the request. That is not OBI-legal (a
// response may not share the cycle with its grant) and exists only while the backing store is
// combinational: it reproduces the behaviour this core has had so far. Any value >= 1
// registers the response, which is what a BRAM or a DDR bridge does.
module mem_adapter #(
    parameter RESPONSE_LATENCY = 0
) (
    input wire clk,
    input wire rst,

    // Core side
    input wire req,
    input wire [31:0] addr,
    input wire we,
    input wire [3:0] be,
    input wire [31:0] wdata,
    output wire gnt,
    output wire rvalid,
    output wire [31:0] rdata,

    // Storage side
    output wire [31:0] store_addr,
    output wire store_we,
    output wire [3:0] store_be,
    output wire [31:0] store_wdata,
    output wire write_fire,
    input wire [31:0] store_rdata
);

    generate
        if (RESPONSE_LATENCY == 0) begin : g_combinational
            assign gnt = req;
            assign rvalid = req;
            assign rdata = store_rdata;
            assign store_addr = addr;
            assign store_we = we;
            assign store_be = be;
            assign store_wdata = wdata;
            assign write_fire = req && we;
        end else begin : g_registered
            localparam COUNT_WIDTH = (RESPONSE_LATENCY < 3) ? 1 :
                                     (RESPONSE_LATENCY < 5) ? 2 :
                                     (RESPONSE_LATENCY < 9) ? 3 :
                                     (RESPONSE_LATENCY < 17) ? 4 : 8;
            localparam [31:0] LAST_FULL = RESPONSE_LATENCY - 1;
            localparam [COUNT_WIDTH-1:0] LAST = LAST_FULL[COUNT_WIDTH-1:0];

            reg busy;
            reg [COUNT_WIDTH-1:0] count;
            reg [31:0] addr_q;
            reg we_q;
            reg [3:0] be_q;
            reg [31:0] wdata_q;
            reg [31:0] rdata_q;
            reg rvalid_q;

            // One transaction at a time. A request is accepted while idle, and not in the cycle a
            // response is being presented: the requester needs that cycle to move to its next
            // address (this core has no prefetch buffer yet).
            assign gnt = req && !busy && !rvalid_q;
            // The last wait cycle: the array read is sampled and a write commits on this edge,
            // so the response appears registered in the next cycle, as a BRAM does.
            wire accept = gnt;
            wire sample_now = busy && (count == LAST);
            wire sample_on_accept = accept && (RESPONSE_LATENCY == 1);

            always @(posedge clk or posedge rst) begin
                if (rst) begin
                    busy <= 1'b0;
                    count <= {COUNT_WIDTH{1'b0}};
                    addr_q <= 32'b0;
                    we_q <= 1'b0;
                    be_q <= 4'b0;
                    wdata_q <= 32'b0;
                    rdata_q <= 32'b0;
                    rvalid_q <= 1'b0;
                end else begin
                    rvalid_q <= 1'b0;
                    if (accept) begin
                        addr_q <= addr;
                        we_q <= we;
                        be_q <= be;
                        wdata_q <= wdata;
                        if (sample_on_accept) begin
                            rdata_q <= store_rdata;
                            rvalid_q <= 1'b1;
                        end else begin
                            busy <= 1'b1;
                            count <= {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                        end
                    end else if (sample_now) begin
                        rdata_q <= store_rdata;
                        rvalid_q <= 1'b1;
                        busy <= 1'b0;
                        count <= {COUNT_WIDTH{1'b0}};
                    end else if (busy) begin
                        count <= count + {{(COUNT_WIDTH-1){1'b0}}, 1'b1};
                    end
                end
            end

            assign store_addr = busy ? addr_q : addr;
            assign store_we = busy ? we_q : we;
            assign store_be = busy ? be_q : be;
            assign store_wdata = busy ? wdata_q : wdata;
            assign write_fire = (sample_now && we_q) || (sample_on_accept && we);
            assign rvalid = rvalid_q;
            assign rdata = rdata_q;
        end
    endgenerate

endmodule
