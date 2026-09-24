import { redirect } from "next/navigation";

// Keep old bookmarks working, but send the redundant public Explore route to
// the overview. The researcher object explorer remains at /research/explore.
export default function Page() {
  redirect("/");
}
