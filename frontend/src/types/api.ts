export interface TaskEntry {
  id: string;
  description: string;
  context: string;
  start: string;
  due: string;
  severity: number;
  status: string;
  total_cost: number;
  effort_invested: number;
  heuristic_value: number;
}

export interface ActiveFilterEntry {
  name: string;
  index: number;
  description: string;
}

export interface TaskListContent {
  algorithm_name: string;
  algorithm_desc: string;
  sort_heuristic: string;
  tasks: TaskEntry[];
  total_tasks: number;
  current_page: number;
  total_pages: number;
  active_filters: ActiveFilterEntry[];
  interactive: boolean;
}

export interface TaskHeuristicInfo {
  name: string;
  value: number;
  comment: string;
}

export interface ExtendedTaskInformation {
  heuristics: TaskHeuristicInfo[];
  metadata: string;
}

export interface TaskInformation {
  task: TaskEntry;
  extended: ExtendedTaskInformation | null;
}

export interface TimeAmount {
  int_representation: number;
}

export interface WorkLogEntry {
  timestamp: number;
  work_units: number;
  task: string;
}

export interface WorkloadStats {
  workload: TimeAmount;
  remainingEffort: TimeAmount;
  maxHeuristic: number;
  HeuristicName: string;
  offender: string;
  offenderMax: TimeAmount;
  workDone: Record<string, number>;
  workDoneLog: WorkLogEntry[];
}

export interface TimePoint {
  timestamp: number;
  str_representation: string;
}

export interface AgendaContent {
  date: TimePoint;
  active_urgent_tasks: TaskEntry[];
  planned_urgent_tasks: TaskEntry[];
  planned_tasks_by_date: Record<string, TaskEntry[]>;
  other_tasks: TaskEntry[];
  other_task_list_info: TaskListContent | null;
}

export interface EventStatistics {
  event_name: string;
  tasks_raising: number;
  tasks_waiting: number;
  is_orphaned: boolean;
  orphan_type: string;
}

export interface EventsContent {
  total_events: number;
  total_raising_tasks: number;
  total_waiting_tasks: number;
  orphaned_events_count: number;
  event_statistics: EventStatistics[];
}

export interface NamedDescriptionEntry {
  name: string;
  description: string;
}

export interface FilterEntry {
  name: string;
  description: string;
  enabled: boolean;
}

export interface ListUpdatedPayload {
  algorithm_description: string;
  most_priority_task: string;
}

export interface NotificationItem {
  message: string;
  timestamp: string;
}

export type ApiTypedPayload =
  | TaskListContent
  | TaskInformation
  | WorkloadStats
  | AgendaContent
  | EventsContent
  | NamedDescriptionEntry[]
  | FilterEntry[]
  | ListUpdatedPayload;

export interface ApiError {
  status: number;
  message: string;
  details?: string;
}

export interface ApiResponse<T> {
  status: number;
  headers: Headers;
  data?: T;
  text?: string;
}

export interface ApiClientConfig {
  baseUrl: string;
  token: string;
  timeoutMs?: number;
}

export type CommandName =
  | "list"
  | "next"
  | "previous"
  | "info"
  | "heuristic"
  | "filter"
  | "done"
  | "set"
  | "new"
  | "schedule"
  | "work"
  | "stats"
  | "events"
  | "snooze"
  | "search"
  | "agenda"
  | "project"
  | "algorithm"
  | "raise";
