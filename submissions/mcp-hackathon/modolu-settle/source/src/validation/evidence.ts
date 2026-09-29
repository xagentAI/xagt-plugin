/**
 * HTTP contract for `GET /v1/payment-intents/:id/evidence`: query parsing,
 * the opaque keyset cursor, and the public evidence representation
 * (ARCHITECTURE.md §9 "Evidence pagination").
 */
import { z } from "zod";

import { formatUsdcAmount } from "@/domain/money";
import type { MatchedTransfer, TransferAssociation } from "@/domain/payment-intent";
import { toChecksumAddress } from "@/lib/addresses";
import { AppError } from "@/lib/errors";
import type { EvidenceCursor, EvidencePage } from "@/ports/payment-repository";
import { DEFAULT_EVIDENCE_LIMIT, MAX_EVIDENCE_LIMIT } from "@/services/get-payment-evidence";

const TX_HASH = /^0x[0-9a-f]{64}$/;

/** Wire form of a cursor: base64url of the JSON tuple `[blockNumber, logIndex, txHash]`. */
const cursorTupleSchema = z.tuple([z.string().regex(/^(0|[1-9][0-9]{0,29})$/), z.int().nonnegative(), z.string().regex(TX_HASH)]);

export function encodeEvidenceCursor(cursor: EvidenceCursor): string {
  return Buffer.from(JSON.stringify([cursor.blockNumber.toString(), cursor.logIndex, cursor.txHash]), "utf8").toString(
    "base64url",
  );
}

export function decodeEvidenceCursor(value: string): EvidenceCursor {
  let tuple: unknown;
  try {
    tuple = JSON.parse(Buffer.from(value, "base64url").toString("utf8")) as unknown;
  } catch {
    throw new AppError("VALIDATION_ERROR", "cursor is not a valid evidence cursor");
  }
  const parsed = cursorTupleSchema.safeParse(tuple);
  if (!parsed.success) {
    throw new AppError("VALIDATION_ERROR", "cursor is not a valid evidence cursor");
  }
  const [blockNumber, logIndex, txHash] = parsed.data;
  return { blockNumber: BigInt(blockNumber), logIndex, txHash };
}

export interface EvidenceQuery {
  readonly limit: number;
  readonly cursor: EvidenceCursor | null;
}

/** Parses `?limit=&cursor=`; unknown parameters are ignored. */
export function parseEvidenceQuery(searchParams: URLSearchParams): EvidenceQuery {
  const rawLimit = searchParams.get("limit");
  let limit = DEFAULT_EVIDENCE_LIMIT;
  if (rawLimit !== null && rawLimit !== "") {
    if (!/^[0-9]{1,3}$/.test(rawLimit)) {
      throw new AppError("VALIDATION_ERROR", `limit must be an integer between 1 and ${MAX_EVIDENCE_LIMIT}`);
    }
    limit = Number(rawLimit);
    if (limit < 1 || limit > MAX_EVIDENCE_LIMIT) {
      throw new AppError("VALIDATION_ERROR", `limit must be an integer between 1 and ${MAX_EVIDENCE_LIMIT}`);
    }
  }
  const rawCursor = searchParams.get("cursor");
  const cursor = rawCursor === null || rawCursor === "" ? null : decodeEvidenceCursor(rawCursor);
  return { limit, cursor };
}

/** Public JSON representation of one evidence row. No row IDs, foreign keys, units or block internals. */
export interface EvidenceItemResponse {
  readonly transactionHash: string;
  readonly logIndex: number;
  /** Decimal string: block numbers are `bigint` and never JavaScript numbers. */
  readonly blockNumber: string;
  readonly from: string;
  readonly to: string;
  readonly amount: string;
  readonly confirmations: number;
  readonly blockTimestamp: string;
  readonly association: TransferAssociation;
}

export interface EvidenceResponse {
  readonly evidence: readonly EvidenceItemResponse[];
  readonly nextCursor: string | null;
}

export function toEvidenceItemResponse(transfer: MatchedTransfer): EvidenceItemResponse {
  return {
    transactionHash: transfer.txHash,
    logIndex: transfer.logIndex,
    blockNumber: transfer.blockNumber.toString(),
    from: toChecksumAddress(transfer.fromAddress),
    to: toChecksumAddress(transfer.toAddress),
    amount: formatUsdcAmount(transfer.amountUnits),
    confirmations: transfer.confirmations,
    blockTimestamp: transfer.blockTimestamp.toISOString(),
    association: transfer.association,
  };
}

export function toEvidenceResponse(page: EvidencePage): EvidenceResponse {
  return {
    evidence: page.items.map(toEvidenceItemResponse),
    nextCursor: page.nextCursor === null ? null : encodeEvidenceCursor(page.nextCursor),
  };
}
