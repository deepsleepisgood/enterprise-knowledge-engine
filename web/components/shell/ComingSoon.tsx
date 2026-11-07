import { PageColumns } from "./PageColumns";

/** Placeholder for pages built in later phases, kept in the same shell. */
export function ComingSoon({ title, phase, children }: { title: string; phase: string; children: React.ReactNode }) {
  return (
    <PageColumns
      railLabel={`${title} filters`}
      main={
        <>
          <p className="eyebrow">{phase}</p>
          <h1 className="mt-3 font-display text-2xl font-bold leading-tight text-ink md:text-[30px]">{title}</h1>
          <div className="mt-4 max-w-prose text-[15px] leading-[1.65] text-muted">{children}</div>
        </>
      }
      rail={<p className="text-[13px] text-muted">Nothing here yet.</p>}
    />
  );
}
