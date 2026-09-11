import Link from "next/link";

const LINKS = [
  { href: "/", label: "Today's Top 10" },
  { href: "/checklist", label: "15-Point Checklist" },
  { href: "/leagues", label: "League Performance" },
  { href: "/models", label: "Model Performance" },
  { href: "/backtest", label: "Historical Backtest" },
  { href: "/system", label: "System Health" },
];

export function Nav() {
  return (
    <header className="border-b border-slate-800 bg-slate-950">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-4 sm:px-6">
        <Link href="/" className="text-sm font-semibold tracking-tight text-slate-100">
          Over 2.5 Platform
        </Link>
        <nav className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="text-slate-400 transition hover:text-slate-100">
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
