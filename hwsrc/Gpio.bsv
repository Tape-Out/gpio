package Gpio;

import RegIf::*;

// 编译期配置即 feature 开关：静态 if 完全展开，未启用的功能不出现在生成的 Verilog 里。
typedef struct {
  Integer numPins;
  Bool    irq;     // 逐针边沿中断
  Bool    bidir;   // False 则只做输出，省掉方向寄存器
} GpioCfg;

GpioCfg gpioDefault = GpioCfg { numPins: 32, irq: True, bidir: True };

// 寄存器偏移。默认基地址由 regmap.yaml 声明，SoC 组装时可覆盖。
Bit#(8) rOUT = 8'h00;
Bit#(8) rIN  = 8'h04;
Bit#(8) rDIR = 8'h08;
Bit#(8) rIEN = 8'h0C;
Bit#(8) rIST = 8'h10;

interface GpioPins#(numeric type n);
  (* always_ready, always_enabled, prefix = "" *)
  method Action pin_in((* port = "gpio_in" *) Bit#(n) v);
  (* always_ready, result = "gpio_out" *) method Bit#(n) pin_out;
  (* always_ready, result = "gpio_dir" *) method Bit#(n) pin_dir;
endinterface

// 本 IP 不认识任何总线：对外只给中立 RegIf 与自身引脚。
// 接 APB4 / AXI4-Lite / Wishbone / TL-UL 由各总线仓的绑定器完成。
interface GpioIfc#(numeric type aw, numeric type dw, numeric type n);
  interface RegIf#(aw, dw) regs;
  interface GpioPins#(n)   pins;
  (* always_ready *) method Bool irq;
endinterface

module mkGpio#(GpioCfg cfg)(GpioIfc#(aw, dw, n))
    provisos (Mul#(TDiv#(dw, 8), 8, dw), Add#(a__, n, dw), Add#(b__, 8, aw));

  Reg#(Bit#(n)) dout <- mkReg(0);
  Reg#(Bit#(n)) dir  <- mkReg(0);
  Reg#(Bit#(n)) din  <- mkReg(0);
  Reg#(Bit#(n)) ien  <- mkReg(0);
  Reg#(Bit#(n)) prev <- mkReg(0);

  // ista 被硬件置位与软件写1清除两处写，须用 CReg 定序。
  // 规则同时读 ien/din（由总线方法写），故规则整体排在方法之前，
  // 端口顺序须与之一致：规则用端口 0，总线方法用端口 1。
  Reg#(Bit#(n)) ista[2] <- mkCReg(2, 0);

  rule edgeDetect (cfg.irq);
    prev <= din;
    ista[0] <= ista[0] | ((din ^ prev) & din & ien);
  endrule

  interface RegIf regs;
    method ActionValue#(RegRsp#(dw)) access(RegReq#(aw, dw) r);
      Bit#(8)  off = truncate(r.addr);
      Bit#(dw) wd  = r.wdata;
      Bit#(dw) rd  = 0;
      Bool     err = False;

      if (off == rOUT) begin
        if (r.write) dout <= truncate(applyStrb(zeroExtend(dout), wd, r.wstrb));
        else rd = zeroExtend(dout);
      end else if (off == rIN) begin
        rd = zeroExtend(din);
      end else if (off == rDIR && cfg.bidir) begin
        if (r.write) dir <= truncate(applyStrb(zeroExtend(dir), wd, r.wstrb));
        else rd = zeroExtend(dir);
      end else if (off == rIEN && cfg.irq) begin
        if (r.write) ien <= truncate(applyStrb(zeroExtend(ien), wd, r.wstrb));
        else rd = zeroExtend(ien);
      end else if (off == rIST && cfg.irq) begin
        if (r.write) ista[1] <= ista[1] & ~truncate(wd);   // 写 1 清除
        else rd = zeroExtend(ista[1]);
      end else begin
        err = True;
      end
      return RegRsp { rdata: rd, err: err };
    endmethod
  endinterface

  interface GpioPins pins;
    method Action pin_in(Bit#(n) v); din <= v; endmethod
    method Bit#(n) pin_out = dout;
    method Bit#(n) pin_dir = cfg.bidir ? dir : maxBound;
  endinterface
  method Bool irq = cfg.irq ? (ista[0] != 0) : False;
endmodule

endpackage
