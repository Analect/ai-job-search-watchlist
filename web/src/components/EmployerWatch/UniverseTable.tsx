import { useEffect, useRef, useState } from "react";

import {
  ApiError,
  addToWatchlist,
  fetchDendrogram,
  removeFromWatchlist,
  type MapCompany,
} from "@/lib/api";

interface UniverseTableProps {
  companies: MapCompany[];
  onCompaniesChange: (next: MapCompany[]) => void;
}

// --- Dendrogram types ---

type DendrogramLeaf = { slug: string; distance: number };
type DendrogramInternal = { distance: number; left: DendrogramNode; right: DendrogramNode };
type DendrogramNode = DendrogramLeaf | DendrogramInternal;

interface LayoutNode {
  x: number;
  y: number;
  slug?: string;
  left?: LayoutNode;
  right?: LayoutNode;
}

function isLeaf(node: DendrogramNode): node is DendrogramLeaf {
  return "slug" in node;
}

function findMaxDistance(node: DendrogramNode): number {
  if (isLeaf(node)) return 0;
  return Math.max(node.distance, findMaxDistance(node.left), findMaxDistance(node.right));
}

function layout(
  node: DendrogramNode,
  maxDist: number,
  treeWidth: number,
  rowHeight: number,
  counter: { n: number },
): LayoutNode {
  if (isLeaf(node)) {
    const x = counter.n * rowHeight + rowHeight / 2;
    counter.n++;
    return { x, y: treeWidth, slug: node.slug };
  }
  const left = layout(node.left, maxDist, treeWidth, rowHeight, counter);
  const right = layout(node.right, maxDist, treeWidth, rowHeight, counter);
  return {
    x: (left.x + right.x) / 2,
    y: maxDist > 0 ? (node.distance / maxDist) * treeWidth : 0,
    left,
    right,
  };
}

function collectLinks(
  node: LayoutNode,
  acc: Array<{ px: number; py: number; cx: number; cy: number }>,
): void {
  if (!node.left || !node.right) return;
  acc.push({ px: node.x, py: node.y, cx: node.left.x, cy: node.left.y });
  acc.push({ px: node.x, py: node.y, cx: node.right.x, cy: node.right.y });
  collectLinks(node.left, acc);
  collectLinks(node.right, acc);
}

function collectLeaves(node: LayoutNode, acc: LayoutNode[]): void {
  if (node.slug) { acc.push(node); return; }
  if (node.left) collectLeaves(node.left, acc);
  if (node.right) collectLeaves(node.right, acc);
}

// --- Component ---

const ROW_HEIGHT = 16;
const TREE_WIDTH = 400;
const LABEL_WIDTH = 180;
const MARGIN = 10;

