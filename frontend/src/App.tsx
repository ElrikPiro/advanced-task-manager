import { useCallback, useMemo, useState } from "react";
import { TaskManagerApi } from "./api/commands";
import { BadgeList } from "./components/BadgeList";
import { CommandForms } from "./components/CommandForms";
import { KeyValueGrid } from "./components/KeyValueGrid";
import { NotificationsPanel } from "./components/NotificationsPanel";
import { TaskTable } from "./components/TaskTable";
import { useInterval } from "./hooks/useInterval";
import { usePersistentState } from "./hooks/usePersistentState";
import type {
  AgendaContent,
  ApiError,
  EventsContent,
  FilterEntry,
  NamedDescriptionEntry,
  NotificationItem,
  TaskInformation,
  TaskListContent,
  WorkloadStats,
} from "./types/api";
import { formatMillisecondsAsDuration, formatTimestamp } from "./utils/time";

const DEFAULT_BASE_URL = "/api";
const DEFAULT_POLL_INTERVAL_MS = 20_000;

type View = "tasks" | "agenda" | "stats" | "events";

function isTaskListContent(data: unknown): data is TaskListContent {
  if (typeof data !== "object" || data === null) {
    return false;
  }

  const candidate = data as Partial<TaskListContent>;
  return Array.isArray(candidate.tasks) && typeof candidate.algorithm_name === "string";
}

function isTaskInformation(data: unknown): data is TaskInformation {
  if (typeof data !== "object" || data === null) {
    return false;
  }

  const candidate = data as Partial<TaskInformation>;
  return typeof candidate.task === "object" && candidate.task !== null;
}

function isWorkloadStats(data: unknown): data is WorkloadStats {
  if (typeof data !== "object" || data === null) {
    return false;
  }

  const candidate = data as Partial<WorkloadStats>;
  return typeof candidate.maxHeuristic === "number" && typeof candidate.workDone === "object";
}

function isAgendaContent(data: unknown): data is AgendaContent {
  if (typeof data !== "object" || data === null) {
    return false;
  }

  const candidate = data as Partial<AgendaContent>;
  return Array.isArray(candidate.active_urgent_tasks) && typeof candidate.planned_tasks_by_date === "object";
}

function isEventsContent(data: unknown): data is EventsContent {
  if (typeof data !== "object" || data === null) {
    return false;
  }

  const candidate = data as Partial<EventsContent>;
  return Array.isArray(candidate.event_statistics) && typeof candidate.total_events === "number";
}

function isNamedDescriptionArray(data: unknown): data is NamedDescriptionEntry[] {
  if (!Array.isArray(data)) {
    return false;
  }

  return data.every((entry) => {
    if (typeof entry !== "object" || entry === null) {
      return false;
    }

    const candidate = entry as Partial<NamedDescriptionEntry>;
    return typeof candidate.name === "string" && typeof candidate.description === "string";
  });
}

function isFilterEntryArray(data: unknown): data is FilterEntry[] {
  if (!Array.isArray(data)) {
    return false;
  }

  return data.every((entry) => {
    if (typeof entry !== "object" || entry === null) {
      return false;
    }

    const candidate = entry as Partial<FilterEntry>;
    return typeof candidate.name === "string" && typeof candidate.enabled === "boolean";
  });
}

function normalizeError(error: unknown): string {
  const maybeApiError = error as Partial<ApiError>;
  if (maybeApiError && typeof maybeApiError.message === "string") {
    if (typeof maybeApiError.details === "string" && maybeApiError.details.length > 0) {
      return `${maybeApiError.message} (${maybeApiError.details})`;
    }
    return maybeApiError.message;
  }

  return String(error);
}

function parseProjectArgs(input: string): string[] {
  return input
    .trim()
    .split(/\s+/)
    .filter((value) => value.length > 0);
}

function getConnectionHint(baseUrl: string): string {
  if (baseUrl.trim().startsWith("/")) {
    return "Using Vite proxy route. Ensure backend is reachable from the Vite dev server.";
  }

  return "Absolute URLs are proxied through /api with dynamic target routing.";
}

