import { redirect } from "next/navigation";

export default async function PublicCopilotRoute({ searchParams }: { searchParams: Promise<{ question?: string }> }) {
  const { question } = await searchParams;
  redirect(question ? `/copilot?question=${encodeURIComponent(question)}` : "/copilot");
}
