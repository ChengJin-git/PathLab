/** Share route imports with intent preloading so the sidebar can warm each page. */
let chat: Promise<typeof import("../pages/AIChatPage")> | undefined;
let datasets: Promise<typeof import("../pages/ListPage")> | undefined;
let upload: Promise<typeof import("../pages/UploadPage")> | undefined;

export function loadChatPage() {
  return (chat ||= import("../pages/AIChatPage").catch((error) => {
    chat = undefined;
    throw error;
  }));
}
export function loadDatasetsPage() {
  return (datasets ||= import("../pages/ListPage").catch((error) => {
    datasets = undefined;
    throw error;
  }));
}
export function loadUploadPage() {
  return (upload ||= import("../pages/UploadPage").catch((error) => {
    upload = undefined;
    throw error;
  }));
}
export function preloadDataPage(path: string) {
  const load =
    path.startsWith("/dashboard")
      ? loadChatPage
      : path === "/datasets"
      ? loadDatasetsPage
      : path === "/upload"
        ? loadUploadPage
        : null;
  if (load) void load().catch(() => {});
}
