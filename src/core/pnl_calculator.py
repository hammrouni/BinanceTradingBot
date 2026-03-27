from src.models.trade import TradeRecord


def calculate_pnl(trades: list[TradeRecord]) -> list[TradeRecord]:
    """
    Pairs buys and sells chronologically (FIFO). Sets pnl_usd on matched sell records.
    Returns the same list order as input, with pnl_usd populated where applicable.
    """
    chronological = sorted(trades, key=lambda t: t.executed_at)
    open_buys: list[TradeRecord] = []
    pnl_map: dict[str, float] = {}

    for trade in chronological:
        if trade.direction == "buy":
            open_buys.append(trade)
        elif trade.direction == "sell" and open_buys:
            matched_buy = open_buys.pop(0)
            pnl = (trade.entry_price - matched_buy.entry_price) * trade.quantity
            pnl_map[trade.id] = round(pnl, 2)

    return [
        trade.model_copy(update={"pnl_usd": pnl_map[trade.id]})
        if trade.id in pnl_map
        else trade
        for trade in trades
    ]
