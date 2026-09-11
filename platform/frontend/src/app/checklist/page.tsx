import Link from "next/link";
import { ApiError, getDailyChecklist } from "@/lib/api";
import { formatDateTime, todayIsoDate } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader, Table } from "@/components/ui";
import type { ChecklistEntry } from "@/lib/types";

export const dynamic = "force-dynamic";

const CHECK_COLUMNS: { key: keyof ChecklistEntry; label: string; title: string }[] = [
  { key: "sample_size_ok", label: "1", title: "1. Sample size: 5+ games played this season by both teams" },
  { key: "btts_rate_ok", label: "2", title: "2. BTTS rate: both teams over 60% this season" },
  { key: "clean_sheet_rate_ok", label: "3", title: "3. Clean sheet rate: both teams under 35% this season" },
  { key: "combined_goals_ok", label: "4", title: "4. Combined goals/game: sum of both teams' totals over 3.5" },
  { key: "league_gap_ok", label: "5", title: "5. League gap: home team 5+ places higher in the table" },
  { key: "shots_on_target_ok", label: "6", title: "6. Shots on target: both teams average over 4 per game" },
  { key: "attack_defence_split_ok", label: "7", title: "7. Attack/defence split: home GF avg and away GA avg both over 3" },
  { key: "xg_ok", label: "8", title: "8. xG: combined expected goals (for + against) for both teams over 2.5" },
  { key: "h2h_ok", label: "9", title: "9. H2H: last 3 meetings all over 2.5 goals" },
  { key: "recent_form_ok", label: "10", title: "10. Recent form: both teams 60%+ over 2.5 in their last 5 games" },
  { key: "vs_league_avg_ok", label: "11", title: "11. Vs league average: both teams scoring above their league's venue-specific average" },
  { key: "early_goals_ok", label: "12", title: "12. Early goals: both teams score in the first 15 minutes 40%+ of games" },
  { key: "late_goals_ok", label: "13", title: "13. Late goals: both teams score in the last 15 minutes 40%+ of games" },
];

function CheckMark({ value }: { value: boolean | null }) {
  if (value === null) {
    return <span className="text-slate-600">—</span>;
  }
  return value ? (
    <span className="font-semibold text-emerald-400">✓</span>
  ) : (
    <span className="font-semibold text-rose-400">✗</span>
  );
}

export default async function ChecklistPage({
  searchParams,
}: {
  searchParams: Promise<{ date?: string }>;
}) {
  const { date: dateParam } = await searchParams;
  const date = dateParam ?? todayIsoDate();

  let data;
  let error: string | null = null;
  try {
    data = await getDailyChecklist(date);
  } catch (err) {
    error = err instanceof ApiError ? err.message : "Could not reach the API.";
  }

  return (
    <div>
      <PageHeader
        title="15-Point Checklist"
        description="A fixed rule checklist, separate from the main probability model - each item is a plain TRUE/FALSE/N/A, never a guess when data is missing. Items 12-13 (goal timing) are always N/A today: this platform doesn't ingest that data yet."
      />

      <form className="mb-6 flex items-center gap-3 text-sm" action="/checklist" method="GET">
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

      {data && data.entries.length === 0 && (
        <EmptyState
          message={`No checklist scores for ${date} yet. Either the checklist hasn't been computed for this date, or every fixture that day had fewer than 5 season games played by one or both teams (excluded per item 1, not scored).`}
        />
      )}

      {data && data.entries.length > 0 && (
        <>
          <Card className="mb-4 text-xs text-slate-500">
            <p>
              Score = checks passed / checks computable (not out of 13 when some checks are N/A for a match). Hover a
              column header for the full check description.
            </p>
          </Card>
          <Table>
            <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Match</th>
                <th className="px-3 py-2">League</th>
                <th className="px-3 py-2">Kickoff</th>
                <th className="px-3 py-2 text-right">Score</th>
                {CHECK_COLUMNS.map((col) => (
                  <th key={col.key} title={col.title} className="px-2 py-2 text-center">
                    {col.label}
                  </th>
                ))}
                <th className="px-3 py-2">Notes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {data.entries.map((entry) => (
                <tr key={entry.fixture_id} className="hover:bg-slate-900/60">
                  <td className="px-3 py-3">
                    <Link href={`/matches/${entry.fixture_id}`} className="font-medium text-slate-100 hover:text-sky-300">
                      {entry.home_team} vs {entry.away_team}
                    </Link>
                  </td>
                  <td className="px-3 py-3 text-slate-400">{entry.league_name}</td>
                  <td className="px-3 py-3 text-slate-400">{formatDateTime(entry.kickoff)}</td>
                  <td className="px-3 py-3 text-right font-mono text-slate-200">
                    {entry.checks_passed}/{entry.checks_computable}
                  </td>
                  {CHECK_COLUMNS.map((col) => (
                    <td key={col.key} className="px-2 py-3 text-center">
                      <CheckMark value={entry[col.key] as boolean | null} />
                    </td>
                  ))}
                  <td className="max-w-xs px-3 py-3 text-xs text-slate-500">
                    {entry.context_notes && <p>{entry.context_notes}</p>}
                    <p>Key players missing: {entry.key_players_missing}</p>
                    {entry.data_gaps && <p className="mt-1 text-amber-500/80">Data gaps: {entry.data_gaps}</p>}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </>
      )}

      <p className="mt-6 text-xs text-slate-500">
        Predictions are probability estimates, not guarantees. This checklist is an independent rule-based signal,
        separate from the platform&apos;s probability/confidence/edge model above — the two are not meant to be
        combined into one score.
      </p>
    </div>
  );
}
