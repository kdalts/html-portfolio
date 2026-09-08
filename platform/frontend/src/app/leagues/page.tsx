import { ApiError, getLeaguePerformance } from "@/lib/api";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function LeaguePerformancePage() {
  let leagues;
  try {
    leagues = await getLeaguePerformance();
  } catch (err) {
    return <ErrorState message={err instanceof ApiError ? err.message : "Could not reach the API."} />;
  }

  return (
    <div>
      <PageHeader
        title="League Performance"
        description="Historical reliability by league, used to filter which leagues can appear in the daily ranking. A league needs enough tested history, low Brier score, and good calibration to be eligible — see docs/BACKTEST.md and MODEL.md in the repo for the exact formula."
      />

      {leagues.length === 0 && <EmptyState message="No league performance data yet — run the backtesting and league-reliability CLIs." />}

      {leagues.length > 0 && (
        <Card>
          <Table>
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">League</th>
                <th className="px-3 py-2">Model</th>
                <th className="px-3 py-2">Window</th>
                <th className="px-3 py-2 text-right">Sample</th>
                <th className="px-3 py-2 text-right">Brier</th>
                <th className="px-3 py-2 text-right">Log Loss</th>
                <th className="px-3 py-2 text-right">Calib. Error</th>
                <th className="px-3 py-2 text-right">Hit Rate</th>
                <th className="px-3 py-2 text-right">Reliability</th>
                <th className="px-3 py-2 text-center">Eligible</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {leagues.map((league) => (
                <tr key={`${league.league_id}-${league.model_type}`} className="hover:bg-slate-900/60">
                  <td className="px-3 py-3 font-medium text-slate-100">{league.league_name}</td>
                  <td className="px-3 py-3 text-slate-400">{league.model_type}</td>
                  <td className="px-3 py-3 text-slate-400">
                    {formatDate(league.evaluation_window_start)} – {formatDate(league.evaluation_window_end)}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-300">{league.sample_size}</td>
                  <td className="px-3 py-3 text-right text-slate-300">{formatNumber(league.brier_score)}</td>
                  <td className="px-3 py-3 text-right text-slate-300">{formatNumber(league.log_loss)}</td>
                  <td className="px-3 py-3 text-right text-slate-300">{formatNumber(league.calibration_error)}</td>
                  <td className="px-3 py-3 text-right text-slate-300">{formatPercent(league.hit_rate)}</td>
                  <td className="px-3 py-3 text-right font-semibold text-sky-300">
                    {formatPercent(league.league_reliability_score)}
                  </td>
                  <td className="px-3 py-3 text-center">
                    {league.is_eligible ? (
                      <span className="rounded-full bg-emerald-950/60 px-2 py-0.5 text-xs font-medium text-emerald-300">
                        Eligible
                      </span>
                    ) : (
                      <span className="rounded-full bg-rose-950/60 px-2 py-0.5 text-xs font-medium text-rose-300">
                        Excluded
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
