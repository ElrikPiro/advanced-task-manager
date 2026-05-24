import type { NotificationItem } from "../types/api";

interface NotificationsPanelProps {
  notifications: NotificationItem[];
  onRefresh: () => Promise<void>;
}

export function NotificationsPanel({ notifications, onRefresh }: NotificationsPanelProps): JSX.Element {
  return (
    <section className="panel">
      <div className="panel-header">
        <h2>Notifications</h2>
        <button type="button" className="secondary" onClick={() => void onRefresh()}>
          Refresh
        </button>
      </div>
      {notifications.length === 0 ? (
        <p className="empty">No notifications</p>
      ) : (
        <ul className="notification-list">
          {notifications.map((notification, index) => (
            <li key={`${notification.timestamp}-${index}`}>
              <p>{notification.message}</p>
              <small>{notification.timestamp}</small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
