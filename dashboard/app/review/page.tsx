import { Suspense } from "react";
import { ReviewView } from "@/components/review/ReviewView";
import { LoadingState } from "@/components/ui/Panel";

export const metadata = { title: "Hold queue" };
export default function ReviewPage() {
  return <Suspense fallback={<LoadingState label="Loading hold queue" />}><ReviewView /></Suspense>;
}
