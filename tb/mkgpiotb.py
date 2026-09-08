"""gpio 的行为测试台：输出、方向、输入读回、边沿中断、写一清零。"""
import pathlib
import sys

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)

(out / "GpioTb.bsv").write_text('''package GpioTb;

import RegIf::*;
import GpioGen::*;

// 由 tb/mkgpiotb.py 生成，勿手改。

Bit#(8) rOUT = 8'h00;
Bit#(8) rIN  = 8'h04;
Bit#(8) rDIR = 8'h08;
Bit#(8) rIEN = 8'h0C;
Bit#(8) rIST = 8'h10;

typedef enum { Setup, Drive, Settle, CheckOut, Feed, CheckIn, Edge,
               CheckIrq, Clear, CheckClear, Done }
  Phase deriving (Bits, Eq);

(* synthesize *)
module mkGpioTb(Empty);
  GpioIfc#(8, 32, 8) g <- mkGpio(GpioCfg { irq: True, bidir: True,
                                           debounce: False });

  Reg#(Phase)    ph  <- mkReg(Setup);
  Reg#(Bit#(8))  s   <- mkReg(0);
  Reg#(Bit#(32)) cyc <- mkReg(0);
  Reg#(Bool)     bad <- mkReg(False);
  Reg#(Bit#(8))  pin <- mkReg(0);
  Reg#(Bool)     sawIrq <- mkReg(False);
  Reg#(Bit#(8))  outSeen <- mkReg(0);
  Reg#(Bit#(8))  dirSeen <- mkReg(0);

  rule pins;
    g.pins.pin_in(pin);
    outSeen <= g.pins.pin_out;
    dirSeen <= g.pins.pin_dir;
    if (g.irq) sawIrq <= True;
  endrule

  rule tick;
    cyc <= cyc + 1;
    if (cyc > 20000) begin
      $display("TIMEOUT in phase %0d", pack(ph));
      $finish(1);
    end
  endrule

  function Action wr(Bit#(8) a, Bit#(32) v) = action
    let _ <- g.regs.access(RegReq { addr: a, write: True,
                                    wdata: v, wstrb: 4'hF });
  endaction;

  rule setup (ph == Setup);
    case (s)
      0: wr(rDIR, 32'h0F);       // 低四位输出
      1: wr(rIEN, 32'h20);       // 只让第 5 针产生中断
      default: ph <= Drive;
    endcase
    s <= s + 1;
  endrule

  rule drive (ph == Drive);
    wr(rOUT, 32'h0A);
    ph <= Settle;
  endrule

  // 写下去的值要下一拍才到寄存器，引脚上的采样再晚一拍
  rule settle (ph == Settle);
    ph <= CheckOut;
  endrule

  // 输出与方向要真的出现在引脚上
  rule checkOut (ph == CheckOut);
    Bool wrong = False;
    if (outSeen != 8'h0A) begin
      $display("FAIL pin_out is %02h, want 0a", outSeen);
      wrong = True;
    end
    if (dirSeen != 8'h0F) begin
      $display("FAIL pin_dir is %02h, want 0f", dirSeen);
      wrong = True;
    end
    if (wrong) bad <= True;
    ph <= Feed;
  endrule

  rule feed (ph == Feed);
    pin <= 8'hC0;                // 高两位拉高
    ph  <= CheckIn;
  endrule

  rule checkIn (ph == CheckIn);
    let x <- g.regs.access(RegReq { addr: rIN, write: False,
                                    wdata: 0, wstrb: 4'hF });
    if (x.rdata[7:0] == 8'hC0) ph <= Edge;
  endrule

  // 第 5 针给一个上升沿：使能开着，中断该置位
  rule edge_ (ph == Edge);
    pin <= 8'hE0;
    ph  <= CheckIrq;
  endrule

  rule checkIrq (ph == CheckIrq);
    let x <- g.regs.access(RegReq { addr: rIST, write: False,
                                    wdata: 0, wstrb: 4'hF });
    Bool wrong = False;
    if (x.rdata[5] == 1) begin
      // 第 6、7 针也动过，但它们的使能是关的，不该置位
      if (x.rdata[7:6] != 0) begin
        $display("FAIL pins without enable also latched: %02h", x.rdata[7:0]);
        wrong = True;
      end
      if (wrong) bad <= True;
      ph <= Clear;
    end
  endrule

  rule clear (ph == Clear);
    wr(rIST, 32'h20);            // 写一清零
    ph <= CheckClear;
  endrule

  rule checkClear (ph == CheckClear);
    let x <- g.regs.access(RegReq { addr: rIST, write: False,
                                    wdata: 0, wstrb: 4'hF });
    Bool wrong = False;
    if (x.rdata[5] != 0) begin
      $display("FAIL status not cleared by write one: %08h", x.rdata);
      wrong = True;
    end
    if (wrong) bad <= True;
    ph <= Done;
  endrule

  rule fin (ph == Done);
    if (!sawIrq) begin
      $display("FAIL irq never went high");
      bad <= True;
    end
    if (bad || !sawIrq) $display("FAILED");
    else $display("PASS gpio: output, direction, input, masked edge, write one clear");
    $finish((bad || !sawIrq) ? 1 : 0);
  endrule
endmodule

endpackage
''', encoding="utf-8")
print("  gpio 行为测试台就位")
