"use client";

import { useParams } from "next/navigation";
import { PublicAirportProfile } from "../../components/product/PublicProfiles";

export default function AirportProfilePage() {
  const params = useParams<{ code: string }>();
  return <PublicAirportProfile airport={(params.code ?? "").toUpperCase()} />;
}
