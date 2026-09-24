import Link from "next/link";

export function ModeSwitcher({ mode }: { mode: "public" | "researcher" }) {
  const target = mode === "public" ? "/research" : "/";
  const label = mode === "public" ? "Researcher View" : "Public View";
  return <Link className="mode-switcher" href={target}><span aria-hidden="true" />{label}<b>↗</b></Link>;
}
