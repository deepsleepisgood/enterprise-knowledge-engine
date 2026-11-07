/**
 * Main column + right rail. At lg and up the rail is a sticky, internally scrolling
 * column on the right; below lg it stacks under the main column as its own section.
 */
export function PageColumns({
  main,
  rail,
  railLabel,
}: {
  main: React.ReactNode;
  rail: React.ReactNode;
  railLabel: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col lg:flex-row">
      <main className="min-w-0 flex-1 px-4 pb-16 pt-6 sm:px-6 md:pt-10 lg:px-10">
        <div className="mx-auto w-full max-w-[760px]">{main}</div>
      </main>
      <aside
        aria-label={railLabel}
        className="min-w-0 border-t border-hairline bg-canvas px-4 py-6 sm:px-6 lg:sticky lg:top-0 lg:h-screen lg:w-[320px] lg:shrink-0 lg:overflow-y-auto lg:border-l lg:border-t-0 lg:bg-surface lg:px-5 xl:w-[360px]"
      >
        {rail}
      </aside>
    </div>
  );
}
