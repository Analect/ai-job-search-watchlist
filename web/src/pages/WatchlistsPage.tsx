import { useEffect, useState } from "react";

import EmployerMap from "@/components/EmployerWatch/Map";
import UniverseTable from "@/components/EmployerWatch/UniverseTable";
import WatchlistTable from "@/components/EmployerWatch/WatchlistTable";
import JobWatchMap from "@/components/JobWatch/Map";
import PromotedList from "@/components/JobWatch/PromotedList";
import { ApiError, fetchJobMapCoordinates, fetchMapCoordinates, type MapCompany, type MapJob } from "@/lib/api";

type TopTab = "employer" | "job";
type EmployerSubTab = "map" | "watchlist" | "universe";
type JobSubTab = "map" | "promoted";

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 text-sm font-medium ${
        active
          ? "border-b-2 border-accent text-accent"
          : "text-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export default function WatchlistsPage() {
  const [topTab, setTopTab] = useState<TopTab>("employer");
  const [employerSubTab, setEmployerSubTab] = useState<EmployerSubTab>("map");
  const [jobSubTab, setJobSubTab] = useState<JobSubTab>("map");

  const [companies, setCompanies] = useState<MapCompany[]>([]);
  const [companiesLoading, setCompaniesLoading] = useState(true);
  const [companiesError, setCompaniesError] = useState<string | null>(null);

  const [jobs, setJobs] = useState<MapJob[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<string | null>(null);

  useEffect(() => {
    fetchMapCoordinates()
      .then((res) => setCompanies(res.companies))
      .catch((err) =>
        setCompaniesError(err instanceof ApiError ? err.message : (err as Error).message),
      )
      .finally(() => setCompaniesLoading(false));

    fetchJobMapCoordinates()
      .then((res) => setJobs(res.jobs))
      .catch((err) =>
        setJobsError(err instanceof ApiError ? err.message : (err as Error).message),
      )
      .finally(() => setJobsLoading(false));
  }, []);

  const renderEmployerContent = () => {
    if (companiesLoading)
      return <p className="p-4 text-sm text-muted">Loading employer map…</p>;
    if (companiesError)
      return <p className="p-4 text-sm text-danger">{companiesError}</p>;

    switch (employerSubTab) {
      case "map":
        return (
          <EmployerMap companies={companies} onCompaniesChange={setCompanies} />
        );
      case "watchlist":
        return (
          <WatchlistTable companies={companies} onCompaniesChange={setCompanies} />
        );
      case "universe":
        return (
          <UniverseTable companies={companies} onCompaniesChange={setCompanies} />
        );
    }
  };

  const renderJobContent = () => {
    switch (jobSubTab) {
      case "map":
        if (jobsLoading)
          return <p className="p-4 text-sm text-muted">Loading job map…</p>;
        if (jobsError)
          return <p className="p-4 text-sm text-danger">{jobsError}</p>;
        return <JobWatchMap jobs={jobs} onJobsChange={setJobs} />;
      case "promoted":
        return <PromotedList />;
    }
  };

  return (
    <div className="space-y-4">
      {/* Top-level tabs */}
      <div className="flex gap-1 border-b border-border-subtle">
        <TabButton active={topTab === "employer"} onClick={() => setTopTab("employer")}>
          Employer Watch
        </TabButton>
        <TabButton active={topTab === "job"} onClick={() => setTopTab("job")}>
          Job Watch
        </TabButton>
      </div>

      {topTab === "employer" ? (
        <>
          {/* Employer sub-tabs */}
          <div className="flex gap-1 border-b border-border-subtle">
            <TabButton
              active={employerSubTab === "map"}
              onClick={() => setEmployerSubTab("map")}
            >
              Map
            </TabButton>
            <TabButton
              active={employerSubTab === "watchlist"}
              onClick={() => setEmployerSubTab("watchlist")}
            >
              Watchlist
            </TabButton>
            <TabButton
              active={employerSubTab === "universe"}
              onClick={() => setEmployerSubTab("universe")}
            >
              Universe
            </TabButton>
          </div>
          {renderEmployerContent()}
        </>
      ) : (
        <>
          {/* Job Watch sub-tabs */}
          <div className="flex gap-1 border-b border-border-subtle">
            <TabButton active={jobSubTab === "map"} onClick={() => setJobSubTab("map")}>
              Map
            </TabButton>
            <TabButton
              active={jobSubTab === "promoted"}
              onClick={() => setJobSubTab("promoted")}
            >
              Promoted List
            </TabButton>
          </div>
          {renderJobContent()}
        </>
      )}
    </div>
  );
}
