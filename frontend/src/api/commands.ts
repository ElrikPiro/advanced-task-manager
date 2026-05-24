import { HttpApiClient, buildQueryWithArgs } from "./client";
import type {
  AgendaContent,
  ApiClientConfig,
  ApiResponse,
  EventsContent,
  FilterEntry,
  NamedDescriptionEntry,
  NotificationItem,
  TaskInformation,
  TaskListContent,
  WorkloadStats,
} from "../types/api";

export class TaskManagerApi {
  private readonly client: HttpApiClient;

  public constructor(config: ApiClientConfig) {
    this.client = new HttpApiClient(config);
  }

  public list(): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>("list");
  }

  public next(): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>("next");
  }

  public previous(): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>("previous");
  }

  public task(index: number): Promise<ApiResponse<TaskInformation>> {
    return this.client.get<TaskInformation>(`task_${index}`);
  }

  public info(): Promise<ApiResponse<TaskInformation>> {
    return this.client.get<TaskInformation>("info");
  }

  public heuristics(): Promise<ApiResponse<NamedDescriptionEntry[]>> {
    return this.client.get<NamedDescriptionEntry[]>("heuristic");
  }

  public heuristicSelect(index: number): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>(`heuristic_${index}`);
  }

  public algorithms(): Promise<ApiResponse<NamedDescriptionEntry[]>> {
    return this.client.get<NamedDescriptionEntry[]>("algorithm");
  }

  public algorithmSelect(index: number): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>(`algorithm_${index}`);
  }

  public filters(): Promise<ApiResponse<FilterEntry[]>> {
    return this.client.get<FilterEntry[]>("filter");
  }

  public filterToggle(index: number): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>(`filter_${index}`);
  }

  public done(): Promise<ApiResponse<TaskListContent>> {
    return this.client.get<TaskListContent>("done");
  }

  public set(param: string, value: string): Promise<ApiResponse<TaskInformation>> {
    return this.client.get<TaskInformation>("set", buildQueryWithArgs([param, value]));
  }

  public create(description: string, context?: string, totalCost?: string): Promise<ApiResponse<TaskInformation>> {
    const payload = context && totalCost ? `${description};${context};${totalCost}` : description;
    return this.client.get<TaskInformation>("new", buildQueryWithArgs([payload]));
  }

  public schedule(expectedWorkPerDay?: string): Promise<ApiResponse<TaskInformation | TaskListContent>> {
    const args = expectedWorkPerDay ? [expectedWorkPerDay] : undefined;
    return this.client.get<TaskInformation | TaskListContent>("schedule", buildQueryWithArgs(args));
  }

  public work(amount: string): Promise<ApiResponse<TaskInformation>> {
    return this.client.get<TaskInformation>("work", buildQueryWithArgs([amount]));
  }

  public snooze(amount?: string): Promise<ApiResponse<TaskInformation>> {
    const args = amount ? [amount] : undefined;
    return this.client.get<TaskInformation>("snooze", buildQueryWithArgs(args));
  }

  public search(...terms: string[]): Promise<ApiResponse<TaskListContent | TaskInformation>> {
    return this.client.get<TaskListContent | TaskInformation>("search", buildQueryWithArgs(terms));
  }

  public stats(): Promise<ApiResponse<WorkloadStats>> {
    return this.client.get<WorkloadStats>("stats");
  }

  public agenda(): Promise<ApiResponse<AgendaContent>> {
    return this.client.get<AgendaContent>("agenda");
  }

  public events(): Promise<ApiResponse<EventsContent>> {
    return this.client.get<EventsContent>("events");
  }

  public project(args: string[]): Promise<ApiResponse<unknown>> {
    return this.client.get<unknown>("project", buildQueryWithArgs(args));
  }

  public raise(eventName: string): Promise<ApiResponse<unknown>> {
    return this.client.get<unknown>("raise", buildQueryWithArgs([eventName]));
  }

  public notifications(maskAsRead: boolean): Promise<ApiResponse<NotificationItem[]>> {
    const query = new URLSearchParams();
    query.set("mask_as_read", String(maskAsRead));
    return this.client.get<NotificationItem[]>("notifications", query);
  }
}
