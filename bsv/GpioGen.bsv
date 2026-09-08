package GpioGen;

import Apb4::*;
import GpioRegs::*;

// 与 E19 的手写 Gpio2.bsv 同构，差别只在寄存器组来自生成器。
typedef struct {
  Bool irq;
  Bool bidir;
  Bool debounce;
} GpioCfg;

interface GpioPins#(numeric type n);
  (* always_ready, always_enabled, prefix = "" *)
  method Action pin_in((* port = "gpio_in" *) Bit#(n) v);
  (* always_ready, result = "gpio_out" *) method Bit#(n) pin_out;
  (* always_ready, result = "gpio_dir" *) method Bit#(n) pin_dir;
  (* always_ready, result = "irq"      *) method Bool    irq;
endinterface

interface GpioIfc#(numeric type aw, numeric type dw, numeric type n);
  interface Apb4SlavePins#(aw, dw) apb;
  interface GpioPins#(n)           pins;
endinterface

module mkGpio#(GpioCfg cfg)(GpioIfc#(aw, dw, n))
    provisos (Mul#(TDiv#(dw, 8), 8, dw), Add#(a__, n, dw), Add#(b__, 8, aw));

  GpioRegsIfc#(aw, dw, n) r <- mkGpioRegs(GpioRegsCfg { bidir: cfg.bidir, irq: cfg.irq });
  Reg#(Bit#(n))  prev <- mkReg(0);
  Wire#(Bit#(n)) raw  <- mkBypassWire;

  if (cfg.debounce) begin
    Reg#(Bit#(n)) s0 <- mkReg(0);
    Reg#(Bit#(n)) s1 <- mkReg(0);
    Reg#(Bit#(n)) s2 <- mkReg(0);
    rule deb;
      s0 <= raw; s1 <= s0; s2 <= s1;
      if (s0 == s1 && s1 == s2) r.din_in(s2);
    endrule
  end else begin
    rule pass;
      r.din_in(raw);
    endrule
  end

  rule edgeDetect (cfg.irq);
    prev <= r.din;
    r.ista_set((r.din ^ prev) & r.din & r.ien);
  endrule

  Apb4SlavePins#(aw, dw) sl <- mkApb4Slave(r.regs);

  interface apb = sl;
  interface GpioPins pins;
    method Action pin_in(Bit#(n) v); raw <= v; endmethod
    method Bit#(n) pin_out = r.dout;
    method Bit#(n) pin_dir = cfg.bidir ? r.dir : maxBound;
    method Bool    irq     = cfg.irq ? (r.ista != 0) : False;
  endinterface
endmodule

endpackage
