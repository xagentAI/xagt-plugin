"use client";

import { NotificationsPopup } from "@/components/dashboard/notifications-popup";

interface NotificationsSidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * Backwards compatibility wrapper that renders the modern NotificationsPopup.
 */
export function NotificationsSidebar({ isOpen, onClose }: NotificationsSidebarProps) {
  return (
    <div className="fixed top-16 right-4 z-[100]">
      <NotificationsPopup isOpen={isOpen} onClose={onClose} />
    </div>
  );
}

export { NotificationsPopup };
