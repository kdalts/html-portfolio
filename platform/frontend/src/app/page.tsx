import Link from "next/link";
import { ApiError, getDailyRanking } from "@/lib/api";
import { formatDateTime, formatPercent, formatSignedPercent, todayIsoDate } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader, Table } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function TodayTopTenPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date: dateParam } = await searchParams;
  const date = dateParam ?? todayIsoDate();

  let data;
  let error: string | null = null;
  try {
    data = await getDailyRanking(date);
  } catch (err) {
    error = err instanceof ApiError ? err.message : "Could not reach the API.";
  }

  return (
    <div>
      <PageHeader
        title="Today's Top 10"
        description="Ranked Over 2.5 selections for the chosen date. Probability, confidence, and market edge are separate figures — a high probability does not by itself mean a confident or high-edge pick."
      />

      <form className="mb-6 flex items-center gap-3 text-sm" action="/" method="GET">
        <label htmlFor="date" className="text-slate-400">
          Date
        </label>
        <input
          id="date"
          name="date"
          type="date"
          defaultValue={date}
          className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-slate-100"
        />
        <button type="submit" className="rounded-md bg-sky-700 px-3 py-1.5 font-medium text-white hover:bg-sky-600">
          Go
        </button>
      </form>

      {error && <ErrorState message={error} />}

      {data && data.rankings.length === 0 && (
        <EmptyState message={`No ranked matches for ${date}. Either the ranking hasn't been generated yet, or nothing qualified.`} />
      )}

      {data && data.rankings.length > 0 && (
        <Card>
          {data.generated_at && (
            <p className="mb-4 text-xs text-slate-500">Generated {formatDateTime(data.generated_at)}</p>
          )}
          <Table>
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">#</th>
                <th className="px-3 py-2">Match</th>
                <th className="px-3 py-2">League</th>
                <th className="px-3 py-2">Kickoff</th>
                <th className="px-3 py-2 text-right">Final</th>
                <th className="px-3 py-2 text-right">Poisson</th>
                <th className="px-3 py-2 text-right">ML</th>
                <th className="px-3 py-2 text-right">Sportmonks</th>
                <th className="px-3 py-2 text-right">Market</th>
                <th className="px-3 py-2 text-right">Edge</th>
                <th className="px-3 py-2 text-right">Confidence</th>
                <th className="px-3 py-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {data.rankings.map((entry) => (
                <tr key={entry.fixture_id} className="hover:bg-slate-900/60">
                  <td className="px-3 py-3 font-mono text-slate-400">{entry.rank}</td>
                  <td className="px-3 py-3">
                    <Link href={`/matches/${entry.fixture_id}`} className="font-medium text-slate-100 hover:text-sky-300">
                      {entry.home_team} vs {entry.away_team}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-slate-400">{entry.league_name}</td>
                  <td className="px-3 py-3 text-slate-400">{formatDateTime(entry.kickoff)}</td>
                  <td className="px-3 py-3 text-right font-semibold text-sky-300">
                    {formatPercent(entry.final_probability)}
                  </td>
                  <td className="px-3 py-3 text-right text-slate-400">{formatPercent(entry.poisson_probability)}</td>
                  <td className="px-3 py-3 text-right text-slate-400">{formatPercent(entry.ml_probability)}</td>
                  <td className="px-3 py-3 text-right text-slate-400">{formatPercent(entry.sportmonks_probability)}</td>
                  <td className="px-3 py-3 text-right text-slate-400">{formatPercent(entry.market_probability)}</td>
                  <td
                    className={`px-3 py-3 text-right font-medium ${
                      entry.edge === null ? "text-slate-500" : entry.edge > 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {formatSignedPercent(entry.edge)}
                  </td>
                  <td className="px-3 py-3 text-right text-violet-300">{formatPercent(entry.confidence_score)}</td>
                  <td className="px-3 py-3 text-right text-slate-400">{entry.ranking_score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}
