# Indicators Request Examples

This document shows request body examples for:

- `POST /api/v1/market/indicators`
- Supported indicator ids: `rsi`, `macd`, `psar`, `cci`

## Common Request Shape

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 120
  },
  "indicators": [
    {
      "key": "indicator_key",
      "id": "rsi_or_macd",
      "params": {}
    }
  ],
  "include_candles": false
}
```

## RSI Example

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 120
  },
  "indicators": [
    {
      "key": "rsi_14",
      "id": "rsi",
      "params": {
        "period": 14
      }
    }
  ],
  "include_candles": false
}
```

## MACD Example (single component)

Use `component` as one of:

- `macd` (main MACD line)
- `signal` (signal line)
- `hist` (histogram)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 150
  },
  "indicators": [
    {
      "key": "macd_hist",
      "id": "macd",
      "params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "component": "hist"
      }
    }
  ],
  "include_candles": false
}
```

## MACD Example (all 3 series in one request)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 150
  },
  "indicators": [
    {
      "key": "macd_line",
      "id": "macd",
      "params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "component": "macd"
      }
    },
    {
      "key": "macd_signal",
      "id": "macd",
      "params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "component": "signal"
      }
    },
    {
      "key": "macd_hist",
      "id": "macd",
      "params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "component": "hist"
      }
    }
  ],
  "include_candles": false
}
```

## Mixed Example (RSI + MACD together)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 200
  },
  "indicators": [
    {
      "key": "rsi_14",
      "id": "rsi",
      "params": {
        "period": 14
      }
    },
    {
      "key": "macd_hist",
      "id": "macd",
      "params": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "component": "hist"
      }
    }
  ],
  "include_candles": false
}
```

## PSAR Example (single component)

Use `component`:

- `sar` (combined PSAR series)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 120
  },
  "indicators": [
    {
      "key": "psar_sar",
      "id": "psar",
      "params": {
        "step": 0.02,
        "max_step": 0.2,
        "component": "sar"
      }
    }
  ],
  "include_candles": false
}
```

## CCI Example

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "recent",
    "count": 120
  },
  "indicators": [
    {
      "key": "cci_20",
      "id": "cci",
      "params": {
        "period": 20,
        "constant": 0.015
      }
    }
  ],
  "include_candles": false
}
```

## Range Window Example

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "window": {
    "type": "range",
    "from": "2026-03-22T00:00:00Z",
    "to": "2026-03-22T02:00:00Z"
  },
  "indicators": [
    {
      "key": "rsi_14",
      "id": "rsi",
      "params": {
        "period": 14
      }
    }
  ],
  "include_candles": true
}
```

## Notes

- For `window.type = "recent"`, use either `end_at` or `cursor` (not both).
- `key` must be unique inside one request.
- Response returns `start_index` and trimmed `values` (without leading `null`).

---

## Strategy Test Winrate (MVP)

Endpoint: `POST /api/v1/strategy/test-winrate`

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 15,
  "expiry_seconds": 30,
  "window": {
    "type": "range",
    "from": "2026-03-22T00:00:00Z",
    "to": "2026-03-22T02:00:00Z"
  },
  "indicators": [
    {
      "key": "psar_main",
      "id": "psar",
      "params": {
        "step": 0.02,
        "max_step": 0.2,
        "component": "sar"
      }
    }
  ],
  "strategy": {
    "type": "psar_reversal",
    "signal_on_close": true,
    "conditions": [
      {
        "indicator_key": "psar_main",
        "operator": "psar_reversal"
      }
    ]
  }
}
```

Response fields include:

- `total_signals` (detected signals, including skipped)
- `wins`
- `losses` (equal close at expiry counts as loss in MVP)
- `skipped_signals` (not enough future candles for expiry)
- `winrate_percent` (`wins / (wins + losses) * 100`)

### CCI level cross (`cci_level_cross`)

- **BUY** on bar `i` when `cci[i-1] < 100` and `cci[i] >= 100` (bars with `null` CCI skipped).
- **SELL** on bar `i` when `cci[i-1] > -100` and `cci[i] <= -100`.
- Win/loss at expiry uses the same close rules as PSAR (tie at expiry = loss).

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "expiry_seconds": 120,
  "window": {
    "type": "range",
    "from": "2026-03-22T00:00:00Z",
    "to": "2026-03-22T04:00:00Z"
  },
  "indicators": [
    {
      "key": "cci_20",
      "id": "cci",
      "params": { "period": 20, "constant": 0.015 }
    }
  ],
  "strategy": {
    "type": "cci_level_cross",
    "signal_on_close": true,
    "conditions": [
      { "indicator_key": "cci_20", "operator": "cci_level_cross" }
    ]
  }
}
```

### Composite AND (`composite` + `combinator: all`)

Сигнал лише там, де **усі** умови спрацювали на **одному й тому ж** індексі бару і з **однаковим** напрямком (`BUY` / `SELL`). Кожна умова має свій `operator` (`psar_reversal` / `cci_level_cross`) і **різний** `indicator_key`. Поле `combinator` має бути `"all"`.

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 15,
  "expiry_seconds": 30,
  "window": {
    "type": "range",
    "from": "2026-03-22T00:00:00Z",
    "to": "2026-03-22T02:00:00Z"
  },
  "indicators": [
    {
      "key": "psar_main",
      "id": "psar",
      "params": { "step": 0.02, "max_step": 0.2, "component": "sar" }
    },
    {
      "key": "cci_20",
      "id": "cci",
      "params": { "period": 20, "constant": 0.015 }
    }
  ],
  "strategy": {
    "type": "composite",
    "combinator": "all",
    "signal_on_close": true,
    "conditions": [
      { "indicator_key": "psar_main", "operator": "psar_reversal" },
      { "indicator_key": "cci_20", "operator": "cci_level_cross" }
    ]
  }
}
```
