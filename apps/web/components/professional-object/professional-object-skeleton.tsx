import styles from "./professional-object-shell.module.css";

function Skeleton({ className }: { className: string }) {
  return <span className={`workspace-skeleton block ${className}`} aria-hidden />;
}

export function ProfessionalObjectSkeleton() {
  return (
    <main className={`workspace-main ${styles.page}`} aria-busy="true" aria-label="Loading professional record">
      <div className={styles.layout}>
        <header className={styles.header}>
          <Skeleton className="h-4 w-44" />
          <Skeleton className="mt-4 h-9 w-[min(38rem,90%)]" />
          <Skeleton className="mt-4 h-7 w-24 rounded-full" />
          <Skeleton className="mt-5 h-5 w-[min(34rem,80%)]" />
        </header>
        <section className={`${styles.content} ${styles.contentSurface}`}>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="mt-5 h-4 w-full" />
          <Skeleton className="mt-3 h-4 w-[92%]" />
          <Skeleton className="mt-3 h-4 w-[74%]" />
        </section>
        <div className={styles.mobileInspectorControl} aria-hidden>
          <Skeleton className="h-11 w-full sm:w-64" />
        </div>
        <aside className={styles.desktopInspector} aria-hidden>
          <Skeleton className="h-5 w-24" />
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className="mt-4 border-b border-[var(--pv-divider)] pb-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-2 h-4 w-full" />
            </div>
          ))}
        </aside>
      </div>
      <span className="sr-only">Loading professional record…</span>
    </main>
  );
}
