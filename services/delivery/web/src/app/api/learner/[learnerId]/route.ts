import { NextResponse } from "next/server";
import { getLearnerMemory, getMemoryStore, toLearnerProfile } from "@/lib/memory";
import { isAuthorized } from "@/lib/apiAuth";

interface RouteContext {
  params: Promise<{ learnerId: string }>;
}

/** Contract A(2) profile endpoint consumed by the personalization service. */
export async function GET(request: Request, { params }: RouteContext) {
  if (!isAuthorized(request)) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { learnerId } = await params;
  if (!learnerId) {
    return NextResponse.json({ error: "learnerId is required." }, { status: 400 });
  }

  try {
    const memory = await getLearnerMemory(learnerId);
    const profile = toLearnerProfile(memory);

    if (new URL(request.url).searchParams.get("include") === "sessions") {
      const sessions = await getMemoryStore().listSessions(learnerId);
      return NextResponse.json({ ...profile, sessions });
    }

    return NextResponse.json(profile);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json(
      { error: "Could not load learner memory.", detail: message },
      { status: 503 },
    );
  }
}
