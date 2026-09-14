import { useEffect, useMemo, useRef, useState } from "react";

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
  x: number;     // vertical position in SVG (row-based)
  y: number;     // horizontal position in SVG (depth from root)
  path: string;  // stable key: root="", left="l", right="r", recursive
  slug?: string; // set for leaves; "__collapsed:<path>" for collapsed subtrees
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

// Prune tree to only include leaf slugs in `keep`. Returns null if the subtree
// has no matching leaves. Internal nodes with one pruned child are collapsed to
// their remaining child (no phantom branch).
function pruneTree(node: DendrogramNode, keep: Set<string>): DendrogramNode | null {
  if (isLeaf(node)) return keep.has(node.slug) ? node : null;
  const left = pruneTree(node.left, keep);
  const right = pruneTree(node.right, keep);
  if (!left && !right) return null;
  if (!left) return right;
  if (!right) return left;
  return { ...node, left, right };
}

// Layout assigns SVG positions. `collapsed` uses path keys so that collapsing a
// node stops position slots being allocated for its children, eliminating gaps.
// y formula: treeWidth * (1 - distance/maxDist) puts the root at x=0 (leftmost)
// and leaf-level merges near x=treeWidth (rightmost), matching standard dendrograms.
function layout(
  node: DendrogramNode,
  path: string,
  maxDist: number,
  treeWidth: number,
  rowHeight: number,
  counter: { n: number },
  collapsed: Set<string>,
): LayoutNode {
  if (isLeaf(node)) {
    const x = counter.n * rowHeight + rowHeight / 2;
    counter.n++;
    return { x, y: treeWidth, slug: node.slug, path };
  }
  // Collapsed internal node: occupies one row like a leaf, placed at its depth
  if (collapsed.has(path)) {
    const x = counter.n * rowHeight + rowHeight / 2;
    counter.n++;
    const y = maxDist > 0 ? treeWidth * (1 - node.distance / maxDist) : 0;
    return { x, y, slug: `__collapsed:${path}`, path };
  }
  const left = layout(node.left, path + "l", maxDist, treeWidth, rowHeight, counter, collapsed);
  const right = layout(node.right, path + "r", maxDist, treeWidth, rowHeight, counter, collapsed);
  const y = maxDist > 0 ? treeWidth * (1 - node.distance / maxDist) : 0;
  return { x: (left.x + right.x) / 2, y, left, right, path };
}

function collectLinks(node: LayoutNode): Array<{ px: number; py: number; cx: number; cy: number }> {
  if (!node.left || !node.right) return [];
  return [
    { px: node.x, py: node.y, cx: node.left.x, cy: node.left.y },
    { px: node.x, py: node.y, cx: node.right.x, cy: node.right.y },
    ...collectLinks(node.left),
    ...collectLinks(node.right),
  ];
}

function collectLeaves(node: LayoutNode): LayoutNode[] {
  if (node.slug !== undefined) return [node];
  return [
    ...(node.left ? collectLeaves(node.left) : []),
    ...(node.right ? collectLeaves(node.right) : []),
  ];
}

function collectInternalNodes(node: LayoutNode): LayoutNode[] {
  if (node.slug !== undefined) return [];
  return [
    node,
    ...(node.left ? collectInternalNodes(node.left) : []),
    ...(node.right ? collectInternalNodes(node.right) : []),
  ];
}

// --- Component ---

const ROW_HEIGHT = 16;
const TREE_WIDTH = 400;
const LABEL_WIDTH = 180;
const MARGIN = 10;

