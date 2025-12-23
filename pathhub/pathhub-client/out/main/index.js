"use strict";
const electron = require("electron");
const path = require("path");
const utils = require("@electron-toolkit/utils");
const child_process = require("child_process");
let pythonProcess = null;
function startPythonSidecar() {
  const isDev = !electron.app.isPackaged;
  let pythonPath = "python3";
  let scriptPath = "";
  if (isDev) {
    scriptPath = path.join(process.cwd(), "python/main.py");
  } else {
    scriptPath = path.join(process.resourcesPath, "python/main.py");
  }
  console.log(`Starting Python sidecar: ${pythonPath} ${scriptPath}`);
  pythonProcess = child_process.spawn(pythonPath, [scriptPath]);
  pythonProcess.stdout?.on("data", (data) => {
    console.log(`[Python]: ${data}`);
  });
  pythonProcess.stderr?.on("data", (data) => {
    console.error(`[Python Error]: ${data}`);
  });
  pythonProcess.on("close", (code) => {
    console.log(`Python process exited with code ${code}`);
    pythonProcess = null;
  });
}
function stopPythonSidecar() {
  if (pythonProcess) {
    console.log("Stopping Python sidecar...");
    pythonProcess.kill();
    pythonProcess = null;
  }
}
if (process.platform === "linux") {
  electron.app.commandLine.appendSwitch("no-sandbox");
}
function createWindow() {
  const mainWindow = new electron.BrowserWindow({
    width: 900,
    height: 670,
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      sandbox: false
    }
  });
  mainWindow.on("ready-to-show", () => {
    mainWindow.show();
  });
  mainWindow.webContents.setWindowOpenHandler((details) => {
    electron.shell.openExternal(details.url);
    return { action: "deny" };
  });
  if (utils.is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(path.join(__dirname, "../renderer/index.html"));
  }
}
electron.app.whenReady().then(() => {
  utils.electronApp.setAppUserModelId("com.pathhub.client");
  electron.app.on("browser-window-created", (_, window) => {
    utils.optimizer.watchWindowShortcuts(window);
  });
  startPythonSidecar();
  createWindow();
  electron.app.on("activate", function() {
    if (electron.BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});
electron.app.on("window-all-closed", () => {
  stopPythonSidecar();
  if (process.platform !== "darwin") {
    electron.app.quit();
  }
});
electron.app.on("before-quit", () => {
  stopPythonSidecar();
});
