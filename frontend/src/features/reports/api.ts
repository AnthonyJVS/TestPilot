import { fetchWithAuth } from "@/lib/api-client";

async function reportBlob(executionId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetchWithAuth(`/executions/${executionId}/report`);
  const disposition = response.headers.get("content-disposition") ?? "";
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `testpilot-${executionId.slice(0, 8)}.html`;
  const blob = new Blob([await response.text()], { type: "text/html" });
  return { blob, filename };
}

/**
 * Opens the self-contained report in a new tab (its own CSP forbids scripts).
 * The tab is opened synchronously, inside the click, so popup blockers allow it; the report is
 * loaded into it afterwards. If the tab is blocked anyway, the report is downloaded instead.
 */
export async function openReport(executionId: string): Promise<void> {
  const tab = window.open("about:blank", "_blank");
  try {
    const { blob, filename } = await reportBlob(executionId);
    const url = URL.createObjectURL(blob);
    if (tab) {
      tab.opener = null;
      tab.location.href = url;
    } else {
      saveBlob(url, filename);
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}

function saveBlob(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}

export async function downloadReport(executionId: string): Promise<void> {
  const { blob, filename } = await reportBlob(executionId);
  const url = URL.createObjectURL(blob);
  saveBlob(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