export default function UniverseTable({ companies, onCompaniesChange }: UniverseTableProps) {
  const [search, setSearch] = useState("");
  const [industryFilter, setIndustryFilter] = useState("");
  const [dendrogram, setDendrogram] = useState<{ slugs: string[]; tree: DendrogramNode } | null>(null);
  const [dendrogramError, setDendrogramError] = useState<string | null>(null);
  const [view, setView] = useState<"table" | "tree">("tree");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const industries = useMemo(() => {
    const set = new Set<string>();
    companies.forEach((c) => { if (c.industry) set.add(c.industry); });
    return Array.from(set).sort();
  }, [companies]);

  useEffect(() => {
    fetchDendrogram()
      .then((d) => setDendrogram(d as { slugs: string[]; tree: DendrogramNode }))
      .catch((err) =>
        setDendrogramError(err instanceof ApiError ? err.message : (err as Error).message),
      );
  }, []);

  // Search highlights in tree; industry filter prunes the tree.
  // Reset collapse state when the industry filter changes so stale paths don't linger.
  useEffect(() => { setCollapsed(new Set()); }, [industryFilter]);

  // Table uses both filters.
  const filtered = useMemo(
    () =>
      companies.filter((c) => {
        const nameOk = !search || c.name.toLowerCase().includes(search.toLowerCase());
        const industryOk = !industryFilter || (c.industry ?? "") === industryFilter;
        return nameOk && industryOk;
      }),
    [companies, search, industryFilter],
  );

  // Tree prunes by industry only; search is shown as highlight so context is preserved.
  const prunedTree = useMemo(() => {
    if (!dendrogram) return null;
    if (!industryFilter) return dendrogram.tree;
    const keep = new Set(
      companies.filter((c) => !industryFilter || (c.industry ?? "") === industryFilter).map((c) => c.slug),
    );
    return pruneTree(dendrogram.tree, keep);
  }, [dendrogram, companies, industryFilter]);

  const companyBySlug = useMemo(() => new Map(companies.map((c) => [c.slug, c])), [companies]);

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
    } else if (!prunedTree) {
      dendrogramSvg = <p className="text-sm text-muted">No companies match this filter.</p>;
    } else {
      const maxDist = findMaxDistance(prunedTree);
      const root = layout(prunedTree, "", maxDist, TREE_WIDTH, ROW_HEIGHT, { n: 0 }, collapsed);
      const links = collectLinks(root);
      const leaves = collectLeaves(root);
      const internalNodes = collectInternalNodes(root);
      const nLeaves = leaves.length;
      const svgHeight = nLeaves * ROW_HEIGHT + MARGIN * 2;
      const svgWidth = TREE_WIDTH + LABEL_WIDTH + MARGIN * 2;
      const searchLower = search.toLowerCase();

      const toggleCollapse = (path: string) => {
        setCollapsed((prev) => {
          const next = new Set(prev);
          if (next.has(path)) next.delete(path); else next.add(path);
          return next;
        });
      };

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
              {/* Stepped elbow connectors */}
              {links.map((l, i) => (
                <path
                  key={i}
                  d={`M ${l.cy},${l.cx} H ${l.py} V ${l.px}`}
                  fill="none"
                  stroke="var(--muted)"
                  strokeWidth={1}
                />
              ))}
              {/* Internal node collapse handles */}
              {internalNodes.map((node) => {
                const isCollapsed = collapsed.has(node.path);
                return (
                  <g
                    key={node.path}
                    transform={`translate(${node.y}, ${node.x})`}
                    onClick={() => toggleCollapse(node.path)}
                    style={{ cursor: "pointer" }}
                  >
                    <circle r={4} fill="var(--surface)" stroke="var(--muted)" strokeWidth={1} />
                    <text x={-3} y={4} fontSize={8} fill="var(--muted)" style={{ userSelect: "none" }}>
                      {isCollapsed ? "+" : "−"}
                    </text>
                  </g>
                );
              })}
              {/* Leaf labels */}
              {leaves.map((leaf) => {
                const isCollapsedNode = leaf.slug?.startsWith("__collapsed:");
                if (isCollapsedNode) {
                  const path = leaf.slug!.slice("__collapsed:".length);
                  return (
                    <g
                      key={leaf.slug}
                      transform={`translate(${leaf.y}, ${leaf.x})`}
                      onClick={() => toggleCollapse(path)}
                      style={{ cursor: "pointer" }}
                    >
                      <circle r={4} fill="var(--muted)" stroke="var(--muted)" strokeWidth={1} />
                      <text x={8} y={4} fontSize={10} fill="var(--muted)">[collapsed group]</text>
                    </g>
                  );
                }
                const company = companyBySlug.get(leaf.slug ?? "");
                const isWatchlisted = company?.short_listed ?? false;
                const name = company?.name ?? leaf.slug ?? "";
                const isMatch = !!searchLower && name.toLowerCase().includes(searchLower);
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
        <select
          value={industryFilter}
          onChange={(e) => setIndustryFilter(e.target.value)}
          className="max-w-[180px] rounded-card border border-border-subtle bg-surface px-2 py-1.5 text-sm text-ink"
        >
          <option value="">All industries</option>
          {industries.map((ind) => (
            <option key={ind} value={ind}>{ind}</option>
          ))}
        </select>
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
