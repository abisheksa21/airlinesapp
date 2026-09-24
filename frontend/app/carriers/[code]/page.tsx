"use client";

import { useParams } from "next/navigation";
import { PublicCarrierProfile } from "../../components/product/PublicProfiles";

export default function CarrierProfilePage() {
  const params = useParams<{ code: string }>();
  return <PublicCarrierProfile carrier={(params.code ?? "").toUpperCase()} />;
}
