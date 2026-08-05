import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { RunProvider } from "./lib/RunContext";
import { Dashboard } from "./pages/Dashboard";
import { RepositoryPage } from "./pages/RepositoryPage";
import { AuditPage } from "./pages/AuditPage";
import { FindingsPage } from "./pages/FindingsPage";
import { FixesPage } from "./pages/FixesPage";
import { AiComparisonPage } from "./pages/AiComparisonPage";
import { MemoryPage } from "./pages/MemoryPage";
import { ReportsPage } from "./pages/ReportsPage";

const ExplorerPage = lazy(() => import("./pages/ExplorerPage").then((m) => ({ default: m.ExplorerPage })));

function App() {
  return (
    <RunProvider>
      <div className="flex h-screen w-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/repository" element={<RepositoryPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route
              path="/explorer"
              element={
                <Suspense fallback={<div className="p-8 text-sm text-fog-2">Loading explorer…</div>}>
                  <ExplorerPage />
                </Suspense>
              }
            />
            <Route path="/findings" element={<FindingsPage />} />
            <Route path="/fixes" element={<FixesPage />} />
            <Route path="/ai-comparison" element={<AiComparisonPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            
          </Routes>
        </main>
      </div>
    </RunProvider>
  );
}

export default App;