export default function UniverseTable({ companies, onCompaniesChange }: UniverseTableProps) {
  const [search, setSearch] = useState("");
  const [dendrogram, setDendrogram] = useState<{ slugs: string[]; tree: DendrogramNode } | null>(null);
  const [dendrogramError, setDendrogramError] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "tree">("table");
  const [message, setMessage] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    fetchDendrogram()
      .then((d) => setDendrogram(d as { slugs: string[]; tree: DendrogramNode }))
      .catch((err) =>
        setDendrogramError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  }, []);

  const filtered = companies.filter(
    (c) =>
      !search ||
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      (c.industry ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const companyBySlug = new Map(companies.map((c) => [c.slug, c]));

  const toggleWatchlist = (company: MapCompany) => {
    const fn = company.short_listed ? removeFromWatchlist : addToWatchlist;
    fn(company.slug)
      .then(() => {
        onCompaniesChange(
          companies.map((c) =>
            c.slug === company.slug ? { ...c, short_listed: !company.short_listed } : c,
          ),
        );
      })
      .catch((err) =>
        setMessage(err instanceof ApiError ? err.message : (err as Error).message),
      );
  };

  // Dendrogram SVG
  let dendrogramSvg: React.ReactNode = null;
  if (view === "tree") {
    if (dendrogramError) {
      dendrogramSvg = <p className="text-sm text-danger">{dendrogramError}</p>;
    } else if (!dendrogram) {
      dendrogramSvg = <p className="text-sm text-muted">Loading dendrogram…</p>;
    } else {
      const nLeaves = dendrogram.slugs.length;
      const svgHeight = nLeaves * ROW_HEIGHT + MARGIN * 2;
      const svgWidth = TREE_WIDTH + LABEL_WIDTH + MARGIN * 2;
      const maxDist = findMaxDistance(dendrogram.tree);
      const root = layout(dendrogram.tree, maxDist, TREE_WIDTH, ROW_HEIGHT, { n: 0 });
      const links: Array<{ px: number; py: number; cx: number; cy: number }> = [];
      collectLinks(root, links);
      const leaves: LayoutNode[] = [];
      collectLeaves(root, leaves);
      const searchLower = search.toLowerCase();

      dendrogramSvg = (
        <div className="overflow-x-auto">
          <svg
            ref={svgRef}
            width={svgWidth}
            height={svgHeight}
            className="text-xs"
            style={{ display: "block" }}
          >
            <g transform={`translate(${MARGIN}, ${MARGIN})`}>
              {/* Links — stepped elbow connectors */}
              {links.map((l, i) => (
                <path
                  key={i}
                  d={`M ${l.cy},${l.cx} H ${l.py} V ${l.px}`}
                  fill="none"
                  stroke="var(--border-subtle)"
                  strokeWidth={0.8}
                />
              ))}
              {/* Leaf labels */}
              {leaves.map((leaf) => {
                const company = companyBySlug.get(leaf.slug ?? "");
                const isWatchlisted = company?.short_listed ?? false;
                const name = company?.name ?? leaf.slug ?? "";
                const isMatch = searchLower && name.toLowerCase().includes(searchLower);
                const truncated = name.length > 22 ? name.slice(0, 21) + "…" : name;
                return (
                  <g key={leaf.slug} transform={`translate(${leaf.y}, ${leaf.x})`}>
                    <circle
                      r={isWatchlisted ? 4 : 2.5}
                      fill={isWatchlisted ? "var(--accent)" : "var(--muted)"}
                    />
                    <text
                      x={7}
                      y={4}
                      fill={isMatch ? "var(--accent)" : isWatchlisted ? "var(--ink)" : "var(--muted)"}
                      fontWeight={isWatchlisted ? "600" : "400"}
                      fontSize={10}
                    >
                      {truncated}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
      );
    }
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex items-center gap-3">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search companies…"
          className="flex-1 rounded-card border border-border-subtle bg-surface px-3 py-1.5 text-sm text-ink placeholder:text-muted"
        />
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setView("table")}
            className={`rounded-card border px-3 py-1 text-xs ${view === "table" ? "border-accent text-accent" : "border-border-subtle text-muted"}`}
          >
            Table
          </button>
          <button
            type="button"
            onClick={() => setView("tree")}
            className={`rounded-card border px-3 py-1 text-xs ${view === "tree" ? "border-accent text-accent" : "border-border-subtle text-muted"}`}
          >
            Tree
          </button>
        </div>
      </div>

      {message ? <p className="text-sm text-danger">{message}</p> : null}

      {view === "table" ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-xs font-medium uppercase tracking-wide text-muted">
                <th className="pb-2 pr-4 font-medium">Company</th>
                <th className="pb-2 pr-4 font-medium">Industry</th>
                <th className="pb-2 pr-4 font-medium">ATS</th>
                <th className="pb-2 font-medium">Watchlist</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 200).map((c) => (
                <tr key={c.slug} className="border-b border-border-subtle last:border-b-0">
                  <td className="py-2 pr-4 text-ink">{c.name}</td>
                  <td className="py-2 pr-4 text-muted">{c.industry ?? "—"}</td>
                  <td className="py-2 pr-4 text-muted">{c.ats_types ?? "—"}</td>
                  <td className="py-2">
                    <button
                      type="button"
                      onClick={() => toggleWatchlist(c)}
                      className={`rounded-card border px-2 py-1 text-xs ${
                        c.short_listed
                          ? "border-danger text-danger"
                          : "border-ok text-ok"
                      }`}
                    >
                      {c.short_listed ? "Remove" : "Add"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length > 200 ? (
            <p className="mt-2 text-xs text-muted">
              Showing 200 of {filtered.length} — search to narrow.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="rounded-card border border-border-subtle bg-surface p-3">
          {dendrogramSvg}
        </div>
      )}
    </div>
  );
}
