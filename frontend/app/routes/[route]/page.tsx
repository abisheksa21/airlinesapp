"use client";

import { useParams } from "next/navigation";
import { PublicRouteProfile } from "../../components/product/PublicProfiles";

export default function RouteProfilePage() {
  const params = useParams<{ route: string }>();
  const [origin = "", destination = ""] = (params.route ?? "").split("-");
  return <PublicRouteProfile origin={origin.toUpperCase()} destination={destination.toUpperCase()} />;
}
