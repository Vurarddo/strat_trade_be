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
