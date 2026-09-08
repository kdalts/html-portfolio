import { ApiError, getBacktestRuns } from "@/lib/api";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function BacktestPage() {
  let runs;
  try {
    runs = await getBacktestRuns();
  } catch (err) {
    return <ErrorState message={err instanceof ApiError ? err.message : "Could not reach the API."} />;
  }

  return (
    <div>
      <PageHeader
        title="Historical Backtest"
        description="Every walk-forward fold's results, by model type — overall metrics plus the probability-band breakdown (predicted probability vs. actual frequency) that's the core calibration diagnostic."
      />

      {runs.length === 0 && <EmptyState message="No backtest runs yet — run python -m app.backtest.cli run." />}

      <div className="space-y-6">
        {runs.map((run) => (
          <Card key={`${run.backtest_run_id}-${run.model_type}`}>
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-slate-100">
                  {run.backtest_run_id} <span className="text-sky-300">· {run.model_type}</span>
                </h3>
                <p className="text-xs text-slate-500">
                  Train {formatDate(run.train_start_date)} – {formatDate(run.train_end_date)} · Test{" "}
                  {formatDate(run.test_start_date)} – {formatDate(run.test_end_date)}
                </p>
              </div>
              {run.overall && (
                <div className="flex gap-4 text-xs text-slate-400">
                  <span>Sample {run.overall.sample_size}</span>
                  <span>Brier {formatNumber(run.overall.brier_score)}</span>
                  <span>Log loss {formatNumber(run.overall.log_loss)}</span>
                  <span>Hit rate {formatPercent(run.overall.hit_rate)}</span>
                </div>
              )}
            </div>

            {run.probability_bands.length === 0 ? (
              <p className="text-sm text-slate-500">No probability-band data for this run.</p>
            ) : (
              <Table>
                <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
                  <tr>
                    <th className="px-3 py-2">Band</th>
                    <th className="px-3 py-2 text-right">Predicted probability</th>
                    <th className="px-3 py-2 text-right">Actual frequency</th>
                    <th className="px-3 py-2 text-right">Sample size</th>
                    <th className="px-3 py-2 text-right">Gap</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {run.probability_bands.map((band) => {
                    const gap =
                      band.predicted_probability_mean !== null && band.actual_frequency !== null
                        ? band.predicted_probability_mean - band.actual_frequency
                        : null;
                    return (
                      <tr key={band.band}>
                        <td className="px-3 py-2 font-mono text-slate-300">{band.band}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{formatPercent(band.predicted_probability_mean)}</td>
                        <td className="px-3 py-2 text-right text-slate-300">{formatPercent(band.actual_frequency)}</td>
                        <td className="px-3 py-2 text-right text-slate-500">{band.sample_size}</td>
                        <td
                          className={`px-3 py-2 text-right font-medium ${
                            gap === null ? "text-slate-500" : Math.abs(gap) < 0.05 ? "text-emerald-400" : "text-amber-400"
                          }`}
                        >
                          {gap === null ? "—" : `${gap > 0 ? "+" : ""}${(gap * 100).toFixed(1)}pt`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}
