import type { Metadata } from "next";
import { CaseView } from "@/components/case/CaseView";

interface CasePageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: CasePageProps): Promise<Metadata> {
  const { id } = await params;
  return { title: `Case ${decodeURIComponent(id)}` };
}

export default async function CasePage({ params }: CasePageProps) {
  const { id } = await params;
  return <CaseView caseId={decodeURIComponent(id)} />;
}
