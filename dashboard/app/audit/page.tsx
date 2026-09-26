import { Suspense } from "react";
import { AuditView } from "@/components/audit/AuditView";
import { LoadingState } from "@/components/ui/Panel";

export const metadata = { title: "Audit log" };
export default function AuditPage() {
  return <Suspense fallback={<LoadingState label="Loading audit log" />}><AuditView /></Suspense>;
}
