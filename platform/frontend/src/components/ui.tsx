import type { ReactNode } from "react";

export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
      {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-slate-800 bg-slate-900/60 p-5 ${className}`}>{children}</div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <Card className="text-sm text-slate-400">
      <p>{message}</p>
    </Card>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-900/60 bg-red-950/40 p-5 text-sm text-red-300">
      <p className="font-medium">Couldn&apos;t load this page</p>
      <p className="mt-1 text-red-400">{message}</p>
    </div>
  );
}

// Distinct colors for the platform's three required, never-conflated
// quantities: probability (blue), confidence (violet), and market edge
// (green when positive, red when negative, slate when unavailable) - the
// same color mapping is used everywhere these appear across the app.
export function ProbabilityPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-sky-900/60 bg-sky-950/40 px-3 py-2 text-center">
      <div className="text-[11px] uppercase tracking-wide text-sky-400">{label}</div>
      <div className="text-lg font-semibold text-sky-200">{value}</div>
    </div>
  );
}

export function ConfidencePill({ value }: { value: string }) {
  return (
    <div className="rounded-md border border-violet-900/60 bg-violet-950/40 px-3 py-2 text-center">
      <div className="text-[11px] uppercase tracking-wide text-violet-400">Confidence</div>
      <div className="text-lg font-semibold text-violet-200">{value}</div>
    </div>
  );
}

export function EdgePill({ value, rawValue }: { value: string; rawValue: number | null }) {
  const tone =
    rawValue === null || rawValue === undefined
      ? "border-slate-700 bg-slate-800/40 text-slate-300"
      : rawValue > 0
        ? "border-emerald-900/60 bg-emerald-950/40 text-emerald-200"
        : "border-rose-900/60 bg-rose-950/40 text-rose-200";
  return (
    <div className={`rounded-md border px-3 py-2 text-center ${tone}`}>
      <div className="text-[11px] uppercase tracking-wide opacity-80">Edge</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full min-w-max text-left text-sm">{children}</table>
    </div>
  );
}