export function App(): JSX.Element {
  const [baseUrl, setBaseUrl] = usePersistentState<string>("atm.baseUrl", DEFAULT_BASE_URL);
  const [token, setToken] = usePersistentState<string>("atm.token", "");
  const [connected, setConnected] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [view, setView] = useState<View>("tasks");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [infoMessage, setInfoMessage] = useState<string>("");

  const [taskList, setTaskList] = useState<TaskListContent | null>(null);
  const [taskInfo, setTaskInfo] = useState<TaskInformation | null>(null);
  const [stats, setStats] = useState<WorkloadStats | null>(null);
  const [agenda, setAgenda] = useState<AgendaContent | null>(null);
  const [events, setEvents] = useState<EventsContent | null>(null);

  const [heuristics, setHeuristics] = useState<NamedDescriptionEntry[]>([]);
  const [algorithms, setAlgorithms] = useState<NamedDescriptionEntry[]>([]);
  const [filters, setFilters] = useState<FilterEntry[]>([]);
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);

  const api = useMemo(() => {
    if (!token.trim()) {
      return null;
    }

    return new TaskManagerApi({
      baseUrl,
      token,
      timeoutMs: 12_000,
    });
  }, [baseUrl, token]);

  const setError = useCallback((value: unknown) => {
    const parsed = normalizeError(value);
    setErrorMessage(parsed);
    setInfoMessage("");
  }, []);

  const setInfo = useCallback((value: string) => {
    setInfoMessage(value);
    setErrorMessage("");
  }, []);

  const withBusy = useCallback(async <T,>(work: () => Promise<T>): Promise<T | null> => {
    setIsBusy(true);
    try {
      return await work();
    } catch (error) {
      setError(error);
      return null;
    } finally {
      setIsBusy(false);
    }
  }, [setError]);

  const fetchNotifications = useCallback(async () => {
    if (!api) {
      return;
    }

    try {
      const response = await api.notifications(true);
      if (Array.isArray(response.data)) {
        setNotifications((previous) => [...response.data!, ...previous].slice(0, 50));
      }
    } catch {
      // Notifications should not disrupt the app flow.
    }
  }, [api]);

  useInterval(
    () => {
      void fetchNotifications();
    },
    connected ? DEFAULT_POLL_INTERVAL_MS : null,
  );

  const refreshList = useCallback(async () => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const [listResponse, heuristicsResponse, algorithmsResponse, filtersResponse] = await Promise.all([
        api.list(),
        api.heuristics(),
        api.algorithms(),
        api.filters(),
      ]);

      if (isTaskListContent(listResponse.data)) {
        setTaskList(listResponse.data);
      } else if (typeof listResponse.text === "string") {
        setInfo(listResponse.text);
      }

      if (isNamedDescriptionArray(heuristicsResponse.data)) {
        setHeuristics(heuristicsResponse.data);
      }

      if (isNamedDescriptionArray(algorithmsResponse.data)) {
        setAlgorithms(algorithmsResponse.data);
      }

      if (isFilterEntryArray(filtersResponse.data)) {
        setFilters(filtersResponse.data);
      }

      setConnected(true);
      setInfo("Connected and list synchronized");
    });
  }, [api, setInfo, withBusy]);

  const selectTask = useCallback(async (index: number) => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const response = await api.task(index);
      if (isTaskInformation(response.data)) {
        setTaskInfo(response.data);
        setView("tasks");
      } else {
        setInfo(response.text ?? "Task selection returned text response");
      }
    });
  }, [api, setInfo, withBusy]);

  const refreshAgenda = useCallback(async () => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const response = await api.agenda();
      if (isAgendaContent(response.data)) {
        setAgenda(response.data);
        setView("agenda");
      } else {
        setInfo(response.text ?? "Agenda endpoint returned text response");
      }
    });
  }, [api, setInfo, withBusy]);

  const refreshStats = useCallback(async () => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const response = await api.stats();
      if (isWorkloadStats(response.data)) {
        setStats(response.data);
        setView("stats");
      } else {
        setInfo(response.text ?? "Stats endpoint returned text response");
      }
    });
  }, [api, setInfo, withBusy]);

  const refreshEvents = useCallback(async () => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const response = await api.events();
      if (isEventsContent(response.data)) {
        setEvents(response.data);
        setView("events");
      } else {
        setInfo(response.text ?? "Events endpoint returned text response");
      }
    });
  }, [api, setInfo, withBusy]);

  const runListRefreshCommand = useCallback(
    async (operation: () => Promise<unknown>, successMessage: string) => {
      await withBusy(async () => {
        await operation();
        await refreshList();
        setInfo(successMessage);
      });
    },
    [refreshList, setInfo, withBusy],
  );

  const loadTaskInfo = useCallback(async () => {
    if (!api) {
      return;
    }

    await withBusy(async () => {
      const response = await api.info();
      if (isTaskInformation(response.data)) {
        setTaskInfo(response.data);
        setView("tasks");
      } else {
        setInfo(response.text ?? "Task info returned text response");
      }
    });
  }, [api, setInfo, withBusy]);

  const initializeConnection = useCallback(async () => {
    if (!api) {
      setConnected(false);
      setError("Token is required");
      return;
    }

    await refreshList();
    await fetchNotifications();
  }, [api, fetchNotifications, refreshList, setError]);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <h1>Advanced Task Manager</h1>
          <p>HTTP frontend for task planning, execution, and reporting.</p>
        </div>
        <div className={`status-pill ${connected ? "online" : "offline"}`}>
          {connected ? "Connected" : "Disconnected"}
        </div>
      </header>

      <section className="panel connection-panel">
        <h2>Connection</h2>
        <div className="connection-fields">
          <label>
            Backend URL
            <input
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="/api"
            />
            <small className="caption">Cross-origin absolute URLs are automatically routed to /api.</small>
            <small className="caption">{getConnectionHint(baseUrl)}</small>
          </label>
          <label>
            Bearer token
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="token"
              type="password"
            />
          </label>
          <button type="button" onClick={() => void initializeConnection()} disabled={isBusy}>
            Connect
          </button>
        </div>
      </section>

      {errorMessage ? <div className="alert error">{errorMessage}</div> : null}
      {infoMessage ? <div className="alert info">{infoMessage}</div> : null}

      <section className="panel">
        <h2>HTTP Backend Checklist</h2>
        <ul>
          <li><code>config.json</code> must have <code>APP_MODE</code> set to <code>5</code> or <code>6</code>.</li>
          <li>Backend process must be running and reachable from the machine running Vite.</li>
          <li>For remote backends, enter the full URL in the connection field (for example <code>http://82.165.173.73:8081</code>).</li>
          <li>Use the HTTP token from <code>config.json</code> in the Bearer token field.</li>
        </ul>
      </section>

      <section className="panel action-bar">
        <div className="button-row">
          <button type="button" onClick={() => void refreshList()} disabled={isBusy || !api}>
            Refresh List
          </button>
          <button type="button" onClick={() => void runListRefreshCommand(() => api!.next(), "Moved to next page")} disabled={isBusy || !api}>
            Next
          </button>
          <button type="button" onClick={() => void runListRefreshCommand(() => api!.previous(), "Moved to previous page")} disabled={isBusy || !api}>
            Previous
          </button>
          <button type="button" onClick={() => void loadTaskInfo()} disabled={isBusy || !api}>
            Info
          </button>
          <button type="button" onClick={() => void runListRefreshCommand(() => api!.done(), "Selected task marked as done")} disabled={isBusy || !api}>
            Done
          </button>
          <button type="button" className="secondary" onClick={() => void refreshAgenda()} disabled={isBusy || !api}>
            Agenda
          </button>
          <button type="button" className="secondary" onClick={() => void refreshStats()} disabled={isBusy || !api}>
            Stats
          </button>
          <button type="button" className="secondary" onClick={() => void refreshEvents()} disabled={isBusy || !api}>
            Events
          </button>
          <button type="button" className="secondary" onClick={() => setView("tasks")}>
            Tasks View
          </button>
        </div>
      </section>

      <main className="layout-grid">
        {view === "tasks" ? (
          <>
            <TaskTable
              title="Task List"
              tasks={taskList?.tasks ?? []}
              onSelect={(task, index) => {
                void selectTask(index + 1);
                setInfo(`Selected task ${task.description}`);
              }}
            />

            <section className="panel">
              <h2>List Context</h2>
              {taskList ? (
                <>
                  <KeyValueGrid
                    entries={[
                      { label: "Algorithm", value: taskList.algorithm_name },
                      { label: "Heuristic", value: taskList.sort_heuristic },
                      { label: "Total Tasks", value: taskList.total_tasks },
                      { label: "Page", value: `${taskList.current_page}/${taskList.total_pages}` },
                    ]}
                  />
                  <p className="caption">{taskList.algorithm_desc}</p>
                  <BadgeList
                    title="Active Filters"
                    values={taskList.active_filters.map((filter) => `${filter.index}. ${filter.name}`)}
                  />
                </>
              ) : (
                <p className="empty">No list loaded</p>
              )}
            </section>

            <section className="panel">
              <h2>Task Information</h2>
              {taskInfo ? (
                <>
                  <KeyValueGrid
                    entries={[
                      { label: "Description", value: taskInfo.task.description },
                      { label: "Context", value: taskInfo.task.context },
                      { label: "Start", value: taskInfo.task.start },
                      { label: "Due", value: taskInfo.task.due },
                      { label: "Severity", value: taskInfo.task.severity.toFixed(2) },
                      { label: "Status", value: taskInfo.task.status || "-" },
                      { label: "Total Cost", value: `${taskInfo.task.total_cost.toFixed(2)}p` },
                      { label: "Effort Invested", value: `${taskInfo.task.effort_invested.toFixed(2)}p` },
                    ]}
                  />
                  {taskInfo.extended ? (
                    <>
                      <h3>Heuristics</h3>
                      <ul className="heuristic-list">
                        {taskInfo.extended.heuristics.map((heuristic) => (
                          <li key={heuristic.name}>
                            <strong>{heuristic.name}</strong>: {heuristic.value.toFixed(3)} - {heuristic.comment}
                          </li>
                        ))}
                      </ul>
                      <h3>Metadata</h3>
                      <pre>{taskInfo.extended.metadata}</pre>
                    </>
                  ) : null}
                </>
              ) : (
                <p className="empty">No task selected</p>
              )}
            </section>

            <CommandForms
              busy={isBusy || !api}
              actions={{
                setParam: async (param, value) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.set(param, value);
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    await refreshList();
                    setInfo("Task field updated");
                  });
                },
                createTask: async (description, context, totalCost) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.create(description, context, totalCost);
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    await refreshList();
                    setInfo("Task created");
                  });
                },
                work: async (amount) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.work(amount);
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    await refreshList();
                    setInfo("Work logged");
                  });
                },
                schedule: async (expectedWorkPerDay) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.schedule(expectedWorkPerDay);
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    await refreshList();
                    setInfo("Task scheduled");
                  });
                },
                snooze: async (amount) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.snooze(amount);
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    await refreshList();
                    setInfo("Task snoozed");
                  });
                },
                search: async (term) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.search(...parseProjectArgs(term));
                    if (isTaskListContent(response.data)) {
                      setTaskList(response.data);
                    }
                    if (isTaskInformation(response.data)) {
                      setTaskInfo(response.data);
                    }
                    setInfo("Search completed");
                  });
                },
                project: async (args) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.project(parseProjectArgs(args));
                    setInfo(response.text ?? "Project command executed");
                    await refreshList();
                  });
                },
                raiseEvent: async (eventName) => {
                  if (!api) {
                    return;
                  }

                  await withBusy(async () => {
                    const response = await api.raise(eventName);
                    setInfo(response.text ?? "Event raised");
                    await refreshList();
                  });
                },
              }}
            />

            <section className="panel">
              <h2>Strategies</h2>
              <div className="strategy-grid">
                <div>
                  <h3>Heuristics</h3>
                  <ul>
                    {heuristics.map((entry, index) => (
                      <li key={entry.name}>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => void runListRefreshCommand(() => api!.heuristicSelect(index + 1), `Selected heuristic ${entry.name}`)}
                          disabled={isBusy || !api}
                        >
                          {index + 1}. {entry.name}
                        </button>
                        <p className="caption">{entry.description}</p>
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3>Algorithms</h3>
                  <ul>
                    {algorithms.map((entry, index) => (
                      <li key={entry.name}>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => void runListRefreshCommand(() => api!.algorithmSelect(index + 1), `Selected algorithm ${entry.name}`)}
                          disabled={isBusy || !api}
                        >
                          {index + 1}. {entry.name}
                        </button>
                        <p className="caption">{entry.description}</p>
                      </li>
                    ))}
                  </ul>
                </div>

                <div>
                  <h3>Filters</h3>
                  <ul>
                    {filters.map((entry, index) => (
                      <li key={entry.name}>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => void runListRefreshCommand(() => api!.filterToggle(index + 1), `Toggled filter ${entry.name}`)}
                          disabled={isBusy || !api}
                        >
                          {entry.enabled ? "Disable" : "Enable"} {entry.name}
                        </button>
                        <p className="caption">{entry.description}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>
          </>
        ) : null}

        {view === "agenda" ? (
          <>
            <section className="panel">
              <h2>Agenda</h2>
              {agenda ? (
                <>
                  <p className="caption">Date: {agenda.date.str_representation}</p>
                  <TaskTable title="Active urgent tasks" tasks={agenda.active_urgent_tasks} />
                  <TaskTable title="Planned urgent tasks" tasks={agenda.planned_urgent_tasks} />
                </>
              ) : (
                <p className="empty">No agenda loaded</p>
              )}
            </section>

            <section className="panel">
              <h2>Planned by Start Date</h2>
              {!agenda ? (
                <p className="empty">No agenda loaded</p>
              ) : (
                Object.entries(agenda.planned_tasks_by_date).map(([startDate, entries]) => (
                  <div key={startDate} className="agenda-group">
                    <h3>{startDate}</h3>
                    <TaskTable title={`Tasks at ${startDate}`} tasks={entries} />
                  </div>
                ))
              )}
            </section>
          </>
        ) : null}

        {view === "stats" ? (
          <>
            <section className="panel">
              <h2>Statistics</h2>
              {stats ? (
                <>
                  <KeyValueGrid
                    entries={[
                      { label: "Heuristic", value: stats.HeuristicName },
                      { label: "Max Heuristic", value: stats.maxHeuristic.toFixed(3) },
                      { label: "Top Offender", value: stats.offender || "-" },
                      { label: "Workload", value: formatMillisecondsAsDuration(stats.workload.int_representation) },
                      {
                        label: "Remaining Effort",
                        value: formatMillisecondsAsDuration(stats.remainingEffort.int_representation),
                      },
                      {
                        label: "Offender Max",
                        value: formatMillisecondsAsDuration(stats.offenderMax.int_representation),
                      },
                    ]}
                  />
                  <h3>Work by Day</h3>
                  <ul>
                    {Object.entries(stats.workDone).map(([date, amount]) => (
                      <li key={date}>
                        {date}: {amount.toFixed(2)} pomodoros
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="empty">No stats loaded</p>
              )}
            </section>

            <section className="panel">
              <h2>Work Log</h2>
              {!stats || stats.workDoneLog.length === 0 ? (
                <p className="empty">No work log entries</p>
              ) : (
                <ul>
                  {stats.workDoneLog.map((entry) => (
                    <li key={`${entry.timestamp}-${entry.task}`}>
                      {formatTimestamp(entry.timestamp)} - {entry.task} ({entry.work_units.toFixed(2)}p)
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}

        {view === "events" ? (
          <>
            <section className="panel">
              <h2>Events</h2>
              {events ? (
                <KeyValueGrid
                  entries={[
                    { label: "Total Events", value: events.total_events },
                    { label: "Raising Tasks", value: events.total_raising_tasks },
                    { label: "Waiting Tasks", value: events.total_waiting_tasks },
                    { label: "Orphaned", value: events.orphaned_events_count },
                  ]}
                />
              ) : (
                <p className="empty">No event statistics loaded</p>
              )}
            </section>

            <section className="panel">
              <h2>Event Breakdown</h2>
              {!events || events.event_statistics.length === 0 ? (
                <p className="empty">No event details</p>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Raising</th>
                      <th>Waiting</th>
                      <th>Orphaned</th>
                      <th>Type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.event_statistics.map((event) => (
                      <tr key={event.event_name} className={event.is_orphaned ? "orphaned" : ""}>
                        <td>{event.event_name}</td>
                        <td>{event.tasks_raising}</td>
                        <td>{event.tasks_waiting}</td>
                        <td>{event.is_orphaned ? "Yes" : "No"}</td>
                        <td>{event.orphan_type}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        ) : null}

        <NotificationsPanel notifications={notifications} onRefresh={fetchNotifications} />
      </main>

      <footer className="footnote panel">
        <p>
          HTTP mode caveat: <code>/export</code> is currently unavailable in backend HTTP service, and some endpoints may return plain text
          instead of JSON.
        </p>
      </footer>
    </div>
  );
}
