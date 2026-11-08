import { Suspense } from "react";

import { AskView } from "@/components/ask/AskView";

export default function AskPage() {
  return (
    <Suspense>
      <AskView />
    </Suspense>
  );
}
