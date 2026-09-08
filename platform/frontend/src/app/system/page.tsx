import { ApiError, getSystemHealth } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Card, ErrorState, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

const LATEST_LABELS: Record<string, string> = {
  last_fixture_ingested_at: "Last fixture ingested/updated",
  last_features_computed_at: "Last features computed",
  last_prediction_at: "Last prediction generated",
  last_ranking_generated_at: "Last daily ranking generated",
};

const COUNT_LABELS: Record<string, string> = {
  leagues: "Leagues",
  teams: "Teams",
  fixtures: "Fixtures",
  predictions: "Predictions",
  rankings: "Ranked selections",
};

export default async function SystemHealthPage() {
  let health;
  try {
    health = await getSystemHealth();
  } catch (err) {
    return <ErrorState message={err instanceof ApiError ? err.message : "Could not reach the API."} />;
  }

  return (
    <div>
      <PageHeader
        title="System Health"
        description="A quick picture of whether data is flowing through the pipeline — not a replacement for real monitoring/alerting (see docs/DEPLOYMENT.md)."
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <Card>
          <h3 className="mb-3 text-sm font-semibold text-slate-100">Status</h3>
          <dl className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">API</dt>
              <dd className="rounded-full bg-emerald-950/60 px-2 py-0.5 text-xs font-medium text-emerald-300">
                {health.status}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Database connection</dt>
              <dd className={health.database_connected ? "text-emerald-300" : "text-rose-300"}>
                {health.database_connected ? "Connected" : "Unavailable"}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-slate-500">Sportmonks token configured</dt>
              <dd className={health.sportmonks_token_configured ? "text-emerald-300" : "text-amber-300"}>
                {health.sportmonks_token_configured ? "Yes" : "No"}
              </dd>
            </div>
          </dl>
        </Card>

        <Card>
          <h3 className="mb-3 text-sm font-semibold text-slate-100">Row counts</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            {Object.entries(health.counts).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-slate-500">{COUNT_LABELS[key] ?? key}</dt>
                <dd className="text-right text-slate-200">{value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <Card>
        <h3 className="mb-3 text-sm font-semibold text-slate-100">Pipeline freshness</h3>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          {Object.entries(health.latest).map(([key, value]) => (
            <div key={key} className="flex items-center justify-between">
              <dt className="text-slate-500">{LATEST_LABELS[key] ?? key}</dt>
              <dd className="text-slate-200">{formatDateTime(value)}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </div>
  );
}
