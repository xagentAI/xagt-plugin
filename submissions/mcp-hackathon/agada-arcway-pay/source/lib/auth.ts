import { Prisma } from "@prisma/client";
import type { Company, User } from "@prisma/client";
import { PrivyClient } from "@privy-io/server-auth";
import { prisma } from "./prisma";
import { isPrivyConfigured } from "./privy";

/**
 * Server-side request authentication.
 *
 * Every non-public API route runs a request through here before touching
 * data. The client sends the Privy access token as `Authorization: Bearer
 * <token>`; this module verifies that token's signature against Privy's
 * verification key, resolves it to our own `User` row, and hands the caller
 * the company that user is allowed to act for.
 *
 * The company on the returned context is the ONLY company a request may read
 * or write. Routes must pass it into every store call rather than trusting
 * anything in the request body — a caller can put any companyId in a payload,
 * but cannot forge a signed token.
 */

export class AuthError extends Error {
  readonly status: number;
  constructor(message: string, status = 401) {
    super(message);
    this.name = "AuthError";
    this.status = status;
  }
}

let cachedClient: PrivyClient | null = null;

function getPrivyClient(): PrivyClient {
  if (!cachedClient) {
    cachedClient = new PrivyClient(
      process.env.PRIVY_APP_ID as string,
      process.env.PRIVY_APP_SECRET as string
    );
  }
  return cachedClient;
}

function bearerToken(request: Request): string {
  const header = request.headers.get("authorization") ?? "";
  const [scheme, token] = header.split(" ");
  if (!/^Bearer$/i.test(scheme ?? "") || !token) {
    throw new AuthError("Missing bearer token.");
  }
  return token;
}

export interface VerifiedIdentity {
  privyUserId: string;
  email: string | null;
}

/**
 * Verifies the request's access token and resolves the caller's Privy
 * identity. Does not touch our database.
 */
export async function verifyIdentity(request: Request): Promise<VerifiedIdentity> {
  if (!isPrivyConfigured) {
    // No credentials means no way to verify a signature, so there is no such
    // thing as an authenticated request. Deny rather than degrade open —
    // mock mode is for the capability endpoint, not for the dashboard.
    throw new AuthError("Authentication is not configured on this server.");
  }

  const token = bearerToken(request);
  const privy = getPrivyClient();

  let privyUserId: string;
  try {
    const claims = await privy.verifyAuthToken(token);
    privyUserId = claims.userId;
  } catch {
    throw new AuthError("Invalid or expired access token.");
  }

  // The token proves who they are but carries no email, and the routing rules
  // in Phase 1 match payees by email — so fetch the linked address.
  let email: string | null = null;
  try {
    const privyUser = await privy.getUserById(privyUserId);
    email = privyUser.email?.address?.toLowerCase() ?? null;
  } catch {
    // A verified token with an unreadable profile is still a valid identity;
    // callers that need the email handle null themselves.
  }

  return { privyUserId, email };
}

export interface AuthContext {
  user: User;
  /** Null for payees, who belong to no company of their own. */
  company: Company | null;
  email: string | null;
}

/**
 * Verifies the request and resolves it to an existing account.
 *
 * Throws 401 when the token is missing, invalid, or belongs to somebody who
 * has not finished signing up — a Privy identity with no `User` row is
 * authenticated but has no account here yet, and must go through
 * `/api/session` before it can reach data.
 */
export async function requireAuth(request: Request): Promise<AuthContext> {
  const { privyUserId, email } = await verifyIdentity(request);

  const user = await prisma.user.findUnique({
    where: { privyUserId },
    include: { company: true },
  });

  if (!user) {
    throw new AuthError("No account for this identity yet.");
  }

  return { user, company: user.company ?? null, email };
}

export interface EmployerContext {
  user: User;
  company: Company;
}

/**
 * The guard for every employer data route.
 *
 * ACCESS IS GRANTED BY CAPABILITY, NOT BY ROLE. Having a company is what makes
 * someone an employer here; `User.role` only decides where sign-in sends them
 * by default. Checking the role as well would lock out anyone whose role field
 * disagrees with their actual relationships — and those two drift apart easily,
 * because a role is assigned once at first sign-in while relationships keep
 * changing afterwards.
 */
