import { useState } from "react";
import { Dashboard } from "./screens/Dashboard";
import { Exposure } from "./screens/Exposure";

type Tab = "dashboard" | "exposure";

const TABS: { id: Tab; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "exposure", label: "Exposure" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("dashboard");

  return (
    <div className="min-h-screen max-w-5xl mx-auto px-4 pb-24 md:pb-8">
      <header className="py-6 flex items-center justify-between">
        <h1 className="text-xl font-bold">
          <span className="text-accent">◆</span> Portfolio Visualizer
        </h1>
        {/* Desktop tabs */}
        <nav className="hidden md:flex gap-1 bg-surface rounded-xl p-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition ${
                tab === t.id ? "bg-accent text-black" : "text-muted hover:text-white"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main>
        {tab === "dashboard" && <Dashboard />}
        {tab === "exposure" && <Exposure />}
      </main>

      {/* Mobile bottom nav (app-like) */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 bg-surface border-t border-white/5 flex">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-4 text-sm font-medium ${
              tab === t.id ? "text-accent" : "text-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
