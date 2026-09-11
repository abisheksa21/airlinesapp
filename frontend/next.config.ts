import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Allow a second local Next app to run beside another project without
  // contending for the same development lockfile.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  // Keep production builds usable on small CI/deployment workers. The
  // default parallel page workers made this 16-route app peak above the
  // available memory in constrained environments even after compilation
  // and type-checking had already succeeded.
  experimental: {
    cpus: 1,
  },
  // Explicitly pins the workspace root to this frontend/ folder. Without
  // this, Next.js guesses based on nearby lockfiles -- a real build log
  // showed it finding a stray root-level package-lock.json (a leftover
  // from an earlier project layout, not part of this repo's current
  // structure) alongside the real one in frontend/, and warning about the
  // ambiguity. Matters beyond local dev too: Vercel's build uses the same
  // detection logic, so this same ambiguity could affect a deployed build,
  // not just `next dev`.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
