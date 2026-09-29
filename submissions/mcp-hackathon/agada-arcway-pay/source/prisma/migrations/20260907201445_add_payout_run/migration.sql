/*
  Warnings:

  - Added the required column `runId` to the `Payout` table without a default value. This is not possible if the table is not empty.

*/
-- AlterTable
ALTER TABLE "Payout" ADD COLUMN     "runId" TEXT NOT NULL;

-- CreateTable
CREATE TABLE "PayoutRun" (
    "id" TEXT NOT NULL,
    "companyId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PayoutRun_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "PayoutRun_companyId_idx" ON "PayoutRun"("companyId");

-- CreateIndex
CREATE INDEX "Payout_runId_idx" ON "Payout"("runId");

-- AddForeignKey
ALTER TABLE "PayoutRun" ADD CONSTRAINT "PayoutRun_companyId_fkey" FOREIGN KEY ("companyId") REFERENCES "Company"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Payout" ADD CONSTRAINT "Payout_runId_fkey" FOREIGN KEY ("runId") REFERENCES "PayoutRun"("id") ON DELETE CASCADE ON UPDATE CASCADE;
