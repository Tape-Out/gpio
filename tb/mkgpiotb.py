"""gpio 的行为测试台：输出、方向、输入读回、边沿中断、写一清零。

认矩阵：针数与三个开关都从这一点的旋钮来。此前这份测试台固定八针、固定开
中断，而默认配置是三十二针——跑的根本不是被测的那个配置。

关掉的开关也要验：`bidir` 关了方向寄存器读回零、引脚方向恒为输出；
`irq` 关了使能与状态都读回零、中断线始终不抬。**门控写漏了的表现就是
「关掉了硬件还在」，只有这几条看得出来。**
"""
import json
import pathlib
import sys

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
out.mkdir(parents=True, exist_ok=True)
cfg = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
label = cfg.get("label", "")
k = cfg.get("knobs", {})
n = int(k.get("numPins", 32))
irq = bool(k.get("irq", True))
bidir = bool(k.get("bidir", True))
debounce = bool(k.get("debounce", False))

mask = (1 << n) - 1
outPat = 0xA5A5A5A5 & mask
dirPat = ((1 << max(n // 2, 1)) - 1) & mask
hot = n - 1                      # 开中断的那一针
cold = n - 2 if n >= 2 else None  # 也会动、但没开使能的那一针
ienPat = 1 << hot
inPat = 0xC0C0C0C0 & mask & ~(1 << hot) & (~(1 << cold) if cold is not None else mask)
edgePat = inPat | (1 << hot) | ((1 << cold) if cold is not None else 0)
dirWant = dirPat if bidir else mask
# 寄存器数据一律 32 位字面量，引脚比较则要正好 n 位——n 位的量写成八位十六
# 进制会被 bsc 判成宽度不符
hexn = max(1, (n + 3) // 4)


def hx(v):
    return f"{v:08X}"


def hn(v):
    return f"{v:0{hexn}X}"


# 中断关掉时的期望整个反过来
if irq:
    irq_setup = f"      1: wr(rIEN, 32'h{hx(ienPat)});"
    stray = ""
    if cold is not None:
        stray = f"""      if ((x.rdata & 32'h{hx(1 << cold)}) != 0) begin
        $display("FAIL a pin without enable latched too: %08h", x.rdata);
        wrong = True;
      end
"""
    irq_phase = f"""  // 第 {hot} 针给一个上升沿：使能开着，状态位该置起来
  rule edge_ (ph == Edge);
    pin <= {n}'h{hn(edgePat)};
    ph  <= CheckIrq;
  endrule

  rule checkIrq (ph == CheckIrq);
    let x <- g.regs.access(RegReq {{ addr: rIST, write: False,
                                    wdata: 0, wstrb: 4'hF }});
    Bool wrong = False;
    if ((x.rdata & 32'h{hx(ienPat)}) != 0) begin
{stray}      if (wrong) bad <= True;
      ph <= Clear;
    end
  endrule

  rule clear (ph == Clear);
    wr(rIST, 32'h{hx(ienPat)});            // 写一清零
    ph <= CheckClear;
  endrule

  rule checkClear (ph == CheckClear);
    let x <- g.regs.access(RegReq {{ addr: rIST, write: False,
                                    wdata: 0, wstrb: 4'hF }});
    Bool wrong = False;
    if ((x.rdata & 32'h{hx(ienPat)}) != 0) begin
      $display("FAIL status not cleared by write one: %08h", x.rdata);
      wrong = True;
    end
    if (wrong) bad <= True;
    ph <= Done;
  endrule
"""
    fin = """  rule fin (ph == Done);
    if (!sawIrq) begin
      $display("FAIL irq never went high");
      bad <= True;
    end
    if (bad || !sawIrq) $display("FAILED");
    else $display("PASS gpio: output, direction, input, masked edge, write one clear");
    $finish((bad || !sawIrq) ? 1 : 0);
  endrule
"""
else:
    irq_setup = f"      1: wr(rIEN, 32'h{hx(mask)});   // 中断关着，写了也该读回零"
    irq_phase = f"""  // 中断关着：动引脚不该有任何反应
  rule edge_ (ph == Edge);
    pin <= {n}'h{hn(edgePat)};
    ph  <= CheckIrq;
  endrule

  rule checkIrq (ph == CheckIrq);
    let x <- g.regs.access(RegReq {{ addr: rIEN, write: False,
                                    wdata: 0, wstrb: 4'hF }});
    if (x.rdata != 0) begin
      $display("FAIL irq is off but the enable register kept a value: %08h",
               x.rdata);
      bad <= True;
    end
    ph <= Clear;
  endrule

  rule clear (ph == Clear);
    ph <= CheckClear;
  endrule

  rule checkClear (ph == CheckClear);
    let x <- g.regs.access(RegReq {{ addr: rIST, write: False,
                                    wdata: 0, wstrb: 4'hF }});
    if (x.rdata != 0) begin
      $display("FAIL irq is off but the status register is not zero: %08h",
               x.rdata);
      bad <= True;
    end
    ph <= Done;
  endrule
"""
    fin = """  rule fin (ph == Done);
    if (sawIrq) begin
      $display("FAIL irq is off but the interrupt line went high");
      bad <= True;
    end
    if (bad) $display("FAILED");
    else $display("PASS gpio: output, direction, input, and the gates really gate");
    $finish(bad ? 1 : 0);
  endrule
"""

txt = f'''package Gpio{label}Tb;

import RegIf::*;
import GpioGen::*;

// 由 tb/mkgpiotb.py 生成，勿手改。
// 这一点：numPins={n} irq={irq} bidir={bidir} debounce={debounce}

Bit#(8) rOUT = 8'h00;
Bit#(8) rIN  = 8'h04;
Bit#(8) rDIR = 8'h08;
Bit#(8) rIEN = 8'h0C;
Bit#(8) rIST = 8'h10;

typedef enum {{ Setup, Drive, Settle, CheckOut, Feed, CheckIn, Edge,
               CheckIrq, Clear, CheckClear, Done }}
  Phase deriving (Bits, Eq);

(* synthesize *)
module mkGpio{label}Tb(Empty);
  GpioIfc#(8, 32, {n}) g <- mkGpio(GpioCfg {{ irq: {"True" if irq else "False"},
                                              bidir: {"True" if bidir else "False"},
                                              debounce: {"True" if debounce else "False"} }});

  Reg#(Phase)    ph  <- mkReg(Setup);
  Reg#(Bit#(8))  s   <- mkReg(0);
  Reg#(Bit#(32)) cyc <- mkReg(0);
  Reg#(Bool)     bad <- mkReg(False);
  Reg#(Bit#({n})) pin <- mkReg(0);
  Reg#(Bool)     sawIrq  <- mkReg(False);
  Reg#(Bit#({n})) outSeen <- mkReg(0);
  Reg#(Bit#({n})) dirSeen <- mkReg(0);

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
    let _ <- g.regs.access(RegReq {{ addr: a, write: True,
                                     wdata: v, wstrb: 4'hF }});
  endaction;

  rule setup (ph == Setup);
    case (s)
      0: wr(rDIR, 32'h{hx(dirPat)});
{irq_setup}
      default: ph <= Drive;
    endcase
    s <= s + 1;
  endrule

  rule drive (ph == Drive);
    wr(rOUT, 32'h{hx(outPat)});
    ph <= Settle;
  endrule

  // 写下去的值要下一拍才到寄存器，引脚上的采样再晚一拍
  rule settle (ph == Settle);
    ph <= CheckOut;
  endrule

  // 输出与方向要真的出现在引脚上。bidir 关掉时方向恒为输出。
  rule checkOut (ph == CheckOut);
    Bool wrong = False;
    if (outSeen != {n}'h{hn(outPat)}) begin
      $display("FAIL pin_out is %08h, want %08h", outSeen, {n}'h{hn(outPat)});
      wrong = True;
    end
    if (dirSeen != {n}'h{hn(dirWant)}) begin
      $display("FAIL pin_dir is %08h, want %08h", dirSeen, {n}'h{hn(dirWant)});
      wrong = True;
    end
    if (wrong) bad <= True;
    ph <= Feed;
  endrule

  rule feed (ph == Feed);
    pin <= {n}'h{hn(inPat)};
    ph  <= CheckIn;
  endrule

  rule checkIn (ph == CheckIn);
    let x <- g.regs.access(RegReq {{ addr: rIN, write: False,
                                     wdata: 0, wstrb: 4'hF }});
    if (x.rdata[{n - 1}:0] == {n}'h{hn(inPat)}) ph <= Edge;
  endrule

{irq_phase}
{fin}endmodule

endpackage
'''

(out / f"Gpio{label}Tb.bsv").write_text(txt, encoding="utf-8")
print(f"  gpio 行为测试台就位：numPins={n} irq={irq} bidir={bidir}")
