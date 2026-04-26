import { useMemo, useState } from "react";

export interface CommandFormActions {
  setParam: (param: string, value: string) => Promise<void>;
  createTask: (description: string, context?: string, totalCost?: string) => Promise<void>;
  work: (amount: string) => Promise<void>;
  schedule: (expectedWorkPerDay?: string) => Promise<void>;
  snooze: (amount?: string) => Promise<void>;
  search: (term: string) => Promise<void>;
  project: (args: string) => Promise<void>;
  raiseEvent: (eventName: string) => Promise<void>;
}

interface CommandFormsProps {
  actions: CommandFormActions;
  busy: boolean;
}

function splitArgs(value: string): string[] {
  return value
    .trim()
    .split(/\s+/)
    .filter((token) => token.length > 0);
}

export function CommandForms({ actions, busy }: CommandFormsProps): JSX.Element {
  const [setParam, setSetParam] = useState("");
  const [setValue, setSetValue] = useState("");

  const [newDescription, setNewDescription] = useState("");
  const [newContext, setNewContext] = useState("");
  const [newTotalCost, setNewTotalCost] = useState("");

  const [workAmount, setWorkAmount] = useState("1p");
  const [scheduleAmount, setScheduleAmount] = useState("");
  const [snoozeAmount, setSnoozeAmount] = useState("5m");
  const [searchTerms, setSearchTerms] = useState("");
  const [projectArgs, setProjectArgs] = useState("");
  const [eventName, setEventName] = useState("");

  const disablePrimary = useMemo(() => busy, [busy]);

  return (
    <section className="panel">
      <h2>Command Center</h2>
      <div className="forms-grid">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!setParam.trim() || !setValue.trim()) {
              return;
            }
            void actions.setParam(setParam, setValue);
          }}
        >
          <h3>Set Task Field</h3>
          <input
            value={setParam}
            onChange={(event) => setSetParam(event.target.value)}
            placeholder="parameter"
            disabled={disablePrimary}
          />
          <input
            value={setValue}
            onChange={(event) => setSetValue(event.target.value)}
            placeholder="value"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /set</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!newDescription.trim()) {
              return;
            }
            void actions.createTask(
              newDescription,
              newContext.trim() || undefined,
              newTotalCost.trim() || undefined,
            );
          }}
        >
          <h3>Create Task</h3>
          <input
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            placeholder="description"
            disabled={disablePrimary}
          />
          <input
            value={newContext}
            onChange={(event) => setNewContext(event.target.value)}
            placeholder="context (optional)"
            disabled={disablePrimary}
          />
          <input
            value={newTotalCost}
            onChange={(event) => setNewTotalCost(event.target.value)}
            placeholder="total cost (optional, e.g. 2p)"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /new</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!workAmount.trim()) {
              return;
            }
            void actions.work(workAmount);
          }}
        >
          <h3>Log Work</h3>
          <input
            value={workAmount}
            onChange={(event) => setWorkAmount(event.target.value)}
            placeholder="time amount, e.g. 0.5p"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /work</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void actions.schedule(scheduleAmount.trim() || undefined);
          }}
        >
          <h3>Schedule Task</h3>
          <input
            value={scheduleAmount}
            onChange={(event) => setScheduleAmount(event.target.value)}
            placeholder="expected work/day (optional)"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /schedule</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void actions.snooze(snoozeAmount.trim() || undefined);
          }}
        >
          <h3>Snooze Task</h3>
          <input
            value={snoozeAmount}
            onChange={(event) => setSnoozeAmount(event.target.value)}
            placeholder="time amount, e.g. 30m"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /snooze</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!searchTerms.trim()) {
              return;
            }
            void actions.search(searchTerms);
          }}
        >
          <h3>Search Tasks</h3>
          <input
            value={searchTerms}
            onChange={(event) => setSearchTerms(event.target.value)}
            placeholder="keywords"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /search</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!projectArgs.trim()) {
              return;
            }
            void actions.project(projectArgs);
          }}
        >
          <h3>Project Command</h3>
          <input
            value={projectArgs}
            onChange={(event) => setProjectArgs(event.target.value)}
            placeholder="project args"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /project</button>
        </form>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!eventName.trim()) {
              return;
            }
            void actions.raiseEvent(eventName);
          }}
        >
          <h3>Raise Event</h3>
          <input
            value={eventName}
            onChange={(event) => setEventName(event.target.value)}
            placeholder="event name"
            disabled={disablePrimary}
          />
          <button type="submit" disabled={disablePrimary}>Apply /raise</button>
        </form>
      </div>
    </section>
  );
}
