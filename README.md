# gpio

![maturity](https://img.shields.io/badge/maturity-simulated-yellow) ![license](https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0%20OR%20MulanPSL--2.0-blue)

Configurable general-purpose IO in Bluespec. Implements the bus-neutral `RegIf`
contract from `hwcore` and nothing else; attach it to APB4, AXI4-Lite, Wishbone
or TL-UL at integration time.

## Features

| Feature | Default | Effect | Cost |
| :--: | :--: | :--: | :--: |
| `irq` | on | per-pin rising-edge interrupt | +1049.7 um2 (+328 cells) on ICS55 |
| `bidir` | on | direction register; off means output only | measured per build |
| `numPins` | 32 | pin count, 1..64 | scales with width |

Costs come from synthesis in CI against the ICS55 standard cell library, so a
configuration choice always carries a visible price.

## Registers

| Offset | Name | Access |
| :--: | :--: | :--: |
| `0x00` | data out | RW |
| `0x04` | data in | RO |
| `0x08` | direction | RW, needs `bidir` |
| `0x0C` | interrupt enable | RW, needs `irq` |
| `0x10` | interrupt status | W1C, needs `irq` |

## Use

```bsv
GpioIfc#(32, 32, 32) g <- mkGpio(GpioCfg { numPins: 32, irq: True, bidir: True });
device('h1000_0000, 'h100, g.regs, tagged Valid g.pins.irq)
```

`archive/` holds the retired picorv32-era Verilog, kept for provenance.

## License

任选其一：

- [MIT](LICENSE-MIT)
- [Apache 2.0](LICENSE-APACHE)
- [木兰宽松许可证 第2版](LICENSE-MULAN)

`SPDX-License-Identifier: MIT OR Apache-2.0 OR MulanPSL-2.0`

除非另行说明，你提交的贡献按上述三者同时授权，不附加其他条件。
