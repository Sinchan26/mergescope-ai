import { CheckCircle2, LoaderCircle, XCircle } from "lucide-react";
import type { ReviewStatus } from "../types";

export const humanize = (value: string) => value.replaceAll("_", " ");

export function StatusBadge({ status }: { status: ReviewStatus }) {
  const icon =
    status === "completed" ? (
      <CheckCircle2 size={14} />
    ) : status === "failed" ? (
      <XCircle size={14} />
    ) : (
      <LoaderCircle size={14} className={status === "running" ? "spin" : ""} />
    );
  return (
    <span className={`status-badge status-${status}`}>
      {icon}
      {humanize(status)}
    </span>
  );
}
