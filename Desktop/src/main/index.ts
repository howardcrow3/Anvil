import { app, BrowserWindow, dialog, ipcMain, Notification, shell } from 'electron'
import { join } from 'node:path'
import type { RuntimeState } from '../shared/types'
import { RuntimeSupervisor, resolveLaunch } from './runtime'

const isDev = !app.isPackaged
let mainWindow: BrowserWindow | null = null

// Attach to an already-running runtime (e.g. started by hand) instead of spawning one.
const externalRuntime = process.env.ANVIL_RUNTIME_WS

const supervisor = new RuntimeSupervisor(
  () =>
    resolveLaunch({
      packaged: app.isPackaged,
      resourcesPath: process.resourcesPath,
      appPath: app.getAppPath(),
      platform: process.platform,
      projectDir: process.env.ANVIL_PROJECT_DIR ?? app.getPath('home'),
      env: process.env
    }),
  join(app.getPath('logs'))
)

function currentRuntime(): RuntimeState {
  return externalRuntime ? { status: 'ready', url: externalRuntime } : supervisor.state
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 760,
    minHeight: 480,
    show: false,
    title: 'Anvil',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#1b1b1f',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.on('closed', () => (mainWindow = null))

  // Links and window.open go to the system browser, never into the app window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    openExternal(url)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (url !== mainWindow?.webContents.getURL()) {
      event.preventDefault()
      openExternal(url)
    }
  })

  if (isDev && process.env.ELECTRON_RENDERER_URL) void mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  else void mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
}

function openExternal(url: string): void {
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:' || parsed.protocol === 'mailto:') {
      void shell.openExternal(parsed.toString())
    }
  } catch {
    /* ignore malformed URLs */
  }
}

function registerIpc(): void {
  ipcMain.handle('runtime:get', () => currentRuntime())
  ipcMain.handle('runtime:restart', async () => {
    if (!externalRuntime) await supervisor.restart()
    return currentRuntime()
  })
  ipcMain.handle('notify', (_e, title: unknown, body: unknown) => {
    if (typeof title === 'string' && typeof body === 'string' && Notification.isSupported()) {
      new Notification({ title: title.slice(0, 120), body: body.slice(0, 400) }).show()
    }
  })
  ipcMain.handle('open-external', (_e, url: unknown) => typeof url === 'string' && openExternal(url))
  ipcMain.handle('dialog:directory', async () => {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] })
    return result.canceled ? null : (result.filePaths[0] ?? null)
  })
  supervisor.on('state', (state: RuntimeState) => mainWindow?.webContents.send('runtime:status', state))
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  void app.whenReady().then(() => {
    registerIpc()
    if (!externalRuntime) supervisor.start()
    createWindow()
    app.on('activate', () => BrowserWindow.getAllWindows().length === 0 && createWindow())
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
  app.on('before-quit', () => void supervisor.stop())
}
