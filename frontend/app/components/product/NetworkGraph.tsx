"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import usStates from "./us-states-2026.json";
import type { NetworkMap, NetworkNode } from "./types";

function shortNumber(value: number) { return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value); }

type Point = { x: number; y: number };
type StateFeature = {
  properties: { GEOID?: string; STATE?: string; NAME?: string };
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: number[][][] | number[][][][] };
};
type LabelPosition = { x: number; y: number; anchor: "start" | "middle" | "end" };
type MappedNode = NetworkNode & Point;
type MappedDirection = { origin: string; dest: string; total_flights: number };
type MappedConnection = { key: string; origin: string; dest: string; directions: MappedDirection[]; total_flights: number; source: MappedNode; target: MappedNode };

const MAP_WIDTH = 1400;
const MAP_HEIGHT = 790;
const MAP_MAIN_HEIGHT = 650;
const MAP_PADDING = 42;
const STATE_FEATURES = (usStates as unknown as { features: StateFeature[] }).features;
const INSET_POINTS: Record<string, Point> = {
  LIH: { x: 94, y: 732 }, HNL: { x: 130, y: 734 }, OGG: { x: 174, y: 739 }, KOA: { x: 238, y: 744 }, ITO: { x: 254, y: 740 },
  FAI: { x: 1245, y: 710 }, ANC: { x: 1212, y: 735 }, JNU: { x: 1326, y: 748 },
};

// Albers equal-area projection, centered on the contiguous United States.
function albers(longitude: number, latitude: number): Point {
  const radians = Math.PI / 180;
  const phi1 = 29.5 * radians;
  const phi2 = 45.5 * radians;
  const phi0 = 37.5 * radians;
  const lambda0 = -96 * radians;
  const phi = latitude * radians;
  const lambda = longitude * radians;
  const n = (Math.sin(phi1) + Math.sin(phi2)) / 2;
  const c = 1 + Math.sin(phi1) * (2 * n - Math.sin(phi1));
  const rho = Math.sqrt(c - 2 * n * Math.sin(phi)) / n;
  const rho0 = Math.sqrt(c - 2 * n * Math.sin(phi0)) / n;
  const theta = n * (lambda - lambda0);
  return { x: rho * Math.sin(theta), y: rho0 - rho * Math.cos(theta) };
}

function ringsFor(feature: StateFeature): number[][][] {
  return feature.geometry.type === "Polygon"
    ? feature.geometry.coordinates as number[][][]
    : (feature.geometry.coordinates as number[][][][]).flat();
}

function placeLabels(nodes: MappedNode[]): Map<string, LabelPosition> {
  const candidates: Array<{ dx: number; dy: number; anchor: LabelPosition["anchor"] }> = [
    { dx: 12, dy: -9, anchor: "start" }, { dx: 12, dy: 14, anchor: "start" },
    { dx: -12, dy: -9, anchor: "end" }, { dx: -12, dy: 14, anchor: "end" },
    { dx: 0, dy: -19, anchor: "middle" }, { dx: 0, dy: 24, anchor: "middle" },
    { dx: 23, dy: -17, anchor: "start" }, { dx: 23, dy: 20, anchor: "start" },
    { dx: -23, dy: -17, anchor: "end" }, { dx: -23, dy: 20, anchor: "end" },
    { dx: 0, dy: -34, anchor: "middle" }, { dx: 0, dy: 39, anchor: "middle" },
  ];
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  const result = new Map<string, LabelPosition>();
  const prioritized = [...nodes].sort((a, b) => b.total_flights - a.total_flights);

  for (const node of prioritized) {
    const options = candidates.map((candidate) => {
      const x = node.x + candidate.dx;
      const y = node.y + candidate.dy;
      const left = candidate.anchor === "start" ? x : candidate.anchor === "end" ? x - 22 : x - 11;
      const right = left + 22;
      const top = y - 10;
      const bottom = y + 3;
      const outside = left < 8 || right > MAP_WIDTH - 8 || top < 8 || bottom > MAP_HEIGHT - 8;
      const overlaps = occupied.filter((box) => left < box.right + 3 && right + 3 > box.left && top < box.bottom + 2 && bottom + 2 > box.top).length;
      return { position: { x, y, anchor: candidate.anchor }, box: { left, right, top, bottom }, cost: (outside ? 1000 : 0) + overlaps * 100 + Math.abs(candidate.dx) + Math.abs(candidate.dy) * 0.3 };
    }).sort((a, b) => a.cost - b.cost);
    const choice = options[0];
    occupied.push(choice.box);
    result.set(node.airport, choice.position);
  }
  return result;
}

function airportRadius(flights: number, selected: boolean) {
  return selected ? 8 : Math.max(4.2, Math.min(7.2, 2.5 + Math.log10(Math.max(1, flights)) / 2));
}

