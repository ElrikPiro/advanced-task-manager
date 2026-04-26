const HOUR_MS = 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;

export function formatMillisecondsAsDuration(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0m";
  }

  const hours = Math.floor(value / HOUR_MS);
  const remaining = value - hours * HOUR_MS;
  const minutes = Math.round(remaining / MINUTE_MS);

  if (hours > 0 && minutes > 0) {
    return `${hours}h ${minutes}m`;
  }

  if (hours > 0) {
    return `${hours}h`;
  }

  return `${minutes}m`;
}

export function formatTimestamp(value: number): string {
  if (!Number.isFinite(value)) {
    return "invalid";
  }

  const asMs = value < 10_000_000_000 ? value * 1000 : value;
  const date = new Date(asMs);

  if (Number.isNaN(date.getTime())) {
    return "invalid";
  }

  return date.toLocaleString();
}
