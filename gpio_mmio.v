`timescale 1ns/1ps

`ifndef MAX_GPIO_NUM
`define MAX_GPIO_NUM 32
`endif

module gpio_mmio #(
    parameter integer GPIO_WIDTH    =   `MAX_GPIO_NUM,
    parameter integer BASE_ADDR     =   32'h8000_0000
)(
    input  wire                     clk,
    input  wire                     resetn,

    input  wire                     mem_valid,
    input  wire                     mem_instr,
    output reg                      mem_ready,
    input  wire [31:0]              mem_addr,
    /* verilator lint_off UNUSEDSIGNAL */
    input  wire [31:0]              mem_wdata,
    /* verilator lint_on UNUSEDSIGNAL */
    input  wire [3:0]               mem_wstrb,
    output reg  [31:0]              mem_rdata,

    input  wire [GPIO_WIDTH-1:0]    gpio_in,
    output reg  [GPIO_WIDTH-1:0]    gpio_out,
    output reg  [GPIO_WIDTH-1:0]    gpio_dir,   // 1 = out, 0 = in

    output reg                      irq,
    input  wire [GPIO_WIDTH-1:0]    eoi
);
    /* verilator lint_off UNUSEDSIGNAL */
    wire [31:0] wmask32 = { {8{mem_wstrb[3]}}, {8{mem_wstrb[2]}}, {8{mem_wstrb[1]}}, {8{mem_wstrb[0]}} };
    /* verilator lint_on UNUSEDSIGNAL */
    wire [GPIO_WIDTH-1:0] wmask_gpio = wmask32[GPIO_WIDTH-1:0];

    reg [GPIO_WIDTH-1:0] ie;                    // interrupt enable
    reg [GPIO_WIDTH-1:0] last_in;               // previous sampled inputs

    reg [GPIO_WIDTH-1:0] ip_edge;               // edge interrupt pending
    reg [GPIO_WIDTH-1:0] ip_level;              // level interrupt pending

    reg [GPIO_WIDTH-1:0] itr_rising;            // 1 = rising edge trigger enable
    reg [GPIO_WIDTH-1:0] itr_falling;           // 1 = falling edge trigger enable

    reg [GPIO_WIDTH-1:0] level_en;              // enable level triggers
    reg [GPIO_WIDTH-1:0] level_pol;             // Level trigger polarity: 1=high, 0=low

    localparam [31:0]
        GPIO_DATA_OUT  = BASE_ADDR + 32'h00,    // GPIO data output register
        GPIO_DATA_IN   = BASE_ADDR + 32'h04,    // GPIO data input register
        GPIO_DIR       = BASE_ADDR + 32'h08,    // GPIO direction control register
        GPIO_IE        = BASE_ADDR + 32'h0C,    // Interrupt enable register
        GPIO_IP_LEVEL  = BASE_ADDR + 32'h10,    // Level interrupt pending register (read-only)
        GPIO_IP_EDGE   = BASE_ADDR + 32'h14,    // Edge interrupt pending register (read/write-to-clear)
        GPIO_ITR_R     = BASE_ADDR + 32'h18,    // Rising edge trigger
        GPIO_ITR_F     = BASE_ADDR + 32'h1C,    // Falling edge trigger
        GPIO_LEVEL_P   = BASE_ADDR + 32'h20,    // Level polarity
        GPIO_LEVEL_E   = BASE_ADDR + 32'h24;    // Level enable

    wire [GPIO_WIDTH-1:0] active_irqs = (ip_level & ie) | (ip_edge & ie);

    integer i;

    always @(posedge clk) begin
        if (!resetn) begin
            last_in    <= 0;
            ip_level   <= 0;
            ip_edge    <= 0;
            irq        <= 0;
        end else begin
            for (i=0; i< GPIO_WIDTH; i = i + 1) begin
                if (gpio_dir[i] == 1'b0) begin: INPUT_GPIO
                    if (level_en[i]) begin: LEVEL
                        ip_edge[i] <= 1'b0;
                        ip_level[i] <= level_pol[i] ? gpio_in[i] : ~gpio_in[i];
                    end else begin: EDGE
                        ip_level[i] <= 1'b0;
                        if (itr_rising[i] & ~last_in[i] & gpio_in[i])
                            ip_edge[i] <= 1'b1;
                        else ;
                        if (itr_falling[i] & last_in[i] & ~gpio_in[i])
                            ip_edge[i] <= 1'b1;
                        else ;
                    end
                    if (eoi[i]) begin: CLEAR
                        ip_edge[i] <= 1'b0;
                    end
                end else begin: OUTPUT_GPIO
                    ip_level[i] <= 1'b0;
                    ip_edge[i] <= 1'b0;
                end
            end
            last_in <= gpio_in;
            irq <= |active_irqs;
        end
    end

    function [31:0] zext32;
        input [GPIO_WIDTH-1:0] in;
        begin
            zext32 = 32'b0;
            zext32[GPIO_WIDTH-1:0] = in;
        end
    endfunction

    always @* begin: MMIO_READ
        if (mem_valid && !mem_instr) begin
            case (mem_addr)
                GPIO_DATA_OUT: mem_rdata = zext32(gpio_out);
                GPIO_DATA_IN:  mem_rdata = zext32(gpio_in);
                GPIO_DIR:      mem_rdata = zext32(gpio_dir);
                GPIO_IE:       mem_rdata = zext32(ie);
                GPIO_IP_LEVEL: mem_rdata = zext32(ip_level);
                GPIO_IP_EDGE:  mem_rdata = zext32(ip_edge);
                GPIO_ITR_R:    mem_rdata = zext32(itr_rising);
                GPIO_ITR_F:    mem_rdata = zext32(itr_falling);
                GPIO_LEVEL_P:  mem_rdata = zext32(level_pol);
                GPIO_LEVEL_E:  mem_rdata = zext32(level_en);
                default:       mem_rdata = 0;
            endcase
        end else mem_rdata = 0;
    end

    always @(posedge clk) begin: MMIO_WRITE
        if (!resetn) begin
            gpio_out    <= 0;
            gpio_dir    <= 0;
            ie          <= 0;
            itr_rising  <= 0;
            itr_falling <= 0;
            level_en    <= 0;
            level_pol   <= 0;
            mem_ready   <= 0;
        end else begin
            if (mem_valid && !mem_instr) begin
                mem_ready <= 1;
                case (mem_addr)
                    GPIO_DATA_OUT: gpio_out     <= (gpio_out & ~wmask_gpio)        | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_DIR:      gpio_dir     <= (gpio_dir & ~wmask_gpio)        | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_IE:       ie           <= (ie & ~wmask_gpio)              | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_ITR_R:    itr_rising   <= (itr_rising & ~wmask_gpio)      | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_ITR_F:    itr_falling  <= (itr_falling & ~wmask_gpio)     | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_LEVEL_E:  level_en     <= (level_en & ~wmask_gpio)        | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_LEVEL_P:  level_pol    <= (level_pol & ~wmask_gpio)       | (mem_wdata[GPIO_WIDTH-1:0] & wmask_gpio);
                    GPIO_IP_EDGE:  ip_edge      <= ip_edge & ~(mem_wdata[GPIO_WIDTH-1:0]&wmask_gpio);
                    default: ;
                endcase
            end else mem_ready <= 0;
        end
    end

endmodule
