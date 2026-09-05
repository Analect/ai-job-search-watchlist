import { NavLink, Route, Routes } from "react-router-dom";

import PostingsPage from "@/pages/PostingsPage";
import MapPage from "@/pages/MapPage";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-card text-sm font-medium ${
    isActive ? "bg-accent text-white" : "text-muted hover:text-ink"
  }`;

export default function App() {
  return (
    <div className="mx-auto max-w-app px-4 py-6">
      <header className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Job Search Watchlist</h1>
        <nav className="flex gap-2">
          <NavLink to="/postings" className={navLinkClass}>
            Postings
          </NavLink>
          <NavLink to="/map" className={navLinkClass}>
            Discover
          </NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<PostingsPage />} />
          <Route path="/postings" element={<PostingsPage />} />
          <Route path="/map" element={<MapPage />} />
        </Routes>
      </main>
    </div>
  );
}
