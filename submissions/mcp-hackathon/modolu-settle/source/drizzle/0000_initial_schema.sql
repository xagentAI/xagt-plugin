CREATE TYPE "public"."match_confidence" AS ENUM('none', 'exact_payer', 'single_sender', 'ambiguous');--> statement-breakpoint
CREATE TYPE "public"."payment_status" AS ENUM('pending', 'detected', 'partial', 'paid', 'overpaid', 'expired', 'ambiguous');--> statement-breakpoint
CREATE TYPE "public"."transfer_association" AS ENUM('matched', 'candidate', 'orphaned');--> statement-breakpoint
CREATE TABLE "matched_transfers" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"payment_intent_id" varchar(40) NOT NULL,
	"tx_hash" varchar(66) NOT NULL,
	"log_index" integer NOT NULL,
	"block_number" bigint NOT NULL,
	"block_hash" varchar(66) NOT NULL,
	"from_address" varchar(42) NOT NULL,
	"to_address" varchar(42) NOT NULL,
	"amount_units" numeric(78, 0) NOT NULL,
	"block_timestamp" timestamp with time zone NOT NULL,
	"association" "transfer_association" NOT NULL,
	"confirmations" integer NOT NULL,
	"first_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	"last_seen_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "matched_transfers_amount_non_negative" CHECK ("matched_transfers"."amount_units" >= 0)
);
--> statement-breakpoint
CREATE TABLE "payment_intents" (
	"id" varchar(40) PRIMARY KEY NOT NULL,
	"account_id" uuid,
	"external_reference" varchar(128),
	"chain" varchar(16) NOT NULL,
	"asset" varchar(16) NOT NULL,
	"token_address" varchar(42) NOT NULL,
	"expected_amount_units" numeric(78, 0) NOT NULL,
	"recipient_address" varchar(42) NOT NULL,
	"payer_address" varchar(42),
	"start_block" bigint NOT NULL,
	"expiry_block" bigint,
	"required_confirmations" smallint DEFAULT 3 NOT NULL,
	"status" "payment_status" DEFAULT 'pending' NOT NULL,
	"received_amount_units" numeric(78, 0) DEFAULT 0 NOT NULL,
	"detected_amount_units" numeric(78, 0) DEFAULT 0 NOT NULL,
	"match_confidence" "match_confidence" DEFAULT 'none' NOT NULL,
	"paid_at" timestamp with time zone,
	"last_reconciled_block" bigint,
	"last_reconciled_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "payment_intents_chain_check" CHECK ("payment_intents"."chain" = 'base'),
	CONSTRAINT "payment_intents_asset_check" CHECK ("payment_intents"."asset" = 'USDC'),
	CONSTRAINT "payment_intents_expected_amount_positive" CHECK ("payment_intents"."expected_amount_units" > 0),
	CONSTRAINT "payment_intents_received_amount_non_negative" CHECK ("payment_intents"."received_amount_units" >= 0),
	CONSTRAINT "payment_intents_detected_amount_non_negative" CHECK ("payment_intents"."detected_amount_units" >= 0),
	CONSTRAINT "payment_intents_required_confirmations_range" CHECK ("payment_intents"."required_confirmations" between 1 and 64),
	CONSTRAINT "payment_intents_expires_after_creation" CHECK ("payment_intents"."expires_at" > "payment_intents"."created_at" and "payment_intents"."expires_at" <= "payment_intents"."created_at" + interval '7 days')
);
--> statement-breakpoint
CREATE TABLE "reconciliation_attempts" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"payment_intent_id" varchar(40) NOT NULL,
	"request_id" varchar(64) NOT NULL,
	"provider" varchar(32) NOT NULL,
	"from_block" bigint NOT NULL,
	"to_block" bigint NOT NULL,
	"latest_block" bigint,
	"candidate_count" integer DEFAULT 0 NOT NULL,
	"result_status" "payment_status",
	"error_code" varchar(64),
	"started_at" timestamp with time zone NOT NULL,
	"completed_at" timestamp with time zone NOT NULL,
	"duration_ms" integer NOT NULL
);
--> statement-breakpoint
ALTER TABLE "matched_transfers" ADD CONSTRAINT "matched_transfers_payment_intent_id_payment_intents_id_fk" FOREIGN KEY ("payment_intent_id") REFERENCES "public"."payment_intents"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "reconciliation_attempts" ADD CONSTRAINT "reconciliation_attempts_payment_intent_id_payment_intents_id_fk" FOREIGN KEY ("payment_intent_id") REFERENCES "public"."payment_intents"("id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
CREATE UNIQUE INDEX "matched_transfers_intent_tx_log_unique" ON "matched_transfers" USING btree ("payment_intent_id","tx_hash","log_index");--> statement-breakpoint
CREATE INDEX "matched_transfers_intent_block_log_idx" ON "matched_transfers" USING btree ("payment_intent_id","block_number","log_index");--> statement-breakpoint
CREATE INDEX "matched_transfers_tx_hash_idx" ON "matched_transfers" USING btree ("tx_hash");--> statement-breakpoint
CREATE INDEX "payment_intents_status_expires_at_idx" ON "payment_intents" USING btree ("status","expires_at");--> statement-breakpoint
CREATE INDEX "payment_intents_recipient_created_at_idx" ON "payment_intents" USING btree ("recipient_address","created_at");--> statement-breakpoint
CREATE INDEX "reconciliation_attempts_intent_started_at_idx" ON "reconciliation_attempts" USING btree ("payment_intent_id","started_at" DESC NULLS LAST);