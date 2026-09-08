import { ApiError, getModelPerformance } from "@/lib/api";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { Card, EmptyState, ErrorState, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function ModelPerformancePage() {
  let models;
  try {
    models = await getModelPerformance();
  } catch (err) {
    return <ErrorState message={err instanceof ApiError ? err.message : "Could not reach the API."} />;
  }

  return (
    <div>
      <PageHeader
        title="Model Performance"
        description="The most recent walk-forward test-period metrics for each model type currently backtested."
      />

      {models.length === 0 && <EmptyState message="No backtest results yet — run python -m app.backtest.cli run." />}

      {models.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {models.map((model) => (
            <Card key={model.model_type}>
              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-sky-300">{model.model_type}</h3>
                <span className="text-xs text-slate-500">
                  {formatDate(model.test_start_date)} – {formatDate(model.test_end_date)}
                </span>
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-slate-500">Sample size</dt>
                <dd className="text-right text-slate-200">{model.sample_size}</dd>
                <dt className="text-slate-500">Log loss</dt>
                <dd className="text-right text-slate-200">{formatNumber(model.log_loss)}</dd>
                <dt className="text-slate-500">Brier score</dt>
                <dd className="text-right text-slate-200">{formatNumber(model.brier_score)}</dd>
                <dt className="text-slate-500">ROC-AUC</dt>
                <dd className="text-right text-slate-200">{formatNumber(model.roc_auc)}</dd>
                <dt className="text-slate-500">Accuracy</dt>
                <dd className="text-right text-slate-200">{formatPercent(model.accuracy)}</dd>
                <dt className="text-slate-500">Precision</dt>
                <dd className="text-right text-slate-200">{formatPercent(model.precision_score)}</dd>
                <dt className="text-slate-500">Recall</dt>
                <dd className="text-right text-slate-200">{formatPercent(model.recall_score)}</dd>
                <dt className="text-slate-500">Calibration error</dt>
                <dd className="text-right text-slate-200">{formatNumber(model.calibration_error)}</dd>
                <dt className="text-slate-500">Hit rate</dt>
                <dd className="text-right text-slate-200">{formatPercent(model.hit_rate)}</dd>
              </dl>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
