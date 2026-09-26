import { Suspense } from "react";
import { TreasuryView } from "@/components/treasury/TreasuryView";
import { LoadingState } from "@/components/ui/Panel";

export const metadata = { title: "Treasury" };
export default function TreasuryPage() {
  return <Suspense fallback={<LoadingState label="Loading treasury" />}><TreasuryView /></Suspense>;
}
