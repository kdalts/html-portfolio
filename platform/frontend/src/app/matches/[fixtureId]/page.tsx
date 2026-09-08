import { notFound } from "next/navigation";
import { ApiError, getFixtureDetail } from "@/lib/api";
import { formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import { Card, ConfidencePill, EdgePill, ErrorState, PageHeader, ProbabilityPill } from "@/components/ui";
import type { TeamRollingForm } from "@/lib/types";

export const dynamic = "force-dynamic";

function TeamFormCard({ form }: { form: TeamRollingForm | null }) {
  if (!form) {
    return (
      <Card>
        <p className="text-sm text-slate-500">No rolling form data available for this team yet.</p>
      </Card>
    );
  }
  return (
    <Card>
      <h3 className="mb-3 text-sm font-semibold text-slate-100">
        {form.team_name} <span className="font-normal text-slate-500">({form.is_home ? "home" : "away"})</span>
      </h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <dt className="text-slate-500">Goals scored (last 5, overall)</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.overall_last5_goals_scored)}</dd>
        <dt className="text-slate-500">Goals conceded (last 5, overall)</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.overall_last5_goals_conceded)}</dd>
        <dt className="text-slate-500">Over 2.5% (last 5, overall)</dt>
        <dd className="text-right text-slate-200">{formatPercent(form.overall_last5_over_2_5_pct)}</dd>
        <dt className="text-slate-500">BTTS% (last 5, overall)</dt>
        <dd className="text-right text-slate-200">{formatPercent(form.overall_last5_btts_pct)}</dd>
        <dt className="text-slate-500">Goals scored (last 5, {form.is_home ? "home" : "away"})</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.venue_last5_goals_scored)}</dd>
        <dt className="text-slate-500">Goals conceded (last 5, {form.is_home ? "home" : "away"})</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.venue_last5_goals_conceded)}</dd>
        <dt className="text-slate-500">Over 2.5% (last 5, {form.is_home ? "home" : "away"})</dt>
        <dd className="text-right text-slate-200">{formatPercent(form.venue_last5_over_2_5_pct)}</dd>
        <dt className="text-slate-500">xG (last 10, overall)</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.overall_last10_xg)}</dd>
        <dt className="text-slate-500">xGA (last 10, overall)</dt>
        <dd className="text-right text-slate-200">{formatNumber(form.overall_last10_xga)}</dd>
        <dt className="text-slate-500">Matches in sample ({form.is_home ? "home" : "away"})</dt>
        <dd className="text-right text-slate-200">{form.venue_last10_matches_played ?? "—"}</dd>
      </dl>
    </Card>
  );
}

export default async function MatchDetailPage({
  params,
}: {
  params: Promise<{ fixtureId: string }>;
}) {
  const { fixtureId } = await params;
  const id = Number(fixtureId);

  let fixture;
  try {
    fixture = await getFixtureDetail(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    return <ErrorState message={err instanceof ApiError ? err.message : "Could not reach the API."} />;
  }

  const prediction = fixture.prediction;
  const mf = fixture.match_features;

  return (
    <div>
      <PageHeader
        title={`${fixture.home_team} vs ${fixture.away_team}`}
        description={`${fixture.league_name} · ${formatDateTime(fixture.kickoff)} · ${fixture.status}${
          fixture.total_goals !== null ? ` · ${fixture.home_goals}-${fixture.away_goals} (${fixture.over_2_5 ? "Over" : "Under"} 2.5)` : ""
        }`}
      />

      {!prediction && (
        <Card className="mb-6 text-sm text-slate-400">No prediction has been generated for this fixture yet.</Card>
      )}

      {prediction && (
        <Card className="mb-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <ProbabilityPill label="Final" value={formatPercent(prediction.final_probability)} />
            <ProbabilityPill label="Poisson" value={formatPercent(prediction.poisson_probability)} />
            <ProbabilityPill label="ML" value={formatPercent(prediction.ml_probability)} />
            <ProbabilityPill label="Sportmonks" value={formatPercent(prediction.sportmonks_probability)} />
            <ProbabilityPill label="Market" value={formatPercent(prediction.market_probability)} />
            <ConfidencePill value={formatPercent(fixture.confidence_score)} />
            <EdgePill value={prediction.edge !== null ? formatPercent(prediction.edge) : "—"} rawValue={prediction.edge} />
            <div className="rounded-md border border-slate-700 bg-slate-900/40 px-3 py-2 text-center">
              <div className="text-[11px] uppercase tracking-wide text-slate-400">Exp. goals (H/A)</div>
              <div className="text-lg font-semibold text-slate-200">
                {formatNumber(prediction.expected_home_goals, 2)} / {formatNumber(prediction.expected_away_goals, 2)}
              </div>
            </div>
          </div>
          <p className="mt-4 text-sm text-slate-400">{prediction.explanation}</p>
          <p className="mt-2 text-xs text-slate-500">
            This is a probability estimate, not a guarantee. Confidence reflects data quality and model agreement;
            edge reflects the gap against the de-vigged market price. Neither implies the market is wrong.
          </p>
        </Card>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <TeamFormCard form={fixture.home_form} />
        <TeamFormCard form={fixture.away_form} />
      </div>

      {mf && (
        <Card>
          <h3 className="mb-3 text-sm font-semibold text-slate-100">League &amp; head-to-head context</h3>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <dt className="text-slate-500">League avg goals</dt>
            <dd className="text-slate-200">{formatNumber(mf.league_avg_goals)}</dd>
            <dt className="text-slate-500">League Over 2.5%</dt>
            <dd className="text-slate-200">{formatPercent(mf.league_over_2_5_pct)}</dd>
            <dt className="text-slate-500">League sample size</dt>
            <dd className="text-slate-200">{mf.league_sample_size ?? "—"}</dd>
            <dt className="text-slate-500">H2H matches</dt>
            <dd className="text-slate-200">{mf.h2h_matches_played ?? "—"}</dd>
            <dt className="text-slate-500">H2H avg total goals</dt>
            <dd className="text-slate-200">{formatNumber(mf.h2h_avg_total_goals)}</dd>
            <dt className="text-slate-500">H2H Over 2.5%</dt>
            <dd className="text-slate-200">{formatPercent(mf.h2h_over_2_5_pct)}</dd>
            <dt className="text-slate-500">H2H BTTS%</dt>
            <dd className="text-slate-200">{formatPercent(mf.h2h_btts_pct)}</dd>
            <dt className="text-slate-500">Data completeness</dt>
            <dd className="text-slate-200">{formatPercent(mf.data_completeness_score)}</dd>
          </dl>
        </Card>
      )}
    </div>
  );
}