export function NetworkGraph({ data, onSelect }: { data: NetworkMap; onSelect?: (airport: string) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedPair, setSelectedPair] = useState<string | null>(null);
  const { states, nodes, connections, labels } = useMemo(() => {
    const projectedStates = STATE_FEATURES.map((feature) => ({
      id: feature.properties.GEOID ?? feature.properties.STATE ?? feature.properties.NAME ?? "state",
      name: feature.properties.NAME ?? "State",
      rings: ringsFor(feature).map((ring) => ring.map(([longitude, latitude]) => albers(longitude, latitude))),
    }));
    const boundaryPoints = projectedStates.flatMap((feature) => feature.rings.flat());
    const minX = Math.min(...boundaryPoints.map((point) => point.x));
    const maxX = Math.max(...boundaryPoints.map((point) => point.x));
    const minY = Math.min(...boundaryPoints.map((point) => point.y));
    const maxY = Math.max(...boundaryPoints.map((point) => point.y));
    const scale = Math.min((MAP_WIDTH - MAP_PADDING * 2) / (maxX - minX), (MAP_MAIN_HEIGHT - MAP_PADDING * 2) / (maxY - minY));
    const offsetX = (MAP_WIDTH - (maxX - minX) * scale) / 2;
    const offsetY = (MAP_MAIN_HEIGHT - (maxY - minY) * scale) / 2;
    const screen = (point: Point): Point => ({ x: offsetX + (point.x - minX) * scale, y: offsetY + (maxY - point.y) * scale });
    const pathFor = (rings: Point[][]) => rings.map((ring) => ring.map((point, index) => {
      const projected = screen(point);
      return `${index === 0 ? "M" : "L"}${projected.x.toFixed(1)},${projected.y.toFixed(1)}`;
    }).join(" ") + " Z").join(" ");
    const states = projectedStates.map((feature) => ({ id: feature.id, name: feature.name, d: pathFor(feature.rings) }));
    // The state layer is for the contiguous U.S. Keep out-of-frame airport
    // coordinates out of the projection rather than drawing them at infinity.
    const nodes: MappedNode[] = data.nodes.flatMap((node) => {
      // Alaska and Hawaii are drawn in labelled location insets; their
      // schematic positions keep those routes visible without distorting the
      // contiguous-state projection.
      const projected = INSET_POINTS[node.airport] ?? screen(albers(node.longitude, node.latitude));
      const inside = projected.x >= 0 && projected.x <= MAP_WIDTH && projected.y >= 0 && projected.y <= MAP_HEIGHT;
      return inside ? [{ ...node, ...projected }] : [];
    });
    const lookup = new Map(nodes.map((node) => [node.airport, node]));
    const pairs = new Map<string, { origin: string; dest: string; total_flights: number; directions: Map<string, MappedDirection> }>();
    for (const edge of data.edges) {
      const [origin, dest] = [edge.origin, edge.dest].sort();
      const key = `${origin}-${dest}`;
      const existing = pairs.get(key);
      if (existing) {
        existing.total_flights += edge.total_flights;
        const directionKey = `${edge.origin}-${edge.dest}`;
        const direction = existing.directions.get(directionKey);
        if (direction) direction.total_flights += edge.total_flights;
        else existing.directions.set(directionKey, { origin: edge.origin, dest: edge.dest, total_flights: edge.total_flights });
      } else pairs.set(key, { origin, dest, total_flights: edge.total_flights, directions: new Map([[`${edge.origin}-${edge.dest}`, { origin: edge.origin, dest: edge.dest, total_flights: edge.total_flights }]]) });
    }
    const connections: MappedConnection[] = [...pairs.values()].flatMap((edge) => {
      const source = lookup.get(edge.origin);
      const target = lookup.get(edge.dest);
      return source && target ? [{ ...edge, key: `${edge.origin}-${edge.dest}`, directions: [...edge.directions.values()], source, target }] : [];
    });
    return { states, nodes, connections, labels: placeLabels(nodes) };
  }, [data]);

  const active = selected ? nodes.find((node) => node.airport === selected) : null;
  const activePair = selectedPair ? connections.find((connection) => connection.key === selectedPair) : null;
  const alaskaAirports = nodes.filter((node) => ["ANC", "FAI", "JNU"].includes(node.airport));
  return <div className="network-map">
    <svg viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="group" aria-label="U.S. route map with selectable airports and connections; Alaska and Hawaii are shown in schematic insets">
      <title>Airline routes on U.S. state geography with Alaska and Hawaii insets</title>
      <rect width={MAP_WIDTH} height={MAP_HEIGHT} fill="#eaf1f3" />
      <g aria-hidden="true" className="network-state-layer">{states.map((state) => <path key={state.id} className="network-state" d={state.d} fillRule="evenodd"><title>{state.name}</title></path>)}</g>
      <g>{connections.map((connection) => {
        const related = selected && (connection.origin === selected || connection.dest === selected);
        const activeRoute = selectedPair === connection.key;
        const muted = Boolean(selected || selectedPair) && !related && !activeRoute;
        const line = `M ${connection.source.x} ${connection.source.y} L ${connection.target.x} ${connection.target.y}`;
        return <g key={connection.key} className="network-route-choice" role="button" tabIndex={0} aria-label={`Select route connection ${connection.origin} to ${connection.dest}`} aria-pressed={activeRoute} onClick={() => { setSelectedPair(connection.key); setSelected(null); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedPair(connection.key); setSelected(null); } }}>
          <path className={`network-edge-hit${activeRoute ? " is-selected" : ""}`} d={line} />
          <path className={`network-edge${related ? " is-related" : ""}${activeRoute ? " is-selected" : ""}${muted ? " is-muted" : ""}`} d={line} strokeWidth={Math.min(4.2, 0.8 + Math.log10(Math.max(1, connection.total_flights)) / 2.3)}><title>{connection.directions.map((direction) => `${direction.origin} → ${direction.dest}`).join(" and ")}: ${shortNumber(connection.total_flights)} flights shown as one airport-pair connection. Select for directional profiles.</title></path>
        </g>;
      })}</g>
      <g className="network-insets" aria-label="Alaska and Hawaii location insets, schematic and not to scale">
        <rect className="network-inset-panel" x="26" y="674" width="274" height="94" rx="8" />
        <text className="network-inset-title" x="42" y="694">HAWAII · LOCATION INSET</text>
        <path className="network-inset-land" d="M64 727 C69 720 76 720 80 725 C79 731 73 734 67 733 Z M94 724 C102 718 113 719 118 726 C117 732 108 735 99 732 Z M129 728 C137 724 145 725 149 731 C146 736 138 737 131 734 Z M157 730 C164 725 173 727 177 733 C174 738 165 739 159 736 Z M192 732 C201 727 211 729 215 736 C213 742 204 744 196 740 Z M229 737 C239 731 251 734 258 742 C254 750 243 753 234 748 Z" />
        <rect className="network-inset-panel" x="1098" y="674" width="274" height="94" rx="8" />
        <text className="network-inset-title" x="1114" y="694">ALASKA · LOCATION INSET</text>
        <path className="network-inset-land" d="M1123 723 L1137 711 L1154 714 L1167 704 L1182 710 L1195 707 L1207 716 L1222 713 L1236 722 L1256 719 L1271 729 L1292 729 L1309 740 L1329 743 L1345 751 L1331 758 L1308 754 L1292 761 L1273 754 L1255 762 L1239 753 L1223 758 L1209 747 L1190 750 L1176 740 L1158 745 L1143 737 L1128 738 Z" />
        <path className="network-inset-islands" d="M1120 741 L1112 744 M1113 745 L1106 748 M1106 749 L1100 751" />
        <text className="network-inset-note" x="1114" y="761">{alaskaAirports.length ? `${alaskaAirports.length} mapped airports · select a dot` : "No Alaska airports in this route slice"}</text>
      </g>
      {nodes.map((node) => {
        const label = labels.get(node.airport)!;
        const connector = Math.hypot(label.x - node.x, label.y - node.y) > 22;
        return <a key={node.airport} href={`/airports/${node.airport}`} aria-label={`Open ${node.airport} airport profile`} onMouseEnter={() => { setSelected(node.airport); setSelectedPair(null); }} onFocus={() => { setSelected(node.airport); setSelectedPair(null); }} onMouseLeave={() => setSelected(null)} onBlur={() => setSelected(null)} onClick={() => onSelect?.(node.airport)}>
          <title>{node.airport}: {shortNumber(node.total_flights)} flights in this compact view; select to open its airport profile</title>
          {connector && <line className="network-label-connector" x1={node.x} y1={node.y} x2={label.x} y2={label.y - 3} />}
          <circle className="network-node" cx={node.x} cy={node.y} r={airportRadius(node.total_flights, selected === node.airport)} />
          <circle cx={node.x} cy={node.y} r="15" fill="transparent" />
          <text className="network-airport-label" x={label.x} y={label.y} textAnchor={label.anchor}>{node.airport}</text>
        </a>;
      })}
    </svg>
    <div className="network-tooltip" aria-live="polite">{active ? <><b>{active.airport}</b> {active.airport === "HNL" ? "is shown in the Hawaii inset" : "is plotted at its airport coordinates"}; its connected route lines are highlighted. Select it to open the airport profile.</> : activePair ? <><b>{activePair.origin} ↔ {activePair.dest}</b> · {shortNumber(activePair.total_flights)} flights across the mapped period. Open a directional record: {activePair.directions.map((direction) => <Link key={`${direction.origin}-${direction.dest}`} href={`/routes/${direction.origin}-${direction.dest}`}>{direction.origin} → {direction.dest}</Link>)}.</> : <>Contiguous U.S. state geography, with Alaska and Hawaii location insets. <b>{connections.length} airport-pair connections</b> are selectable from {data.coverage.routes_mapped} high-volume directional BTS routes. Select a dot for an airport profile or a line for directional route profiles; insets are schematic and not to scale.</>}</div>
  </div>;
}

export function MapPanel({ data }: { data: NetworkMap }) { return <NetworkGraph data={data} />; }
