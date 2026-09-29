const GIT_COMMIT =
  process.env.VERCEL_GIT_COMMIT_SHA ||
  process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA ||
  "c2a44bedd75a16f91da6e7a07787aec8340f40bb";

export async function GET() {
  return Response.json(
    {
      schemaVersion: 1,
      slug: "wisdomdivine-multipu",
      commit: GIT_COMMIT,
    },
    {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=0, must-revalidate",
      },
    }
  );
}
