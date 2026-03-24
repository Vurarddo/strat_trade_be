# Indicators Request Examples

This document shows request body examples for:

- `POST /api/v1/market/indicators`
- Supported indicator ids: `rsi`, `macd`, `psar`, `cci`, `stochastic`, `ema`, `sma`

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

## Stochastic Example

Use `component`:

- `k` (main stochastic line)
- `d` (signal line)

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
      "key": "stoch_k",
      "id": "stochastic",
      "params": {
        "period": 14,
        "smooth_window": 3,
        "component": "k"
      }
    }
  ],
  "include_candles": false
}
```

## EMA Example

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
      "key": "ema_20",
      "id": "ema",
      "params": {
        "period": 20
      }
    }
  ],
  "include_candles": false
}
```

## SMA Example

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
      "key": "sma_20",
      "id": "sma",
      "params": {
        "period": 20
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

### EMA cross (`ema_cross`)

Два рядки в `indicators` з `id: "ema"` і різними `params.period`; у умові — `indicator_key` (**fast**) та **`slow_indicator_key`** (**slow**). Потрібно **`fast.period < slow.period`**.

Сигнали на закритті (строгі нерівності):

- **BUY**: `fast[i-1] < slow[i-1]` і `fast[i] > slow[i]`
- **SELL**: `fast[i-1] > slow[i-1]` і `fast[i] < slow[i]`

Якщо будь-яке з чотирьох значень EMA на парі барів — `null`, бар пропускається. Winrate/expiry — як у PSAR/CCI.

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
    { "key": "ema_fast", "id": "ema", "params": { "period": 9 } },
    { "key": "ema_slow", "id": "ema", "params": { "period": 21 } }
  ],
  "strategy": {
    "type": "ema_cross",
    "signal_on_close": true,
    "conditions": [
      {
        "indicator_key": "ema_fast",
        "slow_indicator_key": "ema_slow",
        "operator": "ema_cross"
      }
    ]
  }
}
```

### MACD vs signal cross (`macd_signal_cross`, лише `composite`)

Два записи в `indicators` з `id: "macd"` і **однаковими** `fast_period` / `slow_period` / `signal_period`, але різним `component`: **`macd`** (лінія MACD) та **`signal`** (сигнальна лінія). У умові — `indicator_key` (лінія MACD) та **`slow_indicator_key`** (сигнальна лінія).

На закритті бару `i` (пропуск, якщо будь-яке з чотирьох значень на `i-1`/`i` — `null`):

- **BUY**: `macd[i-1] < signal[i-1]` і `macd[i] > signal[i]`, і на барі перетину **обидві** лінії строго нижче нуля: `macd[i] < 0` і `signal[i] < 0`.
- **SELL**: `macd[i-1] > signal[i-1]` і `macd[i] < signal[i]`, і на барі перетину **обидві** лінії строго вище нуля: `macd[i] > 0` і `signal[i] > 0`.

**Нуль / півплощина:** якщо після виявленого перетину умови «обидві < 0» або «обидві > 0» не виконуються (наприклад лінії «над/під нулем» по різні боки, або одна з ліній дорівнює `0`) — **сигналу немає** (неоднозначний випадок перетину з нулем).

### Composite AND (`composite` + `combinator: all`)

Сигнал лише там, де **усі** умови спрацювали на **одному й тому ж** індексі бару і з **однаковим** напрямком (`BUY` / `SELL`). Кожна умова має свій `operator` (`psar_reversal`, `cci_level_cross`, `ema_cross`, `rsi_threshold`, `stochastic_dual_threshold`, `ema_cross_or_trend`, `macd_signal_cross`). Для `ema_cross` / `ema_cross_or_trend` / `stochastic_dual_threshold` / `macd_signal_cross` додайте `slow_indicator_key` за потреби. Усі ключі (`indicator_key` та `slow_indicator_key` де є) мають бути **унікальні**. Поле `combinator` має бути `"all"`.

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

### Приклад: `composite` — MACD + PSAR

Типові періоди MACD: `12` / `26` / `9`. Друга умова — `psar_reversal` з ключем PSAR.

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
      "key": "psar_main",
      "id": "psar",
      "params": { "step": 0.02, "max_step": 0.2, "component": "sar" }
    }
  ],
  "strategy": {
    "type": "composite",
    "combinator": "all",
    "signal_on_close": true,
    "conditions": [
      {
        "indicator_key": "macd_line",
        "slow_indicator_key": "macd_signal",
        "operator": "macd_signal_cross"
      },
      { "indicator_key": "psar_main", "operator": "psar_reversal" }
    ]
  }
}
```

### Preset Example: RSI + Stochastic + EMA (M5)

The preset can be composed with `composite` + `combinator: "all"` using three conditions:

- `rsi_threshold` (default-like preset values: `lower=18`, `upper=82`)
- `stochastic_dual_threshold` on two stochastic instances (`K` + `D`, `lower=15`, `upper=85`)
- `ema_cross_or_trend` on `EMA(8)` and `EMA(21)` with optional `max_ema_separation`

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 300,
  "expiry_seconds": 600,
  "window": {
    "type": "range",
    "from": "2026-03-22T00:00:00Z",
    "to": "2026-03-23T00:00:00Z"
  },
  "indicators": [
    { "key": "rsi_7", "id": "rsi", "params": { "period": 7 } },
    { "key": "stoch_k_5_3", "id": "stochastic", "params": { "period": 5, "smooth_window": 3, "component": "k" } },
    { "key": "stoch_d_5_3", "id": "stochastic", "params": { "period": 5, "smooth_window": 3, "component": "d" } },
    { "key": "ema_8", "id": "ema", "params": { "period": 8 } },
    { "key": "ema_21", "id": "ema", "params": { "period": 21 } }
  ],
  "strategy": {
    "type": "composite",
    "combinator": "all",
    "signal_on_close": true,
    "conditions": [
      { "indicator_key": "rsi_7", "operator": "rsi_threshold", "params": { "lower": 18, "upper": 82 } },
      { "indicator_key": "stoch_k_5_3", "slow_indicator_key": "stoch_d_5_3", "operator": "stochastic_dual_threshold", "params": { "lower": 15, "upper": 85 } },
      { "indicator_key": "ema_8", "slow_indicator_key": "ema_21", "operator": "ema_cross_or_trend", "params": { "max_ema_separation": 0.003 } }
    ]
  }
}
```

MVP note: the optional "flat market 30-60 min" filter is not implemented in this iteration.
