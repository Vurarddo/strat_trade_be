# Market indicators API (`POST /api/v1/market/indicators`)

This endpoint loads **one page** of recent candles (same rules as `GET /api/v1/market/candles`) and computes **several** registered indicators on that window in a single round trip.

## Indicator metadata

Before calling `POST /market/indicators`, read the static schema for each indicator:

- **RSI (Wilder):** `GET /api/v1/indicators/rsi`
  - Stable id: `rsi_wilder`
  - Typical params: `{ "length": 14 }` (integer ≥ 1; default internally is 14 if omitted)
  - Minimum `count`: `length + 1` (warmup)

- **Bollinger Bands:** `GET /api/v1/indicators/bollinger-bands`
  - Stable id: `bollinger_bands`
  - Params: `{ "length": 20, "mult": 2.0 }` (`length` ≥ 1 default 20; `mult` > 0 default 2.0)
  - Response output lines: `middle`, `upper`, `lower` (each keyed by `open_time` like other indicators)
  - Minimum `count`: `length` (first full window ends at bar index `length - 1`)

## Request

`POST /api/v1/market/indicators`  
`Content-Type: application/json`

### Top-level fields

| Field               | Type              | Required | Description                                                                                                                     |
| ------------------- | ----------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `asset`             | string            | yes      | Broker symbol, e.g. `EURUSD_otc`                                                                                                |
| `timeframe_seconds` | integer           | yes      | Bar size in seconds (PO native: `1`, `5`, `15`, `30`, `60`, `300`)                                                              |
| `count`             | integer           | yes      | How many bars to fetch (1–5000, capped by server env). Must be ≥ **largest warmup** among runs (`rsi_wilder`: `length + 1`; `bollinger_bands`: `length`) |
| `indicators`        | array             | yes      | Non-empty list of runs (see below)                                                                                              |
| `end_at`            | string (ISO 8601) | no       | Anchor window end for the **first** page only                                                                                   |
| `cursor`            | string (ISO 8601) | no       | Older pages: pass `next_cursor` from a previous response (do not combine with `end_at`)                                         |

### Each element of `indicators[]`

| Field          | Type   | Required | Description                                                                                                              |
| -------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------------ |
| `indicator_id` | string | yes      | Registered id, e.g. `rsi_wilder`, `bollinger_bands`                                                                      |
| `params`       | object | no       | Indicator-specific parameters (defaults apply if omitted)                                                                |
| `key`          | string | no       | Must be **unique** within the request if set. If omitted, internal keys `run_0`, `run_1`, … are used for validation only |

### Example: one RSI(14)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "count": 120,
  "indicators": [
    {
      "indicator_id": "rsi_wilder",
      "params": { "length": 14 }
    }
  ]
}
```

### Example: Bollinger Bands (20, 2.0)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "count": 120,
  "indicators": [
    {
      "indicator_id": "bollinger_bands",
      "params": { "length": 20, "mult": 2.0 }
    }
  ]
}
```

Omit `params` to use defaults (`length` 20, `mult` 2.0). The response includes three maps under `outputs`: `middle`, `upper`, `lower`.

### Example: two RSI runs (14 and 21) with explicit keys

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "count": 200,
  "indicators": [
    {
      "indicator_id": "rsi_wilder",
      "params": { "length": 14 },
      "key": "rsi_14"
    },
    {
      "indicator_id": "rsi_wilder",
      "params": { "length": 21 },
      "key": "rsi_21"
    }
  ]
}
```

`count` here must be at least **22** (because of `length: 21`).

### Example: older page (pagination)

Use `next_cursor` from the previous `POST` (or `GET /market/candles`) response — same semantics as `GET /market/candles`:

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "count": 100,
  "cursor": "2026-03-25T20:00:00+00:00",
  "indicators": [{ "indicator_id": "rsi_wilder", "params": { "length": 14 } }]
}
```

## Response

Shape aligns with `GET /api/v1/market/candles` for **`asset`**, **`timeframe_seconds`**, **`candles`**, **`has_more`**, **`next_cursor`**, plus:

| Field        | Type   | Description                                                                                                           |
| ------------ | ------ | --------------------------------------------------------------------------------------------------------------------- |
| `align_by`   | string | Always `open_time`: each point’s `open_time` matches `candles[].open_time` in **this** JSON payload                      |
| `candles`    | array  | Same object shape as `GET /market/candles` (`open_time`, `open`, `high`, `low`, `close`, `volume`)                    |
| `indicators` | array  | **Same order** as request `indicators[]`. Each item: `indicator_id`, `params`, `outputs`                              |

### `outputs` structure

- `outputs` is an object: **output line name** → **array** of `{ "open_time": "<ISO string>", "value": <number> }`.
- Arrays are in **chronological** bar order. Warmup bars are **omitted** (no `null` entries).

### Example response (abbreviated)

```json
{
  "asset": "EURUSD_otc",
  "timeframe_seconds": 60,
  "align_by": "open_time",
  "candles": [
    {
      "open_time": "2026-03-25T21:52:00Z",
      "open": 1.08412,
      "high": 1.08445,
      "low": 1.08398,
      "close": 1.08433,
      "volume": null
    }
  ],
  "indicators": [
    {
      "indicator_id": "rsi_wilder",
      "params": { "length": 14 },
      "outputs": {
        "rsi": [
          { "open_time": "2026-03-25T21:53:00Z", "value": 64.0625000000004 },
          { "open_time": "2026-03-25T21:54:00Z", "value": 60.02252252251929 },
          { "open_time": "2026-03-25T22:07:00Z", "value": 35.54216867469766 }
        ]
      }
    },
    {
      "indicator_id": "bollinger_bands",
      "params": { "length": 20, "mult": 2.0 },
      "outputs": {
        "middle": [
          { "open_time": "2026-03-25T22:14:00Z", "value": 1.1385359999999998 }
        ],
        "upper": [
          { "open_time": "2026-03-25T22:14:00Z", "value": 1.139427502103194 }
        ],
        "lower": [
          { "open_time": "2026-03-25T22:14:00Z", "value": 1.1376444978968054 }
        ]
      }
    }
  ],
  "has_more": false,
  "next_cursor": null
}
```

### Joining indicators to candles

1. Take `candles[i].open_time` as a string (after JSON parsing).
2. For an indicator line, e.g. `outputs.rsi`, find the object in the array with the same `open_time`, then read `value`.
3. If there is no such element, that bar is still warmup (or undefined) for that line.

## Common errors

| HTTP | Code                        | Typical cause                                                                              |
| ---- | --------------------------- | ------------------------------------------------------------------------------------------ |
| 400  | `INVALID_MARKET_PARAMETERS` | `count` too small for warmup; `cursor` + `end_at` together; duplicate `key`; bad timeframe |
| 400  | `UNKNOWN_INDICATOR`         | Unregistered `indicator_id`                                                                |
| 400  | `INDICATOR_PARAMETER_ERROR` | Invalid params (e.g. `length` &lt; 1)                                                      |
| 502  | `BROKER_UNAVAILABLE`        | Broker/session errors                                                                      |

## Limits

- Maximum number of runs per request: `STRAT_TRADE_MAX_INDICATORS_PER_MARKET_REQUEST` (default 32, max 128).
- `count` is capped by `STRAT_TRADE_MAX_CANDLES_PER_REQUEST` (see server settings).
