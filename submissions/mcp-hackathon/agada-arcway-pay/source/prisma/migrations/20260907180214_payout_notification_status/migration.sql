-- CreateEnum
CREATE TYPE "NotificationStatus" AS ENUM ('pending', 'sent', 'failed', 'skipped');

-- AlterTable
ALTER TABLE "Payout" ADD COLUMN     "notifiedAt" TIMESTAMP(3),
ADD COLUMN     "notifyError" TEXT,
ADD COLUMN     "notifyStatus" "NotificationStatus" NOT NULL DEFAULT 'pending';
