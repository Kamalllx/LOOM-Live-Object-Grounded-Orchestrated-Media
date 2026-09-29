import LoomPlayer from "@/components/LoomPlayer";
import { loadVerifiedCut } from "@/lib/loadVerifiedCut";


export default async function Page() {
  try {
    const cut = await loadVerifiedCut();
    return <LoomPlayer cut={cut} />;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <main className="mx-auto flex min-h-dvh max-w-2xl flex-col justify-center gap-4 px-6">
        <h1 className="font-display text-2xl text-mask">This cut can&apos;t be played</h1>
        <p className="text-muted">
          The player loads <code className="text-text">fixtures/verified-cut.sample.json</code> at
          startup. Fix the file below and refresh — nothing else needs restarting.
        </p>
        <pre className="overflow-x-auto rounded-lg border border-line bg-surface p-4 text-sm whitespace-pre-wrap text-mask">
          {message}
        </pre>
      </main>
    );
  }
}
