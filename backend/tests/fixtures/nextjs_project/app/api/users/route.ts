export function GET() {
  return Response.json([]);
}

export async function POST(request: Request) {
  return Response.json({ ok: true }, { status: 201 });
}
