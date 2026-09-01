import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RefreshResult } from "../api";
import { Card } from "../components/Card";
import { pct } from "../format";

export function MarketDataPanel() {
  const queryClient = useQueryClient();
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });

  const refresh = useMutation<RefreshResult, Error>({
    mutationFn: api.refreshMarketData,
    // Every screen reads prices, so nothing cached survives a refresh.
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const data = coverage.data;
  const complete = data ? data.with_prices === data.total_tickers : false;

  return (
    <Card title="Market data">
      {coverage.error && <p className="text-danger text-sm">Failed to load coverage.</p>}
      {!data && !coverage.error && <p className="text-muted text-sm">Loading…</p>}

      {data && (
        <>
          <p className="text-sm">
            Real prices for <strong>{data.with_prices} of {data.total_tickers}</strong> tickers
            {data.with_metadata < data.total_tickers && (
              <> · fundamentals for {data.with_metadata}</>
            )}
          </p>

          {!complete && (
            <p className="text-warning text-sm mt-2">
              Anything not covered is <strong>estimated</strong>, not real. Sector, factor and
              risk figures stay unreliable until coverage is complete.
            </p>
          )}

          {data.missing.length > 0 && (
            <p className="text-muted text-xs mt-2">
              No prices yet: {data.missing.join(", ")}
            </p>
          )}

          {data.etfs.length > 0 && (
            <div className="mt-3">
              <p className="text-muted text-xs uppercase tracking-wide mb-1.5">
                ETF look-through depth
              </p>
              <ul className="text-xs space-y-1">
                {data.etfs.map((e) => (
                  <li key={e.ticker} className="text-muted">
                    <span className="font-medium text-white">{e.ticker}</span> — {e.constituents}{" "}
                    holdings covering {pct(e.covered_weight)} of the fund
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!data.configured && (
            <p className="text-warning text-sm mt-3">
              No API key. Add <code>ALPHAVANTAGE_API_KEY</code> to <code>backend/.env</code> and
              restart the API.
            </p>
          )}

          <button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending || !data.configured}
            className="mt-4 px-4 py-2 rounded-lg bg-accent text-black text-sm font-semibold disabled:opacity-50"
          >
            {refresh.isPending ? "Refreshing…" : "Refresh market data"}
          </button>
          <p className="text-muted text-xs mt-2">
            Paced at ~1 request/second, so this takes a while. The free tier allows 25 requests
            per day.
          </p>

          {refresh.error && (
            <p className="text-danger text-sm mt-3">{refresh.error.message}</p>
          )}

          {refresh.data && (
            <div className="mt-3 text-sm">
              <p>
                Refreshed {refresh.data.tickers_refreshed} of {refresh.data.tickers_seen} tickers
                in {refresh.data.calls_made} requests.
              </p>
              {refresh.data.messages.map((m) => (
                <p key={m} className="text-warning text-xs mt-1">
                  {m}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}
