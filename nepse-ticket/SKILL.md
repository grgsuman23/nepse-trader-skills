---
name: nepse-ticket
description: Write a plain TMS buy ticket (symbol, quantity in lots of 10, limit price, stop, target, time stop, earliest sale date) for the user to type into TMS themselves, only after the risk gate passes. Use when the user is ready to place a NEPSE order.
---

# NEPSE order ticket

`python nepse-ticket/ticket.py --plan plan.json [--portfolio portfolio.json]`

- Nothing in this pack connects to TMS or places orders, and you must never say an order was placed.
- The script refuses to write a ticket when the gate blocks. `--i-accept-block` overrides that, but use it only if the user has read every block reason and explicitly asked for the ticket anyway.
- Remind the user that TMS rejects prices outside the day's ±15% band and outside the continuous-session band.
