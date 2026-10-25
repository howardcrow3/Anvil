import { contextBridge, ipcRenderer } from 'electron'
import type { AnvilBridge, RuntimeState } from '../shared/types'

const bridge: AnvilBridge = {
  platform: process.platform,
  getRuntime: () => ipcRenderer.invoke('runtime:get'),
  onRuntimeStatus(cb) {
    const handler = (_e: unknown, state: RuntimeState): void => cb(state)
    ipcRenderer.on('runtime:status', handler)
    return () => ipcRenderer.removeListener('runtime:status', handler)
  },
  restartRuntime: () => ipcRenderer.invoke('runtime:restart'),
  notify: (title, body) => ipcRenderer.invoke('notify', title, body),
  openExternal: (url) => ipcRenderer.invoke('open-external', url),
  chooseDirectory: () => ipcRenderer.invoke('dialog:directory')
}

contextBridge.exposeInMainWorld('anvil', bridge)