export async function requireEmployer(request: Request): Promise<EmployerContext> {
  const { user, company } = await requireAuth(request);

  if (!company) {
    throw new AuthError("This account isn't set up with a company yet.", 403);
  }

  return { user, company };
}

/** Turns an AuthError into its JSON response; rethrows anything else. */
export function authErrorResponse(err: unknown): Response | null {
  if (err instanceof AuthError) {
    return Response.json({ error: err.message }, { status: err.status });
  }
  return null;
}

export interface PayeeContext {
  user: User;
  privyUserId: string;
  /** Always present: a payee is resolved by email as well as by Privy id. */
  email: string;
}

/**
 * The guard for every /api/claim/* route.
 *
 * Scoped to the PERSON, not to a company — the mirror image of
 * `requireEmployer`. It returns the identity that person-scoped store queries
 * union across companies with, so a contractor paid by two clients sees both.
 *
 * ACCESS IS GRANTED BY HAVING PAYEE ROWS, NOT BY ROLE. An earlier version
 * refused anyone whose `User.role` was not PAYEE, which locked real people out
 * of their own money: `/api/session` assigns EMPLOYER to any email that signs
 * in before it appears on a payroll, so a contractor who visited the site once
 * out of curiosity could never claim afterwards. Somebody can legitimately run
 * a company AND be paid by another one; both surfaces must stay open to them.
 */
export async function requirePayee(request: Request): Promise<PayeeContext> {
  const { privyUserId, email } = await verifyIdentity(request);

  const resolved = email?.toLowerCase();
  if (!resolved) {
    throw new AuthError("This account has no email address linked.", 403);
  }

  // Deliberately NOT via requireAuth: that throws when no `User` row exists,
  // which is the normal state of a payee arriving for the first time. The
  // claim link in the notification email goes straight to /claim, so
  // /api/session — the only other place that creates a payee's User row —
  // never runs. Requiring it here locked people out of their own money with
  // "No account for this identity yet".
  const paid = await prisma.payee.findFirst({
    where: { OR: [{ privyUserId }, { email: resolved }] },
    select: { id: true },
  });

  if (!paid) {
    throw new AuthError("No payments have been sent to this email address.", 403);
  }

  let user = await prisma.user.findUnique({
    where: { privyUserId },
    include: { company: true },
  });

  if (!user) {
    // Same rule as /api/session case (b), applied where it is actually
    // needed. Being paid is what entitles someone to an account here.
    try {
      user = await prisma.user.create({
        data: { privyUserId, email: resolved, role: "PAYEE" },
        include: { company: true },
      });
    } catch (err) {
      // Two tabs racing on the same first sign-in: whichever lost the unique
      // constraint just reads the row the other created.
      if (
        err instanceof Prisma.PrismaClientKnownRequestError &&
        err.code === "P2002"
      ) {
        user = await prisma.user.findUnique({
          where: { privyUserId },
          include: { company: true },
        });
      } else {
        throw err;
      }
    }
  }

  if (!user) {
    throw new AuthError("Could not resolve this account.", 403);
  }

  return { user, privyUserId: user.privyUserId, email: resolved };
}

/**
 * What this identity may reach, derived from relationships rather than role.
 * Used by /api/session so the client can route without guessing.
 */
export async function resolveCapabilities(
  privyUserId: string,
  email: string | null
): Promise<{ canUseDashboard: boolean; canUseClaim: boolean }> {
  const clauses: { privyUserId?: string; email?: string }[] = [{ privyUserId }];
  if (email) clauses.push({ email: email.toLowerCase() });

  const [user, paid] = await Promise.all([
    prisma.user.findUnique({ where: { privyUserId }, select: { companyId: true } }),
    prisma.payee.findFirst({ where: { OR: clauses }, select: { id: true } }),
  ]);

  return { canUseDashboard: Boolean(user?.companyId), canUseClaim: Boolean(paid) };
}
