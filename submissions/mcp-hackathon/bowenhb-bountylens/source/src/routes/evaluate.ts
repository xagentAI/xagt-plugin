import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import { extractActivity } from "../extractors/activity.js";
import { extractCompetition } from "../extractors/competition.js";
import { extractReward } from "../extractors/reward.js";
import { extractScope } from "../extractors/scope.js";
import type { GitHubClient } from "../github/client.js";
import { GitHubApiError } from "../github/errors.js";
import { InvalidIssueUrlError, parseIssueUrl } from "../github/parse-issue-url.js";
import { scoreOpportunity } from "../scoring/score.js";
import type { DeveloperProfile, OpportunityScore } from "../scoring/types.js";
import { createErrorResponse } from "../schemas/error.js";
import { evaluateRequestSchema, type EvaluateRequest } from "../schemas/request.js";
import { evaluateResponseSchema, type EvaluateResponse } from "../schemas/response.js";

export type EvaluateRouteDependencies = {
  githubClient: GitHubClient;
  now: () => Date;
};

function toDeveloperProfile(
  profile: NonNullable<EvaluateRequest["developer_profile"]>,
): DeveloperProfile {
  return {
    ...(profile.languages === undefined ? {} : { languages: profile.languages }),
    ...(profile.hourly_rate_usd === undefined
      ? {}
      : { hourlyRateUsd: profile.hourly_rate_usd }),
    ...(profile.max_hours === undefined ? {} : { maxHours: profile.max_hours }),
  };
}

function chooseNextActions(result: OpportunityScore): string[] {
  const actions: string[] = [];
  if (result.dimensions.reward_evidence.score === 0) {
    actions.push("Confirm whether an explicit reward is available before investing implementation time.");
  }
  if (result.dimensions.scope_clarity.score < 60) {
    actions.push("Ask the maintainer to confirm acceptance criteria and the expected test command.");
  }
  if (result.dimensions.competition_pressure.score < 50) {
    actions.push("Review existing assignees, claims, and pull requests before starting work.");
  } else {
    actions.push("Post an implementation claim before starting substantial work.");
  }
  actions.push("Inspect the referenced repository files and reproduce the issue locally.");
  return actions.slice(0, 5);
}

function logEvaluation(
  request: FastifyRequest,
  startedAt: number,
  statusCode: number,
  upstreamStatus: number | null,
  upstreamCode: string | null,
): void {
  request.log.info(
    {
      event: "evaluation.completed",
      requestId: request.id,
      path: request.url,
      statusCode,
      durationMs: Number((performance.now() - startedAt).toFixed(2)),
      upstreamStatus,
      upstreamCode,
    },
    "Evaluation request completed",
  );
}

function sendMappedError(
  error: unknown,
  request: FastifyRequest,
  reply: FastifyReply,
  startedAt: number,
): FastifyReply {
  const upstreamStatus = error instanceof GitHubApiError ? error.status ?? null : null;
  const upstreamCode = error instanceof GitHubApiError ? error.code : null;

  if (error instanceof InvalidIssueUrlError) {
    logEvaluation(request, startedAt, 400, null, null);
    return reply
      .code(400)
      .send(createErrorResponse(request.id, "INVALID_ISSUE_URL", error.message, false));
  }

  if (error instanceof GitHubApiError) {
    if (error.code === "GITHUB_NOT_FOUND") {
      logEvaluation(request, startedAt, 404, upstreamStatus, upstreamCode);
      return reply
        .code(404)
        .send(
          createErrorResponse(
            request.id,
            "ISSUE_NOT_FOUND",
            "The GitHub issue is unavailable or private.",
            false,
          ),
        );
    }

    if (error.code === "GITHUB_RATE_LIMITED") {
      const retryAfter = error.rateLimit?.retryAfterSeconds ?? undefined;
      if (retryAfter !== undefined) reply.header("retry-after", String(retryAfter));
      logEvaluation(request, startedAt, 429, upstreamStatus, upstreamCode);
      return reply
        .code(429)
        .send(
          createErrorResponse(
            request.id,
            "GITHUB_RATE_LIMITED",
            "GitHub API rate limit reached. Try again later.",
            true,
            retryAfter,
          ),
        );
    }

    if (error.code === "GITHUB_TIMEOUT") {
      logEvaluation(request, startedAt, 504, upstreamStatus, upstreamCode);
      return reply
        .code(504)
        .send(
          createErrorResponse(
            request.id,
            "UPSTREAM_TIMEOUT",
            "GitHub did not respond within the configured time limit.",
            true,
          ),
        );
    }
  }

  logEvaluation(request, startedAt, 500, upstreamStatus, upstreamCode);
  return reply
    .code(500)
    .send(
      createErrorResponse(
        request.id,
        "EVALUATION_FAILED",
        "The issue could not be evaluated.",
        false,
      ),
    );
}

/** Register the complete GitHub-to-evidence-to-score evaluation pipeline. */
export function registerEvaluateRoute(
  app: FastifyInstance,
  dependencies: EvaluateRouteDependencies,
): void {
  app.post("/v1/evaluate", async (request, reply) => {
    const startedAt = performance.now();
    const parsed = evaluateRequestSchema.safeParse(request.body);
    if (!parsed.success) {
      logEvaluation(request, startedAt, 400, null, null);
      return reply
        .code(400)
        .send(
          createErrorResponse(
            request.id,
            "INVALID_REQUEST",
            "Request body does not match the evaluation schema.",
            false,
          ),
        );
    }

    try {
      const target = parseIssueUrl(parsed.data.issue_url);
      const context = await dependencies.githubClient.getIssueContext(target, {
        requestId: request.id,
      });
      const reward = extractReward(context);
      const scope = extractScope(context);
      const competition = extractCompetition(context);
      const activity = extractActivity(context, dependencies.now());
      const developerProfile =
        parsed.data.developer_profile === undefined
          ? undefined
          : toDeveloperProfile(parsed.data.developer_profile);
      const result = scoreOpportunity({
        reward,
        scope,
        competition,
        activity,
        repositoryLanguages: context.repository.languages,
        ...(developerProfile === undefined ? {} : { developerProfile }),
      });

      const response: EvaluateResponse = evaluateResponseSchema.parse({
        request_id: request.id,
        issue: {
          url: target.canonicalUrl,
          repository: context.repository.fullName,
          number: target.issueNumber,
          state: context.issue.state,
        },
        decision: result.decision,
        score: result.score,
        confidence: result.confidence,
        estimated_effort: {
          min_hours: result.estimatedEffort.minHours,
          max_hours: result.estimatedEffort.maxHours,
          confidence: result.estimatedEffort.confidence,
        },
        reward: {
          amount: reward.value.amount,
          currency: reward.value.currency,
          evidence: reward.evidence.slice(0, 5),
        },
        dimensions: {
          scope_clarity: result.dimensions.scope_clarity.score,
          reward_evidence: result.dimensions.reward_evidence.score,
          repository_activity: result.dimensions.repository_activity.score,
          maintainer_responsiveness: result.dimensions.maintainer_responsiveness.score,
          technical_fit: result.dimensions.technical_fit.score,
          competition_pressure: result.dimensions.competition_pressure.score,
        },
        evidence: result.evidence.slice(0, 40),
        next_actions: chooseNextActions(result),
        limitations: result.limitations,
      });

      logEvaluation(request, startedAt, 200, 200, null);
      return reply.code(200).send(response);
    } catch (error) {
      return sendMappedError(error, request, reply, startedAt);
    }
  });
}
