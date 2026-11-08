import { Suspense } from "react";

import { EntitiesView } from "@/components/pages/EntitiesView";

export default function Page() {
  return (
    <Suspense>
      <EntitiesView />
    </Suspense>
  );
}
